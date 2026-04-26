from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth import require_api_key
from app.models.food import Food, Macros, MealEntry
from app.services.food_parser import ParsedItem, parse_food_text
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


class ParseReq(BaseModel):
    text: str


def _parsed_to_dict(p: ParsedItem) -> dict:
    return {
        "name": p.name,
        "servings": p.servings,
        "calories": p.calories,
        "protein_g": p.protein_g,
        "carbs_g": p.carbs_g,
        "fat_g": p.fat_g,
    }


@router.post("/parse")
async def parse_text(req: ParseReq, request: Request) -> dict:
    """Run text through the local LLM and return structured items.
    Does NOT log anything — caller reviews and then submits via /parse/log.
    """
    settings = request.app.state.settings
    try:
        items = await parse_food_text(settings, req.text)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"parser unavailable: {type(e).__name__}: {e}",
        ) from e
    return {"items": [_parsed_to_dict(i) for i in items]}


class LogParsedItem(BaseModel):
    name: str
    servings: float = 1.0
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


class LogParsedReq(BaseModel):
    items: list[LogParsedItem]
    slot: str = "snack"
    ts: datetime | None = None


@router.post("/parse/log", status_code=201)
async def log_parsed_items(req: LogParsedReq, request: Request) -> dict:
    """Bulk-create Food + MealEntry per parsed item. Each item becomes a
    'paste'-sourced Food (so it's grouped/cleanable later) plus one
    MealEntry with the supplied total macros.
    """
    repo = _repo(request)
    when = req.ts or datetime.now(UTC)
    logged: list[dict] = []
    for it in req.items:
        macros = Macros(
            calories=it.calories,
            protein_g=it.protein_g,
            carbs_g=it.carbs_g,
            fat_g=it.fat_g,
        )
        food = Food(
            name=it.name,
            category="food",
            serving_g=1.0,  # macros are already total — quantity_g=1 means "this whole thing"
            serving_label=None,
            per_serving=macros,
            source="paste",
        )
        food.created_at = datetime.now(UTC)
        stored = await repo.upsert_food(food)
        entry = MealEntry(
            ts=when,
            food_id=stored["id"],
            food_name=stored["name"],
            food_category="food",
            quantity_g=1.0,
            servings=it.servings,
            slot=req.slot,  # type: ignore[arg-type]
            macros=macros,
        )
        logged.append(await repo.insert_entry(entry))
    return {"entries": logged, "count": len(logged)}


@router.get("/{food_id}")
async def get_food(food_id: str, request: Request) -> dict:
    found = await _repo(request).get_food(food_id)
    if not found:
        raise HTTPException(status_code=404, detail="food not found")
    return found
