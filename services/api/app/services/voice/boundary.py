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
