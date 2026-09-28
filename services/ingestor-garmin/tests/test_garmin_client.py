from datetime import date

from app.config import Settings
from app.garmin_client import GarminClient


def _client_with_response(payload):
    c = GarminClient(Settings())
    c._connectapi = lambda _path, _params=None: payload  # type: ignore[assignment]
    return c


def test_fetch_weight_parses_daily_weight_summaries():
    payload = {
        "dailyWeightSummaries": [
            {
                "summaryDate": "2026-04-26",
                "allWeightMetrics": [
                    {"samplePk": 1, "date": 1777191794000, "weight": 114949.0,
                     "calendarDate": "2026-04-26", "sourceType": "INDEX_SCALE"},
                ],
            }
        ],
        "totalAverage": {},
    }
    out = _client_with_response(payload).fetch_weight(date(2026, 4, 1), date(2026, 4, 26))
    assert len(out) == 1
    assert out[0]["weight"] == 114949.0
    assert out[0]["samplePk"] == 1


def test_fetch_weight_dedupes_by_sample_pk_across_days():
    payload = {
        "dailyWeightSummaries": [
            {"allWeightMetrics": [{"samplePk": 7, "date": 1, "weight": 100.0}]},
            {"allWeightMetrics": [{"samplePk": 7, "date": 1, "weight": 100.0}]},
        ]
    }
    out = _client_with_response(payload).fetch_weight(date(2026, 4, 1), date(2026, 4, 2))
    assert len(out) == 1


def test_fetch_weight_falls_back_to_legacy_date_weight_list():
    payload = {"dateWeightList": [{"samplePk": 9, "date": 1, "weight": 50000.0}]}
    out = _client_with_response(payload).fetch_weight(date(2026, 4, 1), date(2026, 4, 2))
    assert len(out) == 1
    assert out[0]["samplePk"] == 9


def test_fetch_weight_handles_empty():
    out = _client_with_response({"dailyWeightSummaries": []}).fetch_weight(
        date(2026, 4, 1), date(2026, 4, 2)
    )
    assert out == []



class _StrictGarmin:
    """Mirrors garminconnect >= 0.3: a query string in the path is refused."""

    display_name = "3aefc992-71fe-461d-bf3e-2601982df048"

    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    def connectapi(self, path, params=None):
        if "?" in path:
            raise ValueError(f"Invalid API path: {path!r}")
        self.calls.append((path, params))
        return []


def test_every_fetch_sends_query_as_params():
    c = GarminClient.__new__(GarminClient)
    c._g = _StrictGarmin()
    d = date(2026, 9, 28)
    c.fetch_sleep(d)
    c.fetch_weight(d, d)
    c.fetch_vo2max(d)
    c.fetch_workouts(d, d)
    c.fetch_rhr_series(d, d)
    c.fetch_intraday_steps(d)
    c.fetch_daily_summary(d)
    assert len(c._g.calls) == 7
    assert c._g.calls[-1] == (
        "/usersummary-service/usersummary/daily/3aefc992-71fe-461d-bf3e-2601982df048",
        {"calendarDate": "2026-09-28"},
    )
