"""The eating window (default 11:00-19:00 local), computed once for every surface.

The coach used to be told "the window is 11:00-19:00" and left to do clock
arithmetic, which it gets wrong ("fasting window closes in 45 minutes" at
11:15). Everything that talks about meal timing reads this instead.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

DEFAULT_WINDOW = ("11:00", "19:00")


def _hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def window_bounds(targets: dict[str, Any] | None) -> tuple[str, str]:
    t = targets or {}
    return (
        t.get("eating_window_start_local") or DEFAULT_WINDOW[0],
        t.get("eating_window_end_local") or DEFAULT_WINDOW[1],
    )


def window_state(now_local: datetime, start: str, end: str) -> dict[str, Any]:
    """Where `now` sits in the eating window, and minutes until that changes."""
    opens = datetime.combine(now_local.date(), _hhmm(start), tzinfo=now_local.tzinfo)
    closes = datetime.combine(now_local.date(), _hhmm(end), tzinfo=now_local.tzinfo)
    if now_local < opens:
        state, change = "before", opens
    elif now_local < closes:
        state, change = "open", closes
    else:
        state, change = "after", opens + timedelta(days=1)
    return {
        "start": start,
        "end": end,
        "state": state,
        "minutes_to_change": int((change - now_local).total_seconds() // 60),
    }


def _duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if h else f"{m} min"


def describe(w: dict[str, Any]) -> str:
    """One plain sentence the coach can repeat without doing any arithmetic."""
    left = _duration(w["minutes_to_change"])
    if w["state"] == "before":
        return (
            f"Fasting. Eating window opens at {w['start']} (in {left}). "
            "No food advice before then; water, coffee, tea are fine."
        )
    if w["state"] == "open":
        return f"Eating window is open until {w['end']} ({left} left)."
    return (
        f"Eating window closed at {w['end']}. Fasting until {w['start']} tomorrow. "
        "No food advice; review the day or talk about tomorrow."
    )


def eating_window(now_local: datetime, targets: dict[str, Any] | None) -> dict[str, Any]:
    w = window_state(now_local, *window_bounds(targets))
    return {**w, "summary": describe(w)}
