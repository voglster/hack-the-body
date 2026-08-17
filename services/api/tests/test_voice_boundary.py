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
