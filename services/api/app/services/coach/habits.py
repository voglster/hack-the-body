"""Habits — config + daily status + auto resolvers.

Config rows live in `habits`; daily status in `habit_status` (one row per
habit per local date). `auto` habits derive their status from existing
data (sleep, vitamins, ...) via a named resolver. `manual` habits are
toggled by the user. `none` habits are just named nudges — no status.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

HabitKind = Literal["auto", "manual", "none"]
HabitStatusValue = Literal["done", "skipped", "missed", "unknown"]


@dataclass
class HabitConfig:
    name: str
    kind: HabitKind
    resolver: str | None = None  # required when kind == "auto"
    schedule: dict[str, Any] | None = None  # reserved; not honored this slice
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "resolver": self.resolver,
            "schedule": self.schedule,
            "active": self.active,
            "created_at": self.created_at,
        }


async def create_habit(db: AsyncDatabase, cfg: HabitConfig) -> str:
    res = await db["habits"].insert_one(cfg.to_dict())
    return str(res.inserted_id)


async def update_habit(
    db: AsyncDatabase, habit_id: str, patch: dict[str, Any],
) -> None:
    await db["habits"].update_one(
        {"_id": ObjectId(habit_id)},
        {"$set": patch},
    )


async def list_habits(db: AsyncDatabase) -> list[dict[str, Any]]:
    cur = db["habits"].find().sort("created_at", 1)
    out: list[dict[str, Any]] = []
    async for d in cur:
        d["id"] = str(d.pop("_id"))
        out.append(d)
    return out


async def get_active_habits(db: AsyncDatabase) -> list[dict[str, Any]]:
    rows = await list_habits(db)
    return [r for r in rows if r.get("active", True)]


async def get_habit_by_name(
    db: AsyncDatabase, name: str,
) -> dict[str, Any] | None:
    d = await db["habits"].find_one({"name": name})
    if d is None:
        return None
    d["id"] = str(d.pop("_id"))
    return d


async def mark_status(
    db: AsyncDatabase,
    habit_id: str,
    local_date: date,
    *,
    status: HabitStatusValue,
    source: Literal["auto", "manual", "coach"],
) -> None:
    await db["habit_status"].update_one(
        {"habit_id": habit_id, "local_date": local_date.isoformat()},
        {
            "$set": {
                "status": status,
                "source": source,
                "noted_at": datetime.now(UTC),
            },
        },
        upsert=True,
    )


async def status_for_day(
    db: AsyncDatabase, habit_id: str, local_date: date,
) -> dict[str, Any] | None:
    return await db["habit_status"].find_one(
        {"habit_id": habit_id, "local_date": local_date.isoformat()},
    )


# ---------------------------------------------------------------------------
# Auto resolvers
# ---------------------------------------------------------------------------

# Each resolver takes (db, local_date, *, tz) and returns a HabitStatusValue
# string (never None — use "unknown" if the data is missing).
ResolverFn = Callable[[AsyncDatabase, date], Awaitable[HabitStatusValue]]

BED_CUTOFF_HOUR = 22  # 22:00 local; deliberately not configurable yet


async def _bed_by_10_resolver(
    db: AsyncDatabase, local_date: date, *, tz: ZoneInfo,
) -> HabitStatusValue:
    """`done` if sleep onset was at or before 22:00 local on `local_date`."""
    # The Garmin sleep doc's `ts` is the onset (UTC). We look for any sleep
    # record whose onset falls between local-noon-of-`local_date` and
    # local-noon-the-next-day, then compare its local hour to the cutoff.
    day_start_local = datetime.combine(local_date, time(12, 0), tzinfo=tz)
    next_day_start_local = day_start_local + timedelta(days=1)
    start_utc = day_start_local.astimezone(UTC)
    end_utc = next_day_start_local.astimezone(UTC)
    doc = await db["metrics_sleep"].find_one(
        {"ts": {"$gte": start_utc, "$lt": end_utc}},
        sort=[("ts", 1)],
    )
    if doc is None:
        return "unknown"
    ts = doc["ts"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    onset_local = ts.astimezone(tz)
    cutoff = datetime.combine(
        onset_local.date(), time(BED_CUTOFF_HOUR, 0), tzinfo=tz,
    )
    return "done" if onset_local <= cutoff else "missed"


async def _vitamins_resolver(
    db: AsyncDatabase, local_date: date, *, tz: ZoneInfo,
) -> HabitStatusValue:
    """`done` if any vitamins entry was logged inside the local day."""
    day_start_local = datetime.combine(local_date, time.min, tzinfo=tz)
    next_day_local = day_start_local + timedelta(days=1)
    start_utc = day_start_local.astimezone(UTC)
    end_utc = next_day_local.astimezone(UTC)
    doc = await db["meal_entries"].find_one({
        "food_name": "Vitamins",
        "ts": {"$gte": start_utc, "$lt": end_utc},
    })
    return "done" if doc is not None else "missed"


RESOLVERS: dict[str, ResolverFn] = {
    "bed_by_10": _bed_by_10_resolver,
    "vitamins": _vitamins_resolver,
}


async def compose_today(
    db: AsyncDatabase, local_date: date, *, tz: ZoneInfo,
) -> list[dict[str, Any]]:
    """Return today's status for every active habit.

    Each item is ``{id, name, kind, status, source, resolver}``:
    - ``auto`` habits run their resolver (source = "auto").
    - ``manual`` habits read ``habit_status`` for the day (source = "manual"
      if set, else "unknown").
    - ``none`` habits are listed with status "unknown".
    """
    habits = await get_active_habits(db)
    out: list[dict[str, Any]] = []
    for h in habits:
        entry: dict[str, Any] = {
            "id": h["id"],
            "name": h["name"],
            "kind": h["kind"],
            "resolver": h.get("resolver"),
        }
        if h["kind"] == "auto":
            resolver_name = h.get("resolver") or ""
            fn = RESOLVERS.get(resolver_name)
            if fn is None:
                entry["status"] = "unknown"
                entry["source"] = "auto"
            else:
                entry["status"] = await fn(db, local_date, tz=tz)
                entry["source"] = "auto"
        elif h["kind"] == "manual":
            row = await status_for_day(db, h["id"], local_date)
            if row is None:
                entry["status"] = "unknown"
                entry["source"] = "manual"
            else:
                entry["status"] = row["status"]
                entry["source"] = row["source"]
        else:  # none
            entry["status"] = "unknown"
            entry["source"] = "none"
        out.append(entry)
    return out
