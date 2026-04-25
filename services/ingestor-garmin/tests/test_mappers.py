from app.mappers import (
    map_body_comp,
    map_hrv,
    map_sleep,
    map_vo2max,
    map_weight,
    map_workout,
)


def test_map_sleep(fixture):
    raw = fixture("sleep.json")
    s = map_sleep(raw)
    assert s.duration_s == 26400
    assert s.deep_s == 3600
    assert s.rem_s == 5400
    assert s.light_s == 15000
    assert s.awake_s == 2400
    assert s.score == 78
    assert s.source == "garmin"
    assert s.source_id.startswith("garmin:sleep:")


def test_map_hrv(fixture):
    raw = fixture("hrv.json")
    h = map_hrv(raw)
    assert h.rmssd_ms == 58.0
    assert h.source_id.startswith("garmin:hrv:")


def test_map_weight_converts_grams_to_kg(fixture):
    raw = fixture("weight.json")
    samples = map_weight(raw)
    assert len(samples) == 1
    assert samples[0].kg == 108.9
    assert samples[0].source_id == "garmin:weight:900000001"


def test_map_body_comp(fixture):
    raw = fixture("body_comp.json")
    samples = map_body_comp(raw)
    assert len(samples) == 1
    bc = samples[0]
    assert bc.weight_kg == 108.9
    assert bc.body_fat_pct == 24.1
    assert bc.muscle_mass_kg == 80.0
    assert bc.body_water_pct == 55.2
    assert bc.bone_mass_kg == 3.8


def test_map_vo2max(fixture):
    raw = fixture("vo2max.json")
    v = map_vo2max(raw)
    assert v.value == 42.0


def test_map_workout(fixture):
    raw = fixture("workout.json")
    workouts = map_workout(raw)
    assert len(workouts) == 1
    w = workouts[0]
    assert w.activity_type == "walking"
    assert w.duration_s == 1800
    assert w.distance_m == 2500.4
    assert w.avg_hr == 112
    assert w.max_hr == 128
    assert w.calories == 240
    assert w.source_id == "garmin:activity:13000000001"
