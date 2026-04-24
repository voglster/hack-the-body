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
