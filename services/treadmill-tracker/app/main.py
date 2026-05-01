"""Treadmill tracker entrypoint.

Polls the ESP8266 CSAFE bridge in idle/active modes and writes raw
samples to Mongo. Crash-safe by design — restart and resume.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from pymongo import AsyncMongoClient

from app.bridge import Bridge
from app.config import get_settings
from app.poller import Mode, Poller
from app.repo import ensure_collection, write_log, write_sample

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("treadmill-tracker")


async def run() -> None:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongo_url, tz_aware=True)
    db = client[settings.mongo_db]
    await ensure_collection(db)
    await write_log(db, status="started", started_at=datetime.now(UTC))

    bridge = Bridge(settings.bridge_host, settings.bridge_port)
    poller = Poller(
        bridge,
        active_hz=settings.active_poll_hz,
        idle_interval_s=settings.idle_probe_interval_s,
        active_timeout_s=settings.active_read_timeout_s,
        idle_timeout_s=settings.idle_read_timeout_s,
        active_fail_threshold=settings.active_fail_threshold,
    )
    log.info("tracker started, bridge=%s:%d, mode=%s",
             settings.bridge_host, settings.bridge_port, poller.mode.value)

    try:
        while True:
            result = await asyncio.to_thread(poller.tick)
            if result.mode_changed:
                log.info("mode -> %s", result.new_mode.value)
                if result.new_mode is Mode.ACTIVE:
                    await write_log(db, status="active", started_at=datetime.now(UTC))
                else:
                    await write_log(db, status="idle", started_at=datetime.now(UTC))
            if result.sample is not None:
                await write_sample(db, result.sample)
            if result.sleep_s > 0:
                await asyncio.sleep(result.sleep_s)
    finally:
        bridge.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
