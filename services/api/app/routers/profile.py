"""User-set targets (calories, protein, optional step-goal override).

Storage: a single doc in `user_profile` keyed `_id="targets"`. We keep
this separate from the existing `_id="vapid"` doc because the lifecycles
differ — VAPID keys are app-managed secrets, targets are user data the
person edits regularly.

The coach reads these and includes them in its prompt context so the
LLM can say "you're at 1,500 / 2,200 cal" instead of guessing from a
stale assumed baseline.
"""
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key

router = APIRouter(prefix="/profile", dependencies=[Depends(require_api_key)])

TARGETS_KEY = "targets"


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
