# Hack the Body — Phase 0 + 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the data spine: docker-compose stack running FastAPI + MongoDB + a Garmin ingestor that pulls sleep/HRV/weight/body-comp/workouts/VO2max nightly, a React web dashboard visualizing trends, and a Pi-kiosk route for the office monitor.

**Architecture:** Three services in docker-compose — `api` (FastAPI, single API-key auth, talks to Mongo), `ingestor-garmin` (Python worker, APScheduler-driven, uses `garth`), `web` (React + Vite, served via nginx in prod / Vite dev in dev). MongoDB 7 with time-series collections for metrics, regular collections for workouts/profile/ingestion log. Single host, single user.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Motor (async MongoDB), `garth` (Garmin OAuth), APScheduler, MongoDB 7, React 18, TypeScript, Vite, TanStack Query, Recharts, Tailwind, Vitest, pytest, Docker Compose.

**Spec reference:** `docs/superpowers/specs/2026-04-24-hack-the-body-design.md`

---

## File Structure

```
hack-the-body/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── services/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── main.py                # FastAPI app factory
│   │   │   ├── config.py              # pydantic-settings
│   │   │   ├── db.py                  # Motor client + TS collection bootstrap
│   │   │   ├── auth.py                # API-key dependency
│   │   │   ├── models/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── metrics.py         # Weight, Sleep, HRV, RHR, BodyComp, VO2Max
│   │   │   │   └── workout.py
│   │   │   ├── routers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── health.py
│   │   │   │   ├── metrics.py
│   │   │   │   ├── workouts.py
│   │   │   │   └── admin.py           # ingest trigger
│   │   │   └── services/
│   │   │       ├── __init__.py
│   │   │       └── metrics_repo.py
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── conftest.py
│   │       ├── test_health.py
│   │       ├── test_auth.py
│   │       ├── test_metrics_repo.py
│   │       └── test_metrics_routes.py
│   ├── ingestor-garmin/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── main.py                # CLI + scheduler entrypoint
│   │   │   ├── config.py
│   │   │   ├── garmin_client.py       # garth wrapper (login + fetch)
│   │   │   ├── mappers.py             # garmin JSON -> our pydantic
│   │   │   ├── repo.py                # Motor writer (upserts by source_id)
│   │   │   └── runner.py              # orchestrates one full sync pass
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── conftest.py
│   │       ├── fixtures/               # JSON snapshots of Garmin responses
│   │       │   ├── sleep.json
│   │       │   ├── hrv.json
│   │       │   ├── weight.json
│   │       │   ├── body_comp.json
│   │       │   ├── workout.json
│   │       │   └── vo2max.json
│   │       ├── test_mappers.py
│   │       └── test_runner.py
│   └── web/
│       ├── Dockerfile
│       ├── nginx.conf
│       ├── package.json
│       ├── tsconfig.json
│       ├── vite.config.ts
│       ├── tailwind.config.js
│       ├── postcss.config.js
│       ├── index.html
│       ├── src/
│       │   ├── main.tsx
│       │   ├── App.tsx
│       │   ├── router.tsx
│       │   ├── api/
│       │   │   ├── client.ts
│       │   │   └── types.ts
│       │   ├── pages/
│       │   │   ├── Dashboard.tsx
│       │   │   └── Kiosk.tsx
│       │   ├── components/
│       │   │   ├── MetricCard.tsx
│       │   │   ├── WeightChart.tsx
│       │   │   ├── SleepChart.tsx
│       │   │   ├── HrvChart.tsx
│       │   │   └── WorkoutList.tsx
│       │   ├── lib/
│       │   │   ├── format.ts
│       │   │   └── trend.ts           # rolling-average helper
│       │   └── index.css
│       └── src/lib/__tests__/
│           ├── format.test.ts
│           └── trend.test.ts
└── docs/
    ├── superpowers/
    │   ├── specs/2026-04-24-hack-the-body-design.md
    │   └── plans/2026-04-24-phase-0-1-data-spine.md
    └── pi-kiosk-setup.md
```

Each file has one responsibility. `mappers.py` is pure functions (easy to test). `repo.py` is the only module that talks to Mongo in each service. `runner.py` orchestrates; it's thin on purpose.

---

## Task 0: Repo skeleton & docker-compose

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `README.md`
- Create: `docs/pi-kiosk-setup.md` (placeholder content, filled in Task 15)

- [ ] **Step 1: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Node
node_modules/
dist/
build/
.vite/

# Env / secrets
.env
.env.local
*.local

# Garmin session cache
.garminsession/
services/*/.garminsession/

# IDE / OS
.idea/
.vscode/
.DS_Store
```

- [ ] **Step 2: Create `.env.example`**

```
# === Shared ===
TZ=America/Denver
MONGO_URL=mongodb://mongo:27017
MONGO_DB=hackthebody

# === API ===
API_KEY=change-me-to-a-long-random-string
API_PORT=8000
CORS_ORIGINS=http://localhost:5173,http://localhost:8080

# === Garmin Ingestor ===
GARMIN_EMAIL=
GARMIN_PASSWORD=
GARMIN_SESSION_DIR=/data/garmin-session
GARMIN_BACKFILL_DAYS=90
GARMIN_SCHEDULE_CRON=0 4 * * *

# === Web ===
VITE_API_URL=http://localhost:8000
VITE_API_KEY=change-me-to-a-long-random-string
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  mongo:
    image: mongo:7
    restart: unless-stopped
    volumes:
      - mongo_data:/data/db
    ports:
      - "27017:27017"
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: ./services/api
    restart: unless-stopped
    depends_on:
      mongo:
        condition: service_healthy
    environment:
      MONGO_URL: ${MONGO_URL}
      MONGO_DB: ${MONGO_DB}
      API_KEY: ${API_KEY}
      CORS_ORIGINS: ${CORS_ORIGINS}
      TZ: ${TZ}
    ports:
      - "${API_PORT}:8000"

  ingestor-garmin:
    build: ./services/ingestor-garmin
    restart: unless-stopped
    depends_on:
      mongo:
        condition: service_healthy
    environment:
      MONGO_URL: ${MONGO_URL}
      MONGO_DB: ${MONGO_DB}
      GARMIN_EMAIL: ${GARMIN_EMAIL}
      GARMIN_PASSWORD: ${GARMIN_PASSWORD}
      GARMIN_SESSION_DIR: ${GARMIN_SESSION_DIR}
      GARMIN_BACKFILL_DAYS: ${GARMIN_BACKFILL_DAYS}
      GARMIN_SCHEDULE_CRON: ${GARMIN_SCHEDULE_CRON}
      TZ: ${TZ}
    volumes:
      - garmin_session:/data/garmin-session

  web:
    build:
      context: ./services/web
      args:
        VITE_API_URL: ${VITE_API_URL}
        VITE_API_KEY: ${VITE_API_KEY}
    restart: unless-stopped
    ports:
      - "8080:80"

volumes:
  mongo_data:
  garmin_session:
```

- [ ] **Step 4: Create `README.md`**

```markdown
# Hack the Body

Self-hosted AI-coached health and training system.

See `docs/superpowers/specs/2026-04-24-hack-the-body-design.md` for full design.

## Quick start (Phase 0+1)

1. `cp .env.example .env` and fill in `API_KEY`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`.
2. `docker compose up --build`.
3. API at `http://localhost:8000/healthz`, web at `http://localhost:8080`.

## Services

- `services/api` — FastAPI data spine (Mongo-backed)
- `services/ingestor-garmin` — Pulls Garmin data nightly
- `services/web` — React dashboard + Pi kiosk

## Development

Each service has its own `pyproject.toml` / `package.json` and is independently runnable.

See `docs/pi-kiosk-setup.md` for setting up the office-monitor Pi.
```

- [ ] **Step 5: Create `docs/pi-kiosk-setup.md`** (placeholder, filled later)

```markdown
# Pi Kiosk Setup

Populated at end of Phase 1. The kiosk route is `http://<web-host>:8080/kiosk`.
```

- [ ] **Step 6: Verify docker-compose parses**

Run: `docker compose config --quiet && echo OK`
Expected: `OK` (no errors). Services won't build yet because their Dockerfiles don't exist — that's fine; `config` only validates the compose file.

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example docker-compose.yml README.md docs/pi-kiosk-setup.md
git commit -m "chore: repo skeleton with docker-compose for api, ingestor, web, mongo"
```

---

## Task 1: API service scaffold with health endpoint (TDD)

**Files:**
- Create: `services/api/pyproject.toml`
- Create: `services/api/Dockerfile`
- Create: `services/api/app/__init__.py` (empty)
- Create: `services/api/app/main.py`
- Create: `services/api/app/config.py`
- Create: `services/api/app/routers/__init__.py` (empty)
- Create: `services/api/app/routers/health.py`
- Create: `services/api/tests/__init__.py` (empty)
- Create: `services/api/tests/conftest.py`
- Create: `services/api/tests/test_health.py`

- [ ] **Step 1: Create `services/api/pyproject.toml`**

```toml
[project]
name = "hack-the-body-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.5",
  "motor>=3.6",
  "python-dateutil>=2.9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "httpx>=0.27",
  "mongomock-motor>=0.0.34",
  "ruff>=0.7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Create `services/api/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create `services/api/app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "hackthebody"
    api_key: str = "dev-key"
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Write failing test for health endpoint**

Create `services/api/tests/conftest.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

Create `services/api/tests/test_health.py`:
```python
async def test_healthz_returns_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd services/api && pip install -e ".[dev]" && pytest tests/test_health.py -v
```
Expected: FAIL (import error on `app.main.create_app`).

- [ ] **Step 6: Implement minimal app**

Create `services/api/app/routers/health.py`:
```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

Create `services/api/app/main.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import health


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Hack the Body API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 7: Run test to verify it passes**

```bash
cd services/api && pytest tests/test_health.py -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add services/api
git commit -m "feat(api): fastapi scaffold with /healthz and test harness"
```

---

## Task 2: MongoDB client + time-series collection bootstrap (TDD)

**Files:**
- Create: `services/api/app/db.py`
- Modify: `services/api/app/main.py` (wire lifespan)
- Modify: `services/api/tests/conftest.py` (mock db fixture)
- Create: `services/api/tests/test_db.py`

- [ ] **Step 1: Write failing test for collection bootstrap**

Create `services/api/tests/test_db.py`:
```python
from app.db import ensure_collections, TIMESERIES_COLLECTIONS


async def test_ensure_collections_creates_timeseries(mock_db):
    await ensure_collections(mock_db)
    names = await mock_db.list_collection_names()
    for name in TIMESERIES_COLLECTIONS:
        assert name in names
```

Update `services/api/tests/conftest.py` to add:
```python
from mongomock_motor import AsyncMongoMockClient


@pytest.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    yield client["testdb"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/api && pytest tests/test_db.py -v
```
Expected: FAIL (ImportError on `app.db`).

- [ ] **Step 3: Implement `services/api/app/db.py`**

```python
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import Settings

# name -> (metaField keys we care about; kept for docs/tests)
TIMESERIES_COLLECTIONS: dict[str, dict] = {
    "metrics_weight": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_sleep": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_hrv": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_rhr": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_body_comp": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
    "metrics_vo2max": {"timeField": "ts", "metaField": "meta", "granularity": "hours"},
}

REGULAR_COLLECTIONS = ["workouts", "user_profile", "ingestion_log"]


async def ensure_collections(db: AsyncIOMotorDatabase) -> None:
    existing = set(await db.list_collection_names())
    for name, opts in TIMESERIES_COLLECTIONS.items():
        if name in existing:
            continue
        try:
            await db.create_collection(name, timeseries=opts)
        except Exception:
            # mongomock may not support timeseries kwarg; fall back to plain.
            await db.create_collection(name)
    for name in REGULAR_COLLECTIONS:
        if name not in existing:
            await db.create_collection(name)

    # workout dedupe by source_id
    await db["workouts"].create_index("source_id", unique=True, sparse=True)
    await db["ingestion_log"].create_index([("source", 1), ("started_at", -1)])


def make_client(settings: Settings) -> AsyncIOMotorClient:
    return AsyncIOMotorClient(settings.mongo_url)


def get_db(client: AsyncIOMotorClient, settings: Settings) -> AsyncIOMotorDatabase:
    return client[settings.mongo_db]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/api && pytest tests/test_db.py -v
```
Expected: PASS.

- [ ] **Step 5: Wire lifespan into `services/api/app/main.py`**

Replace the file with:
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import ensure_collections, get_db, make_client
from app.routers import health


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
    app = FastAPI(title="Hack the Body API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 6: Update conftest to inject mock db into app**

Replace `services/api/tests/conftest.py` with:
```python
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.db import ensure_collections
from app.main import create_app


@pytest.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    db = client["testdb"]
    await ensure_collections(db)
    yield db


@pytest.fixture
def settings():
    return Settings(mongo_url="mongodb://fake", mongo_db="testdb", api_key="test-key")


@pytest.fixture
async def client(settings, mock_db):
    app = create_app(settings)
    # override lifespan-set state with our mock db
    app.state.db = mock_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

- [ ] **Step 7: Run full suite**

```bash
cd services/api && pytest -v
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add services/api
git commit -m "feat(api): mongo lifespan + time-series collection bootstrap"
```

---

## Task 3: API-key auth dependency (TDD)

**Files:**
- Create: `services/api/app/auth.py`
- Create: `services/api/tests/test_auth.py`

- [ ] **Step 1: Write failing test**

Create `services/api/tests/test_auth.py`:
```python
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import require_api_key
from app.config import Settings


async def test_missing_key_rejected():
    app = FastAPI()
    app.state.settings = Settings(api_key="secret")

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/protected")
    assert r.status_code == 401


async def test_wrong_key_rejected():
    app = FastAPI()
    app.state.settings = Settings(api_key="secret")

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/protected", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


async def test_correct_key_accepted():
    app = FastAPI()
    app.state.settings = Settings(api_key="secret")

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/protected", headers={"X-API-Key": "secret"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/api && pytest tests/test_auth.py -v
```
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `services/api/app/auth.py`**

```python
import hmac

from fastapi import Header, HTTPException, Request, status


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.api_key
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/api && pytest tests/test_auth.py -v
```
Expected: PASS (all 3).

- [ ] **Step 5: Commit**

```bash
git add services/api
git commit -m "feat(api): x-api-key auth dependency with constant-time compare"
```

---

## Task 4: Metric pydantic models (TDD)

**Files:**
- Create: `services/api/app/models/__init__.py` (empty)
- Create: `services/api/app/models/metrics.py`
- Create: `services/api/app/models/workout.py`
- Create: `services/api/tests/test_models.py`

- [ ] **Step 1: Write failing test**

Create `services/api/tests/test_models.py`:
```python
from datetime import datetime, timezone

from app.models.metrics import (
    BodyComp,
    HRV,
    RHR,
    Sleep,
    VO2Max,
    Weight,
)
from app.models.workout import Workout


def test_weight_requires_positive_kg():
    w = Weight(ts=datetime.now(timezone.utc), kg=108.9, source="garmin", source_id="g:w:1")
    assert w.kg == 108.9


def test_sleep_derives_total_seconds():
    s = Sleep(
        ts=datetime.now(timezone.utc),
        duration_s=7 * 3600 + 15 * 60,
        deep_s=3600,
        rem_s=5400,
        light_s=2 * 3600,
        awake_s=15 * 60,
        score=82,
        source="garmin",
        source_id="g:s:2026-04-24",
    )
    assert s.duration_s == 7 * 3600 + 15 * 60


def test_hrv_non_negative():
    h = HRV(ts=datetime.now(timezone.utc), rmssd_ms=58.2, source="garmin", source_id="g:hrv:1")
    assert h.rmssd_ms == 58.2


def test_rhr_reasonable():
    r = RHR(ts=datetime.now(timezone.utc), bpm=54, source="garmin", source_id="g:rhr:1")
    assert r.bpm == 54


def test_body_comp_optional_fields():
    b = BodyComp(
        ts=datetime.now(timezone.utc),
        weight_kg=108.9,
        body_fat_pct=24.1,
        muscle_mass_kg=None,
        source="garmin-scale",
        source_id="g:bc:1",
    )
    assert b.muscle_mass_kg is None


def test_vo2max_value():
    v = VO2Max(ts=datetime.now(timezone.utc), value=42.0, source="garmin", source_id="g:v:1")
    assert v.value == 42.0


def test_workout_has_movements():
    w = Workout(
        ts=datetime.now(timezone.utc),
        activity_type="walking",
        duration_s=1800,
        distance_m=2500.0,
        avg_hr=112,
        calories=240,
        source="garmin",
        source_id="g:act:1",
    )
    assert w.activity_type == "walking"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && pytest tests/test_models.py -v
```
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement models**

Create `services/api/app/models/metrics.py`:
```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _TimeseriesBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    source: str
    source_id: str


class Weight(_TimeseriesBase):
    kg: float = Field(gt=0)


class Sleep(_TimeseriesBase):
    duration_s: int = Field(ge=0)
    deep_s: int = Field(ge=0)
    rem_s: int = Field(ge=0)
    light_s: int = Field(ge=0)
    awake_s: int = Field(ge=0)
    score: int | None = Field(default=None, ge=0, le=100)


class HRV(_TimeseriesBase):
    rmssd_ms: float = Field(ge=0)


class RHR(_TimeseriesBase):
    bpm: int = Field(gt=0, lt=250)


class BodyComp(_TimeseriesBase):
    weight_kg: float = Field(gt=0)
    body_fat_pct: float | None = Field(default=None, ge=0, le=100)
    muscle_mass_kg: float | None = Field(default=None, ge=0)
    body_water_pct: float | None = Field(default=None, ge=0, le=100)
    bone_mass_kg: float | None = Field(default=None, ge=0)


class VO2Max(_TimeseriesBase):
    value: float = Field(gt=0)
```

Create `services/api/app/models/workout.py`:
```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Workout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    activity_type: str
    duration_s: int = Field(ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    avg_hr: int | None = Field(default=None, ge=0)
    max_hr: int | None = Field(default=None, ge=0)
    calories: int | None = Field(default=None, ge=0)
    notes: str | None = None
    source: str
    source_id: str
```

- [ ] **Step 4: Run to verify pass**

```bash
cd services/api && pytest tests/test_models.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api
git commit -m "feat(api): pydantic models for weight/sleep/hrv/rhr/body-comp/vo2max/workout"
```

---

## Task 5: MetricsRepo (TDD)

**Files:**
- Create: `services/api/app/services/__init__.py` (empty)
- Create: `services/api/app/services/metrics_repo.py`
- Create: `services/api/tests/test_metrics_repo.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_metrics_repo.py`:
```python
from datetime import datetime, timedelta, timezone

from app.models.metrics import Weight, Sleep
from app.services.metrics_repo import MetricsRepo


async def test_insert_and_latest_weight(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(timezone.utc)
    await repo.insert_weight(
        Weight(ts=now, kg=108.9, source="garmin", source_id="w1")
    )
    latest = await repo.latest_weight()
    assert latest is not None
    assert latest["kg"] == 108.9


async def test_range_weight_returns_ordered(mock_db):
    repo = MetricsRepo(mock_db)
    base = datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc)
    for i in range(5):
        await repo.insert_weight(
            Weight(ts=base + timedelta(days=i), kg=108 + i * 0.1,
                   source="garmin", source_id=f"w{i}")
        )
    rows = await repo.range_weight(base, base + timedelta(days=10))
    assert len(rows) == 5
    assert rows[0]["ts"] < rows[-1]["ts"]


async def test_insert_sleep_and_latest(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(timezone.utc)
    await repo.insert_sleep(
        Sleep(ts=now, duration_s=27000, deep_s=3600, rem_s=5400,
              light_s=16000, awake_s=2000, score=80,
              source="garmin", source_id="s1")
    )
    latest = await repo.latest_sleep()
    assert latest["duration_s"] == 27000
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && pytest tests/test_metrics_repo.py -v
```
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `services/api/app/services/metrics_repo.py`**

```python
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.metrics import BodyComp, HRV, RHR, Sleep, VO2Max, Weight


class MetricsRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # ---------- weight ----------
    async def insert_weight(self, w: Weight) -> None:
        await self.db["metrics_weight"].insert_one(
            {"ts": w.ts, "kg": w.kg, "meta": {"source": w.source, "source_id": w.source_id}}
        )

    async def latest_weight(self) -> dict[str, Any] | None:
        return await self.db["metrics_weight"].find_one(sort=[("ts", -1)])

    async def range_weight(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_weight"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    # ---------- sleep ----------
    async def insert_sleep(self, s: Sleep) -> None:
        await self.db["metrics_sleep"].insert_one(
            {
                "ts": s.ts,
                "duration_s": s.duration_s,
                "deep_s": s.deep_s,
                "rem_s": s.rem_s,
                "light_s": s.light_s,
                "awake_s": s.awake_s,
                "score": s.score,
                "meta": {"source": s.source, "source_id": s.source_id},
            }
        )

    async def latest_sleep(self) -> dict[str, Any] | None:
        return await self.db["metrics_sleep"].find_one(sort=[("ts", -1)])

    async def range_sleep(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_sleep"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    # ---------- hrv ----------
    async def insert_hrv(self, h: HRV) -> None:
        await self.db["metrics_hrv"].insert_one(
            {"ts": h.ts, "rmssd_ms": h.rmssd_ms,
             "meta": {"source": h.source, "source_id": h.source_id}}
        )

    async def latest_hrv(self) -> dict[str, Any] | None:
        return await self.db["metrics_hrv"].find_one(sort=[("ts", -1)])

    async def range_hrv(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_hrv"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    # ---------- rhr ----------
    async def insert_rhr(self, r: RHR) -> None:
        await self.db["metrics_rhr"].insert_one(
            {"ts": r.ts, "bpm": r.bpm,
             "meta": {"source": r.source, "source_id": r.source_id}}
        )

    async def latest_rhr(self) -> dict[str, Any] | None:
        return await self.db["metrics_rhr"].find_one(sort=[("ts", -1)])

    async def range_rhr(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_rhr"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]

    # ---------- body comp ----------
    async def insert_body_comp(self, b: BodyComp) -> None:
        await self.db["metrics_body_comp"].insert_one(
            {
                "ts": b.ts,
                "weight_kg": b.weight_kg,
                "body_fat_pct": b.body_fat_pct,
                "muscle_mass_kg": b.muscle_mass_kg,
                "body_water_pct": b.body_water_pct,
                "bone_mass_kg": b.bone_mass_kg,
                "meta": {"source": b.source, "source_id": b.source_id},
            }
        )

    async def latest_body_comp(self) -> dict[str, Any] | None:
        return await self.db["metrics_body_comp"].find_one(sort=[("ts", -1)])

    # ---------- vo2max ----------
    async def insert_vo2max(self, v: VO2Max) -> None:
        await self.db["metrics_vo2max"].insert_one(
            {"ts": v.ts, "value": v.value,
             "meta": {"source": v.source, "source_id": v.source_id}}
        )

    async def latest_vo2max(self) -> dict[str, Any] | None:
        return await self.db["metrics_vo2max"].find_one(sort=[("ts", -1)])

    async def range_vo2max(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        cur = self.db["metrics_vo2max"].find({"ts": {"$gte": start, "$lte": end}}).sort("ts", 1)
        return [d async for d in cur]
```

- [ ] **Step 4: Run to verify pass**

```bash
cd services/api && pytest tests/test_metrics_repo.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api
git commit -m "feat(api): MetricsRepo with insert/latest/range per metric"
```

---

## Task 6: Metrics HTTP routes (TDD)

**Files:**
- Create: `services/api/app/routers/metrics.py`
- Create: `services/api/app/routers/workouts.py`
- Modify: `services/api/app/main.py` (register routers)
- Create: `services/api/tests/test_metrics_routes.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_metrics_routes.py`:
```python
from datetime import datetime, timezone

from app.models.metrics import Weight
from app.services.metrics_repo import MetricsRepo


async def test_get_latest_weight_requires_auth(client):
    r = await client.get("/metrics/weight/latest")
    assert r.status_code == 401


async def test_get_latest_weight_returns_value(client, mock_db):
    repo = MetricsRepo(mock_db)
    await repo.insert_weight(
        Weight(ts=datetime.now(timezone.utc), kg=108.9,
               source="garmin", source_id="w1")
    )
    r = await client.get("/metrics/weight/latest", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.json()["kg"] == 108.9


async def test_summary_returns_all_latest(client, mock_db):
    repo = MetricsRepo(mock_db)
    await repo.insert_weight(
        Weight(ts=datetime.now(timezone.utc), kg=108.9,
               source="garmin", source_id="w1")
    )
    r = await client.get("/metrics/summary", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert "weight" in body
    assert body["weight"]["kg"] == 108.9
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd services/api && pytest tests/test_metrics_routes.py -v
```
Expected: FAIL (404s — routes don't exist yet).

- [ ] **Step 3: Create `services/api/app/routers/metrics.py`**

```python
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_api_key
from app.services.metrics_repo import MetricsRepo

router = APIRouter(prefix="/metrics", dependencies=[Depends(require_api_key)])


def _repo(request: Request) -> MetricsRepo:
    return MetricsRepo(request.app.state.db)


def _strip_id(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


@router.get("/summary")
async def summary(request: Request):
    repo = _repo(request)
    return {
        "weight": _strip_id(await repo.latest_weight()),
        "sleep": _strip_id(await repo.latest_sleep()),
        "hrv": _strip_id(await repo.latest_hrv()),
        "rhr": _strip_id(await repo.latest_rhr()),
        "body_comp": _strip_id(await repo.latest_body_comp()),
        "vo2max": _strip_id(await repo.latest_vo2max()),
    }


_KINDS = {"weight", "sleep", "hrv", "rhr", "body_comp", "vo2max"}


@router.get("/{kind}/latest")
async def latest(kind: str, request: Request):
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail=f"unknown metric: {kind}")
    repo = _repo(request)
    method = getattr(repo, f"latest_{kind}")
    doc = await method()
    if doc is None:
        raise HTTPException(status_code=404, detail="no data")
    return _strip_id(doc)


@router.get("/{kind}/range")
async def range_(
    kind: str,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
):
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail=f"unknown metric: {kind}")
    repo = _repo(request)
    method_name = f"range_{kind}"
    if not hasattr(repo, method_name):
        raise HTTPException(status_code=400, detail=f"{kind} has no range endpoint")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = await getattr(repo, method_name)(start, end)
    return [_strip_id(r) for r in rows]
```

- [ ] **Step 4: Create `services/api/app/routers/workouts.py`**

```python
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_api_key

router = APIRouter(prefix="/workouts", dependencies=[Depends(require_api_key)])


@router.get("")
async def list_workouts(request: Request, days: int = Query(default=30, ge=1, le=365)):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    cur = request.app.state.db["workouts"].find(
        {"ts": {"$gte": start, "$lte": end}}
    ).sort("ts", -1)
    rows = []
    async for d in cur:
        d.pop("_id", None)
        rows.append(d)
    return rows
```

- [ ] **Step 5: Register routers in `services/api/app/main.py`**

Find the line `app.include_router(health.router)` and replace with:
```python
    from app.routers import metrics, workouts  # noqa: PLC0415
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(workouts.router)
```

- [ ] **Step 6: Run tests to verify pass**

```bash
cd services/api && pytest tests/test_metrics_routes.py -v
```
Expected: PASS (all 3).

- [ ] **Step 7: Run full suite**

```bash
cd services/api && pytest -v
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add services/api
git commit -m "feat(api): /metrics/summary, /metrics/{kind}/latest|range, /workouts list"
```

---

## Task 7: Admin ingest-trigger endpoint

**Files:**
- Create: `services/api/app/routers/admin.py`
- Modify: `services/api/app/main.py` (register)
- Create: `services/api/tests/test_admin.py`

Note: the ingestor service runs its own loop; the admin endpoint records an "ingest requested" signal the ingestor checks on next wake. For Phase 1 simplicity, the signal is a row in `ingestion_log` with status `requested`; the ingestor polls for it.

- [ ] **Step 1: Write failing test**

Create `services/api/tests/test_admin.py`:
```python
async def test_admin_trigger_requires_auth(client):
    r = await client.post("/admin/ingest/garmin")
    assert r.status_code == 401


async def test_admin_trigger_writes_log(client, mock_db):
    r = await client.post("/admin/ingest/garmin", headers={"X-API-Key": "test-key"})
    assert r.status_code == 202
    doc = await mock_db["ingestion_log"].find_one({"source": "garmin", "status": "requested"})
    assert doc is not None


async def test_admin_trigger_unknown_source(client):
    r = await client.post("/admin/ingest/unknown", headers={"X-API-Key": "test-key"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/api && pytest tests/test_admin.py -v
```
Expected: FAIL (404).

- [ ] **Step 3: Implement `services/api/app/routers/admin.py`**

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import require_api_key

router = APIRouter(prefix="/admin", dependencies=[Depends(require_api_key)])

_KNOWN_SOURCES = {"garmin"}


@router.post("/ingest/{source}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest(source: str, request: Request):
    if source not in _KNOWN_SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source: {source}")
    await request.app.state.db["ingestion_log"].insert_one({
        "source": source,
        "status": "requested",
        "started_at": datetime.now(timezone.utc),
        "requested_by": "api",
    })
    return {"accepted": True, "source": source}
```

- [ ] **Step 4: Register router**

In `services/api/app/main.py` change the import line to also include `admin`, then add `app.include_router(admin.router)`:
```python
    from app.routers import admin, metrics, workouts  # noqa: PLC0415
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(workouts.router)
    app.include_router(admin.router)
```

- [ ] **Step 5: Run tests**

```bash
cd services/api && pytest -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add services/api
git commit -m "feat(api): /admin/ingest/{source} trigger endpoint writing request log"
```

---

## Task 8: Garmin ingestor scaffold + config

**Files:**
- Create: `services/ingestor-garmin/pyproject.toml`
- Create: `services/ingestor-garmin/Dockerfile`
- Create: `services/ingestor-garmin/app/__init__.py` (empty)
- Create: `services/ingestor-garmin/app/config.py`
- Create: `services/ingestor-garmin/tests/__init__.py` (empty)
- Create: `services/ingestor-garmin/tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "hack-the-body-ingestor-garmin"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "garth>=0.4.46",
  "motor>=3.6",
  "pydantic>=2.9",
  "pydantic-settings>=2.5",
  "apscheduler>=3.10",
  "python-dateutil>=2.9",
  "tenacity>=9.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "mongomock-motor>=0.0.34",
  "ruff>=0.7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY app ./app
CMD ["python", "-m", "app.main", "run"]
```

- [ ] **Step 3: Create `app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "hackthebody"
    garmin_email: str = ""
    garmin_password: str = ""
    garmin_session_dir: str = "./.garminsession"
    garmin_backfill_days: int = 90
    garmin_schedule_cron: str = "0 4 * * *"


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Create `tests/conftest.py`**

```python
import json
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    yield client["testdb"]


@pytest.fixture
def fixture():
    def _load(name: str):
        with open(FIXTURES / name) as f:
            return json.load(f)
    return _load
```

- [ ] **Step 5: Commit**

```bash
git add services/ingestor-garmin
git commit -m "chore(ingestor-garmin): package scaffold + config + test harness"
```

---

## Task 9: Garmin fixture files

**Files:** Create JSON fixtures that look like real Garmin responses. These drive mapper tests.

- Create: `services/ingestor-garmin/tests/fixtures/sleep.json`
- Create: `services/ingestor-garmin/tests/fixtures/hrv.json`
- Create: `services/ingestor-garmin/tests/fixtures/weight.json`
- Create: `services/ingestor-garmin/tests/fixtures/body_comp.json`
- Create: `services/ingestor-garmin/tests/fixtures/workout.json`
- Create: `services/ingestor-garmin/tests/fixtures/vo2max.json`

- [ ] **Step 1: Create `sleep.json`**

```json
{
  "dailySleepDTO": {
    "id": 1714012345678,
    "userProfilePK": 12345,
    "calendarDate": "2026-04-23",
    "sleepStartTimestampGMT": 1714012800000,
    "sleepEndTimestampGMT": 1714039200000,
    "sleepTimeSeconds": 26400,
    "deepSleepSeconds": 3600,
    "lightSleepSeconds": 15000,
    "remSleepSeconds": 5400,
    "awakeSleepSeconds": 2400,
    "sleepScores": {"overall": {"value": 78}}
  }
}
```

- [ ] **Step 2: Create `hrv.json`**

```json
{
  "hrvSummary": {
    "calendarDate": "2026-04-23",
    "lastNightAvg": 58,
    "lastNight5MinHigh": 85,
    "baseline": {"lowUpper": 48, "balancedLow": 55, "balancedUpper": 68}
  }
}
```

- [ ] **Step 3: Create `weight.json`**

```json
[
  {
    "samplePk": 900000001,
    "date": 1714012800000,
    "calendarDate": "2026-04-23",
    "weight": 108900.0,
    "bmi": null,
    "bodyFat": null,
    "bodyWater": null,
    "boneMass": null,
    "muscleMass": null,
    "sourceType": "MANUAL"
  }
]
```

- [ ] **Step 4: Create `body_comp.json`**

```json
[
  {
    "samplePk": 900000002,
    "date": 1714012800000,
    "calendarDate": "2026-04-23",
    "weight": 108900.0,
    "bmi": 28.7,
    "bodyFat": 24.1,
    "bodyWater": 55.2,
    "boneMass": 3800.0,
    "muscleMass": 80000.0,
    "sourceType": "INDEX_SCALE"
  }
]
```

- [ ] **Step 5: Create `workout.json`**

```json
[
  {
    "activityId": 13000000001,
    "activityName": "Outdoor Walk",
    "startTimeGMT": "2026-04-23 12:30:00",
    "activityType": {"typeKey": "walking"},
    "duration": 1800.5,
    "distance": 2500.4,
    "averageHR": 112.0,
    "maxHR": 128.0,
    "calories": 240.0
  }
]
```

- [ ] **Step 6: Create `vo2max.json`**

```json
{
  "generic": {"vo2MaxPreciseValue": 42.0, "calendarDate": "2026-04-23"}
}
```

- [ ] **Step 7: Commit**

```bash
git add services/ingestor-garmin/tests/fixtures
git commit -m "test(ingestor-garmin): snapshot fixtures for garmin responses"
```

---

## Task 10: Garmin mappers (TDD)

**Files:**
- Create: `services/ingestor-garmin/app/mappers.py`
- Create: `services/ingestor-garmin/tests/test_mappers.py`

Note: the mapper pydantic types are duplicated from the API service to keep ingestor decoupled. Small cost; big isolation win.

- [ ] **Step 1: Copy shared models into ingestor package**

Create `services/ingestor-garmin/app/models.py`:
```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _TSBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    source: str
    source_id: str


class Weight(_TSBase):
    kg: float = Field(gt=0)


class Sleep(_TSBase):
    duration_s: int
    deep_s: int
    rem_s: int
    light_s: int
    awake_s: int
    score: int | None = None


class HRV(_TSBase):
    rmssd_ms: float


class RHR(_TSBase):
    bpm: int


class BodyComp(_TSBase):
    weight_kg: float
    body_fat_pct: float | None = None
    muscle_mass_kg: float | None = None
    body_water_pct: float | None = None
    bone_mass_kg: float | None = None


class VO2Max(_TSBase):
    value: float


class Workout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    activity_type: str
    duration_s: int
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    calories: int | None = None
    notes: str | None = None
    source: str
    source_id: str
```

- [ ] **Step 2: Write failing tests**

Create `services/ingestor-garmin/tests/test_mappers.py`:
```python
from app.mappers import (
    map_body_comp,
    map_hrv,
    map_sleep,
    map_vo2max,
    map_weight,
    map_workout,
)


def test_map_sleep(fixture):
    raw = fixture("sleep.json")
    s = map_sleep(raw)
    assert s.duration_s == 26400
    assert s.deep_s == 3600
    assert s.rem_s == 5400
    assert s.light_s == 15000
    assert s.awake_s == 2400
    assert s.score == 78
    assert s.source == "garmin"
    assert s.source_id.startswith("garmin:sleep:")


def test_map_hrv(fixture):
    raw = fixture("hrv.json")
    h = map_hrv(raw)
    assert h.rmssd_ms == 58.0
    assert h.source_id.startswith("garmin:hrv:")


def test_map_weight_converts_grams_to_kg(fixture):
    raw = fixture("weight.json")
    samples = map_weight(raw)
    assert len(samples) == 1
    assert samples[0].kg == 108.9
    assert samples[0].source_id == "garmin:weight:900000001"


def test_map_body_comp(fixture):
    raw = fixture("body_comp.json")
    samples = map_body_comp(raw)
    assert len(samples) == 1
    bc = samples[0]
    assert bc.weight_kg == 108.9
    assert bc.body_fat_pct == 24.1
    assert bc.muscle_mass_kg == 80.0
    assert bc.body_water_pct == 55.2
    assert bc.bone_mass_kg == 3.8


def test_map_vo2max(fixture):
    raw = fixture("vo2max.json")
    v = map_vo2max(raw)
    assert v.value == 42.0


def test_map_workout(fixture):
    raw = fixture("workout.json")
    workouts = map_workout(raw)
    assert len(workouts) == 1
    w = workouts[0]
    assert w.activity_type == "walking"
    assert w.duration_s == 1800
    assert w.distance_m == 2500.4
    assert w.avg_hr == 112
    assert w.max_hr == 128
    assert w.calories == 240
    assert w.source_id == "garmin:activity:13000000001"
```

- [ ] **Step 3: Run tests to verify failure**

```bash
cd services/ingestor-garmin && pip install -e ".[dev]" && pytest tests/test_mappers.py -v
```
Expected: FAIL (ImportError).

- [ ] **Step 4: Implement `services/ingestor-garmin/app/mappers.py`**

```python
from datetime import datetime, timezone

from app.models import BodyComp, HRV, Sleep, VO2Max, Weight, Workout


def _utc_from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _utc_from_str(s: str) -> datetime:
    # "2026-04-23 12:30:00" in GMT
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def map_sleep(raw: dict) -> Sleep:
    d = raw["dailySleepDTO"]
    score = (d.get("sleepScores") or {}).get("overall", {}).get("value")
    return Sleep(
        ts=_utc_from_ms(d["sleepEndTimestampGMT"]),
        duration_s=int(d["sleepTimeSeconds"]),
        deep_s=int(d["deepSleepSeconds"]),
        rem_s=int(d["remSleepSeconds"]),
        light_s=int(d["lightSleepSeconds"]),
        awake_s=int(d["awakeSleepSeconds"]),
        score=int(score) if score is not None else None,
        source="garmin",
        source_id=f"garmin:sleep:{d['calendarDate']}",
    )


def map_hrv(raw: dict) -> HRV:
    s = raw["hrvSummary"]
    return HRV(
        ts=datetime.strptime(s["calendarDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
        rmssd_ms=float(s["lastNightAvg"]),
        source="garmin",
        source_id=f"garmin:hrv:{s['calendarDate']}",
    )


def map_weight(raw: list[dict]) -> list[Weight]:
    out: list[Weight] = []
    for s in raw:
        out.append(Weight(
            ts=_utc_from_ms(s["date"]),
            kg=round(float(s["weight"]) / 1000.0, 3),
            source="garmin",
            source_id=f"garmin:weight:{s['samplePk']}",
        ))
    return out


def map_body_comp(raw: list[dict]) -> list[BodyComp]:
    out: list[BodyComp] = []
    for s in raw:
        out.append(BodyComp(
            ts=_utc_from_ms(s["date"]),
            weight_kg=round(float(s["weight"]) / 1000.0, 3),
            body_fat_pct=_f(s.get("bodyFat")),
            muscle_mass_kg=_g_to_kg(s.get("muscleMass")),
            body_water_pct=_f(s.get("bodyWater")),
            bone_mass_kg=_g_to_kg(s.get("boneMass")),
            source="garmin-scale",
            source_id=f"garmin:body_comp:{s['samplePk']}",
        ))
    return out


def map_vo2max(raw: dict) -> VO2Max:
    g = raw["generic"]
    return VO2Max(
        ts=datetime.strptime(g["calendarDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
        value=float(g["vo2MaxPreciseValue"]),
        source="garmin",
        source_id=f"garmin:vo2max:{g['calendarDate']}",
    )


def map_workout(raw: list[dict]) -> list[Workout]:
    out: list[Workout] = []
    for a in raw:
        out.append(Workout(
            ts=_utc_from_str(a["startTimeGMT"]),
            activity_type=a["activityType"]["typeKey"],
            duration_s=int(a["duration"]),
            distance_m=_f(a.get("distance")),
            avg_hr=_i(a.get("averageHR")),
            max_hr=_i(a.get("maxHR")),
            calories=_i(a.get("calories")),
            source="garmin",
            source_id=f"garmin:activity:{a['activityId']}",
        ))
    return out


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _i(v) -> int | None:
    return int(v) if v is not None else None


def _g_to_kg(v) -> float | None:
    return round(float(v) / 1000.0, 3) if v is not None else None
```

- [ ] **Step 5: Run tests**

```bash
cd services/ingestor-garmin && pytest tests/test_mappers.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add services/ingestor-garmin
git commit -m "feat(ingestor-garmin): mappers for sleep/hrv/weight/body-comp/vo2max/workout"
```

---

## Task 11: Garmin client wrapper (thin, integration-deferred)

**Files:**
- Create: `services/ingestor-garmin/app/garmin_client.py`

Note: `garth` requires a real Garmin account to test end-to-end. We build a thin wrapper with a clear interface and a `--smoke` CLI mode that logs in and prints counts — manual verification path. Unit-testing is at the mapper level.

- [ ] **Step 1: Implement `app/garmin_client.py`**

```python
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import garth
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings


class GarminClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session_dir = Path(settings.garmin_session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def login(self) -> None:
        try:
            garth.resume(str(self.session_dir))
            garth.client.username  # triggers session check
        except Exception:
            if not self.settings.garmin_email or not self.settings.garmin_password:
                raise RuntimeError("GARMIN_EMAIL and GARMIN_PASSWORD must be set on first run")
            garth.login(self.settings.garmin_email, self.settings.garmin_password)
            garth.save(str(self.session_dir))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _get(self, path: str) -> dict | list:
        return garth.connectapi(path)

    # --- fetchers. Each returns the raw JSON for the mapper to parse. ---

    def fetch_sleep(self, day: date) -> dict:
        return self._get(f"/wellness-service/wellness/dailySleepData/{garth.client.username}?date={day.isoformat()}")

    def fetch_hrv(self, day: date) -> dict:
        return self._get(f"/hrv-service/hrv/{day.isoformat()}")

    def fetch_weight(self, start: date, end: date) -> list[dict]:
        data = self._get(
            f"/weight-service/weight/range/{start.isoformat()}/{end.isoformat()}?includeAll=true"
        )
        return data.get("dateWeightList", []) if isinstance(data, dict) else data

    def fetch_body_comp(self, start: date, end: date) -> list[dict]:
        return self.fetch_weight(start, end)  # same endpoint; mapper picks rich fields when present

    def fetch_vo2max(self, day: date) -> dict:
        return self._get(
            f"/userstats-service/wellness/daily/{garth.client.username}?fromDate={day.isoformat()}&untilDate={day.isoformat()}"
        )

    def fetch_workouts(self, start: date, end: date) -> list[dict]:
        return self._get(
            f"/activitylist-service/activities/search/activities?startDate={start.isoformat()}&endDate={end.isoformat()}&limit=200"
        )

    def fetch_rhr_series(self, start: date, end: date) -> list[dict]:
        return self._get(
            f"/userstats-service/wellness/daily/summary?fromDate={start.isoformat()}&untilDate={end.isoformat()}"
        )


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def backfill_window(days: int) -> tuple[date, date]:
    end = today_utc()
    start = end - timedelta(days=days)
    return start, end
```

Note: exact Garmin Connect endpoint shapes drift. If a fetch fails in production, adjust the path in this one file — the mappers operate on the raw response and are the stable boundary. When adjusting, save a real response as a new fixture in `tests/fixtures/` and update the matching mapper test.

- [ ] **Step 2: Commit** (no test — this module is the integration boundary)

```bash
git add services/ingestor-garmin
git commit -m "feat(ingestor-garmin): garth wrapper with session persistence + retries"
```

---

## Task 12: Ingestor repo (writes to Mongo, TDD)

**Files:**
- Create: `services/ingestor-garmin/app/repo.py`
- Create: `services/ingestor-garmin/tests/test_repo.py`

- [ ] **Step 1: Write failing tests**

Create `services/ingestor-garmin/tests/test_repo.py`:
```python
from datetime import datetime, timezone

from app.models import BodyComp, Sleep, Weight, Workout
from app.repo import GarminRepo


async def test_upsert_weight_idempotent(mock_db):
    repo = GarminRepo(mock_db)
    w = Weight(ts=datetime.now(timezone.utc), kg=108.9, source="garmin", source_id="garmin:weight:1")
    await repo.upsert_weight(w)
    await repo.upsert_weight(w)  # again
    count = await mock_db["metrics_weight"].count_documents({})
    assert count == 1


async def test_upsert_workout_idempotent(mock_db):
    repo = GarminRepo(mock_db)
    w = Workout(
        ts=datetime.now(timezone.utc),
        activity_type="walking",
        duration_s=1800,
        distance_m=2500.0,
        source="garmin",
        source_id="garmin:activity:1",
    )
    await repo.upsert_workout(w)
    await repo.upsert_workout(w)
    count = await mock_db["workouts"].count_documents({})
    assert count == 1


async def test_write_ingest_log(mock_db):
    repo = GarminRepo(mock_db)
    await repo.write_log(
        source="garmin",
        status="ok",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        counts={"weight": 3, "sleep": 1},
    )
    doc = await mock_db["ingestion_log"].find_one({"status": "ok"})
    assert doc["counts"]["weight"] == 3


async def test_consume_requests(mock_db):
    repo = GarminRepo(mock_db)
    await mock_db["ingestion_log"].insert_one({
        "source": "garmin",
        "status": "requested",
        "started_at": datetime.now(timezone.utc),
    })
    pending = await repo.consume_requests("garmin")
    assert pending == 1
    still = await mock_db["ingestion_log"].count_documents({"source": "garmin", "status": "requested"})
    assert still == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/ingestor-garmin && pytest tests/test_repo.py -v
```
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `services/ingestor-garmin/app/repo.py`**

```python
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models import BodyComp, HRV, RHR, Sleep, VO2Max, Weight, Workout


class GarminRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # Time-series collections: dedupe by meta.source_id via a pre-check query.
    # (MongoDB time-series does not support unique indexes directly.)

    async def _ts_upsert(self, coll: str, source_id: str, doc: dict) -> None:
        existing = await self.db[coll].find_one({"meta.source_id": source_id}, {"_id": 1})
        if existing:
            return
        await self.db[coll].insert_one(doc)

    async def upsert_weight(self, w: Weight) -> None:
        await self._ts_upsert(
            "metrics_weight",
            w.source_id,
            {"ts": w.ts, "kg": w.kg, "meta": {"source": w.source, "source_id": w.source_id}},
        )

    async def upsert_sleep(self, s: Sleep) -> None:
        await self._ts_upsert(
            "metrics_sleep",
            s.source_id,
            {
                "ts": s.ts,
                "duration_s": s.duration_s,
                "deep_s": s.deep_s,
                "rem_s": s.rem_s,
                "light_s": s.light_s,
                "awake_s": s.awake_s,
                "score": s.score,
                "meta": {"source": s.source, "source_id": s.source_id},
            },
        )

    async def upsert_hrv(self, h: HRV) -> None:
        await self._ts_upsert(
            "metrics_hrv",
            h.source_id,
            {"ts": h.ts, "rmssd_ms": h.rmssd_ms,
             "meta": {"source": h.source, "source_id": h.source_id}},
        )

    async def upsert_rhr(self, r: RHR) -> None:
        await self._ts_upsert(
            "metrics_rhr",
            r.source_id,
            {"ts": r.ts, "bpm": r.bpm,
             "meta": {"source": r.source, "source_id": r.source_id}},
        )

    async def upsert_body_comp(self, b: BodyComp) -> None:
        await self._ts_upsert(
            "metrics_body_comp",
            b.source_id,
            {
                "ts": b.ts,
                "weight_kg": b.weight_kg,
                "body_fat_pct": b.body_fat_pct,
                "muscle_mass_kg": b.muscle_mass_kg,
                "body_water_pct": b.body_water_pct,
                "bone_mass_kg": b.bone_mass_kg,
                "meta": {"source": b.source, "source_id": b.source_id},
            },
        )

    async def upsert_vo2max(self, v: VO2Max) -> None:
        await self._ts_upsert(
            "metrics_vo2max",
            v.source_id,
            {"ts": v.ts, "value": v.value,
             "meta": {"source": v.source, "source_id": v.source_id}},
        )

    async def upsert_workout(self, w: Workout) -> None:
        await self.db["workouts"].update_one(
            {"source_id": w.source_id},
            {"$set": w.model_dump()},
            upsert=True,
        )

    async def write_log(
        self, *, source: str, status: str, started_at: datetime,
        finished_at: datetime | None = None, counts: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        await self.db["ingestion_log"].insert_one({
            "source": source,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "counts": counts or {},
            "error": error,
        })

    async def consume_requests(self, source: str) -> int:
        result = await self.db["ingestion_log"].delete_many(
            {"source": source, "status": "requested"}
        )
        return result.deleted_count
```

- [ ] **Step 4: Run tests**

```bash
cd services/ingestor-garmin && pytest tests/test_repo.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/ingestor-garmin
git commit -m "feat(ingestor-garmin): GarminRepo with idempotent upserts and log writes"
```

---

## Task 13: Runner — end-to-end sync pass (TDD with fake client)

**Files:**
- Create: `services/ingestor-garmin/app/runner.py`
- Create: `services/ingestor-garmin/tests/test_runner.py`

- [ ] **Step 1: Write failing test (using a fake client)**

Create `services/ingestor-garmin/tests/test_runner.py`:
```python
import json
from datetime import date
from pathlib import Path

from app.repo import GarminRepo
from app.runner import run_sync


FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    with open(FIXTURES / name) as f:
        return json.load(f)


class FakeClient:
    def login(self) -> None: ...
    def fetch_sleep(self, d: date) -> dict: return _load("sleep.json")
    def fetch_hrv(self, d: date) -> dict: return _load("hrv.json")
    def fetch_weight(self, s: date, e: date) -> list[dict]: return _load("weight.json")
    def fetch_body_comp(self, s: date, e: date) -> list[dict]: return _load("body_comp.json")
    def fetch_vo2max(self, d: date) -> dict: return _load("vo2max.json")
    def fetch_workouts(self, s: date, e: date) -> list[dict]: return _load("workout.json")
    def fetch_rhr_series(self, s: date, e: date) -> list[dict]: return []


async def test_run_sync_writes_all_metrics(mock_db):
    repo = GarminRepo(mock_db)
    client = FakeClient()
    counts = await run_sync(client=client, repo=repo, backfill_days=1)
    assert counts["weight"] == 1
    assert counts["body_comp"] == 1
    assert counts["sleep"] == 1
    assert counts["hrv"] == 1
    assert counts["vo2max"] == 1
    assert counts["workouts"] == 1

    assert await mock_db["metrics_weight"].count_documents({}) == 1
    assert await mock_db["workouts"].count_documents({}) == 1


async def test_run_sync_idempotent(mock_db):
    repo = GarminRepo(mock_db)
    client = FakeClient()
    await run_sync(client=client, repo=repo, backfill_days=1)
    await run_sync(client=client, repo=repo, backfill_days=1)
    assert await mock_db["metrics_weight"].count_documents({}) == 1
    assert await mock_db["workouts"].count_documents({}) == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd services/ingestor-garmin && pytest tests/test_runner.py -v
```
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `services/ingestor-garmin/app/runner.py`**

```python
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
            await repo.upsert_weight(w)
            counts["weight"] += 1
    except Exception as e:
        log.exception("weight fetch failed: %s", e)

    try:
        for b in map_body_comp(client.fetch_body_comp(start, end)):
            await repo.upsert_body_comp(b)
            counts["body_comp"] += 1
    except Exception as e:
        log.exception("body_comp fetch failed: %s", e)

    day = end
    for _ in range(backfill_days + 1):
        try:
            await repo.upsert_sleep(map_sleep(client.fetch_sleep(day)))
            counts["sleep"] += 1
        except Exception as e:
            log.warning("sleep %s skipped: %s", day, e)
        try:
            await repo.upsert_hrv(map_hrv(client.fetch_hrv(day)))
            counts["hrv"] += 1
        except Exception as e:
            log.warning("hrv %s skipped: %s", day, e)
        try:
            await repo.upsert_vo2max(map_vo2max(client.fetch_vo2max(day)))
            counts["vo2max"] += 1
        except Exception as e:
            log.warning("vo2max %s skipped: %s", day, e)
        day -= timedelta(days=1)

    try:
        for wo in map_workout(client.fetch_workouts(start, end)):
            await repo.upsert_workout(wo)
            counts["workouts"] += 1
    except Exception as e:
        log.exception("workouts fetch failed: %s", e)

    return counts
```

- [ ] **Step 4: Run tests**

```bash
cd services/ingestor-garmin && pytest tests/test_runner.py -v
```
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add services/ingestor-garmin
git commit -m "feat(ingestor-garmin): end-to-end runner with idempotent per-day sync"
```

---

## Task 14: Ingestor main entrypoint (scheduler + request polling)

**Files:**
- Create: `services/ingestor-garmin/app/main.py`

- [ ] **Step 1: Implement `app/main.py`**

```python
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

    await _do_sync(settings, db)  # startup sync
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
```

- [ ] **Step 2: Smoke-check imports**

```bash
cd services/ingestor-garmin && python -c "from app import main"
```
Expected: no output (imports clean).

- [ ] **Step 3: Commit**

```bash
git add services/ingestor-garmin
git commit -m "feat(ingestor-garmin): main entrypoint with nightly schedule + on-demand poll"
```

---

## Task 15: Web — Vite + React skeleton

**Files:**
- Create: `services/web/package.json`
- Create: `services/web/tsconfig.json`
- Create: `services/web/vite.config.ts`
- Create: `services/web/tailwind.config.js`
- Create: `services/web/postcss.config.js`
- Create: `services/web/index.html`
- Create: `services/web/src/main.tsx`
- Create: `services/web/src/index.css`
- Create: `services/web/src/App.tsx`
- Create: `services/web/Dockerfile`
- Create: `services/web/nginx.conf`

- [ ] **Step 1: `package.json`**

```json
{
  "name": "hack-the-body-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.56.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "recharts": "^2.12.7"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.45",
    "tailwindcss": "^3.4.10",
    "typescript": "^5.5.4",
    "vite": "^5.4.3",
    "vitest": "^2.0.5"
  }
}
```

- [ ] **Step 2: `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: `vite.config.ts`**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
  },
});
```

- [ ] **Step 4: `tailwind.config.js`**

```js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

- [ ] **Step 5: `postcss.config.js`**

```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] **Step 6: `index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Hack the Body</title>
  </head>
  <body class="bg-neutral-950 text-neutral-100">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 7: `src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 8: `src/main.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import "./index.css";
import { router } from "./router";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 9: `src/App.tsx`** (unused; router drives layout — keep minimal placeholder or delete)

Create with a simple placeholder so the tree compiles even if referenced:
```tsx
export function App() {
  return <div>Hack the Body</div>;
}
```

- [ ] **Step 10: `Dockerfile`**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
ARG VITE_API_URL
ARG VITE_API_KEY
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

- [ ] **Step 11: `nginx.conf`**

```nginx
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;
  location / {
    try_files $uri /index.html;
  }
}
```

- [ ] **Step 12: Commit**

```bash
git add services/web
git commit -m "chore(web): vite + react + tailwind + react-query + router skeleton"
```

---

## Task 16: Web — typed API client (TDD on format helpers)

**Files:**
- Create: `services/web/src/api/types.ts`
- Create: `services/web/src/api/client.ts`
- Create: `services/web/src/lib/format.ts`
- Create: `services/web/src/lib/trend.ts`
- Create: `services/web/src/lib/__tests__/format.test.ts`
- Create: `services/web/src/lib/__tests__/trend.test.ts`

- [ ] **Step 1: Types**

Create `src/api/types.ts`:
```ts
export interface Summary {
  weight: WeightPoint | null;
  sleep: SleepPoint | null;
  hrv: HRVPoint | null;
  rhr: RHRPoint | null;
  body_comp: BodyCompPoint | null;
  vo2max: VO2MaxPoint | null;
}

export interface WeightPoint { ts: string; kg: number; meta?: Meta; }
export interface SleepPoint {
  ts: string; duration_s: number; deep_s: number; rem_s: number;
  light_s: number; awake_s: number; score: number | null; meta?: Meta;
}
export interface HRVPoint { ts: string; rmssd_ms: number; meta?: Meta; }
export interface RHRPoint { ts: string; bpm: number; meta?: Meta; }
export interface BodyCompPoint {
  ts: string; weight_kg: number;
  body_fat_pct: number | null; muscle_mass_kg: number | null;
  body_water_pct: number | null; bone_mass_kg: number | null;
  meta?: Meta;
}
export interface VO2MaxPoint { ts: string; value: number; meta?: Meta; }
export interface Workout {
  ts: string; activity_type: string; duration_s: number;
  distance_m: number | null; avg_hr: number | null; max_hr: number | null;
  calories: number | null; notes: string | null;
  source: string; source_id: string;
}
interface Meta { source: string; source_id: string; }
```

- [ ] **Step 2: Client**

Create `src/api/client.ts`:
```ts
import type {
  Summary, WeightPoint, SleepPoint, HRVPoint, RHRPoint, VO2MaxPoint, Workout,
} from "./types";

const BASE = import.meta.env.VITE_API_URL;
const KEY = import.meta.env.VITE_API_KEY;

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { headers: { "X-API-Key": KEY } });
  if (!r.ok) throw new Error(`GET ${path} failed: ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  summary: () => get<Summary>("/metrics/summary"),
  weightRange: (days = 60) => get<WeightPoint[]>(`/metrics/weight/range?days=${days}`),
  sleepRange:  (days = 30) => get<SleepPoint[]>(`/metrics/sleep/range?days=${days}`),
  hrvRange:    (days = 30) => get<HRVPoint[]>(`/metrics/hrv/range?days=${days}`),
  rhrRange:    (days = 30) => get<RHRPoint[]>(`/metrics/rhr/range?days=${days}`),
  vo2maxRange: (days = 90) => get<VO2MaxPoint[]>(`/metrics/vo2max/range?days=${days}`),
  workouts:    (days = 14) => get<Workout[]>(`/workouts?days=${days}`),
  triggerIngest: async (source: string) => {
    const r = await fetch(`${BASE}/admin/ingest/${source}`, {
      method: "POST",
      headers: { "X-API-Key": KEY },
    });
    if (!r.ok) throw new Error(`trigger failed: ${r.status}`);
    return r.json();
  },
};
```

- [ ] **Step 3: Write failing tests**

Create `src/lib/__tests__/format.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { formatDuration, formatKg, formatLbs, kgToLbs } from "../format";

describe("format", () => {
  it("kg to lbs", () => {
    expect(kgToLbs(108.9)).toBeCloseTo(240.08, 1);
  });
  it("formatKg", () => {
    expect(formatKg(108.9)).toBe("108.9 kg");
  });
  it("formatLbs", () => {
    expect(formatLbs(108.9)).toBe("240.1 lb");
  });
  it("formatDuration", () => {
    expect(formatDuration(7 * 3600 + 15 * 60)).toBe("7h 15m");
    expect(formatDuration(59 * 60)).toBe("59m");
  });
});
```

Create `src/lib/__tests__/trend.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { rollingAverage } from "../trend";

describe("rollingAverage", () => {
  it("empty", () => {
    expect(rollingAverage([], 7)).toEqual([]);
  });
  it("window fills as data accumulates", () => {
    const pts = [
      { ts: "2026-01-01", value: 100 },
      { ts: "2026-01-02", value: 102 },
      { ts: "2026-01-03", value: 104 },
    ];
    const out = rollingAverage(pts, 3);
    expect(out[2].avg).toBeCloseTo(102, 5);
    expect(out[0].avg).toBeCloseTo(100, 5);
  });
});
```

- [ ] **Step 4: Run to verify failure**

```bash
cd services/web && npm install && npm run test -- --run
```
Expected: FAIL on missing modules.

- [ ] **Step 5: Implement `src/lib/format.ts`**

```ts
export const kgToLbs = (kg: number): number => kg * 2.2046226218;

export const formatKg = (kg: number): string => `${kg.toFixed(1)} kg`;

export const formatLbs = (kg: number): string => `${kgToLbs(kg).toFixed(1)} lb`;

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}
```

- [ ] **Step 6: Implement `src/lib/trend.ts`**

```ts
export interface Point { ts: string; value: number; }
export interface Averaged extends Point { avg: number; }

export function rollingAverage(pts: Point[], window: number): Averaged[] {
  const out: Averaged[] = [];
  for (let i = 0; i < pts.length; i++) {
    const start = Math.max(0, i - window + 1);
    const slice = pts.slice(start, i + 1);
    const avg = slice.reduce((s, p) => s + p.value, 0) / slice.length;
    out.push({ ...pts[i], avg });
  }
  return out;
}
```

- [ ] **Step 7: Run tests**

```bash
cd services/web && npm run test -- --run
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add services/web
git commit -m "feat(web): typed API client + format/trend lib with unit tests"
```

---

## Task 17: Web — router, Dashboard, components

**Files:**
- Create: `services/web/src/router.tsx`
- Create: `services/web/src/pages/Dashboard.tsx`
- Create: `services/web/src/pages/Kiosk.tsx`
- Create: `services/web/src/components/MetricCard.tsx`
- Create: `services/web/src/components/WeightChart.tsx`
- Create: `services/web/src/components/SleepChart.tsx`
- Create: `services/web/src/components/HrvChart.tsx`
- Create: `services/web/src/components/WorkoutList.tsx`

- [ ] **Step 1: Router**

Create `src/router.tsx`:
```tsx
import { createBrowserRouter } from "react-router-dom";

import { Dashboard } from "./pages/Dashboard";
import { Kiosk } from "./pages/Kiosk";

export const router = createBrowserRouter([
  { path: "/", element: <Dashboard /> },
  { path: "/kiosk", element: <Kiosk /> },
]);
```

- [ ] **Step 2: MetricCard**

Create `src/components/MetricCard.tsx`:
```tsx
interface Props {
  label: string;
  value: string;
  sub?: string;
}

export function MetricCard({ label, value, sub }: Props) {
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 flex flex-col gap-1">
      <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
    </div>
  );
}
```

- [ ] **Step 3: WeightChart**

Create `src/components/WeightChart.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";
import { kgToLbs } from "../lib/format";
import { rollingAverage } from "../lib/trend";

export function WeightChart() {
  const { data } = useQuery({
    queryKey: ["weightRange", 60],
    queryFn: () => api.weightRange(60),
  });
  if (!data?.length) return <div className="text-neutral-500">no weight data yet</div>;

  const pts = data.map(d => ({ ts: d.ts, value: kgToLbs(d.kg) }));
  const smoothed = rollingAverage(pts, 7).map(p => ({
    ts: p.ts.slice(0, 10),
    weight: Number(p.value.toFixed(1)),
    avg7: Number(p.avg.toFixed(1)),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer>
        <LineChart data={smoothed}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="ts" stroke="#737373" fontSize={11} />
          <YAxis stroke="#737373" domain={["dataMin - 2", "dataMax + 2"]} fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Line type="monotone" dataKey="weight" stroke="#a3a3a3" dot={false} strokeWidth={1} />
          <Line type="monotone" dataKey="avg7" stroke="#22d3ee" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: SleepChart**

Create `src/components/SleepChart.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";

export function SleepChart() {
  const { data } = useQuery({
    queryKey: ["sleepRange", 30],
    queryFn: () => api.sleepRange(30),
  });
  if (!data?.length) return <div className="text-neutral-500">no sleep data yet</div>;

  const rows = data.map(s => ({
    ts: s.ts.slice(0, 10),
    hours: Number((s.duration_s / 3600).toFixed(2)),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={rows}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="ts" stroke="#737373" fontSize={11} />
          <YAxis stroke="#737373" domain={[0, 10]} fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Bar dataKey="hours" fill="#818cf8" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 5: HrvChart**

Create `src/components/HrvChart.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";

export function HrvChart() {
  const { data } = useQuery({
    queryKey: ["hrvRange", 30],
    queryFn: () => api.hrvRange(30),
  });
  if (!data?.length) return <div className="text-neutral-500">no HRV data yet</div>;

  const rows = data.map(h => ({
    ts: h.ts.slice(0, 10),
    rmssd: Number(h.rmssd_ms.toFixed(1)),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer>
        <LineChart data={rows}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="ts" stroke="#737373" fontSize={11} />
          <YAxis stroke="#737373" fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Line type="monotone" dataKey="rmssd" stroke="#f472b6" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 6: WorkoutList**

Create `src/components/WorkoutList.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { formatDuration } from "../lib/format";

export function WorkoutList() {
  const { data } = useQuery({
    queryKey: ["workouts", 14],
    queryFn: () => api.workouts(14),
  });
  if (!data?.length) return <div className="text-neutral-500">no workouts logged yet</div>;

  return (
    <ul className="divide-y divide-neutral-800">
      {data.map(w => (
        <li key={w.source_id} className="py-2 flex justify-between gap-4">
          <div>
            <div className="font-medium capitalize">{w.activity_type.replace(/_/g, " ")}</div>
            <div className="text-xs text-neutral-500">{w.ts.slice(0, 16).replace("T", " ")}</div>
          </div>
          <div className="text-right text-sm">
            <div>{formatDuration(w.duration_s)}</div>
            {w.distance_m != null && (
              <div className="text-neutral-500">{(w.distance_m / 1000).toFixed(2)} km</div>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 7: Dashboard page**

Create `src/pages/Dashboard.tsx`:
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { HrvChart } from "../components/HrvChart";
import { MetricCard } from "../components/MetricCard";
import { SleepChart } from "../components/SleepChart";
import { WeightChart } from "../components/WeightChart";
import { WorkoutList } from "../components/WorkoutList";
import { formatDuration, formatLbs } from "../lib/format";

export function Dashboard() {
  const { data: summary } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 60_000,
  });

  const qc = useQueryClient();
  const sync = useMutation({
    mutationFn: () => api.triggerIngest("garmin"),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Hack the Body</h1>
        <button
          onClick={() => sync.mutate()}
          disabled={sync.isPending}
          className="text-xs px-3 py-1.5 rounded bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50"
        >
          {sync.isPending ? "syncing..." : "sync garmin"}
        </button>
      </header>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label="Weight"
          value={summary?.weight ? formatLbs(summary.weight.kg) : "—"}
          sub={summary?.weight ? summary.weight.ts.slice(0, 10) : undefined}
        />
        <MetricCard
          label="Sleep"
          value={summary?.sleep ? formatDuration(summary.sleep.duration_s) : "—"}
          sub={summary?.sleep?.score != null ? `score ${summary.sleep.score}` : undefined}
        />
        <MetricCard
          label="HRV"
          value={summary?.hrv ? `${summary.hrv.rmssd_ms.toFixed(0)} ms` : "—"}
        />
        <MetricCard
          label="VO2 Max"
          value={summary?.vo2max ? summary.vo2max.value.toFixed(1) : "—"}
        />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Weight (60d, 7d avg)</h2>
        <WeightChart />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Sleep (30d)</h2>
        <SleepChart />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">HRV (30d)</h2>
        <HrvChart />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Recent workouts</h2>
        <WorkoutList />
      </section>
    </div>
  );
}
```

- [ ] **Step 8: Kiosk page (minimal placeholder — Task 18 fills it)**

Create `src/pages/Kiosk.tsx`:
```tsx
export function Kiosk() {
  return <div className="p-8">Kiosk (populated in Task 18)</div>;
}
```

- [ ] **Step 9: Build check**

```bash
cd services/web && npm run build
```
Expected: build succeeds, outputs to `dist/`.

- [ ] **Step 10: Commit**

```bash
git add services/web
git commit -m "feat(web): dashboard with summary cards, weight/sleep/hrv charts, workout list"
```

---

## Task 18: Kiosk layout (full-screen, large type)

**Files:**
- Modify: `services/web/src/pages/Kiosk.tsx`

- [ ] **Step 1: Replace `Kiosk.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { formatDuration, formatLbs } from "../lib/format";

export function Kiosk() {
  const { data } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 5 * 60_000,
  });

  const now = new Date();
  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const date = now.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });

  return (
    <div className="min-h-screen bg-black text-white p-10 flex flex-col gap-10 font-sans">
      <header className="flex items-baseline justify-between">
        <div>
          <div className="text-7xl font-semibold tabular-nums">{time}</div>
          <div className="text-2xl text-neutral-400 mt-2">{date}</div>
        </div>
        <div className="text-right">
          <div className="text-lg text-neutral-500 uppercase tracking-widest">Hack the Body</div>
        </div>
      </header>

      <main className="grid grid-cols-2 gap-8 flex-1">
        <KioskMetric
          label="Weight"
          value={data?.weight ? formatLbs(data.weight.kg) : "—"}
          sub={data?.weight?.ts.slice(0, 10)}
        />
        <KioskMetric
          label="Sleep"
          value={data?.sleep ? formatDuration(data.sleep.duration_s) : "—"}
          sub={data?.sleep?.score != null ? `score ${data.sleep.score}` : undefined}
        />
        <KioskMetric
          label="HRV"
          value={data?.hrv ? `${data.hrv.rmssd_ms.toFixed(0)} ms` : "—"}
        />
        <KioskMetric
          label="VO2 Max"
          value={data?.vo2max ? data.vo2max.value.toFixed(1) : "—"}
        />
      </main>

      <footer className="text-neutral-600 text-sm">
        Coach v2 — Phase 2 (not yet built)
      </footer>
    </div>
  );
}

function KioskMetric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col justify-center border border-neutral-800 rounded-2xl p-8 bg-neutral-950">
      <div className="text-xl uppercase tracking-widest text-neutral-500">{label}</div>
      <div className="text-8xl font-semibold tabular-nums mt-4">{value}</div>
      {sub && <div className="text-lg text-neutral-500 mt-2">{sub}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Build check**

```bash
cd services/web && npm run build
```
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add services/web/src/pages/Kiosk.tsx
git commit -m "feat(web): full-screen kiosk layout for /kiosk"
```

---

## Task 19: Pi kiosk setup docs

**Files:**
- Modify: `docs/pi-kiosk-setup.md` (full content)

- [ ] **Step 1: Replace with full instructions**

```markdown
# Pi Kiosk Setup

Turn an older Raspberry Pi + office monitor into a live Hack the Body dashboard.

## Requirements

- Raspberry Pi (3B+ or newer) with HDMI to the monitor
- Raspberry Pi OS (32- or 64-bit) Lite or Desktop
- Network access to the server running `docker compose up` (replace `<SERVER>` below)

## Steps

1. **Install Chromium and matchbox-window-manager (if Lite):**

   ```bash
   sudo apt update
   sudo apt install -y --no-install-recommends \
     xserver-xorg x11-xserver-utils xinit chromium-browser \
     matchbox-window-manager unclutter
   ```

2. **Disable screen blanking in `~/.xsessionrc`:**

   ```bash
   cat > ~/.xsessionrc <<'EOF'
   xset s off
   xset -dpms
   xset s noblank
   unclutter -idle 0 &
   matchbox-window-manager -use_titlebar no &
   chromium-browser --kiosk --incognito \
     --noerrdialogs --disable-infobars \
     --disable-session-crashed-bubble \
     http://<SERVER>:8080/kiosk
   EOF
   ```

3. **Autostart X on boot:** edit `~/.bash_profile`:

   ```bash
   if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
     startx
   fi
   ```

4. **Enable auto-login to tty1:** `sudo raspi-config` → System Options → Boot / Auto Login → Console Autologin.

5. **Reboot:** `sudo reboot`. The Pi should boot directly into the kiosk page.

## Updating

When the web service redeploys, just refresh (or power-cycle the Pi). No update steps on the Pi itself.

## Troubleshooting

- **Blank screen:** check `~/.xsession-errors`.
- **Chromium shows "connection refused":** confirm the server is reachable from the Pi (`curl http://<SERVER>:8080`).
- **Cursor stays on screen:** confirm `unclutter` installed; increase `-idle` if it flickers.
```

- [ ] **Step 2: Commit**

```bash
git add docs/pi-kiosk-setup.md
git commit -m "docs: pi kiosk setup instructions"
```

---

## Task 20: End-to-end smoke test + README quick-start polish

**Files:**
- Modify: `README.md` (expand quick-start)

- [ ] **Step 1: Bring the stack up**

```bash
cp .env.example .env
# edit .env: set API_KEY (long random), GARMIN_EMAIL, GARMIN_PASSWORD
docker compose up --build
```

Wait for:
- mongo healthy
- api logs show `Application startup complete`
- ingestor-garmin logs show `sync ok: {...}` (or a clear error if Garmin creds wrong)

- [ ] **Step 2: Hit the API**

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/metrics/summary | jq
```
Expected: JSON with `weight`, `sleep`, `hrv`, `rhr`, `body_comp`, `vo2max` keys; non-null for metrics that exist in your Garmin account.

- [ ] **Step 3: Open the dashboard**

Open `http://localhost:8080` — confirm metric cards show values and charts render. Click **sync garmin**; confirm ingestor picks up the request within ~30s and refetches.

- [ ] **Step 4: Open the kiosk route**

Open `http://localhost:8080/kiosk`. Confirm full-screen layout.

- [ ] **Step 5: If anything fails, debug**

Use superpowers:systematic-debugging. Common issues:
- **Garmin login fails** → verify email/password in `.env`; delete `garmin_session` volume to force re-login (`docker compose down -v` is destructive — only the garmin_session volume: `docker volume rm hack-the-body_garmin_session` instead).
- **CORS in browser** → confirm `CORS_ORIGINS` includes `http://localhost:8080`.
- **Empty summary** → ingestor may still be running first pull; check `docker compose logs ingestor-garmin`.

- [ ] **Step 6: Expand README quick-start**

Update `README.md` Quick start section with:
```markdown
## Quick start (Phase 0+1)

1. Copy env: `cp .env.example .env`
2. Fill in `.env`:
   - `API_KEY` — generate with `openssl rand -hex 32`
   - `GARMIN_EMAIL` / `GARMIN_PASSWORD` — your Garmin Connect login
3. Bring up the stack: `docker compose up --build -d`
4. Tail logs until ingestor finishes first sync: `docker compose logs -f ingestor-garmin`
5. Visit:
   - Dashboard: http://localhost:8080
   - Kiosk: http://localhost:8080/kiosk
   - API: `curl -H "X-API-Key: $API_KEY" http://localhost:8000/metrics/summary`

## Trigger a manual sync

```bash
curl -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/admin/ingest/garmin
```

## Running tests

```bash
# API
cd services/api && pip install -e ".[dev]" && pytest

# Ingestor
cd services/ingestor-garmin && pip install -e ".[dev]" && pytest

# Web
cd services/web && npm install && npm test -- --run
```
```

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: quick-start + smoke test instructions"
```

---

## Phase exit checklist

- [ ] All service tests green
- [ ] `docker compose up` brings everything up cleanly on a fresh clone
- [ ] Ingestor completes at least one sync against a real Garmin account
- [ ] Dashboard shows real weight, sleep, HRV, VO2max, and recent workouts
- [ ] Kiosk route renders full-screen with large metrics
- [ ] Pi is booting into the kiosk (or deferred pending hardware access)
- [ ] README quick-start works from a clean clone

When this is green, Phase 1 is done. Next plan: **Phase 2 — Telegram coach + voice loop**.

---

## Self-review notes (resolved inline)

- Spec coverage: Garmin ingestor (covers watch + scale as a single source per spec) ✅; web dashboard ✅; Pi kiosk ✅; data spine ✅; admin trigger ✅. Coach, Telegram, food tracker, mobile app, treadmill are explicitly deferred.
- No placeholders: all TODO/TBD removed.
- Type consistency: `source_id` everywhere on time-series meta; `meta` wrapper field consistent across repo + API serialization; ingestor has its own `app/models.py` to keep the service decoupled.
- Scope: single milestone, fits one plan.
