from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.coach.phase import WIND_DOWN_LEAD_MIN, compute_phase


CT = ZoneInfo("America/Chicago")


def test_phase_day_when_far_from_lights_out():
    now = datetime(2026, 5, 19, 14, 0, tzinfo=CT)  # 2 PM
    info = compute_phase(now, "22:00")
    assert info.phase == "day"
    assert info.wind_down_mode is False
    assert info.lights_out_at == datetime(2026, 5, 19, 22, 0, tzinfo=CT)


def test_phase_wind_down_within_lead():
    now = datetime(2026, 5, 19, 21, 0, tzinfo=CT)  # 9 PM, 60 min ahead of 22:00
    info = compute_phase(now, "22:00")
    assert info.phase == "wind-down"
    assert info.wind_down_mode is True


def test_phase_late_after_lights_out():
    now = datetime(2026, 5, 19, 23, 30, tzinfo=CT)
    info = compute_phase(now, "22:00")
    assert info.phase == "late"
    assert info.wind_down_mode is True
    # lights_out_at rolls to tomorrow once we're past today's.
    assert info.lights_out_at == datetime(2026, 5, 20, 22, 0, tzinfo=CT)


def test_phase_late_overnight_before_morning():
    now = datetime(2026, 5, 20, 2, 0, tzinfo=CT)
    info = compute_phase(now, "22:00")
    assert info.phase == "late"


def test_phase_day_back_after_morning():
    now = datetime(2026, 5, 20, 8, 0, tzinfo=CT)
    info = compute_phase(now, "22:00")
    assert info.phase == "day"


def test_phase_wind_down_respects_lead_minutes():
    lights_out = "22:00"
    boundary = datetime(2026, 5, 19, 22, 0, tzinfo=CT)
    # 1 min inside the wind-down window → wind-down
    just_inside = boundary - timedelta(minutes=WIND_DOWN_LEAD_MIN - 1)
    # 1 min outside the wind-down window → day
    just_outside = boundary - timedelta(minutes=WIND_DOWN_LEAD_MIN + 1)
    assert compute_phase(just_inside, lights_out).phase == "wind-down"
    assert compute_phase(just_outside, lights_out).phase == "day"


def test_phase_handles_non_default_lights_out():
    now = datetime(2026, 5, 19, 22, 30, tzinfo=CT)
    info = compute_phase(now, "23:30")
    assert info.phase == "wind-down"
    assert info.lights_out_at == datetime(2026, 5, 19, 23, 30, tzinfo=CT)
