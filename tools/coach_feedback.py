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
  list             pretty-print recent feedback
  dump             stdout JSON, one feedback row per object
  clear            archive all (or --before <iso>) current feedback
  count            quick tally of up vs. down + total

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

    sp = sub.add_parser("count", help="quick tally")
    sp.set_defaults(func=cmd_count)

    sp = sub.add_parser("clear", help="archive feedback rows so future reviews see only fresh ones")
    sp.add_argument("--before", help="only clear rows before this ISO timestamp")
    sp.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    sp.set_defaults(func=cmd_clear)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
