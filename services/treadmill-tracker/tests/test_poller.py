"""State-machine tests using a fake bridge."""
from __future__ import annotations

from datetime import UTC, datetime

from app.bridge import (
    ACTIVE_SWEEP,
    GETCALORIES,
    GETGRADE,
    GETHORIZONTAL,
    GETHRCUR,
    GETSPEED,
    GETSTATUS,
    GETTWORK,
)
from app.csafe import decode as cdec
from app.csafe import encode as cenc
from app.poller import Mode, Poller


def _frame_for(cmd: int, data: bytes) -> bytes:
    """Build a CSAFE response payload as the parser expects:
    <status><cmd><len><data...>."""
    return bytes([0x09, cmd, len(data)]) + data


class FakeBridge:
    """Scriptable bridge: returns canned payloads per command."""

    def __init__(self, table: dict[int, bytes | None] | None = None) -> None:
        self.table = table or {}
        self.calls: list[tuple[int, float]] = []

    def query(self, cmd: int, *, timeout: float) -> bytes | None:
        self.calls.append((cmd, timeout))
        return self.table.get(cmd)

    def status_present(self) -> None:
        self.table[GETSTATUS] = bytes([0x09])

    def status_silent(self) -> None:
        self.table[GETSTATUS] = None

    def set_active_payloads(self) -> None:
        # walking 1.0 mph, 1.5% grade, distance raw 100, hr 110
        self.table[GETSTATUS] = bytes([0x09])
        self.table[GETSPEED] = _frame_for(GETSPEED, (10).to_bytes(2, "little"))
        self.table[GETGRADE] = _frame_for(GETGRADE, (150).to_bytes(2, "little"))
        self.table[GETHORIZONTAL] = _frame_for(GETHORIZONTAL,
                                               (100).to_bytes(2, "little"))
        self.table[GETCALORIES] = _frame_for(GETCALORIES, (12).to_bytes(2, "little"))
        self.table[GETTWORK] = _frame_for(GETTWORK, (60).to_bytes(2, "little"))
        self.table[GETHRCUR] = _frame_for(GETHRCUR, bytes([0, 0, 110]))

    def silence(self) -> None:
        for cmd in ACTIVE_SWEEP:
            self.table[cmd] = None


def make_poller(bridge: FakeBridge) -> Poller:
    return Poller(
        bridge,
        active_hz=10.0,           # tight period for fast tests
        idle_interval_s=15.0,
        active_timeout_s=0.6,
        idle_timeout_s=0.2,
        active_fail_threshold=3,
        clock=lambda tz=UTC: datetime(2026, 5, 1, 12, 0, 0, tzinfo=tz),
    )


def test_starts_idle():
    p = make_poller(FakeBridge())
    assert p.mode is Mode.IDLE


def test_idle_with_silent_bridge_stays_idle():
    b = FakeBridge()
    b.status_silent()
    p = make_poller(b)
    r = p.tick()
    assert r.sample is None
    assert r.new_mode is Mode.IDLE
    assert not r.mode_changed
    assert r.sleep_s == 15.0
    # Idle should only probe GETSTATUS, not the full sweep
    assert all(cmd == GETSTATUS for cmd, _ in b.calls)


def test_idle_to_active_on_first_response():
    b = FakeBridge()
    b.status_present()
    p = make_poller(b)
    r = p.tick()
    assert r.mode_changed
    assert r.new_mode is Mode.ACTIVE
    assert r.sample is None       # probe doesn't produce a full sample
    assert r.sleep_s == 0.0       # immediate transition to active sweep


def test_active_sweep_writes_sample():
    b = FakeBridge()
    b.set_active_payloads()
    p = make_poller(b)
    p.mode = Mode.ACTIVE  # skip the idle->active hop for clarity
    r = p.tick()
    assert r.sample is not None
    s = r.sample
    assert s.state == 0x09
    assert s.speed_mph == 1.0
    assert s.grade_pct == 1.5
    assert s.distance_raw == 100
    assert s.calories == 12
    assert s.twork_s == 60
    assert s.hr_bpm == 110
    assert r.new_mode is Mode.ACTIVE
    assert r.sleep_s == 0.1       # 1/10 Hz


def test_active_to_idle_after_threshold_failures():
    b = FakeBridge()
    b.silence()
    p = make_poller(b)
    p.mode = Mode.ACTIVE

    r1 = p.tick()
    assert r1.new_mode is Mode.ACTIVE  # 1 fail
    assert not r1.mode_changed

    r2 = p.tick()
    assert r2.new_mode is Mode.ACTIVE  # 2 fails
    assert not r2.mode_changed

    r3 = p.tick()
    assert r3.new_mode is Mode.IDLE   # 3 fails -> idle
    assert r3.mode_changed
    assert r3.sleep_s == 15.0


def test_active_partial_response_resets_failure_count():
    b = FakeBridge()
    b.set_active_payloads()
    p = make_poller(b)
    p.mode = Mode.ACTIVE

    # one good sweep
    p.tick()
    # one fail
    b.silence()
    p.tick()
    # good again
    b.set_active_payloads()
    p.tick()
    # silence again — should still need full threshold from zero
    b.silence()
    p.tick()
    p.tick()
    r = p.tick()
    assert r.new_mode is Mode.IDLE
    assert r.mode_changed


def test_hr_zero_when_strap_missing():
    b = FakeBridge()
    b.set_active_payloads()
    b.table[GETHRCUR] = _frame_for(GETHRCUR, bytes([0, 0, 0]))
    p = make_poller(b)
    p.mode = Mode.ACTIVE
    r = p.tick()
    assert r.sample is not None
    assert r.sample.hr_bpm == 0


def test_csafe_encode_decode_roundtrip():
    payload = bytes([0x80])
    frame = cenc(payload)
    assert cdec(frame) == payload
