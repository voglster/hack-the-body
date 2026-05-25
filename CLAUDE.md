# Hack the Body — Project Notes for Claude

## Tooling

**Python: `uv` only.** The `services/api/` and `services/ingestor-garmin/` venvs
were created with `uv venv` and use uv-managed installs. Defaults:

- Run scripts: `uv run <script.py>`, or use the existing `.venv/bin/python`.
- Add a dep to a service: `cd services/<name> && uv pip install <pkg>` (writes
  into that service's `.venv`). For project dependencies that should stick,
  edit `pyproject.toml` and re-sync with `uv sync`.
- Ad-hoc data scripts at the repo root: `uv run --with matplotlib --with pymongo script.py` or similar — uv builds an ephemeral env per invocation.
- **Never** `pipx`, `pip install --user`, or `--break-system-packages`.

## Workflow for this repo

This is a personal tool, single committer, non-critical. Skip the
"don't auto-commit until reviewed" gate from the global CLAUDE.md:
when tests + lint + typecheck are all green, commit and push to
master without waiting for explicit approval. Reserve the review
pause for destructive or hard-to-reverse actions.

**Prod host access (`hd`):** SSH access to `hd` is pre-approved for
this project. Use it freely for read-only inspection (mongo queries,
log tails, `docker ps`, etc.) and for routine deploy actions
(`docker compose pull && up -d`, restarting containers). You manage
this deployment. Still confirm before destructive ops (dropping
collections, removing volumes).

## Repo

- **GitHub:** `voglster/hack-the-body` (public)
- **Default branch:** `main`
- Feature branches → PR → merge to `main` → CI builds + pushes to GHCR → Watchtower updates the running containers.

## Architecture

See `docs/superpowers/specs/2026-04-24-hack-the-body-design.md` (full design) and `docs/superpowers/plans/` (per-phase plans). Phase 0+1 (data spine + Garmin + dashboard + Pi kiosk) is built. Future phases: Telegram coach + voice loop, food/workout tracker, weekly reviewer, treadmill hack.

## Playbooks

- **Coach debugging** — when the coach says something wrong, read
  `docs/coach-debugging.md`. It documents the closed loop: 👎 in the
  app → `tools/coach_feedback.py show <id>` → targeted SYSTEM_PROMPT
  edit → deploy → `tools/coach_feedback.py clear` so the next review
  starts fresh. Every saved insight carries its full prompt inputs
  (food_totals, history_snapshot, rendered prompt, active
  system_prompt) so tuning is never blind.

## Build & deploy

### Single-image strategy

The frontend is bundled **into the API image**. The Vite build runs in a multi-stage Dockerfile (`services/api/Dockerfile`), and FastAPI serves the resulting static files from `/`. There is no separate web container, no nginx, no runtime config-injection script. FastAPI also serves `/config.js` dynamically — it returns `window.__HTB__ = { apiUrl: "", apiKey: "<settings.api_key>" }` so the same-origin browser bundle can authenticate.

Three images ship to GHCR:

- `ghcr.io/voglster/hack-the-body-app` — FastAPI + bundled FE
- `ghcr.io/voglster/hack-the-body-ingestor-garmin` — Garmin nightly puller
- `ghcr.io/voglster/hack-the-body-treadmill-tracker` — Precor CSAFE relay (writes raw samples; pull-on-read aggregator in the API turns them into `workouts`)

### CI

`.github/workflows/build.yml` builds both images on every push to `main`. Build context is the repo root for both (`api/Dockerfile` references `services/web/` to pull the FE source into the build stage). Tags: `:latest` on `main`, `:sha-<short>` always.

### Hosts

User runs Docker on multiple hosts following a consistent pattern:

- `~/compose/<project>/docker-compose.yml` per project, `.env` next to it
- Images pulled from `ghcr.io/voglster/...` (or `docker.jc.turbo.inc/...` for some other projects)
- One Watchtower instance per host watches a named list of containers (60s interval, `~/.docker/config.json` for registry auth). Watchtower lives in `~/compose/lumbergh-cloud/docker-compose.yml` on `hd`.

To deploy hack-the-body to a host:

1. SSH in.
2. `mkdir -p ~/compose/hack-the-body && cd ~/compose/hack-the-body`
3. Copy `compose/docker-compose.yml` and `compose/.env.example` from this repo into that dir; rename `.env.example` → `.env` and fill in `API_KEY`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`.
4. `docker compose up -d`
5. Add the two container names to Watchtower's command list in `~/compose/lumbergh-cloud/docker-compose.yml`:
   ```
   command: --interval 60 --cleanup ...existing... hack-the-body-app hack-the-body-ingestor
   ```
   Then `docker compose up -d watchtower` in that dir to restart Watchtower.

Public GHCR images don't need `docker login`. (Mongo image is from Docker Hub, also public.)

### Hosts in use

- **`hd`** (LAN docker host) — primary. Pi kiosk points at `http://hd:8080/kiosk`.
- **Remote docker host** — secondary instance (separate Garmin pull, separate Mongo). Useful when away from home.

## How the FE/BE merge works

- `services/api/Dockerfile` is multi-stage: stage 1 (`node:20-alpine`) installs `services/web/` deps and runs `npm run build`; stage 2 (`python:3.12-slim`) installs the API and copies `/web/dist` into `/app/static`.
- `services/api/app/main.py` mounts `/app/static/assets` at `/assets` and adds a SPA-fallback catch-all that serves `index.html` for unmatched GETs (so `/`, `/kiosk`, etc. all work).
- `/config.js` is a FastAPI route, not a static file. It writes the API key into `window.__HTB__` so the same-origin browser can call `/metrics/*` etc.
- API endpoints (`/metrics/*`, `/workouts`, `/admin/*`, `/healthz`) are defined before the SPA fallback, so they take precedence.

## Local development

```bash
# Run tests
cd services/api && .venv/bin/pytest          # 21 tests
cd services/ingestor-garmin && .venv/bin/pytest  # 12 tests
cd services/web && npm test -- --run         # 6 tests

# Run the FE in dev mode (hot reload, Vite proxy or env-based API URL)
cd services/web && npm run dev

# Build the production image locally
docker build -t hack-the-body-app:dev -f services/api/Dockerfile .
```

The dev `docker-compose.yml` at the repo root builds locally from source. Production lives in `compose/docker-compose.yml` and pulls from GHCR.

## Conventions

- **Tests required** for logic units (mappers, repos, routes, lib helpers). Boilerplate (Dockerfiles, Vite config, fixtures) doesn't need tests.
- **Mongo time-series collections** dedupe by `meta.source_id` via insert-or-skip. There's no unique index on time-series collections, so the repo does an explicit pre-check. See `services/ingestor-garmin/app/repo.py::_ts_upsert`.
- The ingestor service polls `ingestion_log` every 30s for `status: "requested"` rows that the API writes there in response to `POST /admin/ingest/garmin`. Poor man's job queue, intentional.

## Phase 2 readiness

When implementing Phase 2 (Telegram coach + voice loop), the local LLM, Whisper, TTS, and vision services run on `framework` (RTX 4090, 128GB) and a 3080 box — not on `hd`. The coach service container talks to those over the LAN.
