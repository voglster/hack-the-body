"""Live eval for the food-parser prompt.

Hits a real Ollama instance with each case, scores the output against
expected items, and prints a per-case + overall report. Use this to
A/B prompt changes or compare models without guessing.

Run:
    cd services/api
    .venv/bin/python evals/run_food_parse.py                # default model
    .venv/bin/python evals/run_food_parse.py --model gpt-oss:120b
    .venv/bin/python evals/run_food_parse.py --case crepe_breakdown
    .venv/bin/python evals/run_food_parse.py --url http://10.0.6.45:11434

Exits non-zero if any case fails (handy for tracking regressions).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Allow running as a script from services/api/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.food_parser import ParsedItem, parse_food_text

CASES_PATH = Path(__file__).resolve().parent / "food_parse_cases.json"

# Tolerance for numeric comparisons. Calorie estimates from LLMs are
# never exact, so within 5 cal or 5% (whichever is larger) counts as a
# match. Macros use the same rule.
NUM_ABS_TOL = 5
NUM_REL_TOL = 0.05


@dataclass
class CaseResult:
    case_id: str
    description: str
    elapsed_s: float
    raw_count: int
    matched: int
    expected_count: int
    extras: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    macro_errors: list[str] = field(default_factory=list)
    total_calorie_check: str | None = None

    @property
    def passed(self) -> bool:
        return (
            not self.misses
            and not self.macro_errors
            and self.total_calorie_check in (None, "ok")
        )


def _num_match(actual: float | None, expected: float) -> bool:
    if actual is None:
        return False
    abs_err = abs(actual - expected)
    rel_err = abs_err / expected if expected else abs_err
    return abs_err <= NUM_ABS_TOL or rel_err <= NUM_REL_TOL


def _score_case(case: dict[str, Any], items: list[ParsedItem]) -> CaseResult:
    expected = case.get("expected", [])
    res = CaseResult(
        case_id=case["id"],
        description=case.get("description", ""),
        elapsed_s=0.0,
        raw_count=len(items),
        matched=0,
        expected_count=len(expected),
    )

    # Greedy match: for each expected item, find the first unmatched
    # actual whose name contains the substring.
    actual_names = [i.name.lower() for i in items]
    used: set[int] = set()
    for exp in expected:
        substr = exp["name_contains"].lower()
        match_idx: int | None = None
        for j, name in enumerate(actual_names):
            if j in used:
                continue
            if substr in name:
                match_idx = j
                break
        if match_idx is None:
            res.misses.append(f"missing: '{substr}'")
            continue
        used.add(match_idx)
        res.matched += 1
        actual = items[match_idx]
        for key in ("calories", "protein_g", "carbs_g", "fat_g", "servings"):
            if key in exp:
                got = getattr(actual, key)
                if not _num_match(got, exp[key]):
                    res.macro_errors.append(
                        f"{actual.name!r} {key}: expected {exp[key]}, got {got}",
                    )

    # Anything unmatched is potentially noise — flag as "extra".
    for j, _name in enumerate(actual_names):
        if j not in used:
            res.extras.append(f"extra: {items[j].name!r}")

    # Optional: total-calorie check if the case sets one.
    if "expected_total_calories" in case:
        total = sum((i.calories or 0) for i in items)
        if _num_match(total, case["expected_total_calories"]):
            res.total_calorie_check = "ok"
        else:
            res.total_calorie_check = (
                f"total cal: expected {case['expected_total_calories']}, got {total:.0f}"
            )

    # min_items soft-check (for cases where exact match list is impractical).
    if "min_items" in case and len(items) < case["min_items"]:
        res.misses.append(
            f"item count {len(items)} < min {case['min_items']}",
        )

    return res


def _print_case(r: CaseResult) -> None:
    status = "✓" if r.passed else "✗"
    color = "\033[32m" if r.passed else "\033[31m"
    reset = "\033[0m"
    print(f"  {color}{status}{reset} {r.case_id:<30} "
          f"{r.matched}/{r.expected_count} matched · "
          f"{r.elapsed_s:.1f}s · {r.raw_count} items returned")
    for m in r.misses:
        print(f"      \033[33m·\033[0m {m}")
    for m in r.macro_errors:
        print(f"      \033[33m·\033[0m {m}")
    if r.total_calorie_check and r.total_calorie_check != "ok":
        print(f"      \033[33m·\033[0m {r.total_calorie_check}")
    for e in r.extras:
        print(f"      \033[90m·\033[0m {e}")


async def _run(args: argparse.Namespace) -> int:
    cases = json.loads(CASES_PATH.read_text())
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"no case with id '{args.case}'")
            return 2

    settings = Settings(
        ollama_url=args.url,
        ollama_model=args.model,
        coach_timeout_s=args.timeout,
    )

    print(f"\nmodel:   {settings.ollama_model}")
    print(f"url:     {settings.ollama_url}")
    print(f"cases:   {len(cases)}\n")

    results: list[CaseResult] = []
    for case in cases:
        t0 = time.monotonic()
        try:
            items = await parse_food_text(settings, case["input"])
        except Exception as e:
            print(f"  \033[31m✗\033[0m {case['id']:<30} ERROR: {e}")
            results.append(CaseResult(
                case_id=case["id"], description=case.get("description", ""),
                elapsed_s=time.monotonic() - t0, raw_count=0, matched=0,
                expected_count=len(case.get("expected", [])),
                misses=[f"crashed: {e}"],
            ))
            continue
        r = _score_case(case, items)
        r.elapsed_s = time.monotonic() - t0
        results.append(r)
        _print_case(r)
        if args.verbose:
            for it in items:
                print(f"      \033[90m→ {it.name} | "
                      f"servings={it.servings} cal={it.calories} "
                      f"p={it.protein_g} c={it.carbs_g} f={it.fat_g}\033[0m")

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    avg = sum(r.elapsed_s for r in results) / total if total else 0
    print(f"\n{passed}/{total} cases passed · avg {avg:.1f}s per case\n")
    return 0 if passed == total else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Eval the food-parser prompt against a live LLM.")
    p.add_argument("--model", default="glm-4.7-flash:latest", help="Ollama model name")
    p.add_argument("--url", default="http://10.0.6.46:11434", help="Ollama base URL")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--case", help="Run a single case by id")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print every parsed item per case")
    args = p.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
