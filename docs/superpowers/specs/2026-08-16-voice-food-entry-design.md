# Voice Food Entry — Design

**Date:** 2026-08-16
**Status:** Draft, approved direction
**Related:** `services/api/app/services/food_parser.py`, `services/api/app/routers/foods.py`, `services/web/src/components/PasteFood.tsx`, `~/src/personal/port` (the architecture this ports)

## Problem

Food logging is the highest-friction thing in the system and the protocol
started 2026-08-16 makes it the *primary* thing: the success metric for weeks
6–8 is logging consistency, not weight. Today the only text path is
`PasteFood` — paste a breakdown, review it, bulk-log. That works when you are
sitting at a keyboard with a breakdown already written. It does not work
standing in the kitchen holding a plate, which is when food actually gets
eaten and when logging actually gets skipped.

Meanwhile the whole speech stack is already running and unused.

## Goal

Say what you ate. It gets logged. If it got something wrong, undo is one tap.

Nothing else. No conversation, no coaching, no workout logging.

## What already exists

Two thirds of this is built:

- **Extraction.** `POST /foods/parse` turns freeform text into structured
  items via the local LLM; `POST /foods/parse/log` parses and logs in one
  call; `POST /foods/parse/feedback` and the `parse_feedback` collection
  already capture "this went wrong."
- **Speech.** `llmbox` (tailscale `100.64.183.66`, RTX 3080) runs WhisperLive
  on `:9091` with the `faster_whisper` backend — verified `SERVER_READY`, and
  verified reachable from inside the `hack-the-body-app` container by IP and
  by bare name (`hd` is on the tailnet as `docker02`). Same service and port
  Port's `PPORT_VOICE_STT_HOST` targets.

So this spec is not "build voice." It is "bolt transcription onto a pipeline
that already works, and give the decoder the vocabulary it needs."

## Decisions

Recorded with reasoning, because each has a plausible opposite:

| Decision | Why not the alternative |
|---|---|
| **Food only** | `strength_sets` is written *only* by the Hevy ingestor; the workouts router is read-only. Voice workout logging means building a write path, an exercise catalog and a resolution layer from zero. Food needs none of that. |
| **Auto-log, then undo** | A confirm step costs one deliberate tap on the exact action whose friction broke the habit. `PasteFood` keeps the review flow for pasted breakdowns, where it earns its place. |
| **Batch, not live streaming** | In Port, live (#1143) came long after batch (#697) and *falls back* to it, so batch is a prerequisite either way. Live's payoff is watching a transcript form before you review it — and there is no review step here. |
| **Synchronous request** | Port's "nothing blocking" rule was written for 20-second models and marketers losing cell signal. Single user, own tailnet, parse measured at 1.2–3.3s. This repo has no worker: the `ingestion_log` 30s poll is a bespoke Garmin queue, not a general one. `PasteFood` already awaits a multi-second parse behind a spinner. |
| **Decode audio in the browser** | The API image is `python:3.13-slim` with no ffmpeg (confirmed in the running container). Browser-side `decodeAudioData` avoids a ~100 MB system dependency and makes the server leg a pass-through. Reversible: if live streaming is ever built, ffmpeg arrives then, which is exactly when Port needed it. |
| **No audio retention** | Port keeps audio because a transcript is model output and scoring against it "reports a flawless model forever" — true, and unreconstructable for an archive of many marketers. Here it is one person who can generate twenty labelled samples in ten minutes once a harness exists. Storing audio nothing reads is cost without use. |

## Architecture

### Flow

```
POST /foods/voice/log      multipart: pcm (16kHz mono int16 WAV) + slot + optional ts
  → build SpeechContext   (hotwords + initial_prompt from the food catalog)
  → Transcriber.transcribe(pcm, ctx)        → transcript
  → food_parser.parse(transcript)           → items[]
  → existing parse-and-log write path       → entry ids
  → persist voice_entries doc
  ← { transcript, items[], logged_entry_ids[], ms{...} }
```

One atomic call. Auto-log means there is no review step to hang a second round
trip on, and an atomic call cannot leave a transcript with no entries.

**Latency budget is estimated, not measured:** ~2–4s transcription (a 15s clip
on the 3080 at 10–20× realtime, plus the 0.75s settle hold and 1.5s flush pad)
and ~1–3s parse, so roughly **4–7s**. **Measure this first.** If it lands at
the top of that range, the escape hatch is splitting into
`POST /foods/voice/transcribe` (returns text immediately) and letting the
client chain the existing parse+log, so words appear in ~3s and items a beat
later. Do not build that up front.

### The boundary — `app/services/voice/`

New package. The vendor sits behind an interface this repo owns, **off by
default and mocked**, so tests and CI never reach `llmbox`.

```python
@dataclass
class SpeechContext:
    hotwords: list[str]
    initial_prompt: str

class Transcriber(Protocol):
    async def transcribe(self, pcm: bytes, ctx: SpeechContext) -> str: ...

class BoundaryUnavailable(Exception): ...

def build_transcriber(settings) -> Transcriber   # Mock unless voice_stt_host is set
```

`BoundaryUnavailable` is a first-class answer, not an error. Voice is an
accelerator on a logger that works without it: the caller degrades to
`PasteFood` and the reason lands in the logs. The failure most likely in
practice is `llmbox` being down or unreachable — the thing that works for
months and then quietly does not.

New settings on `Settings`:

| Setting | Default | Note |
|---|---|---|
| `voice_stt_host` | `""` | Empty means the mock. Set to `100.64.183.66`. |
| `voice_stt_port` | `9091` | |
| `voice_timeout_s` | `30.0` | Exceeded → `BoundaryUnavailable` |
| `voice_max_audio_bytes` | `4_000_000` | 60s of 16kHz mono int16 ≈ 1.9 MB |

### `WhisperLiveTranscriber` — ported, not rewritten

Lift from `port/backend/app/deal/voice_boundary.py`, **including the comments
explaining why**. Three behaviours are load-bearing and each is a bug someone
already paid for:

1. The server answers `SERVER_READY` before it will accept audio.
2. It does not flush on end-of-audio, so **the tail of a dictation is lost
   unless silence is pushed in behind it** (1.5s pad, sent at once, with the
   0.75s deadline held separately).
3. It keeps re-sending completed segments while idle, so "settled" is a
   *text has stopped changing* judgement — not a message-arrival one — and the
   transcript is accumulated across messages **by segment `start`**, never
   rebuilt from the last message.

A future edit that "simplifies" any of these reintroduces a known bug. Pin
them with tests.

### Vocabulary — `app/services/voice/vocabulary.py`

Prompting is the entire accuracy story: Jim's own `bench-stt` measured
`base.en` going from 0.054 WER to 0.000 once `initial_prompt` and `hotwords`
were set, with no larger model beating it on clean audio. Without "Fairlife"
in the hotwords the decoder writes "fair life" and the parser has nothing to
match.

Built **at request time** from `foods` (177 docs), `meal_templates`, and mined
usuals signatures. Never a hand-maintained list — the catalog grows every time
something new is logged, and a list correct on the day it was written is wrong
by the end of the week.

Rules:

- **No case normalisation.** `.title()` turns `RXBAR` into `Rxbar` and `OIKOS`
  into `Oikos`. The catalog holds the spelling; it travels unchanged.
- **Budget in tokens, never in names.** faster-whisper shares one 448-token
  decoder context between prompt and output, so hotwords and `initial_prompt`
  compete for the same space. `PROMPT_TOKEN_BUDGET = 384`, same backend, same
  number as Port.
- **Order by logging frequency.** When the pool exceeds budget, Port falls
  back to shortest-name-first because it has no usage signal. This repo does:
  order by how often the food appears in `meal_entries`, so weekly staples
  earn their slots ahead of a one-off scanned in March.
- `initial_prompt` sets register — approximately *"A spoken food log:
  quantities, foods, and brand names."*

### Persistence — `voice_entries`

One doc per dictation, 90-day TTL:

```
{ _id, created_at, transcript, slot, hotword_count,
  items_parsed, logged_entry_ids[],
  ms: { transcribe, parse, total }, stt_model, llm_model, error? }
```

This is what makes it keep working rather than merely work: when it mishears,
the transcript sits beside the entries it produced. 90 days spans the protocol,
and transcripts are tiny.

### Frontend — `VoiceFood.tsx`

Sibling to `PasteFood` inside `TodayMeals`, so the fast path and the deliberate
path sit together and the fallback is one component away.

- **Tap to start, tap to stop.** Hard auto-stop at 60s. Not press-and-hold —
  fine for a phrase, bad for "two eggs, sourdough, butter, coffee and a
  Fairlife."
- States: `idle → recording (timer + level meter) → working → landed → error`.
- `useVoiceRecorder` ports from Port, including the mime preference list
  (`webm;codecs=opus`, `webm`, `mp4`, `ogg;codecs=opus`) and the rule that
  every failure resolves to `unsupported` / `denied` rather than throwing.
  Target is Android Chrome (Pixel 9 Pro XL) and desktop; the list is free
  insurance regardless.
- Decode with `AudioContext.decodeAudioData()`, downsample to 16 kHz mono
  int16, upload as WAV.
- **Landed state** lists what was written, with undo calling the existing
  `DELETE /meals/entries/{id}` per id. No new write path.
- With `voice_stt_host` unset or the boundary down, the mic renders disabled.

## Testing

- **Vocabulary:** token-budget enforcement; frequency ordering; a pin that
  `RXBAR` survives un-title-cased; the pool reflects a food added after
  startup.
- **Transcriber:** the three load-bearing behaviours above, against a fake
  socket — segment accumulation by `start`, settle-on-stable-text, and that
  the silence pad is sent.
- **Endpoint:** happy path via the mock; `BoundaryUnavailable` degrades
  instead of 500ing; oversize audio rejected; and the one that matters most —
  **an empty or degenerate transcript writes zero entries.** Silently logging
  nothing-shaped-as-something is the failure that would never get noticed.
- **Frontend:** Vitest over the recorder state machine (`denied`,
  `unsupported`, 60s auto-stop) and the landed/undo flow.
- **Manual:** one real dictation on the Pixel — which is also where the
  latency number comes from.

CI never reaches `llmbox`; the mock is the default.

## Out of scope

Each recoverable later, none blocking:

- Per-claim confidence. Port's `calibration` command exists precisely because
  nobody has yet shown its confidence scores order anything — building on it
  now would be building on an unvalidated signal.
- Spoken corrections and an eval harness. Worth it once there is a corpus;
  there is not one yet.
- Live streaming transcription.
- Audio retention.
- Workout logging, and any intent routing between food and workout.
- Telegram. Superseded: the Phase 2 design in
  `2026-04-24-hack-the-body-design.md` assumes a Telegram bot with a cloned
  voice. This is in-app instead. That doc should be amended.

## Rollout

One PR. `voice_stt_host` ships empty, so the feature is dark on deploy and the
mic does not render. Set it on `hd`'s `.env`, restart, and dictate once.
Rollback is unsetting it.
