import asyncio
import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings, get_settings
from app.hevy_client import HevyClient
from app.repo import HevyRepo
from app.runner import process_event, run_backfill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ingestor-hevy")


async def _consume_requests(db: AsyncDatabase) -> list[dict]:
    """Atomically claim all requested rows for source=hevy.

    Each row carries `payload.workout_id` and `payload.event`."""
    rows: list[dict] = []
    while True:
        doc = await db["ingestion_log"].find_one_and_update(
            {"source": "hevy", "status": "requested"},
            {"$set": {"status": "claimed"}},
        )
        if doc is None:
            return rows
        rows.append(doc)


async def _process_requested(settings: Settings, db: AsyncDatabase) -> None:
    rows = await _consume_requests(db)
    if not rows:
        return
    if not settings.hevy_api_key:
        log.warning("hevy events queued but HEVY_API_KEY is not set; skipping")
        return
    client = HevyClient(api_key=settings.hevy_api_key, base_url=settings.hevy_api_base)
    repo = HevyRepo(db)
    started = datetime.now(UTC)
    counts = {"inserted": 0, "updated": 0, "noop": 0,
              "deleted": 0, "skipped": 0, "error": 0}
    for r in rows:
        wid = r["payload"]["workout_id"]
        ev = r["payload"]["event"]
        try:
            res = await process_event(repo, client, event_type=ev, workout_id=wid)
            counts[res] += 1
        except Exception:
            log.exception("hevy event %s %s failed", ev, wid)
            counts["error"] += 1
    client.close()
    await db["ingestion_log"].insert_one({
        "source": "hevy", "status": "ok", "kind": "events",
        "started_at": started, "finished_at": datetime.now(UTC),
        "counts": counts, "events_processed": len(rows),
    })
    log.info("hevy events processed: %s", counts)


async def _do_backfill(settings: Settings, db: AsyncDatabase) -> None:
    if not settings.hevy_api_key:
        log.info("HEVY_API_KEY not set; backfill skipped")
        return
    client = HevyClient(api_key=settings.hevy_api_key, base_url=settings.hevy_api_base)
    repo = HevyRepo(db)
    started = datetime.now(UTC)
    try:
        n = await run_backfill(repo, client)
        await db["ingestion_log"].insert_one({
            "source": "hevy", "status": "ok", "kind": "backfill",
            "started_at": started, "finished_at": datetime.now(UTC),
            "counts": {"upserted": n},
        })
        log.info("hevy backfill upserted %d workouts", n)
    except Exception as e:
        log.exception("hevy backfill failed")
        await db["ingestion_log"].insert_one({
            "source": "hevy", "status": "error", "kind": "backfill",
            "started_at": started, "finished_at": datetime.now(UTC),
            "error": str(e),
        })
    finally:
        client.close()


async def _poll_loop(settings: Settings, db: AsyncDatabase, interval_s: int = 30) -> None:
    while True:
        try:
            await _process_requested(settings, db)
        except Exception:
            log.exception("hevy poll loop error")
        await asyncio.sleep(interval_s)


async def _run() -> None:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongo_url, tz_aware=True)
    db = client[settings.mongo_db]

    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _scheduled() -> None:
        await _do_backfill(settings, db)

    scheduler.add_job(
        _scheduled,
        CronTrigger.from_crontab(settings.hevy_schedule_cron),
        id="hevy-backstop",
    )
    scheduler.start()
    log.info("hevy scheduler started cron=%s", settings.hevy_schedule_cron)

    await _do_backfill(settings, db)
    await _poll_loop(settings, db)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
