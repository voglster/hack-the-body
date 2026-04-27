#!/usr/bin/env python3
"""Recommend daily calorie + protein targets, then optionally write them
to /profile/targets so the coach uses them.

The math: Mifflin-St Jeor BMR (the equation everyone serious uses since
1990 — slightly more accurate than Harris-Benedict for adults), then a
TDEE multiplier from a self-reported activity tier, then a deficit
based on the goal weekly weight change. Protein recommendation tracks
ISSN/ACSM cutting guidance: ~0.8–1.0 g per lb of *target* body weight
preserves lean mass through a sustained deficit.

Activity-tier guessing is a known source of error — beginners
overestimate, the multipliers were derived from athletes. Pass
`--activity auto` to skip the guessing entirely: the tool pulls the
last 14 days of Garmin daily_summary from /metrics/daily_summary/range,
takes the median `total_kcal` (Garmin's per-day measured burn), and
uses that as observed TDEE. This is the "honest" number — what your
body has actually been doing. Falls back to a multiplier tier if you
have <5 days of data.

Inputs that change the math:
  --age 44 --sex male --height-in 77 --weight-lb 250
  --activity auto                (auto | sedentary | light | moderate | very | athlete)
  --goal lose-1lb-week           (maintain | lose-0.5lb | lose-1lb-week | lose-1.5lb-week)
  --target-weight-lb 195         (used for protein math; defaults to 'healthy BMI midpoint')

Latest weight can be auto-pulled from /metrics/summary (latest Garmin
scale reading) so you only have to type it once. Pass --pull-weight to
opt in.

Usage:
  recommend                      print the recommendation
  apply --yes                    recommend AND write to /profile/targets
                                 (skip the y/n confirm with --yes)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from _client import client

# ---- conversions ------------------------------------------------------------

KG_PER_LB = 0.45359237
CM_PER_IN = 2.54


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB


def in_to_cm(inches: float) -> float:
    return inches * CM_PER_IN


# ---- activity multipliers ---------------------------------------------------
# Standard Katch-McArdle / NSCA tiers. The numbers are from the literature;
# not opinions. "athlete" is for people doing heavy training >1h/day.
ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,    # desk job, no deliberate exercise
    "light":     1.375,  # 1–3 light sessions / week, mostly walking
    "moderate":  1.55,   # 3–5 sessions / week, some lifting or runs
    "very":      1.725,  # 6–7 sessions / week, structured training
    "athlete":   1.9,    # 2-a-days, high training volume
}

# Weekly weight change → daily kcal deficit. 1 lb of fat ≈ 3500 kcal so
# 1 lb / week ≈ 500 kcal / day. The lookup is named for clarity in the CLI.
GOAL_WEEKLY_DEFICIT_KCAL: dict[str, float] = {
    "maintain":          0.0,
    "lose-0.5lb-week":   250.0,
    "lose-1lb-week":     500.0,
    "lose-1.5lb-week":   750.0,  # aggressive — flag in the output
}


@dataclass
class Recommendation:
    bmr: int
    tdee: int
    deficit: int
    recommended_calories: int
    recommended_protein_g: int
    target_weight_lb: int
    notes: list[str]
    # When activity == "auto", these document what the auto-detect saw.
    # Otherwise None.
    tdee_source: str = "formula"  # "formula" | "observed" | "blend"
    observed_tdee: int | None = None
    observed_days: int = 0


def mifflin_st_jeor_bmr(*, weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Mifflin-St Jeor (1990). Validated as the most accurate widely-used
    BMR equation for non-obese adults. For obese adults use of LBM-based
    Katch-McArdle is technically better but requires a body-fat-% input;
    we'd rather be slightly low than ask for something the user may not
    know."""
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return base + (5.0 if sex == "male" else -161.0)


def healthy_bmi_target_weight_lb(height_cm: float) -> int:
    """Mid-point of the "healthy BMI" band (BMI 22). Standard nutrition-
    counselor heuristic for "what should this person aim for". Intentionally
    conservative; many lifters carry more lean mass and look great at 24-25."""
    height_m = height_cm / 100.0
    bmi_target = 22.0
    kg = bmi_target * (height_m ** 2)
    return round(kg / KG_PER_LB)


MIN_AUTO_DAYS = 5  # below this, fall back to a tier estimate
AUTO_KCAL_FLOOR = 1000  # exclude obviously-partial days from the median


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def observed_tdee_from_history(rows: list[dict]) -> tuple[int, int]:
    """Median Garmin total_kcal over real-data days. Returns
    (median_tdee, days_used). Filters out days under AUTO_KCAL_FLOOR
    (partial-day stubs)."""
    kcals = [
        float(r["total_kcal"]) for r in rows
        if r.get("total_kcal") is not None and r["total_kcal"] >= AUTO_KCAL_FLOOR
    ]
    if not kcals:
        return 0, 0
    return int(round(_median(kcals))), len(kcals)


def recommend(
    *, age: int, sex: str, height_in: float, weight_lb: float,
    activity: str, goal: str, target_weight_lb: int | None,
    history_rows: list[dict] | None = None,
) -> Recommendation:
    """Compute a recommendation. When `activity="auto"` and `history_rows`
    has >= MIN_AUTO_DAYS rows of usable data, TDEE comes from observed
    Garmin burn instead of a multiplier guess."""
    height_cm = in_to_cm(height_in)
    weight_kg = lb_to_kg(weight_lb)
    bmr = mifflin_st_jeor_bmr(
        weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex,
    )
    deficit = GOAL_WEEKLY_DEFICIT_KCAL[goal]
    notes: list[str] = []

    obs_tdee = 0
    obs_days = 0
    if activity == "auto":
        obs_tdee, obs_days = observed_tdee_from_history(history_rows or [])
        if obs_days >= MIN_AUTO_DAYS:
            tdee = obs_tdee
            tdee_source = "observed"
            # Sanity check: if observed TDEE is implausibly low (below
            # BMR), the wearable was probably off-wrist a lot. Warn but
            # still use observed since it's calibrated to *this* body.
            if obs_tdee < bmr * 0.95:
                notes.append(
                    f"observed TDEE ({obs_tdee}) is below predicted BMR "
                    f"({int(round(bmr))}). Wearable may have been off-wrist; "
                    "consider running with --activity light to compare.",
                )
        else:
            # Cold-start: fall back to "light" as the most common honest
            # tier for someone new to tracking.
            tdee = bmr * ACTIVITY_FACTORS["light"]
            tdee_source = "formula"
            notes.append(
                f"only {obs_days} day(s) of usable Garmin history; "
                f"falling back to formula at 'light' activity. "
                "Re-run with --activity auto after 2 weeks of wear.",
            )
    else:
        factor = ACTIVITY_FACTORS[activity]
        tdee = bmr * factor
        tdee_source = "formula"

    rec_cal = tdee - deficit

    if target_weight_lb is None:
        target_weight_lb = healthy_bmi_target_weight_lb(height_cm)

    # Protein: 0.9 g / lb of target body weight is the sweet spot for a
    # sustained deficit. Round to nearest 5 for ergonomics.
    rec_protein = int(round(target_weight_lb * 0.9 / 5.0) * 5)

    if rec_cal < 1800 and sex == "male":
        notes.append(
            "WARNING: recommended kcal under 1,800 for an adult male — "
            "this is crash-cut territory and unsustainable past 4–6 weeks. "
            "Consider easing the goal (e.g. lose-1lb-week) or eating back "
            "exercise calories."
        )
    if goal == "lose-1.5lb-week":
        notes.append(
            "1.5 lb/week is aggressive. Plan to step up to lose-1lb-week "
            "after 8–12 weeks to protect lean mass and HRV."
        )
    if activity == "athlete" and goal != "maintain":
        notes.append(
            "'athlete' multiplier + a deficit is a hard combo. Recovery "
            "tanks fast. Monitor HRV and sleep score weekly; consider a "
            "smaller deficit if either drops >10%."
        )

    return Recommendation(
        bmr=int(round(bmr)),
        tdee=int(round(tdee)),
        deficit=int(deficit),
        recommended_calories=int(round(rec_cal)),
        recommended_protein_g=rec_protein,
        target_weight_lb=target_weight_lb,
        notes=notes,
        tdee_source=tdee_source,
        observed_tdee=obs_tdee or None,
        observed_days=obs_days,
    )


# ---- CLI plumbing -----------------------------------------------------------

def _pull_latest_weight_lb() -> float | None:
    try:
        with client() as c:
            r = c.get("/metrics/summary")
            r.raise_for_status()
            data = r.json()
        kg = (data.get("weight") or {}).get("kg")
        if kg is None:
            return None
        return kg / KG_PER_LB
    except Exception as e:
        sys.stderr.write(f"warning: couldn't pull latest weight ({e}); pass --weight-lb\n")
        return None


def _pull_daily_summary_history(days: int) -> list[dict]:
    """Fetch the last N days of Garmin daily_summary for auto-detect."""
    try:
        with client() as c:
            r = c.get("/metrics/daily_summary/range", params={"days": days})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        sys.stderr.write(f"warning: couldn't pull daily history ({e}); auto-detect disabled\n")
        return []


def _print(rec: Recommendation, args: argparse.Namespace) -> None:
    print("=== inputs ===")
    print(f"  age={args.age}  sex={args.sex}  height={args.height_in}\"  weight={args.weight_lb} lb")
    print(f"  activity={args.activity}  goal={args.goal}")
    print(f"  target_weight_lb={rec.target_weight_lb}")
    print("\n=== math ===")
    print(f"  BMR (Mifflin-St Jeor):     {rec.bmr:>5} kcal/day")
    if rec.tdee_source == "observed":
        print(
            f"  TDEE (observed Garmin):    {rec.tdee:>5} kcal/day  "
            f"(median of {rec.observed_days} days)",
        )
        # Show what the formula would have said as a sanity reference.
        formula_light = int(round(rec.bmr * ACTIVITY_FACTORS["light"]))
        print(f"    formula 'light' would predict:    {formula_light} kcal/day")
    else:
        factor = ACTIVITY_FACTORS.get(args.activity, ACTIVITY_FACTORS["light"])
        label = args.activity if args.activity != "auto" else f"light (auto fallback)"
        print(f"  TDEE @ {label:<18} {rec.tdee:>5} kcal/day  (BMR × {factor})")
    print(f"  deficit:                   {rec.deficit:>5} kcal/day  ({args.goal})")
    print("\n=== recommendation ===")
    print(f"  daily calories:  {rec.recommended_calories:>5} kcal")
    print(f"  daily protein:   {rec.recommended_protein_g:>5} g    (≈0.9 g/lb of target weight)")
    if rec.notes:
        print("\n=== notes ===")
        for n in rec.notes:
            print(f"  • {n}")


def cmd_recommend(args: argparse.Namespace) -> int:
    rec = _build(args)
    _print(rec, args)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    rec = _build(args)
    _print(rec, args)
    if not args.yes:
        confirm = input(
            f"\nWrite calories={rec.recommended_calories}, "
            f"protein={rec.recommended_protein_g} to /profile/targets? [y/N] ",
        ).strip().lower()
        if confirm != "y":
            print("aborted (no write)")
            return 1
    body = {
        "daily_calories": rec.recommended_calories,
        "daily_protein_g": rec.recommended_protein_g,
    }
    if args.step_goal:
        body["step_goal_override"] = args.step_goal
    with client() as c:
        r = c.put("/profile/targets", json=body)
        r.raise_for_status()
    print("\nwrote targets:")
    for k, v in r.json().items():
        print(f"  {k}: {v}")
    return 0


def _build(args: argparse.Namespace) -> Recommendation:
    if args.weight_lb is None:
        if args.pull_weight:
            pulled = _pull_latest_weight_lb()
            if pulled is None:
                sys.stderr.write("error: --pull-weight set but no weight in /metrics/summary\n")
                sys.exit(2)
            args.weight_lb = round(pulled, 1)
            print(f"(pulled latest weight from API: {args.weight_lb} lb)\n")
        else:
            sys.stderr.write("error: --weight-lb required (or pass --pull-weight)\n")
            sys.exit(2)
    history_rows: list[dict] | None = None
    if args.activity == "auto":
        history_rows = _pull_daily_summary_history(args.auto_days)
    return recommend(
        age=args.age, sex=args.sex, height_in=args.height_in,
        weight_lb=args.weight_lb, activity=args.activity, goal=args.goal,
        target_weight_lb=args.target_weight_lb,
        history_rows=history_rows,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--age", type=int, required=True)
        sp.add_argument("--sex", choices=["male", "female"], default="male")
        sp.add_argument("--height-in", type=float, required=True,
                        help="height in inches (e.g. 77 for 6'5\")")
        sp.add_argument("--weight-lb", type=float,
                        help="current weight in lb (or use --pull-weight)")
        sp.add_argument("--pull-weight", action="store_true",
                        help="auto-pull latest weight from /metrics/summary")
        sp.add_argument(
            "--activity",
            choices=["auto", *ACTIVITY_FACTORS.keys()],
            default="auto",
            help="auto = use median Garmin total_kcal from last 14 days (default)",
        )
        sp.add_argument(
            "--auto-days", type=int, default=14,
            help="how many days of history to median over when activity=auto",
        )
        sp.add_argument("--goal", choices=list(GOAL_WEEKLY_DEFICIT_KCAL),
                        default="lose-1lb-week")
        sp.add_argument("--target-weight-lb", type=int,
                        help="goal weight in lb (default: BMI 22 midpoint)")

    sp = sub.add_parser("recommend", help="print the recommendation")
    add_common(sp)
    sp.set_defaults(func=cmd_recommend)

    sp = sub.add_parser("apply", help="recommend AND write to /profile/targets")
    add_common(sp)
    sp.add_argument("--step-goal", type=int, help="also set step_goal_override")
    sp.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    sp.set_defaults(func=cmd_apply)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
