from datetime import UTC, datetime

import pytest

from app.services.coach.brief import Insight, recent_insights, save_insight


@pytest.mark.asyncio
async def test_save_and_recent_round_trip_anchors(mock_db):
    insight = Insight(
        text="Lights out at {{lights_out}}.",
        model="m",
        eval_ms=0,
        total_ms=0,
        generated_at=datetime.now(UTC),
        context={},
        trigger="manual",
        anchors={"lights_out": "2026-05-19T22:00:00-05:00"},
    )
    insight.id = await save_insight(mock_db, insight)
    rows = await recent_insights(mock_db, limit=5)
    assert rows[0]["anchors"] == {"lights_out": "2026-05-19T22:00:00-05:00"}
