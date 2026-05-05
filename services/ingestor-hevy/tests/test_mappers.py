import json
from datetime import UTC, datetime
from pathlib import Path

from app.mappers import map_strength_sets, map_workout

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_map_workout_basics():
    raw = _load("workout_strength.json")
    w = map_workout(raw)
    assert w.source == "hevy"
    assert w.source_id == "hevy:51a93a88-2f2e-42f2-9fe8-97b0791f836e"
    assert w.activity_type == "strength"
    assert w.title == "Bodyweight"
    assert w.ts == datetime(2026, 5, 5, 18, 3, 37, tzinfo=UTC)
    assert w.duration_s == 3701  # 1h01m41s
    assert w.exercise_count == 2
    assert w.set_count == 3
    assert w.distance_m is None
    assert w.calories is None
    assert w.updated_at == datetime(2026, 5, 5, 19, 5, 36, 254000, tzinfo=UTC)
    assert w.raw == raw


def test_map_strength_sets_flattens_per_set():
    raw = _load("workout_strength.json")
    sets = map_strength_sets(raw)
    assert len(sets) == 3
    assert sets[0].workout_source_id == "hevy:51a93a88-2f2e-42f2-9fe8-97b0791f836e"
    assert sets[0].exercise_index == 0
    assert sets[0].set_index == 0
    assert sets[0].exercise_title == "Incline Push Ups"
    assert sets[0].exercise_template_id == "39C99849"
    assert sets[0].reps == 12
    assert sets[0].weight_kg is None
    assert sets[0].set_type == "normal"
    assert sets[0].notes == "5th step"  # exercise note copied to set
    # Plank set: timed instead of reps
    assert sets[2].duration_s == 32
    assert sets[2].reps is None
    assert sets[2].exercise_title == "Plank"
    # ts inherited from parent start_time
    assert sets[2].ts == datetime(2026, 5, 5, 18, 3, 37, tzinfo=UTC)


def test_map_strength_sets_handles_missing_optional_fields():
    raw = {
        "id": "abc",
        "title": "T",
        "start_time": "2026-05-01T00:00:00+00:00",
        "end_time":   "2026-05-01T00:30:00+00:00",
        "updated_at": "2026-05-01T00:30:01Z",
        "exercises": [{
            "index": 0, "title": "Squat", "notes": "",
            "exercise_template_id": "X", "superset_id": "ss-1",
            "sets": [{"index": 0, "type": "warmup",
                      "weight_kg": 60.0, "reps": 5,
                      "distance_meters": None, "duration_seconds": None,
                      "rpe": 7.5}],
        }],
    }
    sets = map_strength_sets(raw)
    assert sets[0].weight_kg == 60.0
    assert sets[0].rpe == 7.5
    assert sets[0].set_type == "warmup"
    assert sets[0].superset_id == "ss-1"
    assert sets[0].notes is None  # empty string normalizes to None
