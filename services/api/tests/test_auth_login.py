"""Tests for the public /auth/verify endpoint."""


async def test_verify_accepts_correct_password(client):
    r = await client.post("/auth/verify", json={"password": "test-key"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_verify_rejects_wrong_password(client):
    r = await client.post("/auth/verify", json={"password": "nope"})
    assert r.status_code == 401


async def test_verify_rejects_empty_body(client):
    r = await client.post("/auth/verify", json={"password": ""})
    assert r.status_code == 422  # pydantic validation


async def test_verify_does_not_require_api_key(client):
    """The login endpoint is intentionally public."""
    r = await client.post("/auth/verify", json={"password": "test-key"})
    assert r.status_code == 200, "no X-API-Key header should be needed"
