from datetime import UTC, datetime

import pytest

from app.services.coach.brief import Insight, recent_insights, save_insight


@pytest.mark.asyncio
async def test_recent_insights_returns_acked_at(mock_db):
    insight = Insight(
        text="hello", model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={}, trigger="manual",
    )
    insight.id = await save_insight(mock_db, insight)
    rows = await recent_insights(mock_db, limit=5)
    assert "acked_at" in rows[0]
    assert rows[0]["acked_at"] is None
