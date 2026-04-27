"""User-set targets: storage, validation, defaults."""

HEADERS = {"X-API-Key": "test-key"}


async def test_get_targets_returns_nulls_when_unset(client):
    """Cold-start: every target is null. The coach treats null as
    'don't judge against this metric'."""
    r = await client.get("/profile/targets", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["daily_calories"] is None
    assert body["daily_protein_g"] is None
    assert body["step_goal_override"] is None


async def test_put_then_get_round_trip(client):
    r = await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 2200, "daily_protein_g": 180,
              "step_goal_override": 12000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["daily_calories"] == 2200
    assert body["daily_protein_g"] == 180
    assert body["step_goal_override"] == 12000
    assert body["updated_at"] is not None

    # GET sees the same values.
    r = await client.get("/profile/targets", headers=HEADERS)
    assert r.json()["daily_calories"] == 2200


async def test_partial_update_replaces_unset_fields_with_null(client):
    """PUT semantics: the body is the new full state. If a field is
    omitted from the JSON body, pydantic defaults it to None, which is
    'no target' — that's intentional so the user can clear a metric by
    leaving its input blank."""
    await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 2200, "daily_protein_g": 180},
    )
    # Now only set calories — protein_g should clear back to None.
    await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 2300},
    )
    r = await client.get("/profile/targets", headers=HEADERS)
    body = r.json()
    assert body["daily_calories"] == 2300
    assert body["daily_protein_g"] is None


async def test_put_rejects_out_of_range(client):
    r = await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 99999},  # > 10000 max
    )
    assert r.status_code == 422


async def test_targets_require_auth(client):
    r = await client.get("/profile/targets")
    assert r.status_code == 401
    r = await client.put("/profile/targets", json={"daily_calories": 2200})
    assert r.status_code == 401
