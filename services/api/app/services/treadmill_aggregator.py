"""Pull-on-read aggregator for treadmill workouts.

Reads raw `treadmill_samples` and turns them into either an active
workout summary or a finalized record in `workouts`. No background
loop — the API computes session state whenever a route asks.

Session boundary rule: a sample that arrives after a >SESSION_GAP_S
silence opens a new session. Lack of samples for >SESSION_GAP_S
closes the current one.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

SESSION_GAP_S = 30
MI_PER_COUNT = 0.001
_U16_WRAP = 65536
_MIN_SAMPLES_FOR_DISTANCE = 2
_MIN_SAMPLES_FOR_ZONES = 2
# How many trailing samples define "right now". 5 samples at 2 Hz =
# ~2.5s — responsive without single-sample twitch.
_LIVE_WINDOW_SAMPLES = 5
# "Real workout" gate. Sessions below ALL of these get dropped at
# finalize time — no `workouts` doc, no Garmin upload. Catches the
# case where the deck powers on (e.g. firmware update, accidental
# tap) but the user never actually walks.
MIN_REAL_DURATION_S = 120     # at least 2 minutes on the deck
MIN_REAL_ACTIVE_S = 60        # at least 1 minute with belt moving
MIN_REAL_DISTANCE_MI = 0.05   # at least ~80m
# Karvonen-derived zones for the user (age 44, RHR 51, HRmax 176,
# HRR 125). Z2 = fat-burn target.
#
# Update when fitness shifts: recompute HRmax (220-age or measured),
# pull current RHR from metrics_daily_summary, redo HRR * %band + RHR.
# Eventually this should live on user_profile.targets and be
# auto-derived from the rolling 30-day RHR.
HR_ZONES = [
    ("z1", 0, 126),
    ("z2", 126, 139),
    ("z3", 139, 151),
    ("z4", 151, 164),
    ("z5", 164, 999),
]
SOURCE = "precor-csafe"


@dataclass
class WorkoutSummary:
    started_at: datetime
    ended_at: datetime
    duration_s: int
    active_s: int
    distance_mi: float
    avg_speed: float
    max_speed: float
    avg_grade: float
    max_grade: float
    avg_hr: int | None
    max_hr: int | None
    hr_zones_s: dict[str, int]
    calories: int
    sample_count: int
    status: str  # "active" | "complete"
    # "Now" readings: last ~2.5s window average. None when not enough
    # recent samples (or session is finalized — current values would be
    # stale). Frontend uses these for live gauges; avg_* for session stats.
    current_speed_mph: float | None = None
    current_grade_pct: float | None = None
    current_hr: int | None = None

    def to_doc(self) -> dict[str, Any]:
        return {
            "ts": self.started_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": self.duration_s,
            "active_s": self.active_s,
            "distance_m": self.distance_mi * 1609.344,
            "distance_mi": self.distance_mi,
            "avg_speed_mph": self.avg_speed,
            "max_speed_mph": self.max_speed,
            "avg_grade_pct": self.avg_grade,
            "max_grade_pct": self.max_grade,
            "avg_hr": self.avg_hr,
            "max_hr": self.max_hr,
            "hr_zones_s": self.hr_zones_s,
            "calories": self.calories,
            "sample_count": self.sample_count,
            "status": self.status,
            "current_speed_mph": self.current_speed_mph,
            "current_grade_pct": self.current_grade_pct,
            "current_hr": self.current_hr,
            "activity_type": "treadmill_walk",
            "duration_s_total": self.duration_s,
            "source": SOURCE,
            "source_id": f"treadmill:{self.started_at.isoformat()}",
        }


def _aggregate(samples: list[dict[str, Any]], status: str) -> WorkoutSummary | None:
    if not samples:
        return None
    samples = sorted(samples, key=lambda d: d["ts"])
    started = samples[0]["ts"]
    ended = samples[-1]["ts"]
    duration_s = max(1, int((ended - started).total_seconds()))

    speeds = [s.get("speed_mph") or 0.0 for s in samples]
    grades = [s.get("grade_pct") or 0.0 for s in samples]
    hrs = [s.get("hr_bpm") or 0 for s in samples if (s.get("hr_bpm") or 0) > 0]
    cals = [s.get("calories") or 0 for s in samples]
    dists = [s.get("distance_raw") for s in samples if s.get("distance_raw") is not None]

    active_count = sum(1 for v in speeds if v > 0)
    # active_s estimated from sample density: ratio of moving samples
    # times duration. Acceptable since sample rate is ~constant.
    active_s = int(duration_s * (active_count / len(samples)))

    distance_mi = 0.0
    if len(dists) >= _MIN_SAMPLES_FOR_DISTANCE:
        delta = dists[-1] - dists[0]
        if delta < 0:
            delta += _U16_WRAP
        distance_mi = delta * MI_PER_COUNT

    hr_zones_s = _hr_zones_seconds(samples)
    cur_speed, cur_grade, cur_hr = _current_window(samples, status)

    return WorkoutSummary(
        started_at=started,
        ended_at=ended,
        duration_s=duration_s,
        active_s=active_s,
        distance_mi=round(distance_mi, 3),
        avg_speed=round(sum(speeds) / len(speeds), 2),
        max_speed=round(max(speeds), 2),
        avg_grade=round(sum(grades) / len(grades), 2),
        max_grade=round(max(grades), 2),
        avg_hr=int(sum(hrs) / len(hrs)) if hrs else None,
        max_hr=max(hrs) if hrs else None,
        hr_zones_s=hr_zones_s,
        calories=max(cals) if cals else 0,
        sample_count=len(samples),
        status=status,
        current_speed_mph=cur_speed,
        current_grade_pct=cur_grade,
        current_hr=cur_hr,
    )


def _current_window(
    samples: list[dict[str, Any]], status: str,
) -> tuple[float | None, float | None, int | None]:
    """Average the trailing _LIVE_WINDOW_SAMPLES samples for live readouts.

    Only meaningful while the session is active — for finalized records,
    "current" is stale by definition, so we return Nones."""
    if status != "active" or not samples:
        return None, None, None
    window = samples[-_LIVE_WINDOW_SAMPLES:]
    speeds = [s.get("speed_mph") for s in window if s.get("speed_mph") is not None]
    grades = [s.get("grade_pct") for s in window if s.get("grade_pct") is not None]
    hrs = [s.get("hr_bpm") for s in window if (s.get("hr_bpm") or 0) > 0]
    speed = round(sum(speeds) / len(speeds), 2) if speeds else None
    grade = round(sum(grades) / len(grades), 2) if grades else None
    hr = int(sum(hrs) / len(hrs)) if hrs else None
    return speed, grade, hr


def _hr_zones_seconds(samples: list[dict[str, Any]]) -> dict[str, int]:
    if len(samples) < _MIN_SAMPLES_FOR_ZONES:
        return {z: 0 for z, _, _ in HR_ZONES}
    times = [s["ts"] for s in samples]
    avg_dt = (times[-1] - times[0]).total_seconds() / max(1, len(samples) - 1)
    zones = {z: 0.0 for z, _, _ in HR_ZONES}
    for s in samples:
        hr = s.get("hr_bpm") or 0
        if hr <= 0:
            continue
        for name, lo, hi in HR_ZONES:
            if lo <= hr < hi:
                zones[name] += avg_dt
                break
    return {k: int(v) for k, v in zones.items()}


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


async def _fetch_samples_since(
    db: AsyncDatabase, since: datetime,
) -> list[dict[str, Any]]:
    cur = db["treadmill_samples"].find(
        {"source": SOURCE, "ts": {"$gte": since}}, sort=[("ts", 1)],
    )
    out = []
    async for d in cur:
        d["ts"] = _aware(d["ts"])
        out.append(d)
    return out


def _split_sessions(
    samples: Iterable[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group samples into sessions separated by SESSION_GAP_S gaps."""
    sessions: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    last_ts: datetime | None = None
    for s in samples:
        ts = s["ts"]
        if (
            last_ts is not None
            and (ts - last_ts).total_seconds() > SESSION_GAP_S
            and current
        ):
            sessions.append(current)
            current = []
        current.append(s)
        last_ts = ts
    if current:
        sessions.append(current)
    return sessions


async def get_active(db: AsyncDatabase) -> WorkoutSummary | None:
    """Return the in-progress treadmill session, or None if quiet.

    Also writes a finalized `workouts` doc for any completed session
    that hasn't been persisted yet.
    """
    now = datetime.now(UTC)
    # Pull last 6 hours of samples — generous bound for a single session.
    samples = await _fetch_samples_since(db, now - timedelta(hours=6))
    if not samples:
        return None

    sessions = _split_sessions(samples)
    most_recent = sessions[-1]
    last_ts: datetime = most_recent[-1]["ts"]
    is_active = (now - last_ts).total_seconds() <= SESSION_GAP_S

    # Finalize any earlier sessions that aren't already in workouts.
    for sess in sessions[:-1]:
        await _finalize_if_missing(db, sess)

    if is_active:
        return _aggregate(most_recent, status="active")

    # Most recent is finished too — finalize and return it once.
    return await _finalize_if_missing(db, most_recent)


def _is_real_workout(summary: WorkoutSummary) -> bool:
    """Filter out non-workouts: treadmill turned on but user never walked
    (firmware update, accidental power-on, brief test of the deck)."""
    return (
        summary.duration_s >= MIN_REAL_DURATION_S
        and summary.active_s >= MIN_REAL_ACTIVE_S
        and summary.distance_mi >= MIN_REAL_DISTANCE_MI
    )


async def _finalize_if_missing(
    db: AsyncDatabase, samples: list[dict[str, Any]],
) -> WorkoutSummary | None:
    summary = _aggregate(samples, status="complete")
    if summary is None:
        return None
    if not _is_real_workout(summary):
        # Non-workout: drop on the floor. Raw samples remain in the
        # time-series until TTL expires — useful for debugging if a
        # legitimate session got wrongly classified.
        return None
    doc = summary.to_doc()
    # Insert-if-missing keyed on source_id (started_at-derived).
    existing = await db["workouts"].find_one({"source_id": doc["source_id"]}, {"_id": 1})
    if existing:
        return summary
    await db["workouts"].insert_one(doc)
    return summary
