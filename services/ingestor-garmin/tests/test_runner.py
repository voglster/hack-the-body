import json
from datetime import date  # noqa: F401  (Protocol-required arg type)
from pathlib import Path

from app.repo import GarminRepo
from app.runner import _no_jitter, run_sync

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    with (FIXTURES / name).open() as f:
        return json.load(f)


class FakeClient:
    def login(self) -> None: ...
    def fetch_sleep(self, _d) -> dict: return _load("sleep.json")
    def fetch_hrv(self, _d) -> dict: return _load("hrv.json")
    def fetch_weight(self, _s, _e) -> list[dict]: return _load("weight.json")
    def fetch_body_comp(self, _s, _e) -> list[dict]: return _load("body_comp.json")
    def fetch_vo2max(self, _d) -> dict: return _load("vo2max.json")
    def fetch_workouts(self, _s, _e) -> list[dict]: return _load("workout.json")
    def fetch_rhr_series(self, _s, _e) -> list[dict]: return []
    def fetch_daily_summary(self, _d) -> dict: return _load("daily_summary.json")


async def test_run_sync_writes_all_metrics(mock_db):
    repo = GarminRepo(mock_db)
    client = FakeClient()
    counts = await run_sync(
        client=client, repo=repo, backfill_days=1, jitter=_no_jitter,
    )
    assert counts["weight"] == 1
    assert counts["body_comp"] == 1
    assert counts["sleep"] == 1
    assert counts["hrv"] == 1
    assert counts["vo2max"] == 1
    assert counts["daily_summary"] == 1
    assert counts["workouts"] == 1

    assert await mock_db["metrics_weight"].count_documents({}) == 1
    assert await mock_db["metrics_daily_summary"].count_documents({}) == 1
    assert await mock_db["workouts"].count_documents({}) == 1


async def test_run_sync_idempotent(mock_db):
    repo = GarminRepo(mock_db)
    client = FakeClient()
    await run_sync(client=client, repo=repo, backfill_days=1, jitter=_no_jitter)
    await run_sync(client=client, repo=repo, backfill_days=1, jitter=_no_jitter)
    assert await mock_db["metrics_weight"].count_documents({}) == 1
    assert await mock_db["workouts"].count_documents({}) == 1
