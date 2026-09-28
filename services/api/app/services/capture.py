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
from app.services.food_parser import ParsedItem, parse_food_text
from app.services.food_repo import FoodRepo, macros_for_quantity

log = logging.getLogger(__name__)

CAPTURES = "captures"
PHRASES = "capture_phrases"

AUTO_MATCH = 0.80
ASK_FLOOR = 0.55
AMBIGUITY_MARGIN = 0.05
MAX_ATTEMPTS = 5
TOKEN_FUZZ = 0.8

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
_STOPWORDS = {"a", "an", "the", "of", "some", "my", "with", "and", "fl"}


def local_tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("TZ") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def infer_slot(ts: datetime, category: str = "food") -> MealSlot:
    if category == "supplement":
        return "supplement"
    if category == "drink":
        return "snack"
    t = ts.astimezone(local_tz()).time()
    if t < time(10, 30):
        return "breakfast"
    if t < time(14, 30):
        return "lunch"
    if time(17, 0) <= t < time(21, 0):
        return "dinner"
    return "snack"


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9. ]+", " ", text.lower()).split())


def _tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t not in _STOPWORDS]


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
    async for d in db["foods"].find():
        d["id"] = str(d.pop("_id"))
        key = normalize(f"{d.get('name', '')} {d.get('brand') or ''}")
        kept = best.get(key)
        if kept is None or usage.get(d["id"], 0) > usage.get(kept["id"], 0):
            best[key] = d
    return list(best.values())


def _quantity_for(
    food: dict[str, Any], item: ParsedItem, explicit_g: float | None, last_qty: dict[str, float]
) -> float:
    if explicit_g:
        return explicit_g
    serving = float(food.get("serving_g") or 100.0)
    if item.servings and item.servings != 1.0:
        return serving * item.servings
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
        slot=infer_slot(ts, category),
        template_id=template_id,
        macros=macros_for_quantity(food, quantity_g),
        capture_id=capture_id,
    )
    return await repo.insert_entry(entry)


async def _log_estimate(
    db: AsyncDatabase, item: ParsedItem, ts: datetime, capture_id: str
) -> dict[str, Any]:
    repo = FoodRepo(db)
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
        slot=infer_slot(ts),
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


async def _phrase(db: AsyncDatabase, text: str) -> list[dict[str, Any]] | None:
    doc = await db[PHRASES].find_one({"phrase": normalize(text)})
    return doc["items"] if doc else None


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
    for item in parsed:
        name, explicit_g = split_quantity(item.name)
        learned = await _phrase(db, name)
        if learned:
            entry_ids.extend([
                (
                    await log_food(
                        db,
                        food_id=li["food_id"],
                        quantity_g=explicit_g or li["quantity_g"],
                        ts=ts,
                        capture_id=capture_id,
                    )
                )["id"]
                for li in learned
            ])
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
        if top and top.score >= AUTO_MATCH and not ambiguous:
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
            entry_ids.append((await _log_estimate(db, item, ts, capture_id))["id"])
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
        entry_ids.append((await _log_estimate(db, pi, ts, capture_id))["id"])
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


async def undo_capture(db: AsyncDatabase, capture_id: str) -> bool:
    cap = await db[CAPTURES].find_one({"_id": ObjectId(capture_id)})
    if not cap:
        return False
    await db["meal_entries"].delete_many({"meta.capture_id": capture_id})
    await db[CAPTURES].delete_one({"_id": cap["_id"]})
    return True


async def sweep_pending(settings: Settings, db: AsyncDatabase) -> int:
    n = 0
    async for cap in db[CAPTURES].find({"status": "pending"}):
        await resolve_capture(settings, db, str(cap["_id"]))
        n += 1
    return n


# ---------- suggestions ----------

HALF_LIFE_DAYS = 14.0
HOUR_SIGMA = 2.0
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
    """Rank grid keys ('food:<id>' or 'template:<id>') by recency and time-of-day."""
    scores: dict[str, float] = {}
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
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


async def suggestions(db: AsyncDatabase, limit: int = 8) -> list[dict[str, Any]]:
    tz = local_tz()
    now_local = datetime.now(tz)
    since = datetime.now(UTC) - timedelta(days=60)
    entries = [e async for e in db["meal_entries"].find({"ts": {"$gte": since}})]
    ranked = score_suggestions(entries, now_local, tz)
    repo = FoodRepo(db)
    last_qty: dict[str, float] = {}
    for e in sorted(entries, key=lambda e: e["ts"]):
        last_qty[e["food_id"]] = e.get("quantity_g") or 0
    out: list[dict[str, Any]] = []
    for key, score in ranked:
        kind, ref = key.split(":", 1)
        if kind == "template":
            tpl = await repo.get_template(ref)
            if tpl:
                out.append(
                    {
                        "kind": "template",
                        "template_id": ref,
                        "name": tpl["name"],
                        "score": round(score, 3),
                    }
                )
        else:
            food = await repo.get_food(ref)
            if food:
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
