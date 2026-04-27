import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.mappers import (
    map_body_comp,
    map_daily_summary,
    map_hrv,
    map_intraday_steps,
    map_sleep,
    map_vo2max,
    map_weight,
    map_workout,
)
from app.repo import GarminRepo

log = logging.getLogger(__name__)

JitterFn = Callable[[], Awaitable[None]]


async def _default_jitter() -> None:
    """0.5-3s random pause between API calls so we don't look like a tight loop."""
    await asyncio.sleep(random.uniform(0.5, 3.0))


async def _no_jitter() -> None:
    return


class ClientProto(Protocol):
    def login(self) -> None: ...
    def fetch_sleep(self, d: date) -> dict: ...
    def fetch_hrv(self, d: date) -> dict: ...
    def fetch_weight(self, s: date, e: date) -> list[dict]: ...
    def fetch_body_comp(self, s: date, e: date) -> list[dict]: ...
    def fetch_vo2max(self, d: date) -> dict: ...
    def fetch_workouts(self, s: date, e: date) -> list[dict]: ...
    def fetch_rhr_series(self, s: date, e: date) -> list[dict]: ...
    def fetch_daily_summary(self, d: date) -> dict: ...
    def fetch_intraday_steps(self, d: date) -> list[dict]: ...


def _is_empty_daily_summary(ds) -> bool:
    """A 'tomorrow stub' has no real data. Match: zero steps AND no goal
    AND no calories. Real days always have at least one of these set."""
    return (
        (ds.steps == 0)
        and ds.step_goal is None
        and ds.total_kcal in (None, 0)
        and ds.active_kcal in (None, 0)
    )


async def _do_weight(client, repo, start, end, counts):
    try:
        for w in map_weight(client.fetch_weight(start, end)):
            if await repo.upsert_weight(w):
                counts["weight"] += 1
    except Exception:
        log.exception("weight fetch failed")


async def _do_body_comp(client, repo, start, end, counts):
    try:
        for b in map_body_comp(client.fetch_body_comp(start, end)):
            if await repo.upsert_body_comp(b):
                counts["body_comp"] += 1
    except Exception:
        log.exception("body_comp fetch failed")


async def _do_workouts(client, repo, start, end, counts):
    try:
        for wo in map_workout(client.fetch_workouts(start, end)):
            if await repo.upsert_workout(wo):
                counts["workouts"] += 1
    except Exception:
        log.exception("workouts fetch failed")


async def _do_daily_per_day(client, repo, days, counts, jitter: JitterFn):
    """Per-day endpoints (sleep / HRV / VO2max / daily summary / intraday steps).

    Sleep/HRV/VO2max/daily-summary are single-record-per-day. Intraday steps
    returns a list of 96 buckets per day. Order randomized within each day.
    """
    shuffled_days = list(days)
    random.shuffle(shuffled_days)
    for day in shuffled_days:
        single = [
            ("sleep", lambda d=day: client.fetch_sleep(d), map_sleep, repo.upsert_sleep),
            ("hrv", lambda d=day: client.fetch_hrv(d), map_hrv, repo.upsert_hrv),
            ("vo2max", lambda d=day: client.fetch_vo2max(d), map_vo2max, repo.upsert_vo2max),
            (
                "daily_summary",
                lambda d=day: client.fetch_daily_summary(d),
                map_daily_summary,
                repo.upsert_daily_summary,
            ),
        ]
        random.shuffle(single)
        for name, fetch, mapper, upsert in single:
            try:
                mapped = mapper(fetch())
                # Garmin returns stub daily_summary rows for "tomorrow"
                # when the user's local TZ is past midnight UTC. They
                # have steps=0 and step_goal=None; persisting them makes
                # latest_daily_summary() return a useless row and the
                # dashboard "loses" its step goal. Skip them.
                if name == "daily_summary" and _is_empty_daily_summary(mapped):
                    continue
                if await upsert(mapped):
                    counts[name] += 1
            except Exception as e:
                log.warning("%s %s skipped: %s", name, day, e)
            await jitter()

        # Intraday steps: list-of-buckets endpoint. Each new bucket = +1 count.
        try:
            buckets = map_intraday_steps(client.fetch_intraday_steps(day))
            for bucket in buckets:
                if await repo.upsert_steps_bucket(bucket):
                    counts["steps_intraday"] += 1
        except Exception as e:
            log.warning("steps_intraday %s skipped: %s", day, e)
        await jitter()


async def run_steps_sync(
    *,
    client: ClientProto,
    repo: GarminRepo,
) -> dict[str, int]:
    """Focused sync: just today's intraday_steps. Used for the 'sync my steps'
    button. Live total = sum(intraday buckets); the step_goal lives on
    daily_summary which the nightly full sync already keeps fresh, so we
    skip it here for speed (one Garmin call instead of two)."""
    client.login()
    today = datetime.now(UTC).date()
    counts = {"steps_intraday": 0}
    try:
        for bucket in map_intraday_steps(client.fetch_intraday_steps(today)):
            if await repo.upsert_steps_bucket(bucket):
                counts["steps_intraday"] += 1
    except Exception as e:
        log.warning("steps_intraday %s skipped: %s", today, e)
    return counts


async def run_sync(
    *,
    client: ClientProto,
    repo: GarminRepo,
    backfill_days: int,
    jitter: JitterFn = _default_jitter,
) -> dict[str, int]:
    client.login()
    end = datetime.now(UTC).date()
    start = end - timedelta(days=backfill_days)
    counts = {"weight": 0, "body_comp": 0, "sleep": 0, "hrv": 0, "vo2max": 0,
              "daily_summary": 0, "steps_intraday": 0, "workouts": 0}

    days = [end - timedelta(days=i) for i in range(backfill_days + 1)]

    # Range-based fetches (one call covers the whole window) — order them randomly.
    range_steps = [
        ("weight", _do_weight),
        ("body_comp", _do_body_comp),
        ("workouts", _do_workouts),
    ]
    random.shuffle(range_steps)

    # Interleave range steps with the per-day chunk; pick where per-day lands randomly.
    insertion = random.randint(0, len(range_steps))
    schedule = list(range_steps)
    schedule.insert(insertion, ("daily", None))

    log.info("sync schedule: %s", [s[0] for s in schedule])

    for name, fn in schedule:
        if name == "daily":
            await _do_daily_per_day(client, repo, days, counts, jitter)
        else:
            await fn(client, repo, start, end, counts)
        await jitter()

    return counts
