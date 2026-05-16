"""Audit log: diff flattening + record_change behavior."""
from __future__ import annotations

import pytest

from app.services.audit import diff, record_change


def test_diff_flat_scalar_change():
    d = diff({"a": 1, "b": 2}, {"a": 1, "b": 3})
    assert d["changes"] == {"b": {"from": 2, "to": 3}}
    assert d["changed_paths"] == ["b"]


def test_diff_dict_add_and_remove():
    d = diff({"a": 1, "gone": "x"}, {"a": 1, "added": 7})
    assert d["changes"]["added"] == {"from": None, "to": 7}
    assert d["changes"]["gone"] == {"from": "x", "to": None}
    assert sorted(d["changed_paths"]) == ["added", "gone"]


def test_diff_nested_list_index():
    before = {"items": [
        {"food_id": "a", "qty": 30},
        {"food_id": "b", "qty": 40},
    ]}
    after = {"items": [
        {"food_id": "a", "qty": 35},  # qty bumped
        {"food_id": "b", "qty": 40},
        {"food_id": "c", "qty": 10},  # new tail
    ]}
    d = diff(before, after)
    # Dotted indexing
    assert d["changes"]["items.0.qty"] == {"from": 30, "to": 35}
    # Appended row should appear with from=None, to=the-new-row
    assert d["changes"]["items.2"]["from"] is None
    assert d["changes"]["items.2"]["to"]["food_id"] == "c"
    assert d["changed_paths"] == ["items"]


def test_diff_create_op_before_is_none():
    d = diff(None, {"daily_calories": 2200})
    assert d["changes"]["daily_calories"] == {"from": None, "to": 2200}
    assert d["changed_paths"] == ["daily_calories"]


def test_diff_delete_op_after_is_none():
    d = diff({"daily_calories": 2200}, None)
    assert d["changes"]["daily_calories"] == {"from": 2200, "to": None}


def test_diff_no_change_is_empty():
    d = diff({"a": 1}, {"a": 1})
    assert d["changes"] == {}
    assert d["changed_paths"] == []


@pytest.mark.asyncio
async def test_record_change_persists(mock_db):
    await record_change(
        mock_db,
        entity="user_profile.targets", entity_id="targets",
        op="update",
        before={"daily_calories": 2000, "daily_protein_g": 180},
        after={"daily_calories": 2200, "daily_protein_g": 180},
        actor="user",
    )
    rows = [r async for r in mock_db["audit_log"].find()]
    assert len(rows) == 1
    row = rows[0]
    assert row["entity"] == "user_profile.targets"
    assert row["op"] == "update"
    assert row["actor"] == "user"
    assert row["changes"] == {"daily_calories": {"from": 2000, "to": 2200}}
    assert row["changed_paths"] == ["daily_calories"]
    assert row["before"]["daily_calories"] == 2000
    assert row["after"]["daily_calories"] == 2200


HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_put_targets_records_audit(client, mock_db):
    """End-to-end: PUT /profile/targets writes an audit_log row with the
    before/after snapshots and the flattened changes dict."""
    await client.put("/profile/targets", headers=HEADERS,
                     json={"daily_calories": 2200})
    await client.put("/profile/targets", headers=HEADERS,
                     json={"daily_calories": 2300})
    rows = [r async for r in mock_db["audit_log"].find(
        {"entity": "user_profile.targets"},
    ).sort("ts", 1)]
    assert len(rows) == 2
    # Second row: before=2200, after=2300
    assert rows[1]["before"]["daily_calories"] == 2200
    assert rows[1]["after"]["daily_calories"] == 2300
    assert rows[1]["changes"]["daily_calories"] == {"from": 2200, "to": 2300}
    assert "daily_calories" in rows[1]["changed_paths"]


@pytest.mark.asyncio
async def test_meal_template_create_and_delete_records_audit(client, mock_db):
    # Need a food first
    food = await client.post("/foods", headers=HEADERS, json={
        "name": "Test Food", "serving_g": 100,
        "per_serving": {"calories": 100},
    })
    food_id = food.json()["id"]
    created = await client.post("/meals/templates", headers=HEADERS, json={
        "name": "Test Usual", "default_slot": "snack",
        "items": [{"food_id": food_id, "quantity_g": 50}],
    })
    tpl_id = created.json()["id"]
    r = await client.delete(f"/meals/templates/{tpl_id}", headers=HEADERS)
    assert r.status_code == 204
    rows = [r async for r in mock_db["audit_log"].find(
        {"entity": "meal_template"},
    ).sort("ts", 1)]
    ops = [r["op"] for r in rows]
    assert ops == ["create", "delete"]
    assert rows[1]["before"]["name"] == "Test Usual"
    assert rows[1]["after"] is None


@pytest.mark.asyncio
async def test_audit_endpoint_filters(client, mock_db):
    # Seed two unrelated entities + actors
    from datetime import datetime, UTC
    await mock_db["audit_log"].insert_many([
        {"ts": datetime.now(UTC), "entity": "user_profile.targets",
         "entity_id": "targets", "op": "update",
         "actor": "user", "actor_ref": None,
         "before": {"a": 1}, "after": {"a": 2},
         "changes": {"a": {"from": 1, "to": 2}}, "changed_paths": ["a"]},
        {"ts": datetime.now(UTC), "entity": "user_profile.targets",
         "entity_id": "targets", "op": "update",
         "actor": "coach", "actor_ref": "t-99",
         "before": {"b": 5}, "after": {"b": 6},
         "changes": {"b": {"from": 5, "to": 6}}, "changed_paths": ["b"]},
        {"ts": datetime.now(UTC), "entity": "meal_template",
         "entity_id": "x", "op": "create",
         "actor": "user", "actor_ref": None,
         "before": None, "after": {"name": "x"},
         "changes": {"name": {"from": None, "to": "x"}},
         "changed_paths": ["name"]},
    ])
    r = await client.get("/audit/log?entity=user_profile.targets", headers=HEADERS)
    assert r.status_code == 200
    assert all(d["entity"] == "user_profile.targets" for d in r.json())

    r = await client.get(
        "/audit/log?entity=user_profile.targets&changed_path=a",
        headers=HEADERS,
    )
    assert len(r.json()) == 1
    assert r.json()[0]["changed_paths"] == ["a"]

    r = await client.get("/audit/log?actor=coach", headers=HEADERS)
    assert len(r.json()) == 1
    assert r.json()[0]["actor"] == "coach"


@pytest.mark.asyncio
async def test_record_change_failure_is_swallowed(mock_db, caplog):
    """Audit must never block the caller — even if the insert blows up,
    record_change returns cleanly."""
    class Broken:
        def __getitem__(self, key):
            class Coll:
                async def insert_one(self, *a, **kw):  # noqa: ARG002
                    raise RuntimeError("mongo down")
            return Coll()
    await record_change(
        Broken(), entity="x", entity_id="y", op="update",
        before={"a": 1}, after={"a": 2},
    )
    # No exception. Warning logged.
    assert any("audit.record_change failed" in m for m in caplog.messages)
