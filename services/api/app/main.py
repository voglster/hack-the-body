import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import ensure_collections, get_db, make_client
from app.routers import health

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    app.state.mongo_client = make_client(settings)
    app.state.db = get_db(app.state.mongo_client, settings)
    await ensure_collections(app.state.db)
    try:
        yield
    finally:
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
    from app.routers import admin, auth, foods, meals, metrics, workouts
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(metrics.router)
    app.include_router(workouts.router)
    app.include_router(admin.router)
    app.include_router(foods.router)
    app.include_router(meals.router)

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
        return FileResponse(STATIC_DIR / "index.html")


app = create_app()
