import asyncio
import logging
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import get_settings
from app.garmin_client import GarminClient
from app.repo import GarminRepo
from app.runner import run_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingestor-garmin")


async def _do_sync(settings, db) -> None:
    repo = GarminRepo(db)
    started = datetime.now(timezone.utc)
    try:
        counts = await run_sync(
            client=GarminClient(settings),
            repo=repo,
            backfill_days=settings.garmin_backfill_days,
        )
        await repo.write_log(
            source="garmin", status="ok",
            started_at=started, finished_at=datetime.now(timezone.utc),
            counts=counts,
        )
        log.info("sync ok: %s", counts)
    except Exception as e:
        log.exception("sync failed")
        await repo.write_log(
            source="garmin", status="error",
            started_at=started, finished_at=datetime.now(timezone.utc),
            error=str(e),
        )


async def _poll_requests(settings, db, interval_s: int = 30) -> None:
    repo = GarminRepo(db)
    while True:
        try:
            n = await repo.consume_requests("garmin")
            if n > 0:
                log.info("on-demand trigger consumed (%d)", n)
                await _do_sync(settings, db)
        except Exception:
            log.exception("poll loop error")
        await asyncio.sleep(interval_s)


async def _run() -> None:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.mongo_db]

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: asyncio.create_task(_do_sync(settings, db)),
        CronTrigger.from_crontab(settings.garmin_schedule_cron),
        id="nightly",
    )
    scheduler.start()
    log.info("scheduler started with cron=%s; polling for on-demand requests",
             settings.garmin_schedule_cron)

    await _do_sync(settings, db)
    await _poll_requests(settings, db)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        settings = get_settings()
        client = AsyncIOMotorClient(settings.mongo_url)
        db = client[settings.mongo_db]
        asyncio.run(_do_sync(settings, db))
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
