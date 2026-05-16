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
    # Optional side-effect run when the habit transitions to "done". Names
    # are keys in HABIT_ACTIONS. The pattern: many habits ARE the user
    # doing something tracked elsewhere (vitamins → a meal_entry), so the
    # generic habit "I did it" gesture can produce the same side effect
    # the dedicated UI would. Idempotent per local day.
    on_done_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "resolver": self.resolver,
            "schedule": self.schedule,
            "active": self.active,
            "created_at": self.created_at,
            "on_done_action": self.on_done_action,
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
    tz: ZoneInfo | None = None,
) -> dict[str, Any]:
    """Set today's status for a habit, optionally running its on-done action.

    Returns a small summary of what happened so callers (the router, HA
    automation) can show the user concrete feedback. The status row is
    upserted by (habit_id, local_date) so double-tapping the IKEA remote
    that triggers this can't produce duplicate work — both the upsert
    AND the registered actions are idempotent per local day.
    """
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
    action_result: dict[str, Any] | None = None
    # Side-effect only fires on transition into "done" (not skipped/missed)
    # AND only when we have a tz to resolve "today" in (router always
    # provides one; tests that don't care can omit). Each registered
    # action is idempotent per (habit, local_date) so re-runs are safe.
    if status == "done" and tz is not None:
        habit_doc = await db["habits"].find_one({"_id": ObjectId(habit_id)})
        action_name = (habit_doc or {}).get("on_done_action")
        if action_name:
            fn = HABIT_ACTIONS.get(action_name)
            if fn is not None:
                action_result = await fn(db, local_date, tz=tz)
    return {"action_ran": action_result is not None, "action": action_result}


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


# ---------------------------------------------------------------------------
# On-done actions — side effects that fire when a habit is marked done.
# ---------------------------------------------------------------------------
#
# Each action takes (db, local_date, *, tz) and returns a small summary dict
# (or None if it was a no-op because today's work was already done). All
# actions MUST be idempotent per local day — a double-tap on the IKEA
# remote, a network retry from HA, or a manual click after a kiosk press
# all converge on the same final state.

ActionFn = Callable[[AsyncDatabase, date], Awaitable[dict[str, Any] | None]]


async def _log_vitamins_action(
    db: AsyncDatabase, local_date: date, *, tz: ZoneInfo,
) -> dict[str, Any] | None:
    """Create today's vitamins meal-entry if none exists yet.

    Idempotent — second/third calls on the same local day return the
    existing entry summary unchanged. This is the pattern HA's IKEA-
    remote automation relies on: hit /habits/{vitamins}/status as many
    times as the button bounces; meal_entries gets exactly one row.
    """
    # Imports inside the function to avoid pulling food_repo + models into
    # the habits module's top-level (which would invert the dependency:
    # coach/habits.py is consumed by routers/habits.py and shouldn't pull
    # router-adjacent collaborators eagerly).
    from app.models.food import Food, Macros, MealEntry  # noqa: PLC0415
    from app.services.food_repo import FoodRepo  # noqa: PLC0415

    repo = FoodRepo(db)
    day_start_local = datetime.combine(local_date, time.min, tzinfo=tz)
    next_day_local = day_start_local + timedelta(days=1)
    start_utc = day_start_local.astimezone(UTC)
    end_utc = next_day_local.astimezone(UTC)
    existing = await db["meal_entries"].find_one({
        "food_name": "Vitamins",
        "ts": {"$gte": start_utc, "$lt": end_utc},
    })
    if existing is not None:
        return {
            "kind": "log_vitamins",
            "created": False,
            "reason": "already logged today",
        }
    # Reuse-or-create the canonical Vitamins food row so the entry joins
    # cleanly against /foods/search and the FE auto-complete.
    hits = await repo.search_foods("Vitamins", limit=5)
    food: dict[str, Any] | None = None
    for h in hits:
        if h.get("name") == "Vitamins" and h.get("category") == "supplement":
            food = h
            break
    if food is None:
        food = await repo.upsert_food(Food(
            name="Vitamins", category="supplement", serving_g=1.0,
            serving_label="1 stack", per_serving=Macros(), source="builtin",
        ))
    entry = MealEntry(
        ts=datetime.now(UTC),
        food_id=food["id"],
        food_name="Vitamins",
        food_category="supplement",
        quantity_g=1.0,
        servings=1.0,
        slot="supplement",
        macros=Macros(),
    )
    inserted = await repo.insert_entry(entry)
    return {"kind": "log_vitamins", "created": True, "entry_id": inserted.get("id")}


HABIT_ACTIONS: dict[str, ActionFn] = {
    "log_vitamins": _log_vitamins_action,
}


async def ensure_default_habits(db: AsyncDatabase) -> None:
    """Idempotent bootstrap so the canonical habits exist on a fresh DB.

    Right now this is just the Vitamins habit so the dashboard card and
    Home-Assistant IKEA-remote automation both have a habit_id to target
    out of the box. New default habits added here should always check
    by name first — running this on an established DB must not duplicate
    or overwrite user customizations.
    """
    existing = await db["habits"].find_one({"name": "Vitamins"})
    if existing is not None:
        # Backfill on_done_action if a Vitamins habit was created before
        # this field existed; otherwise leave the user's customization alone.
        if not existing.get("on_done_action"):
            await db["habits"].update_one(
                {"_id": existing["_id"]},
                {"$set": {"on_done_action": "log_vitamins"}},
            )
        return
    await create_habit(db, HabitConfig(
        name="Vitamins",
        kind="manual",
        on_done_action="log_vitamins",
    ))


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
