from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models import BodyComp, HRV, RHR, Sleep, VO2Max, Weight, Workout


class GarminRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def _ts_upsert(self, coll: str, source_id: str, doc: dict) -> None:
        existing = await self.db[coll].find_one({"meta.source_id": source_id}, {"_id": 1})
        if existing:
            return
        await self.db[coll].insert_one(doc)

    async def upsert_weight(self, w: Weight) -> None:
        await self._ts_upsert(
            "metrics_weight",
            w.source_id,
            {"ts": w.ts, "kg": w.kg, "meta": {"source": w.source, "source_id": w.source_id}},
        )

    async def upsert_sleep(self, s: Sleep) -> None:
        await self._ts_upsert(
            "metrics_sleep",
            s.source_id,
            {
                "ts": s.ts,
                "duration_s": s.duration_s,
                "deep_s": s.deep_s,
                "rem_s": s.rem_s,
                "light_s": s.light_s,
                "awake_s": s.awake_s,
                "score": s.score,
                "meta": {"source": s.source, "source_id": s.source_id},
            },
        )

    async def upsert_hrv(self, h: HRV) -> None:
        await self._ts_upsert(
            "metrics_hrv",
            h.source_id,
            {"ts": h.ts, "rmssd_ms": h.rmssd_ms,
             "meta": {"source": h.source, "source_id": h.source_id}},
        )

    async def upsert_rhr(self, r: RHR) -> None:
        await self._ts_upsert(
            "metrics_rhr",
            r.source_id,
            {"ts": r.ts, "bpm": r.bpm,
             "meta": {"source": r.source, "source_id": r.source_id}},
        )

    async def upsert_body_comp(self, b: BodyComp) -> None:
        await self._ts_upsert(
            "metrics_body_comp",
            b.source_id,
            {
                "ts": b.ts,
                "weight_kg": b.weight_kg,
                "body_fat_pct": b.body_fat_pct,
                "muscle_mass_kg": b.muscle_mass_kg,
                "body_water_pct": b.body_water_pct,
                "bone_mass_kg": b.bone_mass_kg,
                "meta": {"source": b.source, "source_id": b.source_id},
            },
        )

    async def upsert_vo2max(self, v: VO2Max) -> None:
        await self._ts_upsert(
            "metrics_vo2max",
            v.source_id,
            {"ts": v.ts, "value": v.value,
             "meta": {"source": v.source, "source_id": v.source_id}},
        )

    async def upsert_workout(self, w: Workout) -> None:
        await self.db["workouts"].update_one(
            {"source_id": w.source_id},
            {"$set": w.model_dump()},
            upsert=True,
        )

    async def write_log(
        self, *, source: str, status: str, started_at: datetime,
        finished_at: datetime | None = None, counts: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        await self.db["ingestion_log"].insert_one({
            "source": source,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "counts": counts or {},
            "error": error,
        })

    async def consume_requests(self, source: str) -> int:
        result = await self.db["ingestion_log"].delete_many(
            {"source": source, "status": "requested"}
        )
        return result.deleted_count
