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
