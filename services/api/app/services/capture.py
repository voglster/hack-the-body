"""Capture-first logging: record now, resolve later.

A capture is written the moment the user logs anything. Taps and buttons
resolve inline; text resolves in the background through learned phrases,
then a fuzzy catalog match, then an LLM estimate. Only a plausible-but-
unsure catalog match stops to ask — everything else acts.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.models.food import Food, Macros, MealEntry, MealSlot
from app.services.eating_window import window_bounds, window_state
from app.services.food_parser import ParsedItem, estimate_macros, parse_food_text
from app.services.food_repo import FoodRepo, macros_for_quantity

log = logging.getLogger(__name__)

CAPTURES = "captures"
PHRASES = "capture_phrases"
# A retired food is a merged-away duplicate: history keeps it, matching and suggestions don't.
ACTIVE_FOOD: dict[str, Any] = {"retired_into": {"$exists": False}}
EVENTS = "capture_events"

AUTO_MATCH = 0.80
ASK_FLOOR = 0.55
AMBIGUITY_MARGIN = 0.05
MAX_ATTEMPTS = 5
TOKEN_FUZZ = 0.85
NARROW_NAME_TOKENS = 2

_FLUID_OZ_G = 29.5735
_UNIT_G = {
    "oz": _FLUID_OZ_G,
    "ounce": _FLUID_OZ_G,
    "ounces": _FLUID_OZ_G,
    "ml": 1.0,
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "cup": 236.588,
    "cups": 236.588,
}
_QTY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(fl\.?\s*oz|oz|ounces?|ml|grams?|g|cups?)\b",
    re.IGNORECASE,
)
_STATED_MACROS_RE = re.compile(
    r"\d+\s*(k?cal|calories|g\s*protein|protein)\b|^[^:\n]+:\s*\d+\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_STOPWORDS = {"a", "an", "the", "of", "some", "my", "with", "and", "fl"}
# How much, not what: "a cup of rice" is rice.
_MEASURES = {"cup", "cups", "bowl", "bowls", "plate", "plates", "handful", "handfuls", "piece",
             "pieces", "slice", "slices", "serving", "servings", "glass", "scoop", "scoops"}


def local_tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("TZ") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def infer_slot(ts: datetime, category: str = "food", *, first_meal: bool = False) -> MealSlot:
    """The first meal of the day is breakfast whenever it lands (an 11:30
    break-fast under an eating window); later meals go by the clock."""
    if category == "supplement":
        return "supplement"
    if category == "drink":
        return "snack"
    t = ts.astimezone(local_tz()).time()
    if t < time(10, 30) or (first_meal and t < time(14, 0)):
        return "breakfast"
    if t < time(14, 30):
        return "lunch"
    if time(17, 0) <= t < time(21, 0):
        return "dinner"
    return "snack"


def local_day_start(ts: datetime) -> datetime:
    local = ts.astimezone(local_tz())
    return datetime.combine(local.date(), time.min, tzinfo=local_tz()).astimezone(UTC)


async def _slot_for(db: AsyncDatabase, ts: datetime, category: str) -> MealSlot:
    earlier = await db["meal_entries"].find_one(
        {
            "ts": {"$gte": local_day_start(ts), "$lt": ts},
            "food_category": "food",
        }
    )
    return infer_slot(ts, category, first_meal=earlier is None)


def has_stated_macros(text: str) -> bool:
    """'Shawarma: 650 cal, 45g protein' — the user's numbers beat the catalog's."""
    return bool(_STATED_MACROS_RE.search(text))


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9. ]+", " ", text.lower()).split())


def _tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t not in _STOPWORDS and t not in _MEASURES]


def split_quantity(name: str) -> tuple[str, float | None]:
    """'10 oz water' → ('water', 295.7). Quantity in grams (fluids ≈ 1 g/ml)."""
    m = _QTY_RE.search(name)
    if not m:
        return name, None
    unit = re.sub(r"[^a-z]", "", m.group(2).lower()).removeprefix("fl") or "oz"
    grams = float(m.group(1)) * _UNIT_G.get(unit, 1.0)
    return (name[: m.start()] + name[m.end() :]).strip(), grams


def _token_hit(tok: str, pool: list[str]) -> bool:
    return any(tok == p or SequenceMatcher(None, tok, p).ratio() >= TOKEN_FUZZ for p in pool)


def match_score(query: str, food: dict[str, Any]) -> float:
    q = _tokens(query)
    f = _tokens(f"{food.get('name', '')} {food.get('brand') or ''}")
    if not q or not f:
        return 0.0
    q_cov = sum(_token_hit(t, f) for t in q) / len(q)
    f_cov = sum(_token_hit(t, q) for t in f) / len(f)
    seq = SequenceMatcher(None, " ".join(q), normalize(food.get("name", ""))).ratio()
    return 0.7 * q_cov + 0.15 * f_cov + 0.15 * seq


@dataclass
class Candidate:
    food: dict[str, Any]
    score: float


def rank_catalog(
    query: str,
    foods: list[dict[str, Any]],
    usage: dict[str, int],
) -> list[Candidate]:
    """Score every food; frequently eaten foods win ties."""
    out = []
    for f in foods:
        s = match_score(query, f)
        if s <= 0:
            continue
        s += min(usage.get(f["id"], 0), 20) * 0.004
        out.append(Candidate(f, min(s, 1.0)))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


async def _catalog(
    db: AsyncDatabase,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, float]]:
    usage: dict[str, int] = {}
    last_qty: dict[str, float] = {}
    since = datetime.now(UTC) - timedelta(days=180)
    async for e in db["meal_entries"].find({"ts": {"$gte": since}}).sort("ts", 1):
        fid = e.get("food_id")
        if fid:
            usage[fid] = usage.get(fid, 0) + 1
            last_qty[fid] = e.get("quantity_g") or last_qty.get(fid, 0)
    return await _distinct_foods(db, usage), usage, last_qty


async def _distinct_foods(db: AsyncDatabase, usage: dict[str, int]) -> list[dict[str, Any]]:
    """One food per normalized name — paste/voice logging left many duplicates,
    and identical names would otherwise read as an ambiguous match."""
    best: dict[str, dict[str, Any]] = {}
    async for d in db["foods"].find(ACTIVE_FOOD):
        d["id"] = str(d.pop("_id"))
        if (
            d.get("category", "food") == "food"
            and (d.get("per_serving") or {}).get("calories") is None
        ):
            continue
        key = normalize(f"{d.get('name', '')} {d.get('brand') or ''}")
        kept = best.get(key)
        if kept is None or usage.get(d["id"], 0) > usage.get(kept["id"], 0):
            best[key] = d
    return list(best.values())


def _per_unit(food: dict[str, Any]) -> bool:
    """Stored per piece/cup/portion (serving_g of 1), so quantity is a count, not grams."""
    return float(food.get("serving_g") or 100.0) <= 1.0


def scaled_quantity(
    food: dict[str, Any], base_qty: float, item: ParsedItem, explicit_g: float | None
) -> float:
    """The amount to log: stated grams for gram-based foods, otherwise a count.

    Grams never become a count on a per-unit food — '1 cup' (236 g) of a
    per-cup rice is one cup, not 236.
    """
    if explicit_g and not _per_unit(food):
        return explicit_g
    if explicit_g and "cup" in (food.get("serving_label") or "").lower():
        return round(explicit_g / _UNIT_G["cup"], 2)
    count = item.servings if item.servings and item.servings != 1.0 else 1.0
    return base_qty * count


def _quantity_for(
    food: dict[str, Any], item: ParsedItem, explicit_g: float | None, last_qty: dict[str, float]
) -> float:
    serving = float(food.get("serving_g") or 100.0)
    if explicit_g or (item.servings and item.servings != 1.0):
        return scaled_quantity(food, serving, item, explicit_g)
    return last_qty.get(food["id"]) or serving


def _option(food: dict[str, Any], qty: float, score: float | None = None) -> dict[str, Any]:
    opt = {"food_id": food["id"], "name": food["name"], "quantity_g": round(qty, 3)}
    if score is not None:
        opt["score"] = round(score, 3)
    return opt


async def log_food(
    db: AsyncDatabase,
    *,
    food_id: str,
    quantity_g: float,
    ts: datetime,
    capture_id: str,
    template_id: str | None = None,
) -> dict[str, Any]:
    repo = FoodRepo(db)
    food = await repo.get_food(food_id)
    if not food:
        raise LookupError(f"food not found: {food_id}")
    category = food.get("category", "food")
    entry = MealEntry(
        ts=ts,
        food_id=food_id,
        food_name=food["name"],
        food_category=category,
        quantity_g=quantity_g,
        servings=quantity_g / float(food.get("serving_g") or 100.0),
        slot=await _slot_for(db, ts, category),
        template_id=template_id,
        macros=macros_for_quantity(food, quantity_g),
        capture_id=capture_id,
    )
    return await repo.insert_entry(entry)


async def _log_estimate(
    settings: Settings, db: AsyncDatabase, item: ParsedItem, ts: datetime, capture_id: str
) -> dict[str, Any]:
    repo = FoodRepo(db)
    if item.calories is None:
        try:
            item = await estimate_macros(settings, item)
        except Exception as exc:  # an unestimated entry beats a lost one
            log.warning("capture %s: estimate failed: %s", capture_id, exc)
    macros = Macros(
        calories=item.calories, protein_g=item.protein_g, carbs_g=item.carbs_g, fat_g=item.fat_g
    )
    food = Food(
        name=item.name, category="food", serving_g=1.0, per_serving=macros, source="capture"
    )
    stored = await repo.upsert_food(food)
    entry = MealEntry(
        ts=ts,
        food_id=stored["id"],
        food_name=stored["name"],
        food_category="food",
        quantity_g=1.0,
        servings=item.servings,
        slot=await _slot_for(db, ts, "food"),
        macros=macros,
        capture_id=capture_id,
    )
    return await repo.insert_entry(entry)


async def learn_phrase(db: AsyncDatabase, phrase: str, items: list[dict[str, Any]]) -> None:
    key = normalize(phrase)
    if not key or not items:
        return
    await db[PHRASES].update_one(
        {"phrase": key},
        {
            "$set": {
                "items": [{"food_id": i["food_id"], "quantity_g": i["quantity_g"]} for i in items],
                "updated_at": datetime.now(UTC),
            },
            "$inc": {"uses": 1},
        },
        upsert=True,
    )


# Words that describe *when* or *whose*, not *what*: "my morning shake" is the shake.
_MODIFIERS = {
    "morning", "afternoon", "evening", "night", "breakfast", "lunch", "dinner",
    "usual", "normal", "regular", "typical", "daily", "standard", "my", "the", "a", "an",
}


def strip_modifiers(text: str) -> str:
    return " ".join(t for t in normalize(text).split() if t not in _MODIFIERS)


async def _live_items(
    db: AsyncDatabase, items: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """A phrase's foods, following merges; None if any of them was retired outright."""
    out = []
    for item in items:
        food = await db["foods"].find_one({"_id": ObjectId(item["food_id"])}, {"retired_into": 1})
        if food is None or ("retired_into" in food and not food["retired_into"]):
            return None
        out.append({**item, "food_id": food.get("retired_into") or item["food_id"]})
    return out


async def _phrase(db: AsyncDatabase, text: str) -> list[dict[str, Any]] | None:
    core = " ".join(t for t in _tokens(text) if t not in _MODIFIERS)
    for key in dict.fromkeys((normalize(text), strip_modifiers(text), core)):
        doc = await db[PHRASES].find_one({"phrase": key}) if key else None
        if doc and (items := await _live_items(db, doc["items"])):
            return items
    return None


def narrows(query: str, food: dict[str, Any]) -> bool:
    """One generic word ("latte") against a specific variant ("Almond Milk Latte")."""
    return len(_tokens(query)) == 1 and len(_tokens(food.get("name", ""))) > NARROW_NAME_TOKENS


async def set_fields(db: AsyncDatabase, capture_id: str, **fields: Any) -> None:
    await db[CAPTURES].update_one({"_id": ObjectId(capture_id)}, {"$set": fields})


async def resolve_capture(settings: Settings, db: AsyncDatabase, capture_id: str) -> None:
    cap = await db[CAPTURES].find_one({"_id": ObjectId(capture_id)})
    if not cap or cap["status"] != "pending":
        return
    text = (cap.get("input") or {}).get("text") or ""
    ts = cap["ts"].replace(tzinfo=UTC) if cap["ts"].tzinfo is None else cap["ts"]

    whole = await _phrase(db, text)
    if whole:
        ids = [
            (
                await log_food(
                    db,
                    food_id=i["food_id"],
                    quantity_g=i["quantity_g"],
                    ts=ts,
                    capture_id=capture_id,
                )
            )["id"]
            for i in whole
        ]
        await set_fields(
            db,
            capture_id,
            status="resolved",
            entry_ids=ids,
            resolved_at=datetime.now(UTC),
            via="phrase",
        )
        return

    try:
        parsed = await parse_food_text(settings, text)
    except Exception as exc:
        log.warning("capture %s: parse failed: %s", capture_id, exc)
        attempts = cap.get("attempts", 0) + 1
        await set_fields(
            db,
            capture_id,
            attempts=attempts,
            last_error=str(exc),
            status="failed" if attempts >= MAX_ATTEMPTS else "pending",
        )
        return
    if not parsed:
        await set_fields(db, capture_id, status="failed", last_error="no food found in text")
        return

    foods, usage, last_qty = await _catalog(db)
    entry_ids: list[str] = []
    items: list[dict[str, Any]] = []
    stated = has_stated_macros(text)
    for item in parsed:
        name, explicit_g = split_quantity(item.name)
        if stated and item.calories is not None:
            entry_ids.append((await _log_estimate(settings, db, item, ts, capture_id))["id"])
            items.append({"text": name, "status": "logged", "via": "stated"})
            continue
        learned = await _phrase(db, name)
        if learned:
            entry_ids.extend(
                [
                    (
                        await log_food(
                            db,
                            food_id=li["food_id"],
                            quantity_g=scaled_quantity(
                                await db["foods"].find_one({"_id": ObjectId(li["food_id"])}) or {},
                                li["quantity_g"],
                                item,
                                explicit_g,
                            ),
                            ts=ts,
                            capture_id=capture_id,
                        )
                    )["id"]
                    for li in learned
                ]
            )
            items.append({"text": name, "status": "logged", "via": "phrase"})
            continue
        ranked = rank_catalog(name, foods, usage)
        top = ranked[0] if ranked else None
        runner_up = ranked[1] if len(ranked) > 1 else None
        ambiguous = (
            top
            and runner_up
            and top.score - runner_up.score < AMBIGUITY_MARGIN
            and runner_up.score >= AUTO_MATCH
        )
        if top and top.score >= AUTO_MATCH and not ambiguous and not narrows(name, top.food):
            qty = _quantity_for(top.food, item, explicit_g, last_qty)
            entry_ids.append(
                (
                    await log_food(
                        db, food_id=top.food["id"], quantity_g=qty, ts=ts, capture_id=capture_id
                    )
                )["id"]
            )
            items.append(
                {
                    "text": name,
                    "status": "logged",
                    "via": "match",
                    "chosen": _option(top.food, qty, top.score),
                }
            )
            await learn_phrase(db, name, [_option(top.food, qty)])
        elif top and top.score >= ASK_FLOOR:
            items.append(
                {
                    "text": name,
                    "status": "ask",
                    "candidates": [
                        _option(c.food, _quantity_for(c.food, item, explicit_g, last_qty), c.score)
                        for c in ranked[:3]
                        if c.score >= ASK_FLOOR
                    ],
                    "estimate": {
                        "name": item.name,
                        "servings": item.servings,
                        "calories": item.calories,
                        "protein_g": item.protein_g,
                        "carbs_g": item.carbs_g,
                        "fat_g": item.fat_g,
                    },
                }
            )
        else:
            entry_ids.append((await _log_estimate(settings, db, item, ts, capture_id))["id"])
            items.append({"text": name, "status": "logged", "via": "estimate"})

    status = "needs_confirm" if any(i["status"] == "ask" for i in items) else "resolved"
    await set_fields(
        db,
        capture_id,
        status=status,
        items=items,
        entry_ids=entry_ids,
        resolved_at=datetime.now(UTC) if status == "resolved" else None,
    )


async def confirm_item(
    settings: Settings,
    db: AsyncDatabase,
    capture_id: str,
    item_index: int,
    *,
    candidate_index: int | None = None,
    use_estimate: bool = False,
    skip: bool = False,
) -> dict[str, Any]:
    cap = await db[CAPTURES].find_one({"_id": ObjectId(capture_id)})
    if not cap:
        raise LookupError("capture not found")
    items = cap.get("items") or []
    item = items[item_index]
    if item["status"] != "ask":
        raise ValueError("item is not awaiting confirmation")
    ts = cap["ts"].replace(tzinfo=UTC) if cap["ts"].tzinfo is None else cap["ts"]
    entry_ids = list(cap.get("entry_ids") or [])
    if skip:
        item["status"] = "skipped"
    elif use_estimate:
        est = item["estimate"]
        pi = ParsedItem(
            name=est["name"],
            servings=est.get("servings") or 1.0,
            calories=est.get("calories"),
            protein_g=est.get("protein_g"),
            carbs_g=est.get("carbs_g"),
            fat_g=est.get("fat_g"),
        )
        entry_ids.append((await _log_estimate(settings, db, pi, ts, capture_id))["id"])
        item["status"] = "logged"
        item["via"] = "estimate"
    else:
        chosen = item["candidates"][candidate_index or 0]
        entry_ids.append(
            (
                await log_food(
                    db,
                    food_id=chosen["food_id"],
                    quantity_g=chosen["quantity_g"],
                    ts=ts,
                    capture_id=capture_id,
                )
            )["id"]
        )
        item["status"] = "logged"
        item["via"] = "confirm"
        item["chosen"] = chosen
        await learn_phrase(db, item["text"], [chosen])
    status = "needs_confirm" if any(i["status"] == "ask" for i in items) else "resolved"
    await set_fields(
        db,
        capture_id,
        items=items,
        entry_ids=entry_ids,
        status=status,
        resolved_at=datetime.now(UTC) if status == "resolved" else None,
    )
    return await get_capture(db, capture_id)  # type: ignore[return-value]


def capture_to_dict(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def get_capture(db: AsyncDatabase, capture_id: str) -> dict[str, Any] | None:
    doc = await db[CAPTURES].find_one({"_id": ObjectId(capture_id)})
    return capture_to_dict(doc) if doc else None


async def create_capture(
    db: AsyncDatabase,
    *,
    source: str,
    payload: dict[str, Any],
    status: str,
    ts: datetime | None = None,
    device: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc = {
        "ts": ts or now,
        "created_at": now,
        "source": source,
        "device": device,
        "input": payload,
        "status": status,
        "entry_ids": [],
        "attempts": 0,
    }
    res = await db[CAPTURES].insert_one(doc)
    doc["_id"] = res.inserted_id
    return capture_to_dict(doc)


def capture_label(cap: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    """What a person would call this capture: its button label, the foods, or the words."""
    names = ", ".join(e["food_name"] for e in entries)
    typed = (cap.get("input") or {}).get("text")
    return cap.get("label") or names or typed or "Ate something"


async def _entries_for(db: AsyncDatabase, capture_id: str) -> list[dict[str, Any]]:
    return [e async for e in db["meal_entries"].find({"meta.capture_id": capture_id})]


async def _retire_orphans(db: AsyncDatabase, food_ids: set[str]) -> None:
    """A food a capture invented, now eaten by nobody, would otherwise match next time."""
    for fid in food_ids:
        if await db["meal_entries"].find_one({"food_id": fid}):
            continue
        await db["foods"].update_one(
            {"_id": ObjectId(fid), "source": "capture"},
            {"$set": {"retired_into": None, "retired_at": datetime.now(UTC)}},
        )


async def undo_capture(db: AsyncDatabase, capture_id: str) -> bool:
    cap = await db[CAPTURES].find_one({"_id": ObjectId(capture_id)})
    if not cap:
        return False
    await db[EVENTS].insert_one({
        "at": datetime.now(UTC), "kind": "undone", "source": cap.get("source"),
        "label": capture_label(cap, await _entries_for(db, capture_id)),
    })
    invented = {e["food_id"] for e in await _entries_for(db, capture_id)}
    # An undo says the guess was wrong: forget any phrase this capture taught.
    for item in cap.get("items") or []:
        if item.get("via") == "match":
            await db[PHRASES].delete_one({"phrase": normalize(item["text"]), "uses": {"$lte": 1}})
    await db["meal_entries"].delete_many({"meta.capture_id": capture_id})
    await db[CAPTURES].delete_one({"_id": cap["_id"]})
    await _retire_orphans(db, invented)
    return True


REPAIR_WINDOW = timedelta(days=2)


async def repair_unestimated(settings: Settings, db: AsyncDatabase) -> int:
    """Fill in estimates that failed (LLM timeout) — a blank-calorie entry silently
    undercounts the day, so retry until it has numbers."""
    since = datetime.now(UTC) - REPAIR_WINDOW
    repaired = 0
    repo = FoodRepo(db)
    async for food in db["foods"].find({
        "source": "capture", "per_serving.calories": None, "created_at": {"$gte": since},
        **ACTIVE_FOOD,
    }):
        fid = str(food["_id"])
        try:
            est = await estimate_macros(settings, ParsedItem(name=food["name"]))
        except Exception as exc:  # still down; next sweep tries again
            log.warning("repair %s: estimate failed: %s", fid, exc)
            continue
        if est.calories is None:
            continue
        macros = Macros(calories=est.calories, protein_g=est.protein_g,
                        carbs_g=est.carbs_g, fat_g=est.fat_g).model_dump()
        await db["foods"].update_one({"_id": food["_id"]}, {"$set": {"per_serving": macros}})
        async for e in db["meal_entries"].find({"food_id": fid}):
            await repo.update_entry_time(str(e["_id"]), extra_fields={"macros": macros})
        repaired += 1
    return repaired


async def sweep_pending(settings: Settings, db: AsyncDatabase) -> int:
    await repair_unestimated(settings, db)
    n = 0
    async for cap in db[CAPTURES].find({"status": "pending"}):
        await resolve_capture(settings, db, str(cap["_id"]))
        n += 1
    return n


# ---------- suggestions ----------

HALF_LIFE_DAYS = 14.0
HOUR_SIGMA = 2.0
MIN_DAYS = 2
LOOKBACK_DAYS = 120
_EXCLUDE_NAMES = {"water", "vitamins"}


def _hour_distance(a: datetime, b: datetime) -> float:
    ha = a.hour + a.minute / 60
    hb = b.hour + b.minute / 60
    d = abs(ha - hb)
    return min(d, 24 - d)


def score_suggestions(
    entries: list[dict[str, Any]],
    now_local: datetime,
    tz: ZoneInfo,
) -> list[tuple[str, float]]:
    """Rank grid keys ('food:<id>' or 'template:<id>') by recency and time-of-day.

    Foods qualify once eaten on MIN_DAYS distinct days — a one-off restaurant
    meal is not a usual, however recent. Saved usuals (templates) always do."""
    scores: dict[str, float] = {}
    days: dict[str, set[str]] = {}
    seen_templates: set[tuple[str, str]] = set()
    for e in entries:
        ts = e["ts"] if e["ts"].tzinfo else e["ts"].replace(tzinfo=UTC)
        local = ts.astimezone(tz)
        age_days = max((now_local - local).total_seconds() / 86400, 0)
        w = 0.5 ** (age_days / HALF_LIFE_DAYS) * math.exp(
            -(_hour_distance(local, now_local) ** 2) / (2 * HOUR_SIGMA**2)
        )
        if e.get("template_id"):
            marker = (e["template_id"], local.date().isoformat())
            if marker in seen_templates:
                continue
            seen_templates.add(marker)
            key = f"template:{e['template_id']}"
        else:
            if normalize(e.get("food_name", "")) in _EXCLUDE_NAMES:
                continue
            key = f"food:{e['food_id']}"
        scores[key] = scores.get(key, 0.0) + w
        days.setdefault(key, set()).add(local.date().isoformat())
    usual = {
        k: v for k, v in scores.items()
        if k.startswith("template:") or len(days[k]) >= MIN_DAYS
    }
    return sorted(usual.items(), key=lambda kv: kv[1], reverse=True)


async def suggestions(db: AsyncDatabase, limit: int = 8) -> list[dict[str, Any]]:
    tz = local_tz()
    now_local = datetime.now(tz)
    since = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    entries = [e async for e in db["meal_entries"].find({"ts": {"$gte": since}})]
    retired = {
        str(f["_id"]): f["retired_into"]
        async for f in db["foods"].find({"retired_into": {"$exists": True}}, {"retired_into": 1})
    }
    for e in entries:
        e["food_id"] = retired.get(e["food_id"], e["food_id"])
    ranked = score_suggestions(entries, now_local, tz)
    # Saved usuals are the user's own picks: they always get a button,
    # trailing the ranked ones when they haven't been eaten lately.
    seen = {key for key, _ in ranked}
    ranked += [(f"template:{t['_id']}", 0.0) async for t in db["meal_templates"].find()
               if f"template:{t['_id']}" not in seen]
    repo = FoodRepo(db)
    last_qty: dict[str, float] = {}
    for e in sorted(entries, key=lambda e: e["ts"]):
        last_qty[e["food_id"]] = e.get("quantity_g") or 0
    out: list[dict[str, Any]] = []
    shown_foods: set[str] = set()
    for key, score in ranked:
        kind, ref = key.split(":", 1)
        if kind == "template":
            tpl = await repo.get_template(ref)
            lone = tpl["items"][0]["food_id"] if tpl and len(tpl["items"]) == 1 else None
            if tpl and lone not in shown_foods:
                if lone:
                    shown_foods.add(lone)
                out.append(
                    {
                        "kind": "template",
                        "template_id": ref,
                        "name": tpl["name"],
                        "food_ids": [i["food_id"] for i in tpl["items"]],
                        "score": round(score, 3),
                    }
                )
        else:
            food = await repo.get_food(ref) if ref not in shown_foods else None
            if food:
                shown_foods.add(ref)
                out.append(
                    {
                        "kind": "food",
                        "food_id": ref,
                        "name": food["name"],
                        "category": food.get("category", "food"),
                        "quantity_g": last_qty.get(ref) or food.get("serving_g"),
                        "score": round(score, 3),
                    }
                )
        if len(out) >= limit:
            break
    return out


# ---------- day context ----------

DEFAULT_WATER_GOAL_OZ = 100
_WATER_OZ_G = 29.5735


async def day_context(db: AsyncDatabase, limit: int = 8) -> dict[str, Any]:
    tz = local_tz()
    now_local = datetime.now(tz)
    targets = await db["user_profile"].find_one({"_id": "targets"}) or {}
    window = window_state(now_local, *window_bounds(targets))
    start = local_day_start(now_local)
    entries = await FoodRepo(db).list_entries_in_range(start, start + timedelta(days=1))
    food = [e for e in entries if e.get("food_category") == "food"]
    water_g = sum(
        e.get("quantity_g") or 0 for e in entries if normalize(e.get("food_name", "")) == "water"
    )
    eaten_foods = {e["food_id"] for e in food}
    eaten_templates = {e["template_id"] for e in food if e.get("template_id")}

    grid = await suggestions(db, limit=40)
    if window["state"] != "open":
        grid = [s for s in grid if s.get("category") == "drink"]
    grid = [
        s
        for s in grid
        if s.get("category") == "drink"
        or (s["kind"] == "food" and s["food_id"] not in eaten_foods)
        or (
            s["kind"] == "template"
            and s["template_id"] not in eaten_templates
            and not set(s["food_ids"]) <= eaten_foods
        )
    ][:limit]

    def local_hm(e: dict[str, Any]) -> str:
        ts = e["ts"] if e["ts"].tzinfo else e["ts"].replace(tzinfo=UTC)
        return ts.astimezone(tz).strftime("%H:%M")

    return {
        "now_local": now_local.isoformat(),
        "window": window,
        "vitamins_done": any(e.get("food_category") == "supplement" for e in entries),
        "water_oz": round(water_g / _WATER_OZ_G),
        "water_goal_oz": targets.get("daily_water_oz") or DEFAULT_WATER_GOAL_OZ,
        "meals": sorted({e["slot"] for e in food}),
        "first_food_at": local_hm(food[0]) if food else None,
        "last_food_at": local_hm(food[-1]) if food else None,
        "suggestions": grid,
    }


# ---------- recent activity (kiosk feed) ----------

RECENT_MINUTES = 3


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


async def recent_activity(db: AsyncDatabase, minutes: int = RECENT_MINUTES) -> list[dict[str, Any]]:
    """Everything logged or undone in the last few minutes, newest first."""
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    out: list[dict[str, Any]] = []
    async for cap in db[CAPTURES].find({"created_at": {"$gte": since}}):
        entries = await _entries_for(db, str(cap["_id"]))
        kcal = sum((e.get("macros") or {}).get("calories") or 0 for e in entries)
        water_oz = sum(e.get("quantity_g") or 0 for e in entries if e.get("food_name") == "Water")
        out.append({
            "at": _aware(cap["created_at"]).isoformat(),
            "kind": {"resolved": "logged"}.get(cap["status"], cap["status"]),
            "label": capture_label(cap, entries),
            "source": cap.get("source"),
            "kcal": round(kcal) or None,
            "water_oz": round(water_oz / _WATER_OZ_G) or None,
        })
    out.extend([
        {"at": _aware(ev["at"]).isoformat(), "kind": ev["kind"], "label": ev["label"],
         "source": ev.get("source"), "kcal": None, "water_oz": None}
        async for ev in db[EVENTS].find({"at": {"$gte": since}})
    ])
    return sorted(out, key=lambda r: r["at"], reverse=True)
