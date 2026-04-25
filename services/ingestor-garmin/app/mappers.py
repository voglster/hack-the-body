from datetime import datetime, timezone

from app.models import BodyComp, DailySummary, HRV, Sleep, VO2Max, Weight, Workout


def _utc_from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _utc_from_str(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def map_sleep(raw: dict) -> Sleep:
    d = raw["dailySleepDTO"]
    score = (d.get("sleepScores") or {}).get("overall", {}).get("value")
    return Sleep(
        ts=_utc_from_ms(d["sleepEndTimestampGMT"]),
        duration_s=int(d["sleepTimeSeconds"]),
        deep_s=int(d["deepSleepSeconds"]),
        rem_s=int(d["remSleepSeconds"]),
        light_s=int(d["lightSleepSeconds"]),
        awake_s=int(d["awakeSleepSeconds"]),
        score=int(score) if score is not None else None,
        source="garmin",
        source_id=f"garmin:sleep:{d['calendarDate']}",
    )


def map_hrv(raw: dict) -> HRV:
    s = raw["hrvSummary"]
    return HRV(
        ts=datetime.strptime(s["calendarDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
        rmssd_ms=float(s["lastNightAvg"]),
        source="garmin",
        source_id=f"garmin:hrv:{s['calendarDate']}",
    )


def map_weight(raw: list[dict]) -> list[Weight]:
    out: list[Weight] = []
    for s in raw:
        out.append(Weight(
            ts=_utc_from_ms(s["date"]),
            kg=round(float(s["weight"]) / 1000.0, 3),
            source="garmin",
            source_id=f"garmin:weight:{s['samplePk']}",
        ))
    return out


def map_body_comp(raw: list[dict]) -> list[BodyComp]:
    out: list[BodyComp] = []
    for s in raw:
        out.append(BodyComp(
            ts=_utc_from_ms(s["date"]),
            weight_kg=round(float(s["weight"]) / 1000.0, 3),
            body_fat_pct=_f(s.get("bodyFat")),
            muscle_mass_kg=_g_to_kg(s.get("muscleMass")),
            body_water_pct=_f(s.get("bodyWater")),
            bone_mass_kg=_g_to_kg(s.get("boneMass")),
            source="garmin-scale",
            source_id=f"garmin:body_comp:{s['samplePk']}",
        ))
    return out


def map_vo2max(raw: dict) -> VO2Max:
    g = raw["generic"]
    return VO2Max(
        ts=datetime.strptime(g["calendarDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
        value=float(g["vo2MaxPreciseValue"]),
        source="garmin",
        source_id=f"garmin:vo2max:{g['calendarDate']}",
    )


def map_daily_summary(raw: dict) -> DailySummary:
    """Map Garmin's /usersummary-service/usersummary/daily response."""
    cal = raw.get("calendarDate") or raw["calendar_date"]
    return DailySummary(
        ts=datetime.strptime(cal, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        steps=int(raw.get("totalSteps") or 0),
        step_goal=_i(raw.get("dailyStepGoal")),
        distance_m=_f(raw.get("totalDistanceMeters")),
        active_kcal=_i(raw.get("activeKilocalories")),
        total_kcal=_i(raw.get("totalKilocalories")),
        resting_hr=_i(raw.get("restingHeartRate")),
        intensity_minutes=_i(_sum_optional(raw.get("moderateIntensityMinutes"),
                                            raw.get("vigorousIntensityMinutes"))),
        floors_climbed=_i(raw.get("floorsAscended") or raw.get("floorsClimbed")),
        raw=raw,
        source="garmin",
        source_id=f"garmin:daily_summary:{cal}",
    )


def _sum_optional(*vals) -> float | None:
    nums = [v for v in vals if v is not None]
    return sum(nums) if nums else None


def map_workout(raw: list[dict]) -> list[Workout]:
    out: list[Workout] = []
    for a in raw:
        out.append(Workout(
            ts=_utc_from_str(a["startTimeGMT"]),
            activity_type=a["activityType"]["typeKey"],
            duration_s=int(a["duration"]),
            distance_m=_f(a.get("distance")),
            avg_hr=_i(a.get("averageHR")),
            max_hr=_i(a.get("maxHR")),
            calories=_i(a.get("calories")),
            source="garmin",
            source_id=f"garmin:activity:{a['activityId']}",
        ))
    return out


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _i(v) -> int | None:
    return int(v) if v is not None else None


def _g_to_kg(v) -> float | None:
    return round(float(v) / 1000.0, 3) if v is not None else None
