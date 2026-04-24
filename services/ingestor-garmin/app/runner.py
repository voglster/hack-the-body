import logging
from datetime import date, timedelta
from typing import Protocol

from app.mappers import (
    map_body_comp,
    map_hrv,
    map_sleep,
    map_vo2max,
    map_weight,
    map_workout,
)
from app.repo import GarminRepo

log = logging.getLogger(__name__)


class ClientProto(Protocol):
    def login(self) -> None: ...
    def fetch_sleep(self, d: date) -> dict: ...
    def fetch_hrv(self, d: date) -> dict: ...
    def fetch_weight(self, s: date, e: date) -> list[dict]: ...
    def fetch_body_comp(self, s: date, e: date) -> list[dict]: ...
    def fetch_vo2max(self, d: date) -> dict: ...
    def fetch_workouts(self, s: date, e: date) -> list[dict]: ...
    def fetch_rhr_series(self, s: date, e: date) -> list[dict]: ...


async def run_sync(*, client: ClientProto, repo: GarminRepo, backfill_days: int) -> dict[str, int]:
    client.login()
    end = date.today()
    start = end - timedelta(days=backfill_days)
    counts = {"weight": 0, "body_comp": 0, "sleep": 0, "hrv": 0, "vo2max": 0, "workouts": 0}

    try:
        for w in map_weight(client.fetch_weight(start, end)):
            if await repo.upsert_weight(w):
                counts["weight"] += 1
    except Exception as e:
        log.exception("weight fetch failed: %s", e)

    try:
        for b in map_body_comp(client.fetch_body_comp(start, end)):
            if await repo.upsert_body_comp(b):
                counts["body_comp"] += 1
    except Exception as e:
        log.exception("body_comp fetch failed: %s", e)

    day = end
    for _ in range(backfill_days + 1):
        try:
            if await repo.upsert_sleep(map_sleep(client.fetch_sleep(day))):
                counts["sleep"] += 1
        except Exception as e:
            log.warning("sleep %s skipped: %s", day, e)
        try:
            if await repo.upsert_hrv(map_hrv(client.fetch_hrv(day))):
                counts["hrv"] += 1
        except Exception as e:
            log.warning("hrv %s skipped: %s", day, e)
        try:
            if await repo.upsert_vo2max(map_vo2max(client.fetch_vo2max(day))):
                counts["vo2max"] += 1
        except Exception as e:
            log.warning("vo2max %s skipped: %s", day, e)
        day -= timedelta(days=1)

    try:
        for wo in map_workout(client.fetch_workouts(start, end)):
            if await repo.upsert_workout(wo):
                counts["workouts"] += 1
    except Exception as e:
        log.exception("workouts fetch failed: %s", e)

    return counts
