from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Workout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    activity_type: str
    duration_s: int
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    calories: int | None = None
    title: str | None = None
    exercise_count: int | None = None
    set_count: int | None = None
    updated_at: datetime
    raw: dict[str, Any]
    source: str
    source_id: str


class StrengthSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workout_source_id: str
    ts: datetime
    exercise_index: int
    exercise_title: str
    exercise_template_id: str | None = None
    set_index: int
    set_type: str
    reps: int | None = None
    weight_kg: float | None = None
    distance_m: float | None = None
    duration_s: int | None = None
    rpe: float | None = None
    superset_id: str | None = None
    notes: str | None = None
