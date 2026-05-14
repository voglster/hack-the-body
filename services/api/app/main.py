import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import ensure_collections, get_db, make_client
from app.routers import health
from app.services.scheduler import build_scheduler

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    app.state.mongo_client = make_client(settings)
    app.state.db = get_db(app.state.mongo_client, settings)
    await ensure_collections(app.state.db)
    tz = os.environ.get("TZ")
    scheduler = build_scheduler(settings, app.state.db, timezone=tz)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "coach scheduler started: cron times %s (tz=%s)",
        settings.coach_schedule_local, tz or "system-default",
    )
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        app.state.mongo_client.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Hack the Body", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from app.routers import (
        admin,
        auth,
        coach,
        foods,
        habits,
        meals,
        metrics,
        nudges,
        profile,
        push,
        vitamins,
        water,
        webhooks,
        workouts,
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(metrics.router)
    app.include_router(workouts.router)
    app.include_router(admin.router)
    app.include_router(foods.router)
    app.include_router(meals.router)
    app.include_router(coach.router)
    app.include_router(habits.router)
    app.include_router(profile.router)
    app.include_router(push.router)
    app.include_router(water.router)
    app.include_router(vitamins.router)
    app.include_router(nudges.router)
    app.include_router(webhooks.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    if not STATIC_DIR.is_dir():
        return  # tests / dev without a built bundle

    @app.get("/config.js", include_in_schema=False)
    async def config_js() -> Response:
        # apiKey is intentionally NOT shipped here. The browser learns it by
        # POSTing a password to /auth/verify (see services/web/src/lib/auth.ts).
        body = f"window.__HTB__ = {json.dumps({'apiUrl': ''})};"
        return Response(content=body, media_type="application/javascript")

    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # index.html must never be cached — it carries the hashed asset
        # URLs. Browsers (especially the Pi kiosk's Chromium) holding a
        # stale index.html keep loading the old JS bundle even after the
        # container redeploys.
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )


app = create_app()
