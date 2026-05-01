"""Tests for the TCX writer."""
# ruff: noqa: S314  # parsing our own output, not untrusted XML
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from xml.etree.ElementTree import fromstring

from app.tcx import EXT_NS, TCX_NS, build_tcx


def _workout(**overrides):
    started = datetime(2026, 5, 1, 17, 0, 0, tzinfo=UTC)
    base = {
        "started_at": started,
        "ended_at": started + timedelta(minutes=20),
        "duration_s": 1200,
        "distance_mi": 1.0,
        "avg_speed_mph": 3.0,
        "max_speed_mph": 3.5,
        "avg_grade_pct": 1.5,
        "max_grade_pct": 3.0,
        "avg_hr": 130,
        "max_hr": 145,
        "calories": 150,
        "status": "complete",
        "source": "precor-csafe",
        "source_id": "treadmill:2026-05-01T17:00:00+00:00",
    }
    base.update(overrides)
    return base


def _samples(workout, n=10):
    base = workout["started_at"]
    return [
        {
            "ts": base + timedelta(seconds=i * 60),
            "speed_mph": 3.0,
            "grade_pct": 1.0,
            "distance_raw": 1000 + i * 50,
            "hr_bpm": 120 + i,
            "calories": 5 * i,
        }
        for i in range(n)
    ]


def test_tcx_has_required_lap_fields():
    w = _workout()
    xml = build_tcx(w, _samples(w))
    root = fromstring(xml)
    activity = root.find(f"{{{TCX_NS}}}Activities/{{{TCX_NS}}}Activity")
    assert activity is not None
    assert activity.get("Sport") == "Running"
    lap = activity.find(f"{{{TCX_NS}}}Lap")
    assert lap is not None
    total = lap.find(f"{{{TCX_NS}}}TotalTimeSeconds").text
    assert float(total) == 1200.0
    dist = lap.find(f"{{{TCX_NS}}}DistanceMeters").text
    # 1.0 mi -> 1609.34 m
    assert 1609.0 < float(dist) < 1610.0
    avg_hr = lap.find(f"{{{TCX_NS}}}AverageHeartRateBpm/{{{TCX_NS}}}Value").text
    assert avg_hr == "130"


def test_tcx_trackpoint_count_matches_samples():
    w = _workout()
    samples = _samples(w, n=15)
    xml = build_tcx(w, samples)
    root = fromstring(xml)
    track = root.find(
        f"{{{TCX_NS}}}Activities/{{{TCX_NS}}}Activity/"
        f"{{{TCX_NS}}}Lap/{{{TCX_NS}}}Track",
    )
    points = track.findall(f"{{{TCX_NS}}}Trackpoint")
    assert len(points) == 15


def test_tcx_omits_hr_when_strap_missing():
    w = _workout(avg_hr=None, max_hr=None)
    samples = _samples(w)
    for s in samples:
        s["hr_bpm"] = 0
    xml = build_tcx(w, samples)
    root = fromstring(xml)
    # No HeartRateBpm anywhere
    assert root.find(f".//{{{TCX_NS}}}HeartRateBpm") is None


def test_tcx_distance_uses_raw_counter():
    w = _workout()
    samples = _samples(w, n=2)
    samples[0]["distance_raw"] = 1000
    samples[1]["distance_raw"] = 1100  # +100 counts = 0.1 mi = 160.93 m
    xml = build_tcx(w, samples)
    root = fromstring(xml)
    points = root.findall(
        f".//{{{TCX_NS}}}Track/{{{TCX_NS}}}Trackpoint/{{{TCX_NS}}}DistanceMeters",
    )
    assert float(points[0].text) == 0.0
    assert 160.0 < float(points[1].text) < 161.0


def test_tcx_distance_handles_u16_wrap():
    w = _workout()
    samples = _samples(w, n=2)
    # Wraps from 65500 to 100 -> real delta 136
    samples[0]["distance_raw"] = 65500
    samples[1]["distance_raw"] = 100
    xml = build_tcx(w, samples)
    root = fromstring(xml)
    last = root.findall(
        f".//{{{TCX_NS}}}Track/{{{TCX_NS}}}Trackpoint/{{{TCX_NS}}}DistanceMeters",
    )[-1]
    # 136 counts * 0.001 mi/count * 1609.344 m/mi = ~218.87m
    assert 218.0 < float(last.text) < 220.0


def test_tcx_includes_speed_extension():
    w = _workout()
    xml = build_tcx(w, _samples(w))
    root = fromstring(xml)
    speed = root.find(f".//{{{EXT_NS}}}Speed")
    assert speed is not None
    # 3 mph -> ~1.34 m/s
    assert 1.3 < float(speed.text) < 1.4


def test_tcx_synthesizes_two_trackpoints_when_no_samples():
    w = _workout()
    xml = build_tcx(w, [])
    root = fromstring(xml)
    points = root.findall(
        f".//{{{TCX_NS}}}Track/{{{TCX_NS}}}Trackpoint",
    )
    assert len(points) == 2
