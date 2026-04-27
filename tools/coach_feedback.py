#!/usr/bin/env python3
"""Read and manage coach feedback.

Workflow:
  1. Live-use the coach for a few days, tap 👎 when it gets things wrong.
  2. Run `coach_feedback.py list` to see what piled up.
  3. Run `coach_feedback.py dump > /tmp/fb.json` and feed it to Claude with
     "review this feedback and propose edits to SYSTEM_PROMPT in
     services/api/app/services/coach.py".
  4. After applying the prompt edits, run `coach_feedback.py clear` so
     stale complaints don't keep biasing the next review (the cleared
     rows survive in `coach_feedback_archive` for the audit trail).

Subcommands:
  list                pretty-print recent feedback
  dump                stdout JSON, one feedback row per object (includes the
                      full rendered prompt, food_totals, history_snapshot —
                      everything the model saw when it earned the rating)
  show <fb_id>        deep-dive a single feedback row: full insight text,
                      rendered prompt, food_totals, history snapshot
  clear               archive all (or --before <iso>) current feedback
  count               quick tally of up vs. down + total
  insights-clear      archive coach insights so the next prompt's
                      `recent_coach_messages` doesn't include outputs from
                      a prior (now-fixed) prompt. Use after a prompt edit.
  insights-count      how many insights currently in the active set

All commands accept --since <iso> to scope by feedback timestamp; clear
takes --before <iso> instead since "before" is the natural phrasing for
"only sweep up feedback I've already reviewed."
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from textwrap import indent

from _client import client


def _parse_iso(s: str) -> str:
    """Validate the user-supplied ISO timestamp; return it as-is for the
    URL. Mostly here so a typo fails fast instead of silently returning
    everything."""
    datetime.fromisoformat(s.replace("Z", "+00:00"))
    return s


def cmd_list(args: argparse.Namespace) -> int:
    params = {"limit": args.limit}
    if args.since:
        params["since"] = _parse_iso(args.since)
    with client() as c:
        r = c.get("/coach/feedback", params=params)
        r.raise_for_status()
    rows = r.json()
    if not rows:
        print("(no feedback)")
        return 0
    for row in rows:
        face = "👍" if row["rating"] == "up" else "👎"
        ts = row["created_at"]
        ins = row.get("insight") or {}
        print(f"{face}  {ts}  insight={row['insight']['id']}")
        if row.get("note"):
            print(indent(row["note"], "      | "))
        if ins.get("text"):
            preview = ins["text"].strip().splitlines()
            preview = preview[0] if preview else ""
            if len(preview) > 140:
                preview = preview[:140] + "…"
            print(f"      ↳ insight said: {preview}")
        print()
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    params = {"limit": args.limit}
    if args.since:
        params["since"] = _parse_iso(args.since)
    with client() as c:
        r = c.get("/coach/feedback", params=params)
        r.raise_for_status()
    json.dump(r.json(), sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Print everything we have on one feedback row, in a layout that
    makes a prompt-tuning pass straightforward: rating + note → output
    text → food totals + context → recent history → full rendered prompt
    → active system prompt. Anything missing prints '(not captured)' so
    you know if it predates the prompt-input capture work."""
    with client() as c:
        r = c.get("/coach/feedback", params={"limit": 500})
        r.raise_for_status()
    rows = r.json()
    fb = next((x for x in rows if x["id"] == args.id), None)
    if fb is None:
        sys.stderr.write(f"feedback {args.id} not found in the last 500 rows\n")
        return 1
    ins = fb.get("insight") or {}
    face = "👍" if fb["rating"] == "up" else "👎"
    print(f"=== feedback {fb['id']}  {face}  {fb['created_at']}")
    if fb.get("note"):
        print(f"\nuser note:\n{indent(fb['note'], '  ')}")
    print(f"\n--- insight {ins.get('id')}  trigger={ins.get('trigger')}")
    print(f"generated_at: {ins.get('generated_at')}")
    print(f"model: {ins.get('model')}")
    print(f"\noutput:\n{indent(ins.get('text') or '(missing)', '  ')}")

    print("\n--- food_totals (input)")
    ft = ins.get("food_totals")
    print(json.dumps(ft, indent=2, default=str) if ft else "  (not captured)")

    print("\n--- context (input)")
    ctx = ins.get("context") or {}
    print(json.dumps(ctx, indent=2, default=str))

    print("\n--- history_snapshot (input)")
    hist = ins.get("history_snapshot")
    if hist:
        for h in hist:
            print(f"  - [{h.get('trigger')} @ {h.get('generated_at')}] {h.get('text', '')[:200]}")
    else:
        print("  (not captured)")

    print("\n--- system_prompt (active when generated)")
    sp = ins.get("system_prompt")
    print(indent(sp, "  ") if sp else "  (not captured)")

    print("\n--- full rendered prompt sent to LLM")
    pr = ins.get("prompt")
    print(indent(pr, "  ") if pr else "  (not captured — predates prompt capture)")
    return 0


def cmd_count(_args: argparse.Namespace) -> int:
    with client() as c:
        r = c.get("/coach/feedback", params={"limit": 500})
        r.raise_for_status()
    rows = r.json()
    up = sum(1 for r in rows if r["rating"] == "up")
    down = sum(1 for r in rows if r["rating"] == "down")
    print(f"total: {len(rows)}   👍 {up}   👎 {down}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    params: dict[str, str] = {}
    if args.before:
        params["before"] = _parse_iso(args.before)
    if not args.yes:
        target = f" before {args.before}" if args.before else ""
        confirm = input(f"archive all coach feedback{target}? [y/N] ").strip().lower()
        if confirm != "y":
            print("aborted")
            return 1
    with client() as c:
        r = c.delete("/coach/feedback", params=params)
        r.raise_for_status()
    print(f"archived {r.json()['archived']} row(s)")
    return 0


def cmd_insights_count(_args: argparse.Namespace) -> int:
    with client() as c:
        r = c.get("/coach/recent", params={"limit": 50})
        r.raise_for_status()
    rows = r.json()
    print(f"insights in active set (latest 50 visible): {len(rows)}")
    if rows:
        print(f"oldest visible: {rows[-1]['generated_at']}")
        print(f"newest:         {rows[0]['generated_at']}")
    return 0


def cmd_insights_clear(args: argparse.Namespace) -> int:
    """Archive coach insights so they stop polluting `recent_coach_messages`
    in future prompts. Pair this with a prompt edit: after deploy, clear
    so the new prompt isn't biased by output from the old one."""
    params: dict[str, str] = {}
    if args.before:
        params["before"] = _parse_iso(args.before)
    if not args.yes:
        target = f" before {args.before}" if args.before else ""
        confirm = input(
            f"archive all coach INSIGHTS{target}? "
            "(audit trail kept in coach_insights_archive) [y/N] ",
        ).strip().lower()
        if confirm != "y":
            print("aborted")
            return 1
    with client() as c:
        r = c.delete("/coach/insights", params=params)
        r.raise_for_status()
    print(f"archived {r.json()['archived']} insight(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="pretty-print recent feedback")
    sp.add_argument("--since", help="ISO timestamp lower bound (e.g. 2026-04-01T00:00:00Z)")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("dump", help="JSON to stdout (for piping into Claude)")
    sp.add_argument("--since")
    sp.add_argument("--limit", type=int, default=500)
    sp.set_defaults(func=cmd_dump)

    sp = sub.add_parser("show", help="deep-dive a single feedback row including full prompt inputs")
    sp.add_argument("id", help="feedback row id (from `list` or `dump`)")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("count", help="quick tally")
    sp.set_defaults(func=cmd_count)

    sp = sub.add_parser("clear", help="archive feedback rows so future reviews see only fresh ones")
    sp.add_argument("--before", help="only clear rows before this ISO timestamp")
    sp.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    sp.set_defaults(func=cmd_clear)

    sp = sub.add_parser(
        "insights-count",
        help="show how many coach insights are in the active set",
    )
    sp.set_defaults(func=cmd_insights_count)

    sp = sub.add_parser(
        "insights-clear",
        help="archive coach insights (use after a prompt edit so the new prompt isn't biased by old outputs)",
    )
    sp.add_argument("--before", help="only archive insights before this ISO timestamp")
    sp.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    sp.set_defaults(func=cmd_insights_clear)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
