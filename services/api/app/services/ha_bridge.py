"""Home Assistant websocket bridge: remote presses in, spoken lines out.

Runs for the app's lifetime, reconnecting with backoff. Everything HA-facing
is here so the button logic (`buttons.press`) stays testable without HA.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from pymongo.asynchronous.database import AsyncDatabase
from websockets.asyncio.client import connect

from app.config import Settings
from app.services.buttons import decode_tradfri, press

log = logging.getLogger(__name__)

DEBOUNCE_S = 1.0
MAX_BACKOFF_S = 60.0


def _ws_url(base: str) -> str:
    return (
        base.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
        + "/api/websocket"
    )


async def speak(settings: Settings, message: str) -> None:
    domain, _, name = settings.ha_speak_script.partition(".")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{settings.ha_url.rstrip('/')}/api/services/{domain}/{name}",
                headers={"Authorization": f"Bearer {settings.ha_token}"},
                json={"message": message},
            )
    except httpx.HTTPError as exc:
        log.warning("ha bridge: speak failed: %s", exc)


class ButtonRouter:
    """Turns raw zha_event payloads into presses, dropping ZHA's duplicate sends."""

    def __init__(self, remotes: dict[str, str]) -> None:
        self.remotes = remotes
        self._last: dict[str, float] = {}

    def button_for(self, data: dict[str, Any], now: float | None = None) -> str | None:
        remote = self.remotes.get(str(data.get("device_ieee", "")).lower())
        if not remote:
            return None
        name = decode_tradfri(data.get("command", ""), data.get("args"))
        if not name:
            log.info(
                "ha bridge: unmapped %s event %s %s", remote, data.get("command"), data.get("args")
            )
            return None
        key = f"{remote}/{name}"
        now = time.monotonic() if now is None else now
        if now - self._last.get(key, -DEBOUNCE_S) < DEBOUNCE_S:
            return None
        self._last[key] = now
        return key


async def _session(settings: Settings, db: AsyncDatabase, router: ButtonRouter) -> None:
    async with connect(_ws_url(settings.ha_url), max_size=None) as ws:
        json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "auth", "access_token": settings.ha_token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise PermissionError(f"HA auth failed: {auth}")
        await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "zha_event"}))
        log.info("ha bridge: listening for %d remote(s)", len(router.remotes))
        async for raw in ws:
            msg = json.loads(raw)
            data = (msg.get("event") or {}).get("data") or {}
            button = router.button_for(data)
            if not button:
                continue
            try:
                result = await press(db, button)
            except Exception:
                log.exception("ha bridge: press %s failed", button)
                result = {"say": "Sorry, that didn't log."}
            log.info("ha bridge: %s -> %s", button, result.get("say"))
            await speak(settings, result["say"])


async def run_bridge(settings: Settings, db: AsyncDatabase) -> None:
    router = ButtonRouter(settings.ha_remote_names)
    backoff = 1.0
    while True:
        try:
            await _session(settings, db, router)
            backoff = 1.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("ha bridge: disconnected (%s); retrying in %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
