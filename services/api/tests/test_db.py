from app.db import ensure_collections, TIMESERIES_COLLECTIONS


async def test_ensure_collections_creates_timeseries(mock_db):
    await ensure_collections(mock_db)
    names = await mock_db.list_collection_names()
    for name in TIMESERIES_COLLECTIONS:
        assert name in names
