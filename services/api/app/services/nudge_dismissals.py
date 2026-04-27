"""Per-day dismissal overlay for prescriptive nudges.

One Mongo doc per local-date, shape:

    { _id: "<user>_<YYYY-MM-DD>",
      entries: { vitamins_missing: <iso utc ts>, ... } }

`<user>` is a constant placeholder — this app is single-user and we don't
yet model accounts. When that changes, replace USER_KEY with a real user id.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Literal

from pymongo.asynchronous.database import AsyncDatabase

from app.services.nudges import _local_tz

USER_KEY = "default"


def _doc_id(now_utc: datetime) -> str:
    local_date = now_utc.astimezone(_local_tz()).date().isoformat()
    return f"{USER_KEY}_{local_date}"


def end_of_day_local(now_utc: datetime) -> datetime:
    """Local end-of-day (== start of *tomorrow*) for the date that contains `now_utc`."""
    tz = _local_tz()
    local = now_utc.astimezone(tz)
    next_local_midnight = datetime.combine(
        local.date() + timedelta(days=1), time.min, tzinfo=tz,
    )
    return next_local_midnight.astimezone(UTC)


def _resolve_until(
    until: Literal["end_of_day"] | str,
    now_utc: datetime,
) -> datetime:
    if until == "end_of_day":
        return end_of_day_local(now_utc)
    # ISO timestamp string
    parsed = datetime.fromisoformat(until)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def record_dismissal(
    db: AsyncDatabase,
    *,
    nudge_id: str,
    until: Literal["end_of_day"] | str,
    now_utc: datetime | None = None,
) -> None:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    until_dt = _resolve_until(until, now_utc)
    await db["nudge_dismissals"].update_one(
        {"_id": _doc_id(now_utc)},
        {"$set": {f"entries.{nudge_id}": until_dt}},
        upsert=True,
    )


async def get_active_dismissals(
    db: AsyncDatabase,
    *,
    now_utc: datetime | None = None,
) -> set[str]:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    doc = await db["nudge_dismissals"].find_one({"_id": _doc_id(now_utc)})
    if not doc:
        return set()
    entries = doc.get("entries") or {}
    out: set[str] = set()
    for nudge_id, until in entries.items():
        if isinstance(until, datetime):
            until_dt = until if until.tzinfo else until.replace(tzinfo=UTC)
        else:
            try:
                until_dt = datetime.fromisoformat(str(until))
                if until_dt.tzinfo is None:
                    until_dt = until_dt.replace(tzinfo=UTC)
            except Exception:
                continue
        if until_dt > now_utc:
            out.add(nudge_id)
    return out
