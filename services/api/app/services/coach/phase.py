from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal

WIND_DOWN_LEAD_MIN = 90

Phase = Literal["day", "wind-down", "late"]


@dataclass
class PhaseInfo:
    phase: Phase
    lights_out_at: datetime
    wind_down_mode: bool


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":", 1)
    return time(int(h), int(m))


def compute_phase(now_local: datetime, lights_out_local: str) -> PhaseInfo:
    """Derive the day-phase from a tz-aware `now` and an "HH:MM" lights-out.

    `lights_out_at` is the upcoming lights-out: today's if it's still
    ahead, tomorrow's otherwise. "Late" runs from today's lights-out
    until the following morning at 04:00 local; after that we return to
    "day" — the small four-hour buffer keeps middle-of-the-night briefs
    framed as `late` rather than reading as a fresh morning.
    """
    if now_local.tzinfo is None:
        raise ValueError("now_local must be timezone-aware")
    target = _parse_hhmm(lights_out_local)
    todays_lights_out = now_local.replace(
        hour=target.hour, minute=target.minute,
        second=0, microsecond=0,
    )
    morning_break = now_local.replace(
        hour=4, minute=0, second=0, microsecond=0,
    )
    if now_local >= todays_lights_out:
        # Past today's lights-out → late, and next lights-out is tomorrow's.
        return PhaseInfo(
            phase="late",
            lights_out_at=todays_lights_out + timedelta(days=1),
            wind_down_mode=True,
        )
    if now_local < morning_break:
        # Wee hours: still "late" relative to yesterday's lights-out.
        return PhaseInfo(
            phase="late",
            lights_out_at=todays_lights_out,
            wind_down_mode=True,
        )
    delta = todays_lights_out - now_local
    if delta <= timedelta(minutes=WIND_DOWN_LEAD_MIN):
        return PhaseInfo(
            phase="wind-down",
            lights_out_at=todays_lights_out,
            wind_down_mode=True,
        )
    return PhaseInfo(
        phase="day",
        lights_out_at=todays_lights_out,
        wind_down_mode=False,
    )
