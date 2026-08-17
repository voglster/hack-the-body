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


def _strip_wav_header(body: bytes) -> bytes:
    """Bare int16 PCM passes through unchanged. A RIFF/WAVE body has its
    44-byte header — and any other non-audio chunk — stripped down to just
    the `data` chunk's payload, so it does not get decoded as ~1.4ms of
    near-full-scale noise prepended to the transcript.

    Only the chunk graph needed to find `data` is walked; anything that
    doesn't validate as RIFF/WAVE (missing magic, truncated chunk header)
    is treated as raw PCM rather than assumed to be a malformed WAV.
    """
    if len(body) < 12 or body[0:4] != b"RIFF" or body[8:12] != b"WAVE":
        return body
    offset = 12
    while offset + 8 <= len(body):
        chunk_id = body[offset:offset + 4]
        chunk_size = struct.unpack("<I", body[offset + 4:offset + 8])[0]
        payload_start = offset + 8
        if chunk_id == b"data":
            return body[payload_start:payload_start + chunk_size]
        # Chunks are padded to an even byte count.
        offset = payload_start + chunk_size + (chunk_size & 1)
    return body


async def _buffered_frames(pcm: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(pcm), FRAME_BYTES):
        yield pcm[start : start + FRAME_BYTES]


class WhisperLiveTranscriber:
    # Total silence appended to flush the buffer, sent as fifteen 100 ms
    # float32 frames at 16 kHz mono — see `send_audio` below.
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
        pcm = _strip_wav_header(pcm)
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
