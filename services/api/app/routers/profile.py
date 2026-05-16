"""User-set profile docs the coach reads.

Storage: separate docs in `user_profile`, keyed by `_id`:
- `_id="targets"` — calorie / protein / water / step-goal targets.
- `_id="day_note"` — short ephemeral text for *today only* ("dinner
  out tonight, low on purpose"). Auto-expires at local midnight via
  the `local_date` field — when it doesn't match today, the helpers
  return empty.
- `_id="coach_note"` — long-lived stance / philosophy ("trying to
  lose weight slowly; low calories alone are fine"). Edited rarely.

VAPID push keys live under `_id="vapid"` — same collection, different
lifecycle (app-managed secret, never user-edited).

Both `day_note` and `coach_note` feed the shared `COACH_VOICE` block in
the prompt, so they reach the kiosk glance-line AND the main coach
identically.
"""
import os
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key

router = APIRouter(prefix="/profile", dependencies=[Depends(require_api_key)])

TARGETS_KEY = "targets"
DAY_NOTE_KEY = "day_note"
COACH_NOTE_KEY = "coach_note"


def _local_today_iso() -> str:
    tz_name = os.environ.get("TZ") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(UTC).astimezone(tz).date().isoformat()


class Targets(BaseModel):
    """All optional — `null` means "no target set, coach should not judge
    against this metric." Any future targets are added here."""
    daily_calories: int | None = Field(default=None, ge=0, le=10000)
    daily_protein_g: int | None = Field(default=None, ge=0, le=500)
    daily_fat_g: int | None = Field(default=None, ge=0, le=500)
    daily_carbs_g: int | None = Field(default=None, ge=0, le=1000)
    daily_water_oz: int | None = Field(
        default=None, ge=0, le=400,
        description="Daily fluid target in fluid ounces. Half-bodyweight "
                    "rule (lb/2) is a defensible default; 128 oz/day "
                    "(1 gallon) for adult males 200-260 lb is mainstream.",
    )
    step_goal_override: int | None = Field(
        default=None, ge=0, le=100000,
        description="If set, overrides Garmin's step_goal in the dashboard "
                    "and coach context. Useful when you actively disagree "
                    "with Garmin's auto-tuned target.",
    )
    goal_weight_lb: float | None = Field(default=None, ge=50, le=600)
    weekly_loss_rate_min_lb: float | None = Field(
        default=None, ge=0, le=5,
        description="Lower bound of target weekly weight loss in lb. "
                    "Pair with the max for a band; the dashboard colors "
                    "actual rate green when inside [min, max].",
    )
    weekly_loss_rate_max_lb: float | None = Field(
        default=None, ge=0, le=5,
        description="Upper bound of target weekly weight loss in lb.",
    )


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any]:
    if doc is None:
        return Targets().model_dump()
    return {
        "daily_calories": doc.get("daily_calories"),
        "daily_protein_g": doc.get("daily_protein_g"),
        "daily_fat_g": doc.get("daily_fat_g"),
        "daily_carbs_g": doc.get("daily_carbs_g"),
        "daily_water_oz": doc.get("daily_water_oz"),
        "step_goal_override": doc.get("step_goal_override"),
        "goal_weight_lb": doc.get("goal_weight_lb"),
        "weekly_loss_rate_min_lb": doc.get("weekly_loss_rate_min_lb"),
        "weekly_loss_rate_max_lb": doc.get("weekly_loss_rate_max_lb"),
        "updated_at": doc.get("updated_at"),
    }


@router.get("/targets")
async def get_targets(request: Request) -> dict[str, Any]:
    db = request.app.state.db
    doc = await db["user_profile"].find_one({"_id": TARGETS_KEY})
    return _serialize(doc)


@router.put("/targets")
async def put_targets(req: Targets, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    update = req.model_dump()
    update["updated_at"] = datetime.now(UTC)
    await db["user_profile"].update_one(
        {"_id": TARGETS_KEY},
        {"$set": update},
        upsert=True,
    )
    return _serialize(await db["user_profile"].find_one({"_id": TARGETS_KEY}))


async def get_user_targets(db) -> dict[str, Any]:
    """Helper for non-router callers (the coach service). Returns the
    stored doc shape without HTTP wrapping."""
    return _serialize(await db["user_profile"].find_one({"_id": TARGETS_KEY}))


# ---------- day note (resets at local midnight) ----------

DAY_NOTE_MAX_LEN = 500


class DayNoteReq(BaseModel):
    text: str = Field(default="", max_length=DAY_NOTE_MAX_LEN)


def _serialize_day_note(doc: dict[str, Any] | None) -> dict[str, Any]:
    today = _local_today_iso()
    if doc is None:
        return {"text": "", "local_date": None, "is_today": False, "set_at": None}
    stored_date = doc.get("local_date")
    is_today = stored_date == today
    return {
        # When the stored note's day has rolled past, present empty
        # rather than the stale text — same shape as DELETE'd.
        "text": doc.get("text", "") if is_today else "",
        "local_date": stored_date,
        "is_today": is_today,
        "set_at": doc.get("set_at"),
    }


@router.get("/day-note")
async def get_day_note_route(request: Request) -> dict[str, Any]:
    db = request.app.state.db
    doc = await db["user_profile"].find_one({"_id": DAY_NOTE_KEY})
    return _serialize_day_note(doc)


@router.put("/day-note")
async def put_day_note(req: DayNoteReq, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    text = req.text.strip()
    if not text:
        # Empty body == delete. Saves a round-trip and matches what the
        # browser sends when the user clears the input and blurs.
        await db["user_profile"].delete_one({"_id": DAY_NOTE_KEY})
        return _serialize_day_note(None)
    await db["user_profile"].update_one(
        {"_id": DAY_NOTE_KEY},
        {"$set": {
            "text": text,
            "local_date": _local_today_iso(),
            "set_at": datetime.now(UTC),
        }},
        upsert=True,
    )
    return _serialize_day_note(
        await db["user_profile"].find_one({"_id": DAY_NOTE_KEY}),
    )


@router.delete("/day-note")
async def delete_day_note(request: Request) -> dict[str, Any]:
    db = request.app.state.db
    await db["user_profile"].delete_one({"_id": DAY_NOTE_KEY})
    return _serialize_day_note(None)


async def get_day_note(db) -> str | None:
    """Helper for the coach service. Returns the current note's text, or
    None when no note is set OR the stored note's `local_date` has rolled
    past (i.e. yesterday's note never bleeds into today's prompt).
    """
    doc = await db["user_profile"].find_one({"_id": DAY_NOTE_KEY})
    if doc is None:
        return None
    if doc.get("local_date") != _local_today_iso():
        return None
    text = (doc.get("text") or "").strip()
    return text or None


# ---------- coach note (long-lived stance) ----------

COACH_NOTE_MAX_LEN = 2000


class CoachNoteReq(BaseModel):
    text: str = Field(default="", max_length=COACH_NOTE_MAX_LEN)


def _serialize_coach_note(doc: dict[str, Any] | None) -> dict[str, Any]:
    if doc is None:
        return {"text": "", "updated_at": None}
    return {
        "text": doc.get("text", ""),
        "updated_at": doc.get("updated_at"),
    }


@router.get("/coach-note")
async def get_coach_note_route(request: Request) -> dict[str, Any]:
    db = request.app.state.db
    doc = await db["user_profile"].find_one({"_id": COACH_NOTE_KEY})
    return _serialize_coach_note(doc)


@router.put("/coach-note")
async def put_coach_note(req: CoachNoteReq, request: Request) -> dict[str, Any]:
    db = request.app.state.db
    text = req.text.strip()
    if not text:
        await db["user_profile"].delete_one({"_id": COACH_NOTE_KEY})
        return _serialize_coach_note(None)
    await db["user_profile"].update_one(
        {"_id": COACH_NOTE_KEY},
        {"$set": {"text": text, "updated_at": datetime.now(UTC)}},
        upsert=True,
    )
    return _serialize_coach_note(
        await db["user_profile"].find_one({"_id": COACH_NOTE_KEY}),
    )


async def get_coach_note(db) -> str | None:
    """Helper for the coach service. Returns the stored standing-stance
    text, or None when nothing is set.
    """
    doc = await db["user_profile"].find_one({"_id": COACH_NOTE_KEY})
    if doc is None:
        return None
    text = (doc.get("text") or "").strip()
    return text or None
