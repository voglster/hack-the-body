from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _TimeseriesBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    source: str
    source_id: str


class Weight(_TimeseriesBase):
    kg: float = Field(gt=0)


class Sleep(_TimeseriesBase):
    duration_s: int = Field(ge=0)
    deep_s: int = Field(ge=0)
    rem_s: int = Field(ge=0)
    light_s: int = Field(ge=0)
    awake_s: int = Field(ge=0)
    score: int | None = Field(default=None, ge=0, le=100)


class HRV(_TimeseriesBase):
    rmssd_ms: float = Field(ge=0)


class RHR(_TimeseriesBase):
    bpm: int = Field(gt=0, lt=250)


class BodyComp(_TimeseriesBase):
    weight_kg: float = Field(gt=0)
    body_fat_pct: float | None = Field(default=None, ge=0, le=100)
    muscle_mass_kg: float | None = Field(default=None, ge=0)
    body_water_pct: float | None = Field(default=None, ge=0, le=100)
    bone_mass_kg: float | None = Field(default=None, ge=0)


class VO2Max(_TimeseriesBase):
    value: float = Field(gt=0)


class DailySummary(_TimeseriesBase):
    """Daily wellness summary from Garmin's /usersummary-service endpoint.

    Surfaces named fields up front so the dashboard / repos can index/sort/
    chart without parsing JSON. The full Garmin response is also stored in
    `raw` so we can surface new fields later without a historical re-pull.
    """
    steps: int = Field(ge=0)
    step_goal: int | None = Field(default=None, ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    active_kcal: int | None = Field(default=None, ge=0)
    total_kcal: int | None = Field(default=None, ge=0)
    resting_hr: int | None = Field(default=None, gt=0, lt=250)
    intensity_minutes: int | None = Field(default=None, ge=0)
    floors_climbed: int | None = Field(default=None, ge=0)
    raw: dict[str, Any] = Field(default_factory=dict)
