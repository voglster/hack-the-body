# Voice Food Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Say what you ate into the web app and have it logged, with one-tap undo.

**Architecture:** A new `app/services/voice/` package holds a `Transcriber` boundary that is mocked and off by default. One synchronous endpoint `POST /foods/voice/log` takes 16 kHz mono PCM from the browser, transcribes it against hotwords generated from the food catalog, hands the transcript to the existing `food_parser`, and writes through the existing meal-entry path. The browser does its own audio decoding, so the API image needs no ffmpeg.

**Tech Stack:** FastAPI, Motor/mongomock-motor, pytest (async, no `@pytest.mark.asyncio` needed — `asyncio_mode=auto`), React + TanStack Query, Vitest + Testing Library, `websockets` (new API dependency).

**Spec:** `docs/superpowers/specs/2026-08-16-voice-food-entry-design.md`

## Global Constraints

- **Python via `uv` only.** Add deps with `cd services/api && uv pip install <pkg>` and add to `pyproject.toml`. Never `pip install --user` or `--break-system-packages`.
- **Run API tests:** `cd services/api && .venv/bin/pytest`. **Run web tests:** `cd services/web && npm test -- --run`.
- **One pre-existing API test failure** — `tests/test_coach_tools.py::test_habit_status_tool_returns_history` fails on a clean tree. Not caused by this work; do not fix it here, and do not treat it as a regression.
- **Ruff reports 71 pre-existing `CPY001` (missing copyright)** errors repo-wide. Ignore them; do not add copyright headers.
- **Comments carry `why`, not `what`.** This repo prefers expressive code over commentary. The exception, explicitly: the three WhisperLive behaviours in Task 3 keep their explanatory comments verbatim — each is a bug already paid for and each looks like dead weight to someone tidying up.
- **`PROMPT_TOKEN_BUDGET = 384`** — faster-whisper shares one 448-token decoder context between prompt and output, so hotwords and `initial_prompt` compete for the same space.
- **Never case-normalise a food name.** `.title()` turns `RXBAR` into `Rxbar`.
- **STT host is `100.64.183.66:9091`** (llmbox, tailnet). Ships unset so the feature is dark.
- **Commit after every task.** Do not push; the user pushes.

---

### Task 1: Hotword vocabulary from the food catalog

The accuracy lever, and the defence that keeps the learning loop from becoming a drift loop. Independent of every other task — no transcription involved.

**Files:**
- Create: `services/api/app/services/voice/__init__.py`
- Create: `services/api/app/services/voice/vocabulary.py`
- Test: `services/api/tests/test_voice_vocabulary.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SpeechContext` (dataclass, fields `hotwords: list[str]`, `initial_prompt: str`, property `hotword_text: str`), and `async def build_speech_context(db) -> SpeechContext`.

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_voice_vocabulary.py`:

```python
"""Hotwords generated from the live food catalog."""
from app.services.voice.vocabulary import (
    SpeechContext,
    build_speech_context,
    select_hotwords,
)


async def _log(db, name: str, times: int) -> None:
    await db["foods"].insert_one({"name": name, "category": "food"})
    for _ in range(times):
        await db["meal_entries"].insert_one({"food_name": name})


async def test_food_eaten_once_contributes_no_hotword(mock_db):
    """A mis-hearing is logged once and never again. If one entry were enough,
    the decoder would be taught its own mistake permanently."""
    await _log(mock_db, "fair life", 1)
    await _log(mock_db, "Fairlife", 4)
    ctx = await build_speech_context(mock_db)
    assert "Fairlife" in ctx.hotwords
    assert "fair life" not in ctx.hotwords


async def test_orders_by_logging_frequency(mock_db):
    await _log(mock_db, "Rare Thing", 2)
    await _log(mock_db, "Daily Staple", 30)
    ctx = await build_speech_context(mock_db)
    assert ctx.hotwords.index("Daily Staple") < ctx.hotwords.index("Rare Thing")


async def test_does_not_case_normalise(mock_db):
    await _log(mock_db, "RXBAR", 5)
    ctx = await build_speech_context(mock_db)
    assert "RXBAR" in ctx.hotwords


async def test_includes_meal_template_names(mock_db):
    await mock_db["meal_templates"].insert_one({"name": "Post-Lift Shake"})
    ctx = await build_speech_context(mock_db)
    assert "Post-Lift Shake" in ctx.hotwords


async def test_reflects_a_food_added_after_startup(mock_db):
    before = await build_speech_context(mock_db)
    await _log(mock_db, "Skyr", 3)
    after = await build_speech_context(mock_db)
    assert "Skyr" not in before.hotwords
    assert "Skyr" in after.hotwords


def test_select_hotwords_respects_the_token_budget():
    """Budget is in tokens because hotwords share the decoder's 448-token
    context with initial_prompt — counting names would overrun it."""
    names = [(f"Food Number {i}", 100 - i) for i in range(500)]
    chosen = select_hotwords(names, budget_tokens=20)
    assert len(chosen) < 500
    assert sum(max(1, len(n) // 4) for n in chosen) <= 20


def test_select_hotwords_keeps_the_most_eaten_first():
    chosen = select_hotwords([("Rare", 1), ("Common", 99)], budget_tokens=100)
    assert chosen[0] == "Common"


def test_speech_context_hotword_text_is_comma_joined():
    ctx = SpeechContext(hotwords=["A", "B"], initial_prompt="p")
    assert ctx.hotword_text == "A, B"


def test_speech_context_hotword_text_is_empty_when_no_hotwords():
    assert SpeechContext(hotwords=[], initial_prompt="p").hotword_text == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_vocabulary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.voice'`

- [ ] **Step 3: Create the package and implement**

Create empty `services/api/app/services/voice/__init__.py`.

Create `services/api/app/services/voice/vocabulary.py`:

```python
"""The words Whisper is told to expect, generated from the food catalog.

Prompting is the whole accuracy story here. Jim's own `bench-stt` measured
`base.en` going from 0.054 WER to 0.000 once `initial_prompt` and `hotwords`
were set, with no larger model beating it on clean audio. Without "Fairlife"
on the wire the decoder writes "fair life", and the parser then has nothing
a catalog entry can match.

**Generated at request time, from the collections.** A hand-maintained list
is correct on the day it is written and wrong by the end of the week, because
the catalog grows every time something new is logged.

**Eligibility is by `meal_entries` count, not by presence in `foods`.** This
is what makes the loop learn rather than drift: `/foods/parse/log` upserts a
Food per parsed item, so a mis-hearing becomes a permanent catalog row. It is
logged exactly once and never again, so requiring more than one entry starves
it while the correction actually eaten weekly climbs.

**Nothing here case-normalises.** `.title()` turns `RXBAR` into `Rxbar` and
`OIKOS` into `Oikos`. The catalog holds the spelling; it travels unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from pymongo.asynchronous.database import AsyncDatabase

# faster-whisper gives the decoder one 448-token context shared between the
# prompt and the output, so hotwords and `initial_prompt` compete for the same
# space. The number to watch is tokens spent, never how many names fit.
PROMPT_TOKEN_BUDGET = 384

# Whisper's own register hint. Short on purpose — it is spending the same
# budget the hotwords are.
INITIAL_PROMPT = "A spoken food log: quantities, foods, and brand names."

# A food logged exactly once is as likely to be a mis-hearing as a real meal.
MIN_ENTRIES_FOR_HOTWORD = 2

# Rough characters-per-token for English. Deliberately an estimate: the exact
# tokenizer lives in the decoder, and being a little conservative costs one
# name at the tail rather than a truncated prompt.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class SpeechContext:
    hotwords: list[str]
    initial_prompt: str

    @property
    def hotword_text(self) -> str:
        return ", ".join(self.hotwords)


def select_hotwords(
    candidates: list[tuple[str, int]], *, budget_tokens: int,
) -> list[str]:
    """Most-eaten first, until the token budget runs out.

    `candidates` is (name, times_eaten). Ordering by usage is not merely a
    tie-break — it is the mis-hearing defence, because a name heard wrong once
    sorts below everything real.
    """
    ordered = sorted(candidates, key=lambda c: (-c[1], c[0]))
    chosen: list[str] = []
    spent = 0
    for name, _count in ordered:
        cost = max(1, len(name) // _CHARS_PER_TOKEN)
        if spent + cost > budget_tokens:
            continue
        chosen.append(name)
        spent += cost
    return chosen


async def build_speech_context(db: AsyncDatabase) -> SpeechContext:
    counts: dict[str, int] = {}
    async for row in db["meal_entries"].find({}, {"food_name": 1}):
        name = (row.get("food_name") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1

    candidates = [
        (name, n) for name, n in counts.items()
        if n >= MIN_ENTRIES_FOR_HOTWORD
    ]

    # Templates are things Jim named himself, so they are never mis-hearings
    # and do not have to earn their place by frequency.
    async for tpl in db["meal_templates"].find({}, {"name": 1}):
        name = (tpl.get("name") or "").strip()
        if name and name not in counts:
            candidates.append((name, MIN_ENTRIES_FOR_HOTWORD))

    budget = PROMPT_TOKEN_BUDGET - (len(INITIAL_PROMPT) // _CHARS_PER_TOKEN)
    return SpeechContext(
        hotwords=select_hotwords(candidates, budget_tokens=budget),
        initial_prompt=INITIAL_PROMPT,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_vocabulary.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/voice/ services/api/tests/test_voice_vocabulary.py
git commit -m "feat(voice): hotwords from the food catalog

Eligibility is by meal_entries count, not presence in foods: parse/log
upserts a Food per item, so a mis-hearing becomes a permanent catalog row.
Requiring more than one entry starves it instead of teaching the decoder
its own mistake."
```

---

### Task 2: The transcriber boundary and its mock

The vendor sits behind an interface this repo owns, off by default, so tests and CI never reach llmbox.

**Files:**
- Create: `services/api/app/services/voice/boundary.py`
- Modify: `services/api/app/config.py` (add settings after `coach_timeout_s`, around line 20)
- Test: `services/api/tests/test_voice_boundary.py`

**Interfaces:**
- Consumes: `SpeechContext` from Task 1.
- Produces: `BoundaryUnavailable(Exception)`, `Transcriber` Protocol with `async def transcribe(self, pcm: bytes, ctx: SpeechContext) -> str`, `MockTranscriber(text: str = ...)`, `def build_transcriber(settings) -> Transcriber`.

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_voice_boundary.py`:

```python
"""The speech boundary — mocked and off by default."""
import pytest

from app.config import Settings
from app.services.voice.boundary import (
    BoundaryUnavailable,
    MockTranscriber,
    build_transcriber,
)
from app.services.voice.vocabulary import SpeechContext
from app.services.voice.whisperlive import WhisperLiveTranscriber

CTX = SpeechContext(hotwords=["Fairlife"], initial_prompt="p")


def test_build_transcriber_returns_the_mock_when_no_host_is_set():
    """Voice is off by default so CI never reaches llmbox."""
    assert isinstance(build_transcriber(Settings(voice_stt_host="")), MockTranscriber)


def test_build_transcriber_returns_the_real_client_when_a_host_is_set():
    t = build_transcriber(Settings(voice_stt_host="10.0.0.1"))
    assert isinstance(t, WhisperLiveTranscriber)


async def test_mock_transcriber_returns_its_canned_text():
    assert await MockTranscriber("two eggs").transcribe(b"", CTX) == "two eggs"


async def test_mock_transcriber_can_be_told_to_fail():
    """The failure this feature is most likely to hit is the vendor being
    unreachable, so it has to be exercisable without one."""
    with pytest.raises(BoundaryUnavailable):
        await MockTranscriber(fail=True).transcribe(b"", CTX)


def test_voice_is_disabled_by_default():
    assert Settings().voice_stt_host == ""
    assert Settings().voice_stt_port == 9091
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_boundary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.voice.boundary'`

- [ ] **Step 3: Add the settings**

In `services/api/app/config.py`, immediately after the `coach_timeout_s: float = 30.0` line, add:

```python
    # -- voice food entry --------------------------------------------------
    # The vendor is a WhisperLive instance on llmbox (tailnet 100.64.183.66),
    # and it is **off by default**: an empty host means the mock, so tests and
    # CI never reach it. Set `VOICE_STT_HOST` on the host to switch it on;
    # unsetting it is the rollback.
    voice_stt_host: str = ""
    voice_stt_port: int = 9091
    voice_stt_model: str = "small"
    voice_timeout_s: float = 30.0
    # 60s of 16kHz mono int16 is ~1.9MB; this is a backstop against an
    # accidental non-speech upload, not the bound the user records against.
    voice_max_audio_bytes: int = 4_000_000
```

- [ ] **Step 4: Implement the boundary**

Create `services/api/app/services/voice/boundary.py`:

```python
"""The speech boundary this repo owns.

WhisperLive sits outside on the tailnet, so it is unreachable from CI and from
a laptop off the tailnet. The vendor goes behind an interface this repo owns,
**off by default**, and everything above is exercised against the mock.

**Failure is a first-class answer.** `BoundaryUnavailable` means the vendor did
not answer — llmbox down, a timeout, a host never configured. It is not an
error the user should see: voice is an accelerator on a logger that works
without it, so the caller degrades to typing and the reason lands in the logs.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.services.voice.vocabulary import SpeechContext

log = logging.getLogger(__name__)


class BoundaryUnavailable(RuntimeError):
    """The speech vendor did not answer. Degrade to typing; never surface raw."""


class Transcriber(Protocol):
    async def transcribe(self, pcm: bytes, ctx: SpeechContext) -> str: ...


class MockTranscriber:
    """The default. Returns canned text, or fails on demand."""

    def __init__(self, text: str = "two eggs and a coffee", *, fail: bool = False) -> None:
        self._text = text
        self._fail = fail

    async def transcribe(self, pcm: bytes, ctx: SpeechContext) -> str:
        if self._fail:
            raise BoundaryUnavailable("mock transcriber configured to fail")
        return self._text


def build_transcriber(settings) -> Transcriber:
    if not settings.voice_stt_host:
        return MockTranscriber()
    from app.services.voice.whisperlive import WhisperLiveTranscriber  # noqa: PLC0415
    return WhisperLiveTranscriber(
        host=settings.voice_stt_host,
        port=settings.voice_stt_port,
        model=settings.voice_stt_model,
        timeout=settings.voice_timeout_s,
    )
```

Create `services/api/app/services/voice/whisperlive.py` as a stub with the real constructor signature. Task 3 replaces the file wholesale; only the signature has to be right now, so `build_transcriber` and its test are exercisable before the protocol exists:

```python
"""WhisperLive client. The protocol lands in Task 3."""
from __future__ import annotations


class WhisperLiveTranscriber:
    def __init__(self, *, host: str, port: int, model: str, timeout: float,
                 language: str = "en") -> None:
        self._host = host
        self._port = port
        self._model = model
        self._timeout = timeout
        self._language = language
```

`boundary.py` imports it lazily inside `build_transcriber` and does **not** re-export it — the test above imports it from `app.services.voice.whisperlive` directly. Keeping the import lazy is what lets the app boot without the `websockets` dependency on the mock path.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_boundary.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add services/api/app/services/voice/boundary.py services/api/app/services/voice/whisperlive.py services/api/app/config.py services/api/tests/test_voice_boundary.py
git commit -m "feat(voice): transcriber boundary, mocked and off by default

An empty voice_stt_host means the mock, so tests and CI never reach llmbox.
BoundaryUnavailable is a first-class answer: voice is an accelerator on a
logger that works without it."
```

---

### Task 3: The WhisperLive client

Ported from `~/src/personal/port/backend/app/deal/voice_boundary.py`. Three behaviours are load-bearing and each is a bug already paid for — the comments explaining them are part of the deliverable.

**Files:**
- Modify: `services/api/app/services/voice/whisperlive.py` (replace the Task 2 placeholder entirely)
- Modify: `services/api/pyproject.toml` (add `websockets`)
- Test: `services/api/tests/test_voice_whisperlive.py`

**Interfaces:**
- Consumes: `SpeechContext` (Task 1), `BoundaryUnavailable` (Task 2).
- Produces: `WhisperLiveTranscriber` with the Task 2 constructor signature and `async def transcribe(self, pcm: bytes, ctx: SpeechContext) -> str`; plus `_TranscriptAccumulator` and `_as_float32`, both exercised directly by tests.

- [ ] **Step 1: Add the dependency**

```bash
cd services/api && uv pip install websockets
```

Then add `"websockets",` to the `dependencies` list in `services/api/pyproject.toml`.

- [ ] **Step 2: Write the failing tests**

Create `services/api/tests/test_voice_whisperlive.py`:

```python
"""The three load-bearing WhisperLive behaviours.

Each of these is a bug that was already paid for once. A future edit that
"simplifies" any of them reintroduces it, which is why they are pinned here.
"""
import struct

from app.services.voice.whisperlive import _TranscriptAccumulator, _as_float32


def test_as_float32_scales_int16_to_unit_range():
    out = _as_float32(struct.pack("<2h", 32767, -32768))
    a, b = struct.unpack("<2f", out)
    assert 0.99 < a <= 1.0
    assert -1.0 <= b < -0.99


def test_accumulator_keys_completed_segments_by_start():
    """A re-sent completed segment must be idempotent. Joining positionally
    reads each re-emission as another phrase that was uttered."""
    acc = _TranscriptAccumulator()
    acc.absorb([{"start": "0.0", "text": "two eggs", "completed": True}])
    acc.absorb([{"start": "0.0", "text": "two eggs", "completed": True}])
    assert acc.text == "two eggs"


def test_accumulator_keeps_words_after_the_window_slides_past():
    """Past send_last_n_segments the opening of a long dictation falls off the
    wire. Keying by start keeps what has already been heard."""
    acc = _TranscriptAccumulator()
    acc.absorb([{"start": "0.0", "text": "two eggs", "completed": True}])
    acc.absorb([{"start": "5.0", "text": "and toast", "completed": True}])
    assert acc.text == "two eggs and toast"


def test_accumulator_replaces_the_in_flight_segment_rather_than_appending():
    acc = _TranscriptAccumulator()
    acc.absorb([{"start": "5.0", "text": "and to", "completed": False}])
    acc.absorb([{"start": "5.0", "text": "and toast", "completed": False}])
    assert acc.text == "and toast"


def test_accumulator_drops_an_in_flight_hypothesis_of_a_settled_segment():
    """One partial and the completed segment that supersedes it, arriving in
    the same window, is every duplicate in the original bug."""
    acc = _TranscriptAccumulator()
    acc.absorb([
        {"start": "0.0", "text": "two eggs", "completed": True},
        {"start": "0.0", "text": "two eg", "completed": False},
    ])
    assert acc.text == "two eggs"


def test_accumulator_treats_a_missing_completed_flag_as_settled():
    """Absent and false are different answers. WhisperLive states the flag on
    every segment, so a missing one is some other shape entirely."""
    acc = _TranscriptAccumulator()
    acc.absorb([{"start": "0.0", "text": "two eggs"}])
    acc.absorb([{"start": "5.0", "text": "and toast"}])
    assert acc.text == "two eggs and toast"


def test_accumulator_ignores_a_segment_with_no_usable_start():
    acc = _TranscriptAccumulator()
    acc.absorb([{"start": None, "text": "junk", "completed": True}])
    assert acc.text == ""
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_whisperlive.py -v`
Expected: FAIL — `ImportError: cannot import name '_TranscriptAccumulator'`

- [ ] **Step 4: Implement the client**

Replace `services/api/app/services/voice/whisperlive.py` entirely:

```python
"""Speaks WhisperLive's WebSocket protocol to a self-hosted faster-whisper.

WhisperLive is a *streaming* server being used for a batch job, which is why
the shape below is unusual for a one-shot call. Three of its behaviours are
load-bearing, and every one of them is a bug that was already paid for once:

1. The server answers ``SERVER_READY`` before it will accept audio.
2. Its backend only runs the model once at least a second of audio is buffered,
   and **it does not flush on end-of-audio** — so the tail of a dictation is
   lost unless a little silence is pushed in behind it.
3. It keeps re-sending completed segments while idle, so "the transcript has
   settled" is a *text has stopped changing* judgement, not a message-arrival
   one — and only once the audio has all gone out. It also sends only a
   trailing window of them, so the transcript is accumulated across messages by
   segment ``start`` rather than rebuilt from the last one.

``hotwords`` and ``initial_prompt`` ride on the opening config. They are the
reason this is the vendor rather than a batch Whisper backend, which has no
field to put them in — and per `vocabulary.py` they are the whole accuracy
story.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import uuid
from collections.abc import AsyncIterator, Sequence

from app.services.voice.vocabulary import SpeechContext

log = logging.getLogger(__name__)

FRAME_BYTES = 3200

# An in-flight segment starting no later than the last settled one is that
# segment's own superseded hypothesis, not new audio.
_SAME_AUDIO_SECONDS = 0.05


def _seconds(value: object) -> float | None:
    """A segment boundary as a number. WhisperLive writes them as strings."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class _TranscriptAccumulator:
    """The whole dictation, rebuilt from the trailing window the server sends.

    A message carries the last N *completed* segments plus the one still in
    flight, and joining that window positionally gets both halves wrong.

    It duplicates: the in-flight segment churns as the speaker talks and is
    re-sent every time the decoder refines it, and the server keeps re-sending
    a completed segment while it idles — so a positional join reads each
    emission as another phrase that was uttered.

    And it loses: past the window, the opening of a long dictation falls off
    the wire and vanishes with no error at all.

    Both are the same missing idea — **a segment's ``start`` is its identity.**
    Keying completed segments by it makes a re-send idempotent and keeps what
    has already been heard after the window slides past; holding the in-flight
    segment apart lets it be replaced rather than appended.
    """

    def __init__(self) -> None:
        self._completed: dict[float, str] = {}
        self._in_flight: tuple[float, str] | None = None

    def absorb(self, segments: Sequence[dict]) -> str:
        self._in_flight = None
        for segment in segments:
            start = _seconds(segment.get("start"))
            if start is None:
                continue
            text = (segment.get("text") or "").strip()
            # Absent and false are different answers. WhisperLive states the
            # flag on every segment, so a missing one is some other shape
            # entirely — treating that as settled keeps its words, where
            # treating it as in flight would keep only the last segment of
            # each message.
            if segment.get("completed", True):
                self._completed[start] = text
            else:
                self._in_flight = (start, text)
        return self.text

    @property
    def text(self) -> str:
        heard = sorted(self._completed.items())
        if self._in_flight is not None:
            settled_through = heard[-1][0] if heard else -1.0
            if self._in_flight[0] > settled_through + _SAME_AUDIO_SECONDS:
                heard.append(self._in_flight)
        return " ".join(text for _, text in heard if text).strip()


def _as_float32(pcm16: bytes) -> bytes:
    """16-bit signed PCM to the float32 WhisperLive expects."""
    count = len(pcm16) // 2
    samples = struct.unpack(f"<{count}h", pcm16[: count * 2])
    return struct.pack(f"<{count}f", *(sample / 32768.0 for sample in samples))


async def _buffered_frames(pcm: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(pcm), FRAME_BYTES):
        yield pcm[start : start + FRAME_BYTES]


class WhisperLiveTranscriber:
    # 100 ms of 16 kHz mono float32 silence, appended to flush the buffer.
    _SILENCE_SECONDS = 1.5
    _QUIET_GAP_SECONDS = 0.75
    _SENT_HOLD_SECONDS = 0.75
    _RECV_POLL_SECONDS = 0.15
    _NO_SEGMENTS_DEADLINE_SECONDS = 8.0
    _SAMPLE_RATE = 16_000

    def __init__(self, *, host: str, port: int, model: str, timeout: float,
                 language: str = "en") -> None:
        self._host = host
        self._port = port
        self._model = model
        self._timeout = timeout
        self._language = language

    async def transcribe(self, pcm: bytes, ctx: SpeechContext) -> str:
        from app.services.voice.boundary import BoundaryUnavailable  # noqa: PLC0415
        try:
            return await asyncio.wait_for(
                self._run(_buffered_frames(pcm), ctx), timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise BoundaryUnavailable(
                f"speech backend timed out after {self._timeout:.0f}s",
            ) from exc
        except Exception as exc:
            raise BoundaryUnavailable(f"speech backend unreachable: {exc}") from exc

    async def _run(self, frames: AsyncIterator[bytes], ctx: SpeechContext) -> str:
        # Imported here so an install without websockets still boots — the
        # mock path never needs it.
        from websockets.asyncio.client import connect  # noqa: PLC0415

        uid = str(uuid.uuid4())
        tenth = self._SAMPLE_RATE // 10
        silence = struct.pack(f"<{tenth}f", *([0.0] * tenth))

        async with connect(f"ws://{self._host}:{self._port}", max_size=2**24) as socket:
            await socket.send(json.dumps({
                "uid": uid,
                "language": self._language,
                "task": "transcribe",
                "model": self._model,
                "use_vad": True,
                "send_last_n_segments": 30,
                "initial_prompt": ctx.initial_prompt or None,
                "hotwords": ctx.hotword_text or None,
            }))

            loop = asyncio.get_running_loop()
            heard = _TranscriptAccumulator()
            sent = asyncio.Event()
            send_task: asyncio.Task[None] | None = None
            latest = ""
            latest_changed_at = 0.0
            sent_at: float | None = None

            async def send_audio() -> None:
                try:
                    async for frame in frames:
                        if frame:
                            await socket.send(_as_float32(frame))
                    # The silence pad. The audio has ended, so flush whatever
                    # the server is still holding — without this the tail of
                    # every dictation is lost.
                    for _ in range(int(self._SILENCE_SECONDS * 10)):
                        await socket.send(silence)
                    # Then hold `sent` down a moment longer. It is the deadline
                    # for the tail: the quiet gap does not start running until
                    # it is set, and a server still decoding the last phrase
                    # has said nothing new for long enough to look finished.
                    await asyncio.sleep(self._SENT_HOLD_SECONDS)
                finally:
                    sent.set()

            while True:
                try:
                    raw = await asyncio.wait_for(
                        socket.recv(), timeout=self._RECV_POLL_SECONDS,
                    )
                except TimeoutError:
                    if sent.is_set() and sent_at is None:
                        sent_at = loop.time()
                    if (
                        sent.is_set() and latest
                        and loop.time() - latest_changed_at > self._QUIET_GAP_SECONDS
                    ):
                        break
                    if (
                        sent_at is not None and not latest
                        and loop.time() - sent_at > self._NO_SEGMENTS_DEADLINE_SECONDS
                    ):
                        break
                    continue

                if isinstance(raw, bytes):
                    continue
                message = json.loads(raw)
                if message.get("uid") != uid:
                    continue
                if message.get("message") == "SERVER_READY" and send_task is None:
                    send_task = asyncio.create_task(send_audio())
                    continue
                if message.get("status") in ("ERROR", "WARNING", "WAIT"):
                    log.warning("whisperlive status: %s", message.get("status"))
                    continue
                segments = message.get("segments")
                if segments is None:
                    continue
                text = heard.absorb(segments)
                if text and text != latest:
                    latest = text
                    latest_changed_at = loop.time()

            if send_task is not None:
                send_task.cancel()
            return heard.text
```

`boundary.py` needs no change — it already imports this lazily inside `build_transcriber`, and the constructor signature is unchanged from the Task 2 stub.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_whisperlive.py tests/test_voice_boundary.py -v`
Expected: PASS (12 tests)

- [ ] **Step 6: Commit**

```bash
git add services/api/app/services/voice/whisperlive.py services/api/app/services/voice/boundary.py services/api/tests/ services/api/pyproject.toml
git commit -m "feat(voice): WhisperLive client, ported from port

Three load-bearing behaviours, each a bug already paid for: the SERVER_READY
gate, the silence pad (the server does not flush on end-of-audio, so the tail
is lost without it), and settle-by-text-stability with segments accumulated
by start rather than rebuilt from the last message. All three pinned."
```

---

### Task 4: The endpoint

**Files:**
- Create: `services/api/app/routers/voice.py`
- Modify: `services/api/app/main.py` (register the router beside the other routers)
- Modify: `services/api/app/db.py:22-25` (add `voice_entries` to `REGULAR_COLLECTIONS`) and the index block (~line 57)
- Test: `services/api/tests/test_voice_endpoint.py`

**Interfaces:**
- Consumes: `build_speech_context` (Task 1), `build_transcriber` / `BoundaryUnavailable` / `MockTranscriber` (Task 2).
- Produces: `POST /foods/voice/log` returning `{transcript, items, logged_entry_ids, count}`.

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_voice_endpoint.py`:

```python
"""POST /foods/voice/log — audio in, meal entries out."""
from unittest.mock import patch

import httpx

from app.services.voice.boundary import MockTranscriber
from tests.conftest import llm_body

H = {"X-API-Key": "test-key"}
PARSED = '[{"name": "Scrambled Eggs", "servings": 2, "calories": 150}]'


def _llm(text: str):
    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return llm_body(text)

    async def _post(_self, _url, **_kw):
        return _R()
    return _post


def _audio(n: int = 3200) -> bytes:
    return b"\x00\x01" * (n // 2)


async def test_logs_what_was_heard(client, mock_db):
    with patch.object(httpx.AsyncClient, "post", _llm(PARSED)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs")):
        r = await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "breakfast"},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["transcript"] == "two scrambled eggs"
    assert body["count"] == 1
    assert len(body["logged_entry_ids"]) == 1
    assert await mock_db["meal_entries"].count_documents({}) == 1


async def test_voice_logged_foods_are_marked_as_such(client, mock_db):
    """Mis-hearings become permanent catalog rows; source keeps them sweepable."""
    with patch.object(httpx.AsyncClient, "post", _llm(PARSED)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs")):
        await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "breakfast"},
        )
    food = await mock_db["foods"].find_one({"name": "Scrambled Eggs"})
    assert food["source"] == "voice"


async def test_an_empty_transcript_writes_nothing(client, mock_db):
    """Silently logging nothing-shaped-as-something is the failure that would
    never get noticed."""
    with patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("   ")):
        r = await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "snack"},
        )
    assert r.status_code == 201
    assert r.json()["count"] == 0
    assert await mock_db["meal_entries"].count_documents({}) == 0


async def test_an_unavailable_vendor_degrades_rather_than_500ing(client):
    with patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber(fail=True)):
        r = await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "snack"},
        )
    assert r.status_code == 503
    assert "voice" in r.json()["detail"].lower()


async def test_oversize_audio_is_rejected(client, settings):
    too_big = b"\x00" * (settings.voice_max_audio_bytes + 2)
    r = await client.post(
        "/foods/voice/log", headers=H,
        files={"audio": ("a.wav", too_big, "audio/wav")},
        data={"slot": "snack"},
    )
    assert r.status_code == 413


async def test_the_dictation_is_recorded_for_later_tuning(client, mock_db):
    """voice_entries is what makes it keep working: the transcript sits beside
    the entries it produced, which is the mined-correction signal."""
    with patch.object(httpx.AsyncClient, "post", _llm(PARSED)), \
         patch("app.routers.voice.build_transcriber",
               lambda _s: MockTranscriber("two scrambled eggs")):
        await client.post(
            "/foods/voice/log", headers=H,
            files={"audio": ("a.wav", _audio(), "audio/wav")},
            data={"slot": "breakfast"},
        )
    doc = await mock_db["voice_entries"].find_one({})
    assert doc["transcript"] == "two scrambled eggs"
    assert len(doc["logged_entry_ids"]) == 1
    assert doc["items_parsed"] == 1
    assert doc["hotword_count"] >= 0


async def test_requires_the_api_key(client):
    r = await client.post(
        "/foods/voice/log",
        files={"audio": ("a.wav", _audio(), "audio/wav")},
        data={"slot": "snack"},
    )
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_endpoint.py -v`
Expected: FAIL — 404 on every request (router not registered)

- [ ] **Step 3: Register the collection**

In `services/api/app/db.py`, add `"voice_entries"` to the `REGULAR_COLLECTIONS` list (line 22-25). Then in `ensure_collections`, beside the other index declarations (~line 57), add:

```python
    # Voice dictations: time-ordered, and aged out after 90 days. Long enough
    # to look back across a training block; transcripts are tiny.
    await db["voice_entries"].create_index([("created_at", -1)])
    await db["voice_entries"].create_index(
        "created_at", expireAfterSeconds=90 * 24 * 3600,
    )
```

- [ ] **Step 4: Implement the router**

Create `services/api/app/routers/voice.py`:

```python
"""Voice food entry — say what you ate, have it logged.

Synchronous on purpose. The "nothing blocking" rule that governs the ingestors
was written for slow models and flaky networks; this is one user on their own
tailnet, and the repo has no general worker to hand the job to. The frontend
already awaits a multi-second `/foods/parse` behind a spinner.

Audio arrives as 16 kHz mono int16 PCM because the browser decodes it — which
is why the API image needs no ffmpeg.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import perf_counter

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.models.food import Food, Macros, MealEntry
from app.services.food_parser import parse_food_text
from app.services.food_repo import FoodRepo
from app.services.voice.boundary import BoundaryUnavailable, build_transcriber
from app.services.voice.vocabulary import build_speech_context

log = logging.getLogger(__name__)

router = APIRouter(prefix="/foods/voice", tags=["voice"])


@router.post("/log", status_code=201)
async def log_dictation(
    request: Request,
    audio: UploadFile = File(...),
    slot: str = Form("snack"),
) -> dict:
    settings = request.app.state.settings
    db = request.app.state.db

    pcm = await audio.read()
    if len(pcm) > settings.voice_max_audio_bytes:
        raise HTTPException(status_code=413, detail="recording too large")

    ctx = await build_speech_context(db)
    transcriber = build_transcriber(settings)

    t0 = perf_counter()
    try:
        transcript = await transcriber.transcribe(pcm, ctx)
    except BoundaryUnavailable as exc:
        # Not an error the user should see as a failure: voice is an
        # accelerator on a logger that works without it.
        log.warning("voice unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="voice is unavailable — type it instead",
        ) from exc
    transcribe_ms = int((perf_counter() - t0) * 1000)

    transcript = (transcript or "").strip()
    items = []
    t1 = perf_counter()
    if transcript:
        items = await parse_food_text(settings, transcript)
    parse_ms = int((perf_counter() - t1) * 1000)

    repo = FoodRepo(db)
    when = datetime.now(UTC)
    logged: list[dict] = []
    for it in items:
        macros = Macros(
            calories=it.calories, protein_g=it.protein_g,
            carbs_g=it.carbs_g, fat_g=it.fat_g,
        )
        food = Food(
            name=it.name, category="food", serving_g=1.0, serving_label=None,
            per_serving=macros, source="voice",
        )
        food.created_at = when
        stored = await repo.upsert_food(food)
        entry = MealEntry(
            ts=when, food_id=stored["id"], food_name=stored["name"],
            food_category="food", quantity_g=1.0, servings=it.servings,
            slot=slot,  # type: ignore[arg-type]
            macros=macros,
        )
        logged.append(await repo.insert_entry(entry))

    entry_ids = [e["id"] for e in logged]
    await db["voice_entries"].insert_one({
        "created_at": when,
        "transcript": transcript,
        "slot": slot,
        "hotword_count": len(ctx.hotwords),
        "items_parsed": len(items),
        "logged_entry_ids": entry_ids,
        "ms": {
            "transcribe": transcribe_ms,
            "parse": parse_ms,
            "total": transcribe_ms + parse_ms,
        },
        "stt_model": settings.voice_stt_model,
        "llm_model": settings.llm_model,
    })

    return {
        "transcript": transcript,
        "items": [
            {"name": i.name, "servings": i.servings, "calories": i.calories,
             "protein_g": i.protein_g, "carbs_g": i.carbs_g, "fat_g": i.fat_g}
            for i in items
        ],
        "logged_entry_ids": entry_ids,
        "count": len(logged),
    }
```

In `services/api/app/main.py`, import the router alongside the existing router imports and include it the same way the others are included (`app.include_router(voice.router)`), placing it **before** the SPA catch-all.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd services/api && .venv/bin/pytest tests/test_voice_endpoint.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Run the whole API suite**

Run: `cd services/api && .venv/bin/pytest -q`
Expected: all pass except the one known pre-existing failure named in Global Constraints.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/routers/voice.py services/api/app/main.py services/api/app/db.py services/api/tests/test_voice_endpoint.py
git commit -m "feat(voice): POST /foods/voice/log

Transcribe, parse with the existing food parser, write through the existing
meal-entry path. Foods get source=voice so mis-hearings stay sweepable. An
empty transcript writes zero entries. An unavailable vendor is a 503 telling
the user to type, never a 500."
```

---

### Task 5: Browser audio capture and encoding

**Files:**
- Create: `services/web/src/lib/wav.ts`
- Create: `services/web/src/hooks/useVoiceRecorder.ts`
- Test: `services/web/src/lib/wav.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `encodeWav(samples: Float32Array, sampleRate: number): Blob`, `downsampleTo16k(input: Float32Array, inputRate: number): Float32Array`, and the `useVoiceRecorder()` hook returning `{ state, seconds, start, stop }` where `state: "idle" | "recording" | "unsupported" | "denied"` and `stop(): Promise<Blob | null>` resolves to a 16 kHz mono WAV.

- [ ] **Step 1: Write the failing tests**

Create `services/web/src/lib/wav.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { downsampleTo16k, encodeWav, MAX_RECORDING_SECONDS } from "./wav";

describe("downsampleTo16k", () => {
  it("halves a 32k input", () => {
    const out = downsampleTo16k(new Float32Array(3200), 32000);
    expect(out.length).toBe(1600);
  });

  it("passes 16k through untouched", () => {
    const input = new Float32Array([0.5, -0.5]);
    expect(Array.from(downsampleTo16k(input, 16000))).toEqual([0.5, -0.5]);
  });
});

describe("encodeWav", () => {
  it("writes a RIFF/WAVE header", async () => {
    const blob = encodeWav(new Float32Array([0, 0.5]), 16000);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const tag = String.fromCharCode(...bytes.slice(0, 4));
    const fmt = String.fromCharCode(...bytes.slice(8, 12));
    expect(tag).toBe("RIFF");
    expect(fmt).toBe("WAVE");
  });

  it("emits 16-bit samples after the 44-byte header", async () => {
    const blob = encodeWav(new Float32Array([0, 0.5, -0.5]), 16000);
    expect(blob.size).toBe(44 + 3 * 2);
  });

  it("clamps out-of-range samples instead of wrapping", async () => {
    const blob = encodeWav(new Float32Array([2.0, -2.0]), 16000);
    const view = new DataView(await blob.arrayBuffer());
    expect(view.getInt16(44, true)).toBe(32767);
    expect(view.getInt16(46, true)).toBe(-32768);
  });
});

describe("MAX_RECORDING_SECONDS", () => {
  it("is one minute", () => {
    expect(MAX_RECORDING_SECONDS).toBe(60);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/web && npm test -- --run src/lib/wav.test.ts`
Expected: FAIL — cannot resolve `./wav`

- [ ] **Step 3: Implement the encoder**

Create `services/web/src/lib/wav.ts`:

```ts
/**
 * Audio encoding for voice food entry.
 *
 * The browser decodes its own recording and uploads 16 kHz mono PCM, rather
 * than shipping the container up and decoding server-side. That keeps ffmpeg
 * — and ~100 MB — out of the API image, and makes the server leg a
 * pass-through to WhisperLive, which wants exactly this format.
 */

/** How long any recording may run. A dictated meal is a sentence. */
export const MAX_RECORDING_SECONDS = 60;

/** WhisperLive's sample rate. Not negotiable on its side. */
export const TARGET_SAMPLE_RATE = 16000;

/**
 * Nearest-neighbour decimation. Speech at 16 kHz through a Whisper model does
 * not reward a windowed resampler, and this has no dependencies.
 */
export function downsampleTo16k(input: Float32Array, inputRate: number): Float32Array {
  if (inputRate === TARGET_SAMPLE_RATE) return input;
  const ratio = inputRate / TARGET_SAMPLE_RATE;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) out[i] = input[Math.floor(i * ratio)];
  return out;
}

export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const ascii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };

  ascii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);          // PCM
  view.setUint16(22, 1, true);          // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, samples.length * 2, true);

  for (let i = 0; i < samples.length; i++) {
    // Clamp rather than let the cast wrap: a wrapped peak is a click, and a
    // click mid-word is a word the decoder loses.
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/web && npm test -- --run src/lib/wav.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Implement the recorder hook**

Create `services/web/src/hooks/useVoiceRecorder.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from "react";

import { downsampleTo16k, encodeWav, MAX_RECORDING_SECONDS, TARGET_SAMPLE_RATE } from "../lib/wav";

/**
 * Recording a dictation in the browser.
 *
 * `MediaRecorder`, deliberately not the Web Speech API: that ships the audio
 * to Google or Apple to be transcribed, which defeats the point of running
 * Whisper on our own hardware.
 *
 * The container is whatever the browser gives us and that is not negotiable —
 * Chrome records `audio/webm;codecs=opus`, Safari records `audio/mp4` (AAC) —
 * so the type is asked for in preference order and `decodeAudioData` handles
 * whichever we got.
 *
 * Every failure resolves to `unsupported` or `denied` rather than throwing.
 * Voice is an accelerator on a logger that works without it, so a browser that
 * cannot record must land on the typed form and not on an error.
 */

export type RecorderState = "idle" | "recording" | "unsupported" | "denied";

const PREFERRED_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return PREFERRED_TYPES.find((t) => MediaRecorder.isTypeSupported?.(t));
}

export function useVoiceRecorder() {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = useCallback(() => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setState("denied");
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    const mimeType = pickMimeType();
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    recorderRef.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    tickRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
  }, []);

  const stop = useCallback(async (): Promise<Blob | null> => {
    const rec = recorderRef.current;
    if (!rec || rec.state === "inactive") { setState("idle"); return null; }

    const finished = new Promise<void>((resolve) => { rec.onstop = () => resolve(); });
    rec.stop();
    await finished;
    cleanup();
    setState("idle");

    const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
    if (blob.size === 0) return null;

    const AC = window.AudioContext ?? (window as never as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const audioCtx = new AC();
    try {
      const decoded = await audioCtx.decodeAudioData(await blob.arrayBuffer());
      const mono = decoded.getChannelData(0);
      return encodeWav(downsampleTo16k(mono, decoded.sampleRate), TARGET_SAMPLE_RATE);
    } catch {
      return null;
    } finally {
      await audioCtx.close();
    }
  }, [cleanup]);

  // The recorder stops itself at the cap so a pocket-dial cannot run forever.
  useEffect(() => {
    if (state === "recording" && seconds >= MAX_RECORDING_SECONDS) {
      void stop();
    }
  }, [state, seconds, stop]);

  return { state, seconds, start, stop };
}
```

- [ ] **Step 6: Run the web suite**

Run: `cd services/web && npm test -- --run`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add services/web/src/lib/wav.ts services/web/src/lib/wav.test.ts services/web/src/hooks/useVoiceRecorder.ts
git commit -m "feat(voice): browser audio capture and 16kHz WAV encoding

The browser decodes its own recording so the API image needs no ffmpeg.
MediaRecorder rather than the Web Speech API, which would ship audio to a
third party. Every failure resolves to unsupported/denied, never a throw."
```

---

### Task 6: The VoiceFood component

**Files:**
- Create: `services/web/src/components/VoiceFood.tsx`
- Create: `services/web/src/components/VoiceFood.test.tsx`
- Modify: `services/web/src/api/client.ts` (add `logVoiceFood` beside `parseAndLogFood`, ~line 158)
- Modify: `services/web/src/components/TodayMeals.tsx:171` (render `<VoiceFood>` above `<PasteFood>`)

**Interfaces:**
- Consumes: `useVoiceRecorder` (Task 5), `POST /foods/voice/log` (Task 4), the existing `api.deleteEntry`.
- Produces: `<VoiceFood onLogged={() => void} slot?: MealSlot />`.

- [ ] **Step 1: Add the API client method**

In `services/web/src/api/client.ts`, add to the `api` object beside the other food methods:

```ts
  logVoiceFood: async (audio: Blob, slot: MealSlot) => {
    const form = new FormData();
    form.append("audio", audio, "dictation.wav");
    form.append("slot", slot);
    const r = await fetch(`${BASE}/foods/voice/log`, {
      method: "POST", headers: authHeaders(), body: form,
    });
    if (r.status === 401) handleUnauthorized();
    if (r.status === 503) throw new Error("voice-unavailable");
    if (!r.ok) throw new Error(`voice log failed: ${r.status}`);
    return (await r.json()) as {
      transcript: string;
      items: ParsedFoodItem[];
      logged_entry_ids: string[];
      count: number;
    };
  },
```

Confirm `deleteEntry` already exists in the client; if it does not, add `deleteEntry: (id: string) => del(`/meals/entries/${id}`)`.

- [ ] **Step 2: Write the failing tests**

Create `services/web/src/components/VoiceFood.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VoiceFood } from "./VoiceFood";

const mockRecorder = {
  state: "idle" as string,
  seconds: 0,
  start: vi.fn(),
  stop: vi.fn().mockResolvedValue(new Blob(["x"], { type: "audio/wav" })),
};

vi.mock("../hooks/useVoiceRecorder", () => ({
  useVoiceRecorder: () => mockRecorder,
}));

vi.mock("../api/client", () => ({
  api: {
    logVoiceFood: vi.fn().mockResolvedValue({
      transcript: "two scrambled eggs",
      items: [{ name: "Scrambled Eggs", servings: 2, calories: 150 }],
      logged_entry_ids: ["e1"],
      count: 1,
    }),
    deleteEntry: vi.fn().mockResolvedValue(undefined),
  },
}));

describe("VoiceFood", () => {
  it("shows what landed after a dictation", async () => {
    const { api } = await import("../api/client");
    render(<VoiceFood onLogged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /record|speak/i }));
    mockRecorder.state = "recording";
    await userEvent.click(screen.getByRole("button", { name: /stop|done/i }));
    await waitFor(() => expect(api.logVoiceFood).toHaveBeenCalled());
    expect(await screen.findByText(/two scrambled eggs/i)).toBeTruthy();
    expect(screen.getByText(/Scrambled Eggs/)).toBeTruthy();
  });

  it("undoes by deleting every entry it wrote", async () => {
    const { api } = await import("../api/client");
    render(<VoiceFood onLogged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /record|speak/i }));
    mockRecorder.state = "recording";
    await userEvent.click(screen.getByRole("button", { name: /stop|done/i }));
    const undo = await screen.findByRole("button", { name: /undo/i });
    await userEvent.click(undo);
    await waitFor(() => expect(api.deleteEntry).toHaveBeenCalledWith("e1"));
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd services/web && npm test -- --run src/components/VoiceFood.test.tsx`
Expected: FAIL — cannot resolve `./VoiceFood`

- [ ] **Step 4: Implement the component**

Create `services/web/src/components/VoiceFood.tsx`:

```tsx
/**
 * Say what you ate. It gets logged. Undo is one tap.
 *
 * Deliberately auto-logs rather than showing a draft to confirm, unlike
 * `PasteFood` next to it: a confirm step costs a deliberate tap on the exact
 * action whose friction is the reason logging lapses. Pasting a long breakdown
 * earns a review pass; saying "two eggs" does not.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { MealSlot, ParsedFoodItem } from "../api/types";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";

function defaultSlot(): MealSlot {
  const h = new Date().getHours();
  if (h < 10) return "breakfast";
  if (h < 14) return "lunch";
  if (h < 16) return "snack";
  if (h < 21) return "dinner";
  return "snack";
}

interface Landed {
  transcript: string;
  items: ParsedFoodItem[];
  entryIds: string[];
}

export function VoiceFood({ onLogged, slot }: { onLogged: () => void; slot?: MealSlot }) {
  const { state, seconds, start, stop } = useVoiceRecorder();
  const [busy, setBusy] = useState(false);
  const [landed, setLanded] = useState<Landed | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onStop = async () => {
    const blob = await stop();
    if (!blob) { setError("nothing was recorded"); return; }
    setBusy(true); setError(null);
    try {
      const res = await api.logVoiceFood(blob, slot ?? defaultSlot());
      setLanded({
        transcript: res.transcript,
        items: res.items,
        entryIds: res.logged_entry_ids,
      });
      if (res.count > 0) onLogged();
      if (res.count === 0) setError("nothing food-like was heard");
    } catch (e) {
      setError(
        (e as Error).message === "voice-unavailable"
          ? "voice is unavailable — type it instead"
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };

  const onUndo = async () => {
    if (!landed) return;
    await Promise.all(landed.entryIds.map((id) => api.deleteEntry(id)));
    setLanded(null);
    onLogged();
  };

  if (state === "unsupported" || state === "denied") {
    return (
      <p className="text-sm text-neutral-500">
        {state === "denied" ? "microphone permission denied" : "this browser can't record"} — type it below
      </p>
    );
  }

  return (
    <section className="flex flex-col gap-2">
      {state !== "recording" ? (
        <button
          onClick={start}
          disabled={busy}
          className="rounded-lg bg-neutral-800 px-4 py-3 text-left text-white disabled:opacity-50"
        >
          {busy ? "logging…" : "🎤 Speak a meal"}
        </button>
      ) : (
        <button
          onClick={onStop}
          className="rounded-lg bg-red-600 px-4 py-3 text-left text-white"
        >
          ■ Stop · {seconds}s
        </button>
      )}

      {error && <p className="text-sm text-amber-500">{error}</p>}

      {landed && landed.items.length > 0 && (
        <div className="rounded-lg border border-neutral-700 p-3 text-sm">
          <p className="italic text-neutral-400">“{landed.transcript}”</p>
          <ul className="mt-2">
            {landed.items.map((i, n) => (
              <li key={n} className="flex justify-between">
                <span>{i.name}</span>
                <span className="tabular-nums text-neutral-400">
                  {i.calories != null ? `${Math.round(i.calories)} cal` : "—"}
                </span>
              </li>
            ))}
          </ul>
          <button onClick={onUndo} className="mt-2 text-neutral-400 underline">
            Undo
          </button>
        </div>
      )}
    </section>
  );
}
```

In `services/web/src/components/TodayMeals.tsx`, import `VoiceFood` and render it immediately above the existing `<PasteFood ... />` at line 171:

```tsx
      <VoiceFood onLogged={refresh} />
      <PasteFood onLogged={refresh} day={day} />
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd services/web && npm test -- --run`
Expected: PASS, all suites.

- [ ] **Step 6: Typecheck and build**

Run: `cd services/web && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add services/web/src/components/VoiceFood.tsx services/web/src/components/VoiceFood.test.tsx services/web/src/components/TodayMeals.tsx services/web/src/api/client.ts
git commit -m "feat(voice): VoiceFood component

Auto-logs and shows what landed with undo, deliberately unlike PasteFood
beside it: a confirm step costs a tap on the exact action whose friction is
why logging lapses."
```

---

### Task 7: Turn it on and dictate once

The acceptance test. Nothing above has ever touched llmbox.

**Files:**
- Modify: `compose/.env.example` (document the new vars)
- Modify: `CLAUDE.md` (a line under Architecture noting voice food entry and its off-by-default switch)

- [ ] **Step 1: Document the switch**

Add to `compose/.env.example`:

```
# Voice food entry. Empty = off (the API uses a mock transcriber).
# Set to llmbox's tailnet IP to enable; unsetting it is the rollback.
VOICE_STT_HOST=
VOICE_STT_PORT=9091
```

Add to `CLAUDE.md` under Architecture:

```markdown
- **Voice food entry** — `POST /foods/voice/log` takes 16kHz mono WAV from the
  browser, transcribes against hotwords built from the food catalog
  (`app/services/voice/`), and logs through the existing food parser. Off
  unless `VOICE_STT_HOST` is set; the vendor is WhisperLive on `llmbox:9091`.
```

- [ ] **Step 2: Commit and push**

```bash
git add compose/.env.example CLAUDE.md
git commit -m "docs(voice): document the VOICE_STT_HOST switch"
```

Then ask the user before pushing — pushing triggers CI and a Watchtower deploy.

- [ ] **Step 3: Enable on hd**

After the image has been built and deployed:

```bash
ssh hd 'cd ~/compose/hack-the-body && cp .env .env.bak-$(date +%Y%m%d-%H%M%S) \
  && echo "VOICE_STT_HOST=100.64.183.66" >> .env \
  && docker compose up -d app'
```

Verify the setting is live:

```bash
ssh hd 'docker exec hack-the-body-app python3 -c "from app.config import Settings; print(Settings().voice_stt_host)"'
```
Expected: `100.64.183.66`

- [ ] **Step 4: Dictate once, on the phone**

Open the app on the Pixel, tap **Speak a meal**, say a real meal including at least one brand name already in the catalog, and stop.

Confirm:
- entries appear in Today's meals
- the transcript shown matches what was said
- **Undo** removes exactly those entries
- a `voice_entries` doc exists with a non-zero `hotword_count`:

```bash
ssh hd 'docker exec hack-the-body-mongo mongosh --quiet hackthebody --eval "printjson(db.voice_entries.find().sort({created_at:-1}).limit(1).toArray())"'
```

Record the observed `ms.total` on the issue or in the commit message. It is a data point, **not** a gate — latency is explicitly not a design constraint for this feature.

- [ ] **Step 5: Report back**

Report to the user: what was said, what was heard, what was logged, the `hotword_count`, and the round-trip time. If the transcript was wrong in a way hotwords should have caught, that is the first tuning input — do not change the design in response to a single sample.

---

## Notes for the executor

- **Do not add ffmpeg to the Dockerfile.** The browser decodes; that is a deliberate decision recorded in the spec.
- **Do not build a background job or a progress-staging path.** Both were considered and rejected in the spec.
- **Do not lower `MIN_ENTRIES_FOR_HOTWORD` to 1.** It looks like an off-by-one and it is the mis-hearing defence.
- If a task reveals the spec is wrong, stop and say so rather than diverging silently.
