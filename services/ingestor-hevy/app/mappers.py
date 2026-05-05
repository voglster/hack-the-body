from datetime import datetime
from typing import Any

from app.models import StrengthSet, Workout


def _parse_iso(s: str) -> datetime:
    # Hevy mixes "+00:00" and trailing "Z". fromisoformat handles "+00:00";
    # normalize "Z" first.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _none_if_blank(s: str | None) -> str | None:
    if s is None or s == "":
        return None
    return s


def map_workout(raw: dict[str, Any]) -> Workout:
    start = _parse_iso(raw["start_time"])
    end = _parse_iso(raw["end_time"])
    duration_s = int((end - start).total_seconds())
    exercises = raw.get("exercises") or []
    set_count = sum(len(ex.get("sets") or []) for ex in exercises)
    return Workout(
        ts=start,
        activity_type="strength",
        duration_s=duration_s,
        title=_none_if_blank(raw.get("title")),
        exercise_count=len(exercises),
        set_count=set_count,
        updated_at=_parse_iso(raw["updated_at"]),
        raw=raw,
        source="hevy",
        source_id=f"hevy:{raw['id']}",
    )


def map_strength_sets(raw: dict[str, Any]) -> list[StrengthSet]:
    workout_source_id = f"hevy:{raw['id']}"
    ts = _parse_iso(raw["start_time"])
    out: list[StrengthSet] = []
    for ex in raw.get("exercises") or []:
        ex_index = ex["index"]
        ex_title = ex["title"]
        ex_tpl = ex.get("exercise_template_id")
        ex_notes = _none_if_blank(ex.get("notes"))
        superset_id = ex.get("superset_id")
        out.extend(
            StrengthSet(
                workout_source_id=workout_source_id,
                ts=ts,
                exercise_index=ex_index,
                exercise_title=ex_title,
                exercise_template_id=ex_tpl,
                set_index=s["index"],
                set_type=s.get("type") or "normal",
                reps=s.get("reps"),
                weight_kg=s.get("weight_kg"),
                distance_m=s.get("distance_meters"),
                duration_s=s.get("duration_seconds"),
                rpe=s.get("rpe"),
                superset_id=superset_id,
                notes=ex_notes,
            )
            for s in ex.get("sets") or []
        )
    return out
