from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.models.food import Food
from app.services.food_repo import FoodRepo
from app.services.openfoodfacts import fetch_off_product
from app.services.usda_fdc import fetch_fdc_by_barcode

router = APIRouter(prefix="/foods", dependencies=[Depends(require_api_key)])

# Sentinel values our pre-serving-resolution code wrote when OFF didn't
# publish a real serving size. Used to detect stale cached rows.
_OFF_PLACEHOLDER_SERVING_G = 100.0
_OFF_PLACEHOLDER_SERVING_LABEL = "100 g"


def _repo(r: Request) -> FoodRepo:
    return FoodRepo(r.app.state.db)


def _looks_like_legacy_off_default(cached: dict) -> bool:
    """Pre-serving-resolution OFF rows were stored with serving_g=100,
    serving_label='100 g' regardless of what OFF actually published.
    These rows make the FE log '1 serving = 100 g' for products whose
    real serving is e.g. 325 g — a 3x undercount. Treat them as stale."""
    return (
        cached.get("source") == "off"
        and float(cached.get("serving_g") or 0) == _OFF_PLACEHOLDER_SERVING_G
        and cached.get("serving_label") == _OFF_PLACEHOLDER_SERVING_LABEL
    )


@router.get("/search")
async def search(
    request: Request,
    q: Annotated[str, Query(min_length=1)],
    limit: int = 20,
) -> list[dict]:
    return await _repo(request).search_foods(q, limit=limit)


@router.get("/barcode/{barcode}")
async def by_barcode(
    barcode: str,
    request: Request,
    *,
    refresh: bool = False,
) -> dict:
    """Look up a food by barcode. Cache hit returns the stored record;
    cache miss queries Open Food Facts, then USDA FoodData Central as a
    fallback, stores whichever returned, and returns it.
    """
    repo = _repo(request)
    if not refresh:
        cached = await repo.get_food_by_barcode(barcode)
        if cached and not _looks_like_legacy_off_default(cached):
            return cached
        # Cached row predates serving-size resolution (placeholder
        # 100 g serving). Try OFF once more — if it has a real serving
        # now, the upsert below replaces the stale row. If OFF still
        # has nothing better, fall back to what we already cached.
        if cached:
            food = await fetch_off_product(barcode)
            if food and (
                food.serving_g != _OFF_PLACEHOLDER_SERVING_G
                or food.serving_label != _OFF_PLACEHOLDER_SERVING_LABEL
            ):
                return await repo.upsert_food(food)
            return cached

    food = await fetch_off_product(barcode)
    if food is None:
        api_key = request.app.state.settings.usda_fdc_api_key
        food = await fetch_fdc_by_barcode(barcode, api_key)
    if food is None:
        raise HTTPException(status_code=404, detail=f"barcode {barcode} not found")
    return await repo.upsert_food(food)


@router.post("", status_code=201)
async def create_food(food: Food, request: Request) -> dict:
    food.created_at = datetime.now(UTC)
    return await _repo(request).upsert_food(food)


@router.get("/{food_id}")
async def get_food(food_id: str, request: Request) -> dict:
    found = await _repo(request).get_food(food_id)
    if not found:
        raise HTTPException(status_code=404, detail="food not found")
    return found


class RenameFoodReq(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.patch("/{food_id}")
async def rename_food(food_id: str, req: RenameFoodReq, request: Request) -> dict:
    """Rename a Food and cascade the new name to every snapshotted meal
    entry that references it. Returns the updated Food. Used by the
    dashboard's per-entry rename affordance to fix sloppy OFF labels."""
    updated = await _repo(request).rename_food(food_id, req.name.strip())
    if updated is None:
        raise HTTPException(status_code=404, detail="food not found")
    return updated
