"""How current is the Garmin data — distinct from whether the ingestor ran.

The ingestor polls Garmin every 30 min and succeeds even when the phone
hasn't pushed anything new; the watch only reaches Garmin when the Connect
app syncs (every couple of hours unless opened). So "steps are low" and
"steps haven't arrived" look identical unless we check how far the data
actually reaches.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

BUCKET = timedelta(minutes=15)
STALE_AFTER = timedelta(minutes=90)
AWAKE = (time(8, 0), time(22, 0))


def assess(latest_bucket_utc: datetime | None, now_local: datetime) -> dict[str, Any]:
    """`stale` only while awake — nothing syncing at 3am is normal."""
    awake = AWAKE[0] <= now_local.time() < AWAKE[1]
    if latest_bucket_utc is None:
        return {
            "through_local": None,
            "stale_minutes": None,
            "stale": awake,
            "summary": _stale_summary(None) if awake else "No Garmin data yet today.",
        }
    if latest_bucket_utc.tzinfo is None:
        latest_bucket_utc = latest_bucket_utc.replace(tzinfo=UTC)
    through = (latest_bucket_utc + BUCKET).astimezone(now_local.tzinfo)
    lag = now_local - through
    stale = awake and lag > STALE_AFTER
    through_hm = through.strftime("%H:%M")
    return {
        "through_local": through_hm,
        "stale_minutes": max(int(lag.total_seconds() // 60), 0),
        "stale": stale,
        "summary": _stale_summary(through_hm)
        if stale
        else f"Garmin data is current (through {through_hm}).",
    }


def _stale_summary(through_hm: str | None) -> str:
    since = f"since {through_hm}" if through_hm else "today"
    return (
        f"Garmin hasn't synced {since}. Steps, sleep and HRV are out of date — "
        "do not judge activity from them. Ask Jim to open the Garmin Connect app."
    )


async def garmin_freshness(db: AsyncDatabase, now_local: datetime) -> dict[str, Any]:
    start_of_day = datetime.combine(now_local.date(), time.min, tzinfo=now_local.tzinfo)
    latest = await db["metrics_steps_intraday"].find_one(
        {"ts": {"$gte": start_of_day.astimezone(UTC)}},
        sort=[("ts", -1)],
    )
    return assess(latest["ts"] if latest else None, now_local)
