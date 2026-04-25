from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_api_key
from app.models.food import Food
from app.services.food_repo import FoodRepo
from app.services.openfoodfacts import fetch_off_product
from app.services.usda_fdc import fetch_fdc_by_barcode

router = APIRouter(prefix="/foods", dependencies=[Depends(require_api_key)])


def _repo(r: Request) -> FoodRepo:
    return FoodRepo(r.app.state.db)


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
        if cached:
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
