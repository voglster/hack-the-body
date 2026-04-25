

async def test_admin_trigger_requires_auth(client):
    r = await client.post("/admin/ingest/garmin")
    assert r.status_code == 401


async def test_admin_trigger_writes_log(client, mock_db):
    r = await client.post("/admin/ingest/garmin", headers={"X-API-Key": "test-key"})
    assert r.status_code == 202
    doc = await mock_db["ingestion_log"].find_one({"source": "garmin", "status": "requested"})
    assert doc is not None


async def test_admin_trigger_unknown_source(client):
    r = await client.post("/admin/ingest/unknown", headers={"X-API-Key": "test-key"})
    assert r.status_code == 404
