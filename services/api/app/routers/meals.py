from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.models.food import MealEntry, MealSlot, MealTemplate
from app.services.food_repo import FoodRepo, macros_for_quantity


def _resolve_window(
    start: datetime | None,
    end: datetime | None,
    day: str | None,
) -> tuple[datetime, datetime]:
    """Resolve (start, end) UTC bounds with the most-specific source winning.

    Browser callers pass explicit start/end UTC timestamps for the local
    day. Older callers may pass `day=YYYY-MM-DD` (treated as UTC). Default
    is the UTC day containing 'now'.
    """
    if start is not None:
        return start, end if end is not None else start + timedelta(days=1)
    if day is not None:
        s = datetime.combine(date.fromisoformat(day), time.min, tzinfo=UTC)
        return s, s + timedelta(days=1)
    now = datetime.now(UTC)
    s = datetime.combine(now.date(), time.min, tzinfo=UTC)
    return s, s + timedelta(days=1)


async def _entries_in_window(
    repo: FoodRepo, start: datetime, end: datetime,
) -> list[dict]:
    return await repo.list_entries_in_range(start, end)

router = APIRouter(prefix="/meals", dependencies=[Depends(require_api_key)])


def _repo(r: Request) -> FoodRepo:
    return FoodRepo(r.app.state.db)


# ---------- entries ----------

class LogEntryReq(BaseModel):
    food_id: str
    quantity_g: float = Field(gt=0)
    slot: MealSlot = "snack"
    ts: datetime | None = None
    note: str | None = None


@router.post("/entries", status_code=201)
async def log_entry(req: LogEntryReq, request: Request):
    repo = _repo(request)
    food = await repo.get_food(req.food_id)
    if not food:
        raise HTTPException(status_code=404, detail="food not found")
    macros = macros_for_quantity(food, req.quantity_g)
    entry = MealEntry(
        ts=req.ts or datetime.now(UTC),
        food_id=req.food_id,
        food_name=food["name"],
        food_category=food.get("category", "food"),
        quantity_g=req.quantity_g,
        servings=req.quantity_g / float(food.get("serving_g") or 100.0),
        slot=req.slot,
        note=req.note,
        macros=macros,
    )
    return await repo.insert_entry(entry)


@router.get("/entries")
async def list_entries(
    request: Request,
    day: Annotated[
        str | None,
        Query(description="YYYY-MM-DD; ignored if start is provided"),
    ] = None,
    start: Annotated[
        datetime | None,
        Query(description="UTC start; preferred (browser passes local-day bounds)"),
    ] = None,
    end: Annotated[datetime | None, Query(description="UTC end")] = None,
):
    s, e = _resolve_window(start, end, day)
    return await _entries_in_window(_repo(request), s, e)


@router.delete("/entries/{entry_id}", status_code=204)
async def delete_entry(entry_id: str, request: Request):
    ok = await _repo(request).delete_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="entry not found")


class EditEntryReq(BaseModel):
    ts: datetime | None = None
    slot: MealSlot | None = None


@router.patch("/entries/{entry_id}")
async def edit_entry(entry_id: str, req: EditEntryReq, request: Request):
    """Move an entry to a new time/slot. Time-series collections require
    a delete+reinsert so the returned id will differ from the original.
    """
    if req.ts is None and req.slot is None:
        raise HTTPException(status_code=400, detail="ts or slot required")
    out = await _repo(request).update_entry_time(entry_id, new_ts=req.ts, new_slot=req.slot)
    if out is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return out


@router.get("/today/totals")
async def today_totals(
    request: Request,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
):
    """Compute today's running totals across all logged entries.

    The browser passes local-day UTC bounds via start/end. When omitted,
    falls back to UTC-day for legacy callers."""
    repo = _repo(request)
    s, e = _resolve_window(start, end, None)
    entries = await _entries_in_window(repo, s, e)
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0,
              "fiber_g": 0.0, "sugar_g": 0.0, "sodium_mg": 0.0}
    by_slot: dict[str, dict[str, float]] = {}
    supplements: list[dict] = []
    for e in entries:
        m = e.get("macros") or {}
        for k in totals:
            v = m.get(k)
            if v is not None:
                totals[k] += float(v)
        slot = e.get("slot", "snack")
        by_slot.setdefault(slot, {"calories": 0.0, "protein_g": 0.0,
                                   "carbs_g": 0.0, "fat_g": 0.0})
        for k in by_slot[slot]:
            v = m.get(k)
            if v is not None:
                by_slot[slot][k] += float(v)
        if e.get("food_category") == "supplement":
            supplements.append({
                "id": e["id"], "name": e.get("food_name"), "ts": e.get("ts"),
                "quantity_g": e.get("quantity_g"),
            })
    return {
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "by_slot": {s: {k: round(v, 1) for k, v in d.items()}
                     for s, d in by_slot.items()},
        "supplements": supplements,
        "entry_count": len(entries),
    }


# ---------- templates ----------

@router.post("/templates", status_code=201)
async def create_template(t: MealTemplate, request: Request):
    return await _repo(request).upsert_template(t)


@router.get("/templates")
async def list_templates(request: Request):
    return await _repo(request).list_templates()


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: str, request: Request):
    ok = await _repo(request).delete_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="template not found")


class LogTemplateReq(BaseModel):
    slot: MealSlot | None = None
    ts: datetime | None = None


@router.post("/templates/{template_id}/log", status_code=201)
async def log_template(template_id: str, req: LogTemplateReq, request: Request):
    repo = _repo(request)
    template = await repo.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="template not found")
    slot = req.slot or template.get("default_slot", "snack")
    ts = req.ts or datetime.now(UTC)
    inserted: list[dict] = []
    for item in template.get("items", []):
        food = await repo.get_food(item["food_id"])
        if not food:
            continue  # silently skip; food was deleted
        macros = macros_for_quantity(food, float(item["quantity_g"]))
        entry = MealEntry(
            ts=ts,
            food_id=item["food_id"],
            food_name=food["name"],
            food_category=food.get("category", "food"),
            quantity_g=float(item["quantity_g"]),
            servings=float(item["quantity_g"]) / float(food.get("serving_g") or 100.0),
            slot=slot,
            template_id=template_id,
            macros=macros,
        )
        inserted.append(await repo.insert_entry(entry))
    return {"template": template["name"], "entries": inserted}
