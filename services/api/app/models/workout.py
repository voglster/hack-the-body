from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Workout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    activity_type: str
    duration_s: int = Field(ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    avg_hr: int | None = Field(default=None, ge=0)
    max_hr: int | None = Field(default=None, ge=0)
    calories: int | None = Field(default=None, ge=0)
    notes: str | None = None
    source: str
    source_id: str
