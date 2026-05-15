import asyncio
import logging
import random
import sys
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pymongo import AsyncMongoClient

from app.config import get_settings
from app.garmin_client import GarminClient
from app.repo import GarminRepo
from app.runner import run_steps_sync, run_sync
from app.treadmill_uploader import upload_pending

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingestor-garmin")


async def _do_sync(settings, db, *, kind: str = "full", startup_jitter_s: int = 0) -> None:
    repo = GarminRepo(db)
    if startup_jitter_s > 0:
        delay = random.randint(0, startup_jitter_s)
        log.info("startup jitter: sleeping %ds before sync", delay)
        await asyncio.sleep(delay)
    started = datetime.now(UTC)
    try:
        if kind == "steps":
            counts = await run_steps_sync(
                client=GarminClient(settings),
                repo=repo,
            )
        else:
            counts = await run_sync(
                client=GarminClient(settings),
                repo=repo,
                backfill_days=settings.garmin_backfill_days,
            )
        await repo.write_log(
            source="garmin", status="ok", kind=kind,
            started_at=started, finished_at=datetime.now(UTC),
            counts=counts,
        )
        log.info("sync ok (%s): %s", kind, counts)
    except Exception as e:
        log.exception("sync failed (%s)", kind)
        await repo.write_log(
            source="garmin", status="error", kind=kind,
            started_at=started, finished_at=datetime.now(UTC),
            error=str(e),
        )


async def _poll_requests(settings, db, interval_s: int = 30) -> None:
    repo = GarminRepo(db)
    while True:
        try:
            kinds = await repo.consume_requests("garmin")
            # Collapse: any "full" subsumes "steps" in the same batch.
            if kinds:
                effective = "full" if "full" in kinds else "steps"
                log.info("on-demand trigger consumed (%d, kinds=%s, running=%s)",
                         len(kinds), kinds, effective)
                await _do_sync(settings, db, kind=effective)
        except Exception:
            log.exception("poll loop error")
        await asyncio.sleep(interval_s)


async def _treadmill_upload_loop(settings, db, interval_s: int = 60) -> None:
    """Push finalized treadmill workouts to Garmin. The watch doesn't
    auto-record the walk and Garmin's daily steps under-count without
    our upload, so this fills the gap."""
    while True:
        try:
            counts = await upload_pending(db, GarminClient(settings))
            if counts["uploaded"] or counts["failed"]:
                log.info("treadmill -> garmin: %s", counts)
        except Exception:
            log.exception("treadmill upload loop error")
        await asyncio.sleep(interval_s)


async def _run() -> None:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongo_url, tz_aware=True)
    db = client[settings.mongo_db]

    scheduler = AsyncIOScheduler(timezone="UTC")
    # Nightly cron fires at the configured minute, but we add up to 15 min
    # of randomized startup jitter inside _do_sync so we don't ping Garmin at the
    # exact same instant every night. Register an async coroutine fn (not a
    # lambda) so AsyncIOScheduler routes the job to its AsyncIOExecutor.

    async def _scheduled_sync() -> None:
        await _do_sync(settings, db, startup_jitter_s=900)

    async def _scheduled_steps_sync() -> None:
        # Light pull of today's daily summary so the kiosk catches Garmin
        # Connect updates within ~30 min instead of next-day. The watch
        # itself only reaches Connect when the phone's BT bridge syncs,
        # so this is best-effort: if the phone hasn't synced, the pull
        # returns the same data as last cycle. Cheap either way.
        await _do_sync(settings, db, kind="steps")

    scheduler.add_job(
        _scheduled_sync,
        CronTrigger.from_crontab(settings.garmin_schedule_cron),
        id="nightly",
    )
    scheduler.add_job(
        _scheduled_steps_sync,
        CronTrigger.from_crontab(
            settings.garmin_steps_schedule_cron,
            timezone=settings.garmin_steps_schedule_tz,
        ),
        id="intraday_steps",
    )
    scheduler.start()
    log.info(
        "scheduler started: nightly=%s, steps=%s (%s); polling for on-demand requests",
        settings.garmin_schedule_cron,
        settings.garmin_steps_schedule_cron,
        settings.garmin_steps_schedule_tz,
    )

    await _do_sync(settings, db)
    # Run the treadmill uploader concurrently with the request poller.
    await asyncio.gather(
        _poll_requests(settings, db),
        _treadmill_upload_loop(settings, db),
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        settings = get_settings()
        client = AsyncMongoClient(settings.mongo_url, tz_aware=True)
        db = client[settings.mongo_db]
        asyncio.run(_do_sync(settings, db))
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
