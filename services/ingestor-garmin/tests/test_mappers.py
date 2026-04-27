from app.mappers import (
    map_body_comp,
    map_daily_summary,
    map_hrv,
    map_intraday_steps,
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


def test_map_vo2max_no_measurement():
    # Garmin omits "generic" on days without a qualifying activity.
    assert map_vo2max({}) is None
    assert map_vo2max({"generic": None}) is None
    assert map_vo2max({"generic": {"calendarDate": "2026-04-25"}}) is None


def test_map_sleep_no_measurement():
    # Repeat-pull during the day: dailySleepDTO present but timestamps null.
    stub = {
        "dailySleepDTO": {
            "calendarDate": "2026-04-27",
            "sleepEndTimestampGMT": None,
            "sleepTimeSeconds": None,
            "deepSleepSeconds": None,
            "remSleepSeconds": None,
            "lightSleepSeconds": None,
            "awakeSleepSeconds": None,
        },
    }
    assert map_sleep(stub) is None
    assert map_sleep({}) is None
    assert map_sleep({"dailySleepDTO": None}) is None


def test_map_hrv_no_measurement():
    # Garmin omits hrvSummary (or its lastNightAvg) on days without a reading.
    assert map_hrv({}) is None
    assert map_hrv({"hrvSummary": None}) is None
    assert map_hrv({"hrvSummary": {"calendarDate": "2026-04-27", "lastNightAvg": None}}) is None


def test_map_daily_summary(fixture):
    raw = fixture("daily_summary.json")
    s = map_daily_summary(raw)
    assert s.steps == 8742
    assert s.step_goal == 10000
    assert s.distance_m == 6510.4
    assert s.active_kcal == 480
    assert s.total_kcal == 2840
    assert s.resting_hr == 54
    assert s.intensity_minutes == 35  # 23 moderate + 12 vigorous
    assert s.floors_climbed == 8
    assert s.source_id == "garmin:daily_summary:2026-04-23"
    # Raw blob is preserved for future use.
    assert s.raw["userProfileId"] == 12345
    assert s.raw["wellnessKilocalories"] == 2840


def test_map_intraday_steps(fixture):
    raw = fixture("intraday_steps.json")
    buckets = map_intraday_steps(raw)
    assert len(buckets) == 4
    assert buckets[0].steps == 0
    assert buckets[2].steps == 856
    assert buckets[2].activity_level == "active"
    assert buckets[3].activity_level == "highlyActive"
    # Source IDs are unique per bucket-start.
    assert len({b.source_id for b in buckets}) == 4
    # Raw is preserved.
    assert buckets[2].raw["primaryActivityLevel"] == "active"


def test_map_intraday_steps_empty():
    assert map_intraday_steps([]) == []
    assert map_intraday_steps(None) == []  # type: ignore[arg-type]


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
