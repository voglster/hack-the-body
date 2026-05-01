"""Decode CSAFE response payloads into typed sample fields."""
from __future__ import annotations

from app.bridge import (
    GETCALORIES,
    GETGRADE,
    GETHORIZONTAL,
    GETHRCUR,
    GETSPEED,
    GETTWORK,
)

_HEADER_LEN = 3
_U16_LEN = 2


def _data_after_header(payload: bytes, cmd: int) -> bytes:
    if len(payload) >= _HEADER_LEN and payload[1] == cmd:
        n = payload[2]
        return payload[_HEADER_LEN:_HEADER_LEN + n]
    return b""


def parse_status(payload: bytes) -> int | None:
    """Bottom nibble of GETSTATUS payload byte 0. Top nibble is a frame
    counter that toggles between polls — strip it."""
    if not payload:
        return None
    return payload[0] & 0x0F


def parse_u16(payload: bytes, cmd: int) -> int | None:
    data = _data_after_header(payload, cmd)
    if len(data) < _U16_LEN:
        return None
    return int.from_bytes(data[:2], "little")


def parse_speed_mph(payload: bytes) -> float | None:
    v = parse_u16(payload, GETSPEED)
    return v / 10.0 if v is not None else None


def parse_grade_pct(payload: bytes) -> float | None:
    v = parse_u16(payload, GETGRADE)
    return v / 100.0 if v is not None else None


def parse_distance_raw(payload: bytes) -> int | None:
    return parse_u16(payload, GETHORIZONTAL)


def parse_calories(payload: bytes) -> int | None:
    return parse_u16(payload, GETCALORIES)


def parse_twork_s(payload: bytes) -> int | None:
    return parse_u16(payload, GETTWORK)


def parse_hr_bpm(payload: bytes) -> int | None:
    """HRCUR payload: <status><cmd><len><data...>. Last data byte is bpm."""
    data = _data_after_header(payload, GETHRCUR)
    if not data:
        return None
    return data[-1]


# Distance: 1 raw count = 0.001 mi (calibrated 2026-05-01)
MI_PER_COUNT = 0.001


def status_to_state(payload: bytes) -> int:
    s = parse_status(payload)
    return s if s is not None else 0
