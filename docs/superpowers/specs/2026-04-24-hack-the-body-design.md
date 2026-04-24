# Hack the Body — System Design

**Date:** 2026-04-24
**Owner:** Jim (Matthew Wisdom)
**Goal:** A self-hosted, AI-coached system that tracks health metrics and automates programming for strength, cardio, sleep, and nutrition — so the user stops thinking about "what's next" and just follows the plan.

---

## 1. User profile

- 43M, 6'5", 240lb
- Background: distance runner (HS track/XC), lifelong bodyweight/calisthenics preference; never barbell-trained
- Equipment: rings, parallettes, mats, treadmill (older, hackable), pool (seasonal), outdoor walking
- Constraints: full-time job; minor right-knee tenderness (likely load-related, not injury)
- Tech: self-hoster; Python/React/Expo dev; GPUs available (RTX 4090 + 128GB RAM framework desktop, RTX 3080 secondary); Garmin watch + Garmin scale; already cloned voices via Qwen3-TTS
- Goal phrasing: *"strong and healthy, live longer, build habits that keep it"* — aesthetics are an afterthought

## 2. System goals and non-goals

**Goals**
- Single source of truth for all health and training data
- Zero-friction logging (voice, photo, barcode, auto-ingestion)
- AI coach that **auto-adjusts** the plan based on recovery signals — not just suggests
- Conversational interface (Telegram + cloned female voice)
- Visible progress at a glance (web dashboard + Pi kiosk on office monitor)
- Habit durability — system should still be used at month 12, month 24
- Self-hosted, private; hybrid local LLM + Claude API where it earns its keep

**Non-goals (v1)**
- Multi-user support. Single tenant.
- Public mobile app store distribution. Expo Go / TestFlight is fine.
- Medical-grade accuracy or clinical claims.
- Replacing a doctor — bloodwork is manual upload, not automated.

## 3. Success criteria (6 months)

- Data spine captures ≥95% of daily metrics (sleep, weight, HR, HRV, workouts) without manual intervention
- User logs ≥80% of meals (voice/photo/barcode counts)
- ≥5 training sessions completed per week on average
- Coach has auto-adjusted ≥1 session per week based on recovery data
- Measurable: body composition shift, strength progression on documented calisthenics movements, VO2max trend up, resting HR down, sleep duration ≥7h average

## 4. Architecture

Four loosely-coupled layers. Each can be built, tested, and replaced independently.

```
+---------------------------------------------------------------+
|                         APPS (clients)                        |
|  Web dashboard (React)   Expo mobile   Pi kiosk   Telegram    |
+----------------------------+----------------------------------+
                             |
                             v
+---------------------------------------------------------------+
|                    API (FastAPI, Python)                      |
|   Auth (single user)   REST + WS   Orchestration              |
+----------------+-----------------------+----------------------+
                 |                       |
                 v                       v
+----------------------------+  +-----------------------------+
|       DATA SPINE           |  |       COACH BRAIN           |
|   MongoDB (time-series +   |  |   Daily planner (cron)      |
|   document collections)    |  |   Chat coach (on-demand)    |
|                            |  |   Weekly reviewer (cron)    |
+----------------------------+  |   Voice loop (Whisper+TTS)  |
                 ^              +--------------+--------------+
                 |                             |
                 |                             v
+------------------------------+   +-----------------------------+
|        INGESTORS             |   |     LOCAL AI SERVICES       |
|  garmin_ingestor             |   |  Whisper STT (3080)         |
|  (HR/HRV/sleep/weight/       |   |  Qwen3-TTS cloned voice     |
|   body-comp/workouts/VO2max) |   |  Local LLM (4090, 70B Q4)   |
|  food_ingestor (own UI)      |   |  Vision model (meal photos) |
|  treadmill_ingestor (P5)     |   |  Claude API (weekly review) |
+------------------------------+   +-----------------------------+
```

All runs via **docker-compose**. Single-host deploy on one of the user's servers.

## 5. Tech stack

| Layer | Choice | Why |
|---|---|---|
| DB | MongoDB (7+ time-series collections) | User preference; document shape fits workouts/meals/coach memory naturally |
| API | Python + FastAPI + Pydantic | User's primary language; async-native |
| Workers | Python + APScheduler (or Celery if it grows) | Same codebase as API; simpler than Celery for single-host |
| Web | React + Vite + TanStack Query + Recharts | Standard; Pi kiosk reuses the same bundle |
| Mobile | Expo (React Native) | User has shipped Expo apps before |
| Bot | python-telegram-bot | Mature; supports voice messages |
| Local LLM | Ollama or vLLM hosting Qwen/Llama 70B at Q4 on 4090 | Private, free per-token, always-on |
| STT | faster-whisper on 3080 | Fast, local |
| TTS | Qwen3-TTS with user's pre-cloned female voice | Already set up |
| Vision | Qwen-VL (or similar) on 4090 for meal photo → macros | Local |
| Remote LLM | Claude API (Opus 4.7) for weekly review, with prompt caching | Deep reasoning, once/week, cheap via cache |
| Orchestration | docker-compose (single host) | User preference |
| Secrets | `.env` + docker secrets | Self-hosted; no cloud secret manager needed |

## 6. Data model (MongoDB collections)

Time-series collections (`timeseries: { timeField, metaField, granularity }`):
- `metrics.heart_rate` — resting, max, zones
- `metrics.hrv` — nightly HRV from Garmin
- `metrics.sleep` — duration, stages, score
- `metrics.weight` — daily morning weigh-in
- `metrics.body_comp` — BF%, lean mass, water % (from Garmin scale)
- `metrics.vo2max` — trended from Garmin
- `metrics.rhr` — resting HR trend

Document collections:
- `user_profile` — single doc: goals, constraints, zones, targets
- `plans.daily` — today's plan (workout, macros, nudges) — regenerated each morning
- `plans.weekly` — current week's structure (written Sundays by reviewer)
- `plans.program` — 6-month program template; the coach instantiates against it
- `workouts` — completed sessions: movements, sets, reps, RPE, notes
- `meals` — logged meals: items, macros, source (barcode/photo/voice), timestamp
- `coach_memory.summary` — rolling 90-day summary, refreshed weekly
- `coach_memory.journal` — coach's written weekly reviews, monthly reports
- `nudges` — scheduled + sent push/telegram messages, with ack status
- `ingestion_log` — per-ingestor runs: source, start/end, counts, errors
- `conversations` — Telegram chat history (for context, privacy-controlled retention)

Indexes: `(userId, timestamp)` on metrics; text index on journal/summary for recall.

## 7. Components

### 7.1 Data spine API
Single-user FastAPI app. Endpoints grouped:
- `/metrics/*` — read trends, latest values, windowed queries
- `/plans/today`, `/plans/week` — read/write
- `/workouts`, `/meals` — CRUD
- `/coach/message` — proxy to coach brain (supports streaming)
- `/ingest/trigger/{source}` — manual re-pull
- `/admin/health` — system status

Auth: single API key for local clients + Telegram bot token for bot. No multi-user complexity.

### 7.2 Ingestors
Each ingestor is a small Python module with a `run(since: datetime)` function and a cron entry.

- **garmin_ingestor** — uses `garth` (Garmin's unofficial OAuth) or `python-garminconnect`. Nightly at 4am local + on-demand. Pulls: sleep, HRV, resting HR, workouts (including indoor/outdoor), weight, body comp, VO2max. Idempotent (upserts on `(source_id)`).
- **food_ingestor** — reads our own food-tracker writes; no external source. Open Food Facts barcode DB is bundled/cached locally.
- **treadmill_ingestor (Phase 5)** — BLE FTMS profile first; fall back to microcontroller-on-console-headers approach if the treadmill is too old to expose FTMS.

### 7.3 Coach brain
Three agents, one codebase, same tool set, different triggers.

**Shared tools (function-call interface):**
- `get_metrics(kind, window)` — read time-series
- `get_plan(day|week)`, `update_plan(day|week, diff)`
- `log_workout(...)`, `log_meal(...)`
- `send_telegram(text, voice?)`
- `schedule_nudge(when, text)`
- `read_journal(window)`, `write_journal(entry)`
- `search_memory(query)` — over `coach_memory.*`

**Daily planner** (cron, 5:30am local): reads last night's sleep + HRV + yesterday's completion + current weekly plan → generates today's plan doc → sends Telegram morning message (text + cloned-voice audio). Low-HRV auto-swap: if HRV drops >1 SD below rolling 14-day mean or sleep <6h, swap strength for Z2, or swap Z2 for mobility.

**Chat coach** (on-demand): Telegram bot webhook → transcribe (if voice) → LLM w/ tools → respond (text + audio). Keeps last N turns in `conversations`.

**Weekly reviewer** (cron, Sunday 9pm local): aggregates the week → writes journal entry → updates `coach_memory.summary` → sets next week's plan → Sunday-night voice convo prompt. Uses **Claude API** (not local LLM) because this is the deep-think pass; prompt-cached over the 90-day summary for low cost.

### 7.4 Apps
- **Web dashboard** — trends, today's plan, log-anywhere. Primary desktop surface.
- **Expo mobile** — quick-log (barcode, photo, voice), workout timer with set/rep/RPE entry, Telegram is *not* replaced (it stays as primary chat).
- **Pi kiosk** — same React bundle, `?mode=kiosk` route: today's plan + 3 big metrics + next nudge + time + clock of next workout. Boots Chromium in kiosk mode pointing at local URL.
- **Telegram bot** — chat coach, morning push, meal-photo upload, voice in/out.

### 7.5 Voice loop
1. Telegram voice message → bot receives OGG → faster-whisper (3080) → text
2. Text → local LLM (4090) w/ tools → response text
3. Response text → Qwen3-TTS w/ cloned female voice → OGG → Telegram voice reply
4. Transcript + audio saved to `conversations`

Latency target: <6s from end-of-speech to start of reply audio.

## 8. The 6-month program

Defaults; coach adapts weekly. Movements reference Steven Low's *Overcoming Gravity* progressions.

**Months 1–2: Foundation**
- **Strength** 3×/week (Mon/Wed/Fri): ring rows, push-up progressions, parallette dips, tuck holds, hollow-body, Bulgarian split squats, single-leg RDLs. Hip/glute bias to protect the right knee.
- **Z2 cardio** 4×/week (Tue/Thu/Sat + 1 flex): 30–45min on treadmill or outdoor walk, HR-capped by Garmin zone.
- **Mobility** 10min daily: hip/shoulder/thoracic.
- **Nutrition**: ~500 kcal deficit, protein ~200g/day (≈1g/lb lean mass estimate), whole foods bias. Targets set from 7-day weight trend, not daily noise.
- **Sleep**: 7.5h window enforced by nudges.

**Months 3–4: Build**
- Strength adds: ring dips, pseudo-planche push-ups, pistol progressions, L-sit work, chin-ups on rings.
- One cardio day → intervals. Pool opens → swim replaces one Z2.
- Nutrition → maintenance as comp improves; protein floor holds.

**Months 5–6: Consolidate**
- Skills: muscle-up progression, handstand, front lever progression.
- Mixed cardio: Z2, intervals, swim, long walk.
- Habit audit: coach doubles down on what stuck, quietly drops what didn't.

**Biomarkers tracked:** RHR, HRV, sleep duration/stages, weight (7-day avg), BF% if scale gives it, VO2max, strength PRs (reps×load proxy), streak counts, subjective energy 1–10 (daily 1-tap).

## 9. Feedback loops

- **Daily**: HRV + sleep score + yesterday's completion → today's plan auto-adjusts
- **Weekly**: weight trend + completion rate + subjective energy → next week's plan + nutrition targets adjusted
- **Monthly**: VO2max, BF%, strength PRs → coach writes progress report, tweaks program phase if ahead/behind
- **Quarterly (manual)**: bloodwork upload (OCR) → coach notes shifts, flags

## 10. Non-negotiables the coach enforces

- 7.5h sleep window; nag if bedtime drifting
- Protein floor ~200g/day
- Daily weigh-in (trend, not noise)
- Daily Z2 *or* strength; rest day must be intentional (confirmed, not accidental)
- Sunday-night weekly voice check-in with cloned coach

## 11. Build phases

**Phase 0 — Repo skeleton (day 1)**
Monorepo, docker-compose, Mongo, FastAPI skeleton, Expo skeleton, env/secrets scaffold.

**Phase 1 — Data spine + Garmin + dashboard (week 1–2)**
- Mongo time-series collections
- Garmin ingestor (covers watch + scale)
- Web dashboard: weight, sleep, HRV, RHR, VO2max, workouts
- Pi kiosk mode
- Milestone: **user sees all their data in one place**

**Phase 2 — Coach v1 + Telegram voice loop (week 3)**
- Telegram bot
- Whisper STT, Qwen3-TTS cloned voice, local LLM
- Daily planner agent + chat coach
- Long-term memory collections
- Milestone: **user wakes up to "here's your day" in her voice**

**Phase 3 — Workout + food tracker (week 4–5)**
- Expo app: workout logger (sets/reps/RPE, timer)
- Food tracker: barcode (Open Food Facts), photo→vision→macros, voice logging
- Milestone: **logging friction near zero**

**Phase 4 — Weekly reviewer + smart nudges (week 6)**
- Claude-API-backed Sunday reviewer (prompt-cached)
- Push notifications (Expo push)
- Bedtime/hydration/Z2-window nudges
- Milestone: **system self-tunes weekly**

**Phase 5 — Treadmill hack + swim (when pool warms)**
- BLE FTMS first; microcontroller fallback
- Swim logging via Garmin (already supported by Phase 1 ingestor)
- Milestone: **every modality captured**

**Phase 6 — Polish + habit reports (ongoing)**
- Monthly PDF/email progress report
- Streak heatmaps, habit reports
- Manual bloodwork upload + OCR

## 12. Risks and open questions

- **Local LLM quality at 70B Q4**: may be insufficient for nuanced coaching. Mitigation: route complex queries to Claude API on fallback; weekly review is always Claude.
- **Garmin API stability**: `garth` is unofficial. Mitigation: cache raw responses; manual export fallback path.
- **Treadmill hack unknowns**: until we open it up, unknown whether FTMS / serial / hall-effect sensor route is needed. Deferred to Phase 5 intentionally.
- **Habit durability is the real test, not the build**: the system succeeds only if used at month 6. Phase 4's nudge tuning is load-bearing.
- **Single-user assumption is load-bearing**: auth, multi-tenancy, ACLs are explicitly out. If this ever changes, expect non-trivial rework.

## 13. Out of scope (v1)

- Multi-user / family sharing
- Social features
- Public distribution
- Medical/clinical advice
- Supplement or pharmaceutical recommendations
- Automated grocery ordering (maybe v2)
- Continuous glucose monitor integration (maybe v2)
