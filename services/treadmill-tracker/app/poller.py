"""Idle/active polling state machine.

Held entirely separate from Mongo + sockets so it's testable.
Caller drives `tick()` repeatedly; poller decides what to do
(probe vs sweep), reports a Sample (or None) and the next sleep.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from app.bridge import ACTIVE_SWEEP, GETSTATUS
from app.parser import (
    parse_calories,
    parse_distance_raw,
    parse_grade_pct,
    parse_hr_bpm,
    parse_speed_mph,
    parse_twork_s,
    status_to_state,
)


class Mode(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"


@dataclass
class Sample:
    ts: datetime
    state: int
    speed_mph: float | None
    grade_pct: float | None
    distance_raw: int | None
    calories: int | None
    twork_s: int | None
    hr_bpm: int | None


@dataclass
class TickResult:
    sample: Sample | None
    mode_changed: bool
    new_mode: Mode
    sleep_s: float


class BridgeQuery(Protocol):
    def query(self, cmd: int, *, timeout: float) -> bytes | None: ...


class Poller:
    def __init__(
        self,
        bridge: BridgeQuery,
        *,
        active_hz: float = 2.0,
        idle_interval_s: float = 15.0,
        active_timeout_s: float = 0.6,
        idle_timeout_s: float = 0.2,
        active_fail_threshold: int = 3,
        clock=datetime.now,
    ) -> None:
        self.bridge = bridge
        self.active_period_s = 1.0 / active_hz
        self.idle_interval_s = idle_interval_s
        self.active_timeout_s = active_timeout_s
        self.idle_timeout_s = idle_timeout_s
        self.active_fail_threshold = active_fail_threshold
        self._clock = clock
        self.mode: Mode = Mode.IDLE
        self._consecutive_failures = 0

    def _now(self) -> datetime:
        return self._clock(UTC)

    def _idle_tick(self) -> TickResult:
        payload = self.bridge.query(GETSTATUS, timeout=self.idle_timeout_s)
        if payload is None:
            return TickResult(sample=None, mode_changed=False,
                              new_mode=Mode.IDLE, sleep_s=self.idle_interval_s)
        # Got a response — flip to active for next tick. Don't write the
        # probe sample (we're missing the other fields anyway); the very
        # next active sweep will produce a real sample.
        self.mode = Mode.ACTIVE
        self._consecutive_failures = 0
        return TickResult(sample=None, mode_changed=True,
                          new_mode=Mode.ACTIVE, sleep_s=0.0)

    def _active_tick(self) -> TickResult:
        results: dict[int, bytes] = {}
        any_response = False
        for cmd in ACTIVE_SWEEP:
            payload = self.bridge.query(cmd, timeout=self.active_timeout_s)
            if payload is not None:
                results[cmd] = payload
                any_response = True

        if not any_response:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.active_fail_threshold:
                self.mode = Mode.IDLE
                self._consecutive_failures = 0
                return TickResult(sample=None, mode_changed=True,
                              new_mode=Mode.IDLE, sleep_s=self.idle_interval_s)
            return TickResult(sample=None, mode_changed=False,
                              new_mode=Mode.ACTIVE, sleep_s=self.active_period_s)

        self._consecutive_failures = 0
        sample = Sample(
            ts=self._now(),
            state=status_to_state(results.get(0x80, b"")),
            speed_mph=parse_speed_mph(results.get(0xA5, b"")),
            grade_pct=parse_grade_pct(results.get(0xA8, b"")),
            distance_raw=parse_distance_raw(results.get(0xA1, b"")),
            calories=parse_calories(results.get(0xA3, b"")),
            twork_s=parse_twork_s(results.get(0xA0, b"")),
            hr_bpm=parse_hr_bpm(results.get(0xB0, b"")),
        )
        return TickResult(sample=sample, mode_changed=False,
                          new_mode=Mode.ACTIVE, sleep_s=self.active_period_s)

    def tick(self) -> TickResult:
        if self.mode is Mode.IDLE:
            return self._idle_tick()
        return self._active_tick()
