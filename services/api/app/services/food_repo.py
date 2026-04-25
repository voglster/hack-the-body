"""Mongo repo for foods, meal entries, and templates.

Mongo `_id` is exposed as the model's `id` (string) on read; on write we let
mongo allocate it.
"""
import logging
from datetime import UTC, datetime, time
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.models.food import Food, Macros, MealEntry, MealTemplate

logger = logging.getLogger(__name__)


def _oid(s: str) -> ObjectId:
    return ObjectId(s)


def _doc_to_dict(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    out = {**doc, "id": str(doc["_id"])}
    out.pop("_id", None)
    return out


class FoodRepo:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    # ---------- foods ----------
    async def upsert_food(self, food: Food) -> dict[str, Any]:
        """Upsert by barcode if present; else insert as new.

        `created_at` is owned by `$setOnInsert` so it stays stable across
        re-fetches; we drop it from the `$set` payload to avoid a Mongo
        path-conflict error.
        """
        doc = food.model_dump(exclude={"id"})
        if food.barcode:
            doc.pop("created_at", None)
            await self.db["foods"].update_one(
                {"barcode": food.barcode},
                {"$set": doc, "$setOnInsert": {"created_at": datetime.now(UTC)}},
                upsert=True,
            )
            stored = await self.db["foods"].find_one({"barcode": food.barcode})
        else:
            # Sparse unique index on barcode skips *absent* fields, not
            # nulls — so emit no key at all when there's no barcode.
            doc.pop("barcode", None)
            res = await self.db["foods"].insert_one(doc)
            stored = await self.db["foods"].find_one({"_id": res.inserted_id})
        return _doc_to_dict(stored)  # type: ignore[return-value]

    async def get_food(self, food_id: str) -> dict[str, Any] | None:
        return _doc_to_dict(await self.db["foods"].find_one({"_id": _oid(food_id)}))

    async def get_food_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        return _doc_to_dict(await self.db["foods"].find_one({"barcode": barcode}))

    async def search_foods(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if not query:
            return []
        # text index search; fall back to regex if no text index (e.g. mongomock)
        try:
            cur = self.db["foods"].find(
                {"$text": {"$search": query}},
                {"score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})]).limit(limit)
            rows = [_doc_to_dict(d) async for d in cur]
            if rows:
                return rows  # type: ignore[return-value]
        except Exception as exc:  # text index optional (mongomock fallback)
            logger.debug("text search unavailable, falling back to regex: %s", exc)
        cur = self.db["foods"].find(
            {"$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"brand": {"$regex": query, "$options": "i"}},
            ]}
        ).limit(limit)
        return [_doc_to_dict(d) async for d in cur]  # type: ignore[return-value]

    # ---------- meal entries ----------
    async def insert_entry(self, e: MealEntry) -> dict[str, Any]:
        doc = e.model_dump(exclude={"id"})
        # time-series collections require a known meta field
        doc["meta"] = {"food_id": e.food_id, "slot": e.slot}
        res = await self.db["meal_entries"].insert_one(doc)
        # Time-series doesn't always allow find_one by _id; query by all fields
        stored = await self.db["meal_entries"].find_one({"_id": res.inserted_id})
        return _doc_to_dict(stored)  # type: ignore[return-value]

    async def list_entries_for_day(self, day: datetime) -> list[dict[str, Any]]:
        """day is interpreted as UTC midnight start."""
        start = datetime.combine(day.date(), time.min, tzinfo=UTC)
        end = datetime.combine(day.date(), time.max, tzinfo=UTC)
        cur = self.db["meal_entries"].find(
            {"ts": {"$gte": start, "$lte": end}}
        ).sort("ts", 1)
        return [_doc_to_dict(d) async for d in cur]  # type: ignore[return-value]

    async def delete_entry(self, entry_id: str) -> bool:
        res = await self.db["meal_entries"].delete_one({"_id": _oid(entry_id)})
        return res.deleted_count > 0

    async def update_entry_time(
        self,
        entry_id: str,
        new_ts: datetime | None = None,
        new_slot: str | None = None,
    ) -> dict[str, Any] | None:
        """Move an entry to a new timestamp / slot.

        Time-series collections in MongoDB don't allow updating the time
        field, so we delete the original and reinsert with the new fields.
        Returns the new doc (with a fresh _id) or None if not found.
        """
        existing = await self.db["meal_entries"].find_one({"_id": _oid(entry_id)})
        if not existing:
            return None
        new_doc = {k: v for k, v in existing.items() if k != "_id"}
        if new_ts is not None:
            new_doc["ts"] = new_ts
        if new_slot is not None:
            new_doc["slot"] = new_slot
            meta = dict(new_doc.get("meta") or {})
            meta["slot"] = new_slot
            new_doc["meta"] = meta
        await self.db["meal_entries"].delete_one({"_id": _oid(entry_id)})
        res = await self.db["meal_entries"].insert_one(new_doc)
        stored = await self.db["meal_entries"].find_one({"_id": res.inserted_id})
        return _doc_to_dict(stored)

    # ---------- templates ----------
    async def upsert_template(self, t: MealTemplate) -> dict[str, Any]:
        doc = t.model_dump(exclude={"id"})
        await self.db["meal_templates"].update_one(
            {"name": t.name},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(UTC)}},
            upsert=True,
        )
        stored = await self.db["meal_templates"].find_one({"name": t.name})
        return _doc_to_dict(stored)  # type: ignore[return-value]

    async def list_templates(self) -> list[dict[str, Any]]:
        cur = self.db["meal_templates"].find().sort("name", 1)
        return [_doc_to_dict(d) async for d in cur]  # type: ignore[return-value]

    async def get_template(self, template_id: str) -> dict[str, Any] | None:
        return _doc_to_dict(
            await self.db["meal_templates"].find_one({"_id": _oid(template_id)})
        )

    async def delete_template(self, template_id: str) -> bool:
        res = await self.db["meal_templates"].delete_one({"_id": _oid(template_id)})
        return res.deleted_count > 0


def macros_for_quantity(food: dict[str, Any], quantity_g: float) -> Macros:
    """Scale a food's per-serving macros to a real quantity in grams."""
    serving_g = float(food.get("serving_g") or 100.0)
    factor = quantity_g / serving_g if serving_g else 0.0
    per = food.get("per_serving") or {}
    def s(k: str) -> float | None:
        v = per.get(k)
        return round(v * factor, 2) if v is not None else None
    return Macros(
        calories=s("calories"),
        protein_g=s("protein_g"),
        carbs_g=s("carbs_g"),
        fat_g=s("fat_g"),
        fiber_g=s("fiber_g"),
        sugar_g=s("sugar_g"),
        sodium_mg=s("sodium_mg"),
    )
