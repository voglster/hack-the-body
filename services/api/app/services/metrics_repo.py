from datetime import datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.models.metrics import HRV, RHR, BodyComp, DailySummary, Sleep, VO2Max, Weight


class MetricsRepo:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def insert_weight(self, w: Weight) -> None:
        await self.db["metrics_weight"].insert_one(
            {
                "ts": w.ts, "kg": w.kg, "raw": w.raw,
                "meta": {"source": w.source, "source_id": w.source_id},
            },
        )

    async def latest_weight(self) -> dict[str, Any] | None:
        return await self.db["metrics_weight"].find_one(sort=[("ts", -1)])

    async def range_weight(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_weight"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    async def insert_sleep(self, s: Sleep) -> None:
        await self.db["metrics_sleep"].insert_one(
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

    async def latest_sleep(self) -> dict[str, Any] | None:
        return await self.db["metrics_sleep"].find_one(sort=[("ts", -1)])

    async def range_sleep(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_sleep"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    async def insert_hrv(self, h: HRV) -> None:
        await self.db["metrics_hrv"].insert_one(
            {
                "ts": h.ts, "rmssd_ms": h.rmssd_ms, "raw": h.raw,
                "meta": {"source": h.source, "source_id": h.source_id},
            },
        )

    async def latest_hrv(self) -> dict[str, Any] | None:
        return await self.db["metrics_hrv"].find_one(sort=[("ts", -1)])

    async def range_hrv(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_hrv"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    async def insert_rhr(self, r: RHR) -> None:
        await self.db["metrics_rhr"].insert_one(
            {
                "ts": r.ts, "bpm": r.bpm, "raw": r.raw,
                "meta": {"source": r.source, "source_id": r.source_id},
            },
        )

    async def latest_rhr(self) -> dict[str, Any] | None:
        return await self.db["metrics_rhr"].find_one(sort=[("ts", -1)])

    async def range_rhr(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_rhr"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    async def insert_body_comp(self, b: BodyComp) -> None:
        await self.db["metrics_body_comp"].insert_one(
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

    async def latest_body_comp(self) -> dict[str, Any] | None:
        return await self.db["metrics_body_comp"].find_one(sort=[("ts", -1)])

    async def insert_vo2max(self, v: VO2Max) -> None:
        await self.db["metrics_vo2max"].insert_one(
            {
                "ts": v.ts, "value": v.value, "raw": v.raw,
                "meta": {"source": v.source, "source_id": v.source_id},
            },
        )

    async def latest_vo2max(self) -> dict[str, Any] | None:
        return await self.db["metrics_vo2max"].find_one(sort=[("ts", -1)])

    async def range_vo2max(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_vo2max"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    async def range_steps_intraday(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = (
            self.db["metrics_steps_intraday"]
            .find({"ts": {"$gte": start, "$lte": end}})
            .sort("ts", 1)
        )
        return [d async for d in cur]

    # ---------- daily summary (steps, active calories, etc.) ----------
    async def insert_daily_summary(self, s: DailySummary) -> None:
        await self.db["metrics_daily_summary"].insert_one(
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
            }
        )

    async def latest_daily_summary(self) -> dict[str, Any] | None:
        """Most recent daily summary that's actually filled in.

        Garmin returns stub rows for "tomorrow" when the local TZ is well
        ahead of UTC (a 7 PM Mountain query lands on the next UTC date,
        which Garmin answers with steps=0 / step_goal=null). Without this
        guard, those stubs win latest-by-ts and the dashboard "loses" its
        step goal. Prefer a row that has step_goal set; fall back to the
        absolute latest only if no such row exists.
        """
        doc = await self.db["metrics_daily_summary"].find_one(
            {"step_goal": {"$ne": None}},
            sort=[("ts", -1)],
        )
        if doc is not None:
            return doc
        return await self.db["metrics_daily_summary"].find_one(sort=[("ts", -1)])

    async def range_daily_summary(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = (
            self.db["metrics_daily_summary"]
            .find({"ts": {"$gte": start, "$lte": end}})
            .sort("ts", 1)
        )
        return [d async for d in cur]
