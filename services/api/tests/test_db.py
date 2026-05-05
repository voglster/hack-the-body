import pytest
from mongomock_motor import AsyncMongoMockClient

from app.db import TIMESERIES_COLLECTIONS, ensure_collections


async def test_ensure_collections_creates_timeseries(mock_db):
    await ensure_collections(mock_db)
    names = await mock_db.list_collection_names()
    for name in TIMESERIES_COLLECTIONS:
        assert name in names


@pytest.mark.asyncio
async def test_strength_sets_collection_and_indexes_created():
    client = AsyncMongoMockClient()
    db = client["htb_test"]
    await ensure_collections(db)
    assert "strength_sets" in await db.list_collection_names()
    indexes = await db["strength_sets"].index_information()
    # Composite child index for parent lookups
    assert any(
        spec["key"] == [("workout_source_id", 1), ("exercise_index", 1), ("set_index", 1)]
        for spec in indexes.values()
    )
    # Per-exercise time index for "all my pull-up sets" queries
    assert any(
        spec["key"] == [("exercise_template_id", 1), ("ts", -1)]
        for spec in indexes.values()
    )
