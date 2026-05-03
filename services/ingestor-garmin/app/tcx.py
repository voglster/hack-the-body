"""TCX (Training Center XML) writer for treadmill workouts.

Garmin Connect accepts TCX uploads for activities. We render the
finalized `workouts` doc (status: complete, source: precor-csafe)
plus its raw samples as a single-lap TCX activity. Trackpoints
carry time / distance / heart-rate / speed.

Format reference: Garmin TCX schema v2 + ActivityExtension v2.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
EXT_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

register_namespace("", TCX_NS)
register_namespace("ext", EXT_NS)

MI_PER_COUNT = 0.001
M_PER_MI = 1609.344
M_PER_S_PER_MPH = 0.44704


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _trackpoint(
    parent: Element,
    ts: datetime,
    *,
    distance_m: float,
    speed_mps: float | None,
    hr_bpm: int | None,
) -> None:
    tp = SubElement(parent, f"{{{TCX_NS}}}Trackpoint")
    SubElement(tp, f"{{{TCX_NS}}}Time").text = _iso(ts)
    SubElement(tp, f"{{{TCX_NS}}}DistanceMeters").text = f"{distance_m:.2f}"
    if hr_bpm is not None and hr_bpm > 0:
        hr = SubElement(tp, f"{{{TCX_NS}}}HeartRateBpm")
        SubElement(hr, f"{{{TCX_NS}}}Value").text = str(int(hr_bpm))
    if speed_mps is not None:
        ext = SubElement(tp, f"{{{TCX_NS}}}Extensions")
        tpx = SubElement(ext, f"{{{EXT_NS}}}TPX")
        SubElement(tpx, f"{{{EXT_NS}}}Speed").text = f"{speed_mps:.3f}"


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _build_lap(parent: Element, workout: dict[str, Any], started: datetime) -> Element:
    duration_s = int(workout.get("duration_s", 0))
    distance_mi = float(workout.get("distance_mi", 0.0))
    calories = int(workout.get("calories") or 0)
    avg_hr = workout.get("avg_hr")
    max_hr = workout.get("max_hr")

    lap = SubElement(parent, f"{{{TCX_NS}}}Lap",
                     attrib={"StartTime": _iso(started)})
    SubElement(lap, f"{{{TCX_NS}}}TotalTimeSeconds").text = f"{duration_s:.1f}"
    SubElement(lap, f"{{{TCX_NS}}}DistanceMeters").text = (
        f"{distance_mi * M_PER_MI:.2f}"
    )
    SubElement(lap, f"{{{TCX_NS}}}MaximumSpeed").text = (
        f"{(workout.get('max_speed_mph') or 0.0) * M_PER_S_PER_MPH:.3f}"
    )
    SubElement(lap, f"{{{TCX_NS}}}Calories").text = str(calories)
    if avg_hr:
        h = SubElement(lap, f"{{{TCX_NS}}}AverageHeartRateBpm")
        SubElement(h, f"{{{TCX_NS}}}Value").text = str(int(avg_hr))
    if max_hr:
        h = SubElement(lap, f"{{{TCX_NS}}}MaximumHeartRateBpm")
        SubElement(h, f"{{{TCX_NS}}}Value").text = str(int(max_hr))
    SubElement(lap, f"{{{TCX_NS}}}Intensity").text = "Active"
    SubElement(lap, f"{{{TCX_NS}}}TriggerMethod").text = "Manual"
    return lap


def _emit_trackpoints_from_samples(
    track: Element, samples: list[dict[str, Any]],
) -> None:
    sorted_samples = sorted(samples, key=lambda d: d["ts"])
    first_raw = next(
        (s.get("distance_raw") for s in sorted_samples
         if s.get("distance_raw") is not None),
        None,
    )
    for s in sorted_samples:
        ts = _aware(s["ts"])
        raw = s.get("distance_raw")
        if raw is not None and first_raw is not None:
            delta = raw - first_raw
            if delta < 0:
                delta += 65536
            dist_m = delta * MI_PER_COUNT * M_PER_MI
        else:
            dist_m = 0.0
        speed_mph = s.get("speed_mph")
        speed_mps = speed_mph * M_PER_S_PER_MPH if speed_mph is not None else None
        _trackpoint(track, ts, distance_m=dist_m,
                    speed_mps=speed_mps, hr_bpm=s.get("hr_bpm"))


def _emit_synthetic_trackpoints(
    track: Element, workout: dict[str, Any], started: datetime,
) -> None:
    duration_s = int(workout.get("duration_s", 0))
    distance_mi = float(workout.get("distance_mi", 0.0))
    avg_hr = workout.get("avg_hr")
    _trackpoint(track, started, distance_m=0.0, speed_mps=0.0, hr_bpm=None)
    _trackpoint(
        track, started + timedelta(seconds=duration_s),
        distance_m=distance_mi * M_PER_MI,
        speed_mps=(distance_mi * M_PER_MI / duration_s) if duration_s else 0.0,
        hr_bpm=avg_hr,
    )


def _append_creator(activity: Element) -> None:
    creator = SubElement(activity, f"{{{TCX_NS}}}Creator",
                         attrib={f"{{{XSI_NS}}}type": "Device_t"})
    SubElement(creator, f"{{{TCX_NS}}}Name").text = "Hack the Body Treadmill Bridge"
    SubElement(creator, f"{{{TCX_NS}}}UnitId").text = "0"
    SubElement(creator, f"{{{TCX_NS}}}ProductID").text = "0"
    version = SubElement(creator, f"{{{TCX_NS}}}Version")
    SubElement(version, f"{{{TCX_NS}}}VersionMajor").text = "1"
    SubElement(version, f"{{{TCX_NS}}}VersionMinor").text = "0"


def build_tcx(workout: dict[str, Any], samples: list[dict[str, Any]]) -> bytes:
    """Render the workout as a TCX XML byte string suitable for upload."""
    started = _aware(workout["started_at"])

    root = Element(
        f"{{{TCX_NS}}}TrainingCenterDatabase",
        attrib={f"{{{XSI_NS}}}schemaLocation": (
            "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 "
            "http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd"
        )},
    )
    activities = SubElement(root, f"{{{TCX_NS}}}Activities")
    # TCX v2 only supports Running/Biking/Other. These are walking workouts,
    # so "Other" is the honest choice — we fix the real Garmin activity type
    # via set_activity_type() right after upload.
    activity = SubElement(activities, f"{{{TCX_NS}}}Activity",
                          attrib={"Sport": "Other"})
    SubElement(activity, f"{{{TCX_NS}}}Id").text = _iso(started)

    lap = _build_lap(activity, workout, started)
    track = SubElement(lap, f"{{{TCX_NS}}}Track")
    if samples:
        _emit_trackpoints_from_samples(track, samples)
    else:
        _emit_synthetic_trackpoints(track, workout, started)

    _append_creator(activity)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root)
