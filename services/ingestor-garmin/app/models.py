from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _TSBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    source: str
    source_id: str


class Weight(_TSBase):
    kg: float = Field(gt=0)


class Sleep(_TSBase):
    duration_s: int
    deep_s: int
    rem_s: int
    light_s: int
    awake_s: int
    score: int | None = None


class HRV(_TSBase):
    rmssd_ms: float


class RHR(_TSBase):
    bpm: int


class BodyComp(_TSBase):
    weight_kg: float
    body_fat_pct: float | None = None
    muscle_mass_kg: float | None = None
    body_water_pct: float | None = None
    bone_mass_kg: float | None = None


class VO2Max(_TSBase):
    value: float


class DailySummary(_TSBase):
    steps: int
    step_goal: int | None = None
    distance_m: float | None = None
    active_kcal: int | None = None
    total_kcal: int | None = None
    resting_hr: int | None = None
    intensity_minutes: int | None = None
    floors_climbed: int | None = None
    # Full Garmin response so we can surface more fields later without a
    # full historical re-pull. Schema may evolve; consumers should treat it
    # as opaque except for the explicit named fields above.
    raw: dict[str, Any] = Field(default_factory=dict)


class Workout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    activity_type: str
    duration_s: int
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    calories: int | None = None
    notes: str | None = None
    source: str
    source_id: str
