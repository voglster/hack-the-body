from datetime import UTC, datetime

from app.models.metrics import Weight
from app.services.metrics_repo import MetricsRepo


async def test_get_latest_weight_requires_auth(client):
    r = await client.get("/metrics/weight/latest")
    assert r.status_code == 401


async def test_get_latest_weight_returns_value(client, mock_db):
    repo = MetricsRepo(mock_db)
    await repo.insert_weight(
        Weight(ts=datetime.now(UTC), kg=108.9,
               source="garmin", source_id="w1")
    )
    r = await client.get("/metrics/weight/latest", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.json()["kg"] == 108.9


async def test_summary_returns_all_latest(client, mock_db):
    repo = MetricsRepo(mock_db)
    await repo.insert_weight(
        Weight(ts=datetime.now(UTC), kg=108.9,
               source="garmin", source_id="w1")
    )
    r = await client.get("/metrics/summary", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert "weight" in body
    assert body["weight"]["kg"] == 108.9


async def test_weight_projection_returns_fit(client, mock_db):
    """Seed enough synthetic data to make the decay fit, then check the route."""
    import math
    from datetime import timedelta
    from app.services.metrics_repo import MetricsRepo
    repo = MetricsRepo(mock_db)
    start = datetime.now(UTC) - timedelta(days=60)
    w0, w_inf, k = 115.0, 100.0, 0.10  # kg
    for i in range(60):
        t_weeks = i / 7
        kg = w_inf + (w0 - w_inf) * math.exp(-k * t_weeks)
        await repo.insert_weight(Weight(
            ts=start + timedelta(days=i), kg=kg,
            source="test", source_id=f"w{i}",
        ))
    r = await client.get(
        "/metrics/weight/projection?days=120&goal=230",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fit"] is not None
    assert body["fit"]["asymptote_lb"] == pytest_approx(
        100.0 * 2.2046226, abs=5.0,
    )
    assert body["fit"]["n_points"] == 60
    assert body["eta"] is not None
    assert body["eta"]["goal_lb"] == 230
    assert "date" in body["eta"]


async def test_weight_projection_returns_null_when_insufficient_data(client, mock_db):
    from datetime import timedelta
    from app.services.metrics_repo import MetricsRepo
    repo = MetricsRepo(mock_db)
    # Only 10 days — below MIN_DAYS_FOR_FIT
    for i in range(10):
        await repo.insert_weight(Weight(
            ts=datetime.now(UTC) - timedelta(days=i), kg=110.0 - i * 0.1,
            source="test", source_id=f"w{i}",
        ))
    r = await client.get(
        "/metrics/weight/projection",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fit"] is None
    assert body["reason"] == "insufficient_data"


def pytest_approx(*a, **kw):
    import pytest
    return pytest.approx(*a, **kw)
