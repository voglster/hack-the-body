from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from app.models import StrengthSet, Workout


def _as_utc(dt: datetime) -> datetime:
    """Return dt as UTC-aware; attach UTC if naive (mongomock strips tzinfo)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class HevyRepo:
    def __init__(self, db: AsyncDatabase) -> None:
        self.db = db

    async def get_existing_updated_at(self, source_id: str) -> datetime | None:
        doc = await self.db["workouts"].find_one(
            {"source_id": source_id},
            projection={"updated_at": 1},
        )
        if doc is None:
            return None
        raw = doc.get("updated_at")
        return _as_utc(raw) if raw is not None else None

    async def upsert_workout_with_sets(
        self,
        workout: Workout,
        sets: list[StrengthSet],
    ) -> bool:
        """Insert or replace a Hevy workout and its sets.

        Returns True if anything was written, False if the existing
        document's `updated_at` was equal-or-newer (no-op).
        """
        existing = await self.get_existing_updated_at(workout.source_id)
        if existing is not None and existing >= _as_utc(workout.updated_at):
            return False

        # Replace workout document (upsert=True creates if absent).
        await self.db["workouts"].replace_one(
            {"source_id": workout.source_id},
            workout.model_dump(),
            upsert=True,
        )
        # Replace sets: delete all children for this workout, insert new.
        await self.db["strength_sets"].delete_many(
            {"workout_source_id": workout.source_id},
        )
        if sets:
            await self.db["strength_sets"].insert_many(
                [s.model_dump() for s in sets],
            )
        return True

    async def delete_workout(self, source_id: str) -> bool:
        result = await self.db["workouts"].delete_one({"source_id": source_id})
        await self.db["strength_sets"].delete_many({"workout_source_id": source_id})
        return result.deleted_count > 0
