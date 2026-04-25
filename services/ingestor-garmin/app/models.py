from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _TSBase(BaseModel):
    """Common fields for every Garmin time-series record.

    `raw` is the slice of Garmin's response this record was derived from,
    preserved verbatim so we can surface new fields later without a re-pull.
    """
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    source: str
    source_id: str
    raw: dict[str, Any] = Field(default_factory=dict)


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


class StepsBucket(_TSBase):
    end_ts: datetime
    steps: int
    activity_level: str | None = None


class DailySummary(_TSBase):
    steps: int
    step_goal: int | None = None
    distance_m: float | None = None
    active_kcal: int | None = None
    total_kcal: int | None = None
    resting_hr: int | None = None
    intensity_minutes: int | None = None
    floors_climbed: int | None = None


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
    raw: dict[str, Any] = Field(default_factory=dict)
