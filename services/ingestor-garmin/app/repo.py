from datetime import datetime

from pymongo.asynchronous.database import AsyncDatabase

from app.models import (
    HRV,
    RHR,
    BodyComp,
    DailySummary,
    Sleep,
    StepsBucket,
    VO2Max,
    Weight,
    Workout,
)


class GarminRepo:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def _ts_upsert(self, coll: str, source_id: str, doc: dict) -> bool:
        existing = await self.db[coll].find_one({"meta.source_id": source_id}, {"_id": 1})
        if existing:
            return False
        await self.db[coll].insert_one(doc)
        return True

    async def _ts_replace(self, coll: str, source_id: str, doc: dict) -> bool:
        """Insert-or-replace by source_id. Time-series collections don't
        support direct updates to the time field, so we delete-then-insert.
        Used for daily_summary — today's row is a moving target since
        steps + goal change throughout the day."""
        await self.db[coll].delete_many({"meta.source_id": source_id})
        await self.db[coll].insert_one(doc)
        return True

    async def upsert_weight(self, w: Weight) -> bool:
        return await self._ts_upsert(
            "metrics_weight",
            w.source_id,
            {
                "ts": w.ts, "kg": w.kg, "raw": w.raw,
                "meta": {"source": w.source, "source_id": w.source_id},
            },
        )

    async def upsert_sleep(self, s: Sleep) -> bool:
        return await self._ts_upsert(
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
                "raw": s.raw,
                "meta": {"source": s.source, "source_id": s.source_id},
            },
        )

    async def upsert_hrv(self, h: HRV) -> bool:
        return await self._ts_upsert(
            "metrics_hrv",
            h.source_id,
            {
                "ts": h.ts, "rmssd_ms": h.rmssd_ms, "raw": h.raw,
                "meta": {"source": h.source, "source_id": h.source_id},
            },
        )

    async def upsert_rhr(self, r: RHR) -> bool:
        return await self._ts_upsert(
            "metrics_rhr",
            r.source_id,
            {
                "ts": r.ts, "bpm": r.bpm, "raw": r.raw,
                "meta": {"source": r.source, "source_id": r.source_id},
            },
        )

    async def upsert_body_comp(self, b: BodyComp) -> bool:
        return await self._ts_upsert(
            "metrics_body_comp",
            b.source_id,
            {
                "ts": b.ts,
                "weight_kg": b.weight_kg,
                "body_fat_pct": b.body_fat_pct,
                "muscle_mass_kg": b.muscle_mass_kg,
                "body_water_pct": b.body_water_pct,
                "bone_mass_kg": b.bone_mass_kg,
                "raw": b.raw,
                "meta": {"source": b.source, "source_id": b.source_id},
            },
        )

    async def upsert_vo2max(self, v: VO2Max) -> bool:
        return await self._ts_upsert(
            "metrics_vo2max",
            v.source_id,
            {
                "ts": v.ts, "value": v.value, "raw": v.raw,
                "meta": {"source": v.source, "source_id": v.source_id},
            },
        )

    async def upsert_daily_summary(self, s: DailySummary) -> bool:
        # Replace, don't skip-if-exists. The per-day row keeps mutating as
        # the user walks; if we keep the first morning sync forever, today's
        # row says steps=0 and goal=null because Garmin hadn't published
        # them yet at sync time.
        return await self._ts_replace(
            "metrics_daily_summary",
            s.source_id,
            {
                "ts": s.ts,
                "steps": s.steps,
                "step_goal": s.step_goal,
                "distance_m": s.distance_m,
                "active_kcal": s.active_kcal,
                "total_kcal": s.total_kcal,
                "resting_hr": s.resting_hr,
                "intensity_minutes": s.intensity_minutes,
                "floors_climbed": s.floors_climbed,
                "raw": s.raw,
                "meta": {"source": s.source, "source_id": s.source_id},
            },
        )

    async def upsert_steps_bucket(self, b: StepsBucket) -> bool:
        # Replace-if-changed, not insert-or-skip. Garmin retroactively revises
        # `wellnessSteps` per bucket as the watch finishes syncing and as
        # recorded activities upload — if we keep the first poll's value
        # forever, today's intraday total drifts ~1k+ steps below the real
        # daily total. Compare the value-bearing fields so the counter still
        # reflects meaningful churn.
        coll = self.db["metrics_steps_intraday"]
        # end_ts is fully determined by ts (always +15min), so we only need
        # to compare the value-bearing fields. Avoids tz-aware vs naive
        # datetime mismatches that pymongo introduces on read.
        existing = await coll.find_one(
            {"meta.source_id": b.source_id},
            {"steps": 1, "activity_level": 1},
        )
        if (
            existing
            and existing.get("steps") == b.steps
            and existing.get("activity_level") == b.activity_level
        ):
            return False
        if existing:
            await coll.delete_many({"meta.source_id": b.source_id})
        await coll.insert_one({
            "ts": b.ts,
            "end_ts": b.end_ts,
            "steps": b.steps,
            "activity_level": b.activity_level,
            "raw": b.raw,
            "meta": {"source": b.source, "source_id": b.source_id},
        })
        return True

    async def upsert_workout(self, w: Workout) -> bool:
        existing = await self.db["workouts"].find_one({"source_id": w.source_id}, {"_id": 1})
        if existing:
            return False
        await self.db["workouts"].insert_one(w.model_dump())
        return True

    async def write_log(
        self, *, source: str, status: str, started_at: datetime,
        finished_at: datetime | None = None, counts: dict[str, int] | None = None,
        error: str | None = None, kind: str = "full",
    ) -> None:
        await self.db["ingestion_log"].insert_one({
            "source": source,
            "status": status,
            "kind": kind,
            "started_at": started_at,
            "finished_at": finished_at,
            "counts": counts or {},
            "error": error,
        })

    async def consume_requests(self, source: str) -> list[str]:
        """Atomically claim all pending requests for a source. Returns the
        `kind` of each consumed request (defaults to "full" for legacy rows
        without the field). Order is insertion-order within the batch."""
        kinds: list[str] = [
            doc.get("kind") or "full"
            async for doc in self.db["ingestion_log"].find(
                {"source": source, "status": "requested"},
                sort=[("started_at", 1)],
            )
        ]
        if kinds:
            await self.db["ingestion_log"].delete_many(
                {"source": source, "status": "requested"}
            )
        return kinds
