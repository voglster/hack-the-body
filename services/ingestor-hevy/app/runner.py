import logging
from typing import Literal, Protocol

from app.mappers import map_strength_sets, map_workout
from app.repo import HevyRepo

log = logging.getLogger(__name__)

EventType = Literal["workout.created", "workout.updated", "workout.deleted"]
ProcessResult = Literal["inserted", "updated", "noop", "deleted", "skipped"]


class HevyClientProto(Protocol):
    def get_workout(self, workout_id: str) -> dict: ...
    def list_workouts(self, page: int, page_size: int) -> dict: ...


async def process_event(
    repo: HevyRepo,
    client: HevyClientProto,
    *,
    event_type: EventType,
    workout_id: str,
) -> ProcessResult:
    if event_type == "workout.deleted":
        ok = await repo.delete_workout(f"hevy:{workout_id}")
        return "deleted" if ok else "skipped"

    raw = client.get_workout(workout_id)
    workout = map_workout(raw)
    sets = map_strength_sets(raw)
    existing = await repo.get_existing_updated_at(workout.source_id)
    changed = await repo.upsert_workout_with_sets(workout, sets)
    if not changed:
        return "noop"
    return "updated" if existing is not None else "inserted"


async def run_backfill(
    repo: HevyRepo,
    client: HevyClientProto,
    *,
    page_size: int = 10,
) -> int:
    """Page through Hevy's full workout list, upserting each."""
    total = 0
    page = 1
    while True:
        resp = client.list_workouts(page=page, page_size=page_size)
        workouts = resp.get("workouts") or []
        for raw in workouts:
            workout = map_workout(raw)
            sets = map_strength_sets(raw)
            if await repo.upsert_workout_with_sets(workout, sets):
                total += 1
        page_count = int(resp.get("page_count") or 1)
        if page >= page_count:
            break
        page += 1
    return total
