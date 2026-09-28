from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.routers import capture as router_mod
from app.services import capture as svc
from app.services.food_parser import ParsedItem

H = {"X-API-Key": "test-key"}


async def _food(client, name, serving_g=100.0, calories=100.0, brand=None, category="food"):
    r = await client.post(
        "/foods",
        headers=H,
        json={
            "name": name,
            "brand": brand,
            "serving_g": serving_g,
            "category": category,
            "per_serving": {"calories": calories, "protein_g": 10},
        },
    )
    return r.json()


@pytest.fixture
def parsed(monkeypatch):
    box: dict = {"items": [], "error": None, "calls": 0}

    async def fake(_settings, _text):
        box["calls"] += 1
        if box["error"]:
            raise box["error"]
        return box["items"]

    monkeypatch.setattr(svc, "parse_food_text", fake)
    return box


async def test_tap_capture_logs_immediately(client):
    shake = await _food(
        client, "Vanilla Premier Protein Shake", 325.0, 160, brand="premier protein"
    )
    r = await client.post("/capture", headers=H, json={"food_id": shake["id"]})
    assert r.status_code == 201
    cap = r.json()
    assert cap["status"] == "resolved"
    assert len(cap["entry_ids"]) == 1
    today = (await client.get("/capture/today", headers=H)).json()
    assert today["totals"]["calories"] == 160


async def test_text_matches_catalog_and_repeat_skips_llm(client, parsed):
    shake = await _food(
        client, "Vanilla Premier Protein Shake", 325.0, 160, brand="premier protein"
    )
    await _food(client, "KIRKLAND Signature ALBACORE SOLID WHITE TUNA IN WATER", 153, 200)
    parsed["items"] = [ParsedItem(name="premier vanilla")]
    cap = (await client.post("/capture", headers=H, json={"text": "premier vanilla"})).json()
    stored = (await client.get("/capture/today", headers=H)).json()["captures"][0]
    assert stored["id"] == cap["id"]
    assert stored["status"] == "resolved"
    assert stored["entries"][0]["food_id"] == shake["id"]

    parsed["items"] = [ParsedItem(name="premier vanilla")]
    calls = parsed["calls"]
    await client.post("/capture", headers=H, json={"text": "Premier vanilla"})
    today = (await client.get("/capture/today", headers=H)).json()
    assert parsed["calls"] == calls
    assert all(c["status"] == "resolved" for c in today["captures"])
    assert today["totals"]["calories"] == 320


async def test_whole_text_phrase_skips_llm(client, parsed, mock_db):
    shake = await _food(client, "Vanilla Premier Protein Shake", 325.0, 160)
    await svc.learn_phrase(mock_db, "my shake", [{"food_id": shake["id"], "quantity_g": 325.0}])
    await client.post("/capture", headers=H, json={"text": "My shake"})
    assert parsed["calls"] == 0
    today = (await client.get("/capture/today", headers=H)).json()
    assert today["captures"][0]["status"] == "resolved"


async def test_explicit_quantity_in_text(client, parsed):
    water = await _food(client, "Water", 236.588, 0, category="drink")
    parsed["items"] = [ParsedItem(name="10 oz water")]
    await client.post("/capture", headers=H, json={"text": "10 ounces of water"})
    entry = (await client.get("/capture/today", headers=H)).json()["captures"][0]["entries"][0]
    assert entry["food_id"] == water["id"]
    assert entry["quantity_g"] == pytest.approx(295.7, abs=0.1)


async def test_no_match_logs_estimate_without_asking(client, parsed):
    await _food(client, "Water", 236.588, 0, category="drink")
    parsed["items"] = [ParsedItem(name="Brewery burger and fries", calories=1100)]
    await client.post("/capture", headers=H, json={"text": "burger and fries at the brewery"})
    today = (await client.get("/capture/today", headers=H)).json()
    assert today["captures"][0]["status"] == "resolved"
    assert today["totals"]["calories"] == 1100


async def test_plausible_match_asks_then_confirm_teaches(client, parsed):
    a = await _food(client, "Chocolate Premier Protein Shake", 325, 160)
    await _food(client, "Vanilla Premier Protein Shake", 325, 160)
    parsed["items"] = [ParsedItem(name="premier shake")]
    cap = (await client.post("/capture", headers=H, json={"text": "premier shake"})).json()
    inbox = (await client.get("/capture/inbox", headers=H)).json()
    assert [c["id"] for c in inbox] == [cap["id"]]
    item = inbox[0]["items"][0]
    idx = next(i for i, c in enumerate(item["candidates"]) if c["food_id"] == a["id"])
    r = await client.post(
        f"/capture/{cap['id']}/confirm", headers=H, json={"item_index": 0, "candidate_index": idx}
    )
    assert r.json()["status"] == "resolved"
    assert (await client.get("/capture/inbox", headers=H)).json() == []

    parsed["items"] = [ParsedItem(name="premier shake")]
    await client.post("/capture", headers=H, json={"text": "premier shake"})
    latest = (await client.get("/capture/today", headers=H)).json()["captures"][0]
    assert latest["status"] == "resolved"
    assert latest["entries"][0]["food_id"] == a["id"]


async def test_llm_failure_keeps_capture_pending_then_sweep_resolves(
    client, parsed, settings, mock_db
):
    shake = await _food(client, "Vanilla Premier Protein Shake", 325, 160)
    parsed["error"] = RuntimeError("llm down")
    cap = (await client.post("/capture", headers=H, json={"text": "vanilla premier shake"})).json()
    assert (await svc.get_capture(mock_db, cap["id"]))["status"] == "pending"
    parsed["error"] = None
    parsed["items"] = [ParsedItem(name="vanilla premier shake")]
    await svc.sweep_pending(settings, mock_db)
    stored = await svc.get_capture(mock_db, cap["id"])
    assert stored["status"] == "resolved"
    entries = (await client.get("/capture/today", headers=H)).json()["captures"][0]["entries"]
    assert entries[0]["food_id"] == shake["id"]


async def test_undo_removes_entries(client):
    shake = await _food(client, "Vanilla Premier Protein Shake", 325, 160)
    cap = (await client.post("/capture", headers=H, json={"food_id": shake["id"]})).json()
    assert (await client.delete(f"/capture/{cap['id']}", headers=H)).status_code == 204
    today = (await client.get("/capture/today", headers=H)).json()
    assert today["captures"] == []
    assert today["totals"]["calories"] == 0


async def test_placeholder_then_fill_with_text(client, parsed):
    shake = await _food(client, "Vanilla Premier Protein Shake", 325, 160)
    cap = (await client.post("/capture", headers=H, json={"placeholder": True})).json()
    assert cap["status"] == "placeholder"
    assert (await client.get("/capture/today", headers=H)).json()["unresolved"] == 1
    parsed["items"] = [ParsedItem(name="vanilla premier shake")]
    await client.post(
        f"/capture/{cap['id']}/confirm", headers=H, json={"text": "vanilla premier shake"}
    )
    today = (await client.get("/capture/today", headers=H)).json()
    assert today["unresolved"] == 0
    assert today["captures"][0]["entries"][0]["food_id"] == shake["id"]


async def test_template_capture(client):
    a = await _food(client, "Greek yogurt", 170, 100)
    b = await _food(client, "Granola", 30, 160)
    tpl = (
        await client.post(
            "/meals/templates",
            headers=H,
            json={
                "name": "Breakfast Yogurt",
                "items": [
                    {"food_id": a["id"], "quantity_g": 170},
                    {"food_id": b["id"], "quantity_g": 30},
                ],
            },
        )
    ).json()
    cap = (await client.post("/capture", headers=H, json={"template_id": tpl["id"]})).json()
    assert len(cap["entry_ids"]) == 2


def test_suggestions_favor_recent_same_time_of_day():
    tz = ZoneInfo("UTC")
    now = datetime(2026, 9, 28, 8, 0, tzinfo=tz)

    def e(fid, days_ago, hour):
        ts = (now - timedelta(days=days_ago)).replace(hour=hour)
        return {"ts": ts.astimezone(UTC), "food_id": fid, "food_name": fid}

    entries = (
        [e("shake", d, 8) for d in range(1, 6)]
        + [e("dinner", d, 19) for d in range(1, 8)]
        + [e("old", 50, 8) for _ in range(5)]
        + [e("water", 1, 8) for _ in range(10)]
    )
    ranked = [k for k, _ in svc.score_suggestions(entries, now, tz)]
    assert ranked[0] == "food:shake"
    assert "food:water" not in ranked
    assert ranked.index("food:dinner") > ranked.index("food:old") or ranked[1] == "food:dinner"


def test_infer_slot(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    at = lambda h, m=0: datetime(2026, 9, 28, h, m, tzinfo=UTC)  # noqa: E731
    assert svc.infer_slot(at(8)) == "breakfast"
    assert svc.infer_slot(at(12)) == "lunch"
    assert svc.infer_slot(at(15)) == "snack"
    assert svc.infer_slot(at(18)) == "dinner"
    assert svc.infer_slot(at(8), "supplement") == "supplement"


async def test_voice_capture_transcribes_then_resolves(client, parsed, monkeypatch):
    shake = await _food(client, "Vanilla Premier Protein Shake", 325, 160)

    class FakeTranscriber:
        async def transcribe(self, _pcm, _ctx):
            return "vanilla premier shake"

    monkeypatch.setattr(router_mod, "build_transcriber", lambda _s: FakeTranscriber())
    parsed["items"] = [ParsedItem(name="vanilla premier shake")]
    r = await client.post(
        "/capture/voice", headers=H, files={"audio": ("d.wav", b"\x00" * 64, "audio/wav")}
    )
    assert r.status_code == 201
    assert r.json()["input"]["text"] == "vanilla premier shake"
    entry = (await client.get("/capture/today", headers=H)).json()["captures"][0]["entries"][0]
    assert entry["food_id"] == shake["id"]


async def test_estimate_fills_missing_macros(client, parsed, monkeypatch):
    async def fake_estimate(_settings, item):
        return ParsedItem(name=item.name, servings=item.servings, calories=650, protein_g=30)

    monkeypatch.setattr(svc, "estimate_macros", fake_estimate)
    parsed["items"] = [ParsedItem(name="Brewery burger")]
    await client.post("/capture", headers=H, json={"text": "brewery burger"})
    assert (await client.get("/capture/today", headers=H)).json()["totals"]["calories"] == 650


async def test_macro_less_foods_are_not_match_targets(client, parsed, monkeypatch):
    await client.post("/foods", headers=H, json={"name": "Burger", "per_serving": {}})

    async def fake_estimate(_settings, item):
        return ParsedItem(name=item.name, calories=700)

    monkeypatch.setattr(svc, "estimate_macros", fake_estimate)
    parsed["items"] = [ParsedItem(name="Burger")]
    await client.post("/capture", headers=H, json={"text": "burger"})
    assert (await client.get("/capture/today", headers=H)).json()["totals"]["calories"] == 700


def test_window_state():
    tz = ZoneInfo("UTC")
    at = lambda h, m=0: datetime(2026, 9, 28, h, m, tzinfo=tz)  # noqa: E731
    assert svc.window_state(at(9, 40), "11:00", "19:00") == {
        "start": "11:00",
        "end": "19:00",
        "state": "before",
        "minutes_to_change": 80,
    }
    assert svc.window_state(at(15), "11:00", "19:00")["state"] == "open"
    after = svc.window_state(at(20), "11:00", "19:00")
    assert after["state"] == "after"
    assert after["minutes_to_change"] == 15 * 60


def test_first_meal_is_breakfast_even_late(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    ts = datetime(2026, 9, 28, 11, 30, tzinfo=UTC)
    assert svc.infer_slot(ts, first_meal=True) == "breakfast"
    assert svc.infer_slot(ts) == "lunch"


async def test_context_hides_eaten_food_and_shows_done_things(client, monkeypatch):
    monkeypatch.setattr(
        svc,
        "window_state",
        lambda *_a: {"state": "open", "start": "11:00", "end": "19:00", "minutes_to_change": 60},
    )
    yogurt = await _food(client, "Greek yogurt", 170, 100)
    salad = await _food(client, "Chicken salad", 300, 450)
    vit = await _food(client, "Vitamins", 1, 0, category="supplement")
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    for f in (yogurt, salad):
        await client.post(
            "/meals/entries", headers=H, json={"food_id": f["id"], "quantity_g": 100, "ts": old}
        )
    await client.post("/capture", headers=H, json={"food_id": yogurt["id"]})
    await client.post("/capture", headers=H, json={"food_id": vit["id"]})
    ctx = (await client.get("/capture/context", headers=H)).json()
    names = [s["name"] for s in ctx["suggestions"]]
    assert "Chicken salad" in names
    assert "Greek yogurt" not in names
    assert ctx["vitamins_done"] is True
    assert ctx["window"]["state"] == "open"


async def test_context_outside_window_offers_drinks_only(client, monkeypatch):
    monkeypatch.setattr(
        svc,
        "window_state",
        lambda *_a: {"state": "after", "start": "11:00", "end": "19:00", "minutes_to_change": 900},
    )
    salad = await _food(client, "Chicken salad", 300, 450)
    tea = await _food(client, "Green tea", 240, 0, category="drink")
    old = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    for f in (salad, tea):
        await client.post(
            "/meals/entries", headers=H, json={"food_id": f["id"], "quantity_g": 100, "ts": old}
        )
    names = [
        s["name"] for s in (await client.get("/capture/context", headers=H)).json()["suggestions"]
    ]
    assert names == ["Green tea"]
