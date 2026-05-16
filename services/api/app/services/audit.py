"""Append-only audit log for tracked mutations.

Why this exists: when a one-off `curl` accidentally clobbered the user's
targets, the only recovery was scraping recent coach insights. Going
forward, every mutation to a tracked entity appends an immutable row to
`audit_log` so we can answer "what changed, when, by whom, from what."

Schema (per row):
- `ts`: server time of the write
- `entity`: dotted label, e.g. "user_profile.targets", "meal_template"
- `entity_id`: stable key for that entity (the mongo `_id`, or the
   collection key for singletons like "targets" / "day_note")
- `op`: "create" | "update" | "delete"
- `actor`: "user" | "coach" | "system"
- `actor_ref`: optional context (e.g. coach thread_id) — null for `user`
- `before`: full doc snapshot prior to the write, or None for create
- `after`: full doc snapshot after the write, or None for delete
- `changes`: flat `{dotted.path: {from, to}}` map of diffs (derived)
- `changed_paths`: list of top-level field names that changed (queryable)

The `changes` / `changed_paths` fields are derived from `before`/`after`
via `deepdiff`. They're stored alongside the snapshots so the CLI can
pretty-print without rerunning the diff, and so mongo queries like
`{entity: "user_profile.targets", changed_paths: "daily_calories"}` can
find every change to a specific field without an aggregation pipeline.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from deepdiff import DeepDiff
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

Actor = Literal["user", "coach", "system"]
Op = Literal["create", "update", "delete"]

# DeepDiff emits paths like `root['items'][0]['qty']`. We flatten those to
# dotted `items.0.qty` so they're greppable, indexable, and human-readable.
_PATH_TOKEN = re.compile(r"\['([^']+)'\]|\[(\d+)\]")


def _flatten_path(deep_path: str) -> str:
    """Turn a DeepDiff `root['x'][0]['y']` path into `x.0.y`."""
    s = deep_path.removeprefix("root")
    parts: list[str] = []
    for m in _PATH_TOKEN.finditer(s):
        parts.append(m.group(1) if m.group(1) is not None else m.group(2))
    return ".".join(parts)


def _get_at(doc: dict[str, Any] | None, dotted: str) -> Any:
    """Walk `doc` along a dotted path (with numeric indices). Returns None
    if any segment is missing — used so we can report `from`/`to` values
    for added/removed items without separate code paths."""
    if doc is None or not dotted:
        return doc
    cur: Any = doc
    for seg in dotted.split("."):
        if cur is None:
            return None
        try:
            if seg.isdigit() and isinstance(cur, list):
                cur = cur[int(seg)]
            elif isinstance(cur, dict):
                cur = cur.get(seg)
            else:
                return None
        except (IndexError, KeyError, TypeError):
            return None
    return cur


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """Compute a flat, queryable diff between two docs.

    Returns `{"changes": {path: {from, to}}, "changed_paths": [top_level, ...]}`.
    Handles dict edits, dict adds/removes, list-index edits, and
    list-index adds/removes. Nested structures resolve to dotted paths.
    """
    dd = DeepDiff(before or {}, after or {}, ignore_order=False).to_dict()
    changes: dict[str, dict[str, Any]] = {}
    for raw_path, change in (dd.get("values_changed") or {}).items():
        path = _flatten_path(raw_path)
        changes[path] = {
            "from": change.get("old_value"),
            "to": change.get("new_value"),
        }
    # `dictionary_item_added` / `iterable_item_added` come back as either a
    # set-of-paths (when DeepDiff doesn't know the new values, rare) or a
    # dict-of-path-to-value. Handle both.
    added_raw = dd.get("dictionary_item_added") or []
    added_iter = dd.get("iterable_item_added") or {}
    for raw_path in _iter_paths(added_raw):
        path = _flatten_path(raw_path)
        changes[path] = {"from": None, "to": _get_at(after, path)}
    if isinstance(added_iter, dict):
        for raw_path, val in added_iter.items():
            path = _flatten_path(raw_path)
            changes[path] = {"from": None, "to": val}
    removed_raw = dd.get("dictionary_item_removed") or []
    removed_iter = dd.get("iterable_item_removed") or {}
    for raw_path in _iter_paths(removed_raw):
        path = _flatten_path(raw_path)
        changes[path] = {"from": _get_at(before, path), "to": None}
    if isinstance(removed_iter, dict):
        for raw_path, val in removed_iter.items():
            path = _flatten_path(raw_path)
            changes[path] = {"from": val, "to": None}
    # Top-level field names that changed — first segment of each path
    changed_paths = sorted({p.split(".", 1)[0] for p in changes if p})
    return {"changes": changes, "changed_paths": changed_paths}


def _iter_paths(obj: Any) -> list[str]:
    """DeepDiff returns added/removed as either a set, list, or dict of
    paths depending on the version + input shape — coerce to a list of
    path strings."""
    if obj is None:
        return []
    if isinstance(obj, dict):
        return list(obj.keys())
    try:
        return list(obj)
    except TypeError:
        return []


async def record_change(
    db: AsyncDatabase,
    *,
    entity: str,
    entity_id: str,
    op: Op,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    actor: Actor = "user",
    actor_ref: str | None = None,
) -> None:
    """Append one audit row. Best-effort: a failure here must never
    block the user-facing write (logged and swallowed).
    """
    try:
        d = diff(before, after)
        row = {
            "ts": datetime.now(UTC),
            "entity": entity,
            "entity_id": entity_id,
            "op": op,
            "actor": actor,
            "actor_ref": actor_ref,
            "before": before,
            "after": after,
            **d,
        }
        await db["audit_log"].insert_one(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit.record_change failed: %r", exc)
