from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import nudges
from app.services.data_freshness import assess

TZ = ZoneInfo("America/Chicago")


def _at(h, m=0):
    return datetime(2026, 9, 28, h, m, tzinfo=TZ)


def test_unsynced_afternoon_is_stale():
    latest_bucket = _at(11, 30).astimezone(UTC)
    f = assess(latest_bucket, _at(13, 56))
    assert f["stale"] is True
    assert f["through_local"] == "11:45"
    assert "open the Garmin Connect app" in f["summary"]


def test_recent_sync_is_current():
    f = assess((_at(13, 15)).astimezone(UTC), _at(13, 56))
    assert f["stale"] is False


def test_overnight_gap_is_not_stale():
    f = assess((_at(0, 15) - timedelta(hours=2)).astimezone(UTC), _at(3, 0))
    assert f["stale"] is False


def test_no_data_while_awake_is_stale():
    assert assess(None, _at(12))["stale"] is True


def _ctx(**kw):
    base = nudges.NudgeContext(
        now_local=_at(15),
        targets={"step_goal_override": 12000},
        vitamins_count_today=1,
        water_oz_today=80,
        weight_logged_today=True,
        steps_today=2000,
        garmin=None,
    )
    return replace(base, **kw)


def test_stale_data_swaps_steps_nudge_for_sync_nudge():
    stale = {"stale": True, "through_local": "11:45"}
    fired = {n.id for n in nudges.evaluate_all(_ctx(garmin=stale), dismissed_ids=set())}
    assert "steps_below_pace" not in fired
    assert "garmin_stale" in fired


def test_fresh_low_steps_still_nudges():
    fresh = {"stale": False, "through_local": "14:45"}
    fired = {n.id for n in nudges.evaluate_all(_ctx(garmin=fresh), dismissed_ids=set())}
    assert "steps_below_pace" in fired
    assert "garmin_stale" not in fired
