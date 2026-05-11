"""Habits — config + daily status + auto resolvers.

Config rows live in `habits`; daily status in `habit_status` (one row per
habit per local date). `auto` habits derive their status from existing
data (sleep, vitamins, ...) via a named resolver. `manual` habits are
toggled by the user. `none` habits are just named nudges — no status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

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
