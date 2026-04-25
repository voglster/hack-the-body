"""Water tracking — thin sugar over /meals/entries with a managed Water food.

Water is just a logged consumption with category='drink'. We auto-provision
a single canonical 'Water' food the first time someone logs water so the
caller doesn't have to know the food's id. Quantity is sent in fluid
ounces (1oz = 29.5735g) which is the unit the dashboard buttons speak in.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.models.food import Food, Macros, MealEntry
from app.services.food_repo import FoodRepo

router = APIRouter(prefix="/water", dependencies=[Depends(require_api_key)])

OZ_TO_G = 29.5735
WATER_NAME = "Water"


async def _get_or_create_water_food(repo: FoodRepo) -> dict[str, Any]:
    """Lookup the singleton Water food or create it on first use."""
    hits = await repo.search_foods(WATER_NAME, limit=1)
    for h in hits:
        if h.get("name") == WATER_NAME and h.get("category") == "drink":
            return h
    food = Food(
        name=WATER_NAME,
        category="drink",
        serving_g=OZ_TO_G * 8,  # 1 serving = 8oz cup, by convention
        serving_label="1 cup (8 oz)",
        per_serving=Macros(),  # all macros zero
        source="builtin",
    )
    return await repo.upsert_food(food)


class WaterLogReq(BaseModel):
    oz: float = Field(gt=0, le=200)


@router.post("/log", status_code=201)
async def log_water(req: WaterLogReq, request: Request) -> dict[str, Any]:
    repo = FoodRepo(request.app.state.db)
    food = await _get_or_create_water_food(repo)
    grams = req.oz * OZ_TO_G
    entry = MealEntry(
        ts=datetime.now(UTC),
        food_id=food["id"],
        food_name=WATER_NAME,
        food_category="drink",
        quantity_g=grams,
        servings=req.oz / 8.0,  # 8oz per "serving"
        slot="snack",
        macros=Macros(),
    )
    return await repo.insert_entry(entry)


@router.get("/today")
async def today(
    request: Request,
    start: Annotated[datetime | None, Query(description="UTC start of day window")] = None,
    end: Annotated[datetime | None, Query(description="UTC end of day window")] = None,
) -> dict[str, Any]:
    """Total water (oz) within the given UTC window. Defaults to today UTC."""
    repo = FoodRepo(request.app.state.db)
    if start is None:
        now = datetime.now(UTC)
        start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    if end is None:
        end = start + timedelta(days=1)
    entries = await repo.list_entries_for_day(start)
    grams = 0.0
    count = 0
    for e in entries:
        if e.get("food_name") != WATER_NAME:
            continue
        ts = e["ts"]
        # mongomock-motor doesn't honor tz_aware, so coerce naive UTC to aware.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if start <= ts <= end:
            grams += float(e.get("quantity_g") or 0)
            count += 1
    return {
        "oz": round(grams / OZ_TO_G, 1),
        "ml": round(grams, 0),
        "entries": count,
        "start": start,
        "end": end,
    }
