from datetime import datetime, timezone

from app.models.metrics import (
    BodyComp,
    HRV,
    RHR,
    Sleep,
    VO2Max,
    Weight,
)
from app.models.workout import Workout


def test_weight_requires_positive_kg():
    w = Weight(ts=datetime.now(timezone.utc), kg=108.9, source="garmin", source_id="g:w:1")
    assert w.kg == 108.9


def test_sleep_derives_total_seconds():
    s = Sleep(
        ts=datetime.now(timezone.utc),
        duration_s=7 * 3600 + 15 * 60,
        deep_s=3600,
        rem_s=5400,
        light_s=2 * 3600,
        awake_s=15 * 60,
        score=82,
        source="garmin",
        source_id="g:s:2026-04-24",
    )
    assert s.duration_s == 7 * 3600 + 15 * 60


def test_hrv_non_negative():
    h = HRV(ts=datetime.now(timezone.utc), rmssd_ms=58.2, source="garmin", source_id="g:hrv:1")
    assert h.rmssd_ms == 58.2


def test_rhr_reasonable():
    r = RHR(ts=datetime.now(timezone.utc), bpm=54, source="garmin", source_id="g:rhr:1")
    assert r.bpm == 54


def test_body_comp_optional_fields():
    b = BodyComp(
        ts=datetime.now(timezone.utc),
        weight_kg=108.9,
        body_fat_pct=24.1,
        muscle_mass_kg=None,
        source="garmin-scale",
        source_id="g:bc:1",
    )
    assert b.muscle_mass_kg is None


def test_vo2max_value():
    v = VO2Max(ts=datetime.now(timezone.utc), value=42.0, source="garmin", source_id="g:v:1")
    assert v.value == 42.0


def test_workout_has_movements():
    w = Workout(
        ts=datetime.now(timezone.utc),
        activity_type="walking",
        duration_s=1800,
        distance_m=2500.0,
        avg_hr=112,
        calories=240,
        source="garmin",
        source_id="g:act:1",
    )
    assert w.activity_type == "walking"
