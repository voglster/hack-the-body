from datetime import date

from app.config import Settings
from app.garmin_client import GarminClient


def _client_with_response(payload):
    c = GarminClient(Settings())
    c._connectapi = lambda _path: payload  # type: ignore[assignment]
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
