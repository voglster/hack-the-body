# Hack the Body

Self-hosted AI-coached health and training system.

See `docs/superpowers/specs/2026-04-24-hack-the-body-design.md` for full design.

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

## Services

- `services/api` — FastAPI data spine (Mongo-backed)
- `services/ingestor-garmin` — Pulls Garmin data nightly
- `services/web` — React dashboard + Pi kiosk

## Running tests

```bash
# API
cd services/api && pip install -e ".[dev]" && pytest

# Ingestor
cd services/ingestor-garmin && pip install -e ".[dev]" && pytest

# Web
cd services/web && npm install && npm test -- --run
```

## Pi kiosk

See `docs/pi-kiosk-setup.md` to set up the office monitor as a live dashboard.
