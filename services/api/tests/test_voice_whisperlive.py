"""The three load-bearing WhisperLive behaviours.

Each of these is a bug that was already paid for once. A future edit that
"simplifies" any of them reintroduces it, which is why they are pinned here.
"""
import struct

from app.services.voice.whisperlive import (
    _as_float32,
    _strip_wav_header,
    _TranscriptAccumulator,
)


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


def _wav(pcm: bytes) -> bytes:
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, 16000, 32000, 2, 16,
        b"data", len(pcm),
    )
    return header + pcm


def test_strip_wav_header_leaves_bare_pcm_untouched():
    pcm = struct.pack("<4h", 1, 2, 3, 4)
    assert _strip_wav_header(pcm) == pcm


def test_strip_wav_header_locates_the_data_chunk():
    pcm = struct.pack("<4h", 100, -200, 300, -400)
    assert _strip_wav_header(_wav(pcm)) == pcm


def test_strip_wav_header_skips_non_data_chunks_before_data():
    """A WAV with an extra chunk (e.g. `LIST`/metadata) between `fmt ` and
    `data` must still land on the audio, not on the extra chunk's bytes."""
    pcm = struct.pack("<2h", 111, -222)
    extra = struct.pack("<4sI", b"JUNK", 4) + b"\x01\x02\x03\x04"
    wav = _wav(pcm)
    # Splice the extra chunk in just before the `data` chunk.
    data_idx = wav.index(b"data")
    spliced = wav[:data_idx] + extra + wav[data_idx:]
    assert _strip_wav_header(spliced) == pcm


def test_strip_wav_header_treats_a_short_or_unrecognized_body_as_raw_pcm():
    assert _strip_wav_header(b"\x01\x02\x03") == b"\x01\x02\x03"
    not_wav = b"NOPE" + b"\x00" * 20
    assert _strip_wav_header(not_wav) == not_wav
