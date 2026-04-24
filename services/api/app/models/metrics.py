from datetime import datetime

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
