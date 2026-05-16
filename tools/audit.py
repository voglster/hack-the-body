"""View the audit log from the terminal.

Usage:
    python tools/audit.py show targets              # last 20 changes to user_profile.targets
    python tools/audit.py show targets --field daily_calories
    python tools/audit.py show meal_template
    python tools/audit.py recent --actor coach      # what the coach has been changing
    python tools/audit.py json --entity user_profile.targets --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from _client import client

ENTITY_ALIASES = {
    "targets": "user_profile.targets",
    "day-note": "user_profile.day_note",
    "coach-note": "user_profile.coach_note",
    "templates": "meal_template",
    "template": "meal_template",
}


def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(ts)


def _fmt_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, str) and len(v) > 60:
        return v[:57] + "…"
    if isinstance(v, dict | list):
        return json.dumps(v, default=str)[:60]
    return repr(v)


def _print_pretty(rows: list[dict[str, Any]], field_filter: str | None) -> None:
    if not rows:
        print("(no audit rows)")
        return
    for row in rows:
        ts = _fmt_ts(row.get("ts", ""))
        actor = row.get("actor", "?")
        actor_ref = row.get("actor_ref")
        op = row.get("op", "?")
        entity = row.get("entity", "?")
        entity_id = row.get("entity_id", "?")
        ref_suffix = f" ({actor_ref})" if actor_ref else ""
        print(f"\n● {ts}  {op:<6}  {entity}  [{entity_id}]")
        print(f"  by {actor}{ref_suffix}")
        changes: dict[str, dict[str, Any]] = row.get("changes") or {}
        if field_filter:
            changes = {
                k: v for k, v in changes.items()
                if k == field_filter or k.startswith(field_filter + ".")
            }
        if not changes:
            print("  (no field-level diff)")
            continue
        for path in sorted(changes):
            ch = changes[path]
            print(f"    {path}: {_fmt_value(ch.get('from'))}  →  {_fmt_value(ch.get('to'))}")


def cmd_show(args: argparse.Namespace) -> int:
    entity = ENTITY_ALIASES.get(args.entity, args.entity)
    params: dict[str, Any] = {"entity": entity, "limit": args.limit}
    if args.id:
        params["entity_id"] = args.id
    if args.field:
        params["changed_path"] = args.field.split(".", 1)[0]
    with client() as c:
        r = c.get("/audit/log", params=params)
    r.raise_for_status()
    rows = r.json()
    _print_pretty(rows, args.field)
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {"limit": args.limit}
    if args.actor:
        params["actor"] = args.actor
    if args.entity:
        params["entity"] = ENTITY_ALIASES.get(args.entity, args.entity)
    with client() as c:
        r = c.get("/audit/log", params=params)
    r.raise_for_status()
    _print_pretty(r.json(), None)
    return 0


def cmd_json(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {"limit": args.limit}
    if args.entity:
        params["entity"] = ENTITY_ALIASES.get(args.entity, args.entity)
    if args.id:
        params["entity_id"] = args.id
    if args.field:
        params["changed_path"] = args.field.split(".", 1)[0]
    if args.actor:
        params["actor"] = args.actor
    with client() as c:
        r = c.get("/audit/log", params=params)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="show history for one entity")
    p_show.add_argument("entity", help="entity label or alias (e.g. 'targets')")
    p_show.add_argument("--id", help="entity_id (optional)")
    p_show.add_argument("--field", help="filter to a specific changed field (dotted path)")
    p_show.add_argument("--limit", type=int, default=20)
    p_show.set_defaults(func=cmd_show)

    p_recent = sub.add_parser("recent", help="show most-recent rows across all entities")
    p_recent.add_argument("--actor", choices=["user", "coach", "system"])
    p_recent.add_argument("--entity", help="filter to one entity label/alias")
    p_recent.add_argument("--limit", type=int, default=20)
    p_recent.set_defaults(func=cmd_recent)

    p_json = sub.add_parser("json", help="raw JSON dump for scripting")
    p_json.add_argument("--entity")
    p_json.add_argument("--id")
    p_json.add_argument("--field")
    p_json.add_argument("--actor")
    p_json.add_argument("--limit", type=int, default=20)
    p_json.set_defaults(func=cmd_json)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
