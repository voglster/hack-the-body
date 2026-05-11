"""Habits router integration tests."""

HEADERS = {"X-API-Key": "test-key"}


async def test_create_and_list_habits(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "brush teeth", "kind": "manual",
    })
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    assert hid

    r = await client.get("/habits", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert any(h["name"] == "brush teeth" for h in rows)


async def test_create_auto_habit_requires_resolver(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "bed by 10", "kind": "auto",
    })
    assert r.status_code == 400


async def test_create_auto_habit_with_unknown_resolver_rejected(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "weird", "kind": "auto", "resolver": "nope",
    })
    assert r.status_code == 400


async def test_patch_habit_can_deactivate(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "old habit", "kind": "manual",
    })
    hid = r.json()["id"]
    r = await client.patch(
        f"/habits/{hid}", headers=HEADERS, json={"active": False},
    )
    assert r.status_code == 200
    assert r.json()["active"] is False


async def test_today_returns_active_habits_with_status(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    await client.post("/habits", headers=HEADERS, json={
        "name": "make the bed", "kind": "manual",
    })
    r = await client.get("/habits/today", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert any(h["name"] == "make the bed" for h in rows)
    bed = next(h for h in rows if h["name"] == "make the bed")
    assert bed["status"] == "unknown"
    assert bed["kind"] == "manual"


async def test_status_post_marks_manual_done(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "make the bed", "kind": "manual",
    })
    hid = r.json()["id"]
    r = await client.post(
        f"/habits/{hid}/status", headers=HEADERS,
        json={"status": "done"},
    )
    assert r.status_code == 200, r.text
    r = await client.get("/habits/today", headers=HEADERS)
    bed = next(h for h in r.json() if h["name"] == "make the bed")
    assert bed["status"] == "done"
    assert bed["source"] == "manual"


async def test_status_400_on_bad_status_value(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "x", "kind": "manual",
    })
    hid = r.json()["id"]
    r = await client.post(
        f"/habits/{hid}/status", headers=HEADERS,
        json={"status": "bogus"},
    )
    assert r.status_code == 422  # FastAPI validation
