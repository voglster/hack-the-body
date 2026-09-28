from app.services import buttons
from app.services.ha_bridge import ButtonRouter

H = {"X-API-Key": "test-key"}
REMOTE = "habit_remote_1"


async def _seed(client, mock_db):
    shake = (
        await client.post(
            "/foods",
            headers=H,
            json={
                "name": "Vanilla Premier Protein Shake",
                "serving_g": 325.3085,
                "per_serving": {"calories": 160, "protein_g": 30},
            },
        )
    ).json()
    await buttons.ensure_default_buttons(mock_db)
    return shake


async def _press(client, name):
    r = await client.post("/capture/button", headers=H, json={"button": f"{REMOTE}/{name}"})
    assert r.status_code == 200
    return r.json()


async def test_shake_button_logs_and_speaks(client, mock_db):
    await _seed(client, mock_db)
    assert (await _press(client, "right"))["say"] == "Shake logged."
    today = (await client.get("/capture/today", headers=H)).json()
    assert today["totals"]["calories"] == 160


async def test_water_button_reports_running_total(client, mock_db):
    await _seed(client, mock_db)
    await _press(client, "up")
    assert (await _press(client, "up"))["say"] == "Water. 16 ounces today."


async def test_undo_removes_last_button_capture(client, mock_db):
    await _seed(client, mock_db)
    await _press(client, "right")
    assert (await _press(client, "down"))["say"] == "Undid Shake."
    assert (await client.get("/capture/today", headers=H)).json()["totals"]["calories"] == 0
    assert (await _press(client, "down"))["say"] == "Nothing to undo."


async def test_placeholder_button_lands_in_inbox(client, mock_db):
    await _seed(client, mock_db)
    await _press(client, "left")
    inbox = (await client.get("/capture/inbox", headers=H)).json()
    assert [c["status"] for c in inbox] == ["placeholder"]


async def test_center_marks_vitamins_habit(client, mock_db):
    await _seed(client, mock_db)
    assert (await _press(client, "center"))["say"] == "Vitamins done."
    habits = (await client.get("/habits/today", headers=H)).json()
    assert any(h["name"] == "Vitamins" and h["status"] == "done" for h in habits)


async def test_unmapped_button_says_so(client, mock_db):
    await _seed(client, mock_db)
    r = await client.post("/capture/button", headers=H, json={"button": "other_remote/up"})
    assert r.json()["say"] == "That button isn't set up."


async def test_remap_button(client, mock_db):
    await _seed(client, mock_db)
    await client.put(
        f"/capture/buttons/{REMOTE}/up",
        headers=H,
        json={"action": "water", "label": "Big water", "oz": 16},
    )
    assert (await _press(client, "up"))["say"] == "Water. 16 ounces today."


def test_router_decodes_tradfri_and_debounces():
    router = ButtonRouter({"d0:cf:5e:ff:fe:23:62:6c": REMOTE})
    event = {"device_ieee": "D0:CF:5E:FF:FE:23:62:6C", "command": "press", "args": [256, 13, 0]}
    assert router.button_for(event, now=10.0) == f"{REMOTE}/right"
    assert router.button_for(event, now=10.4) is None
    assert router.button_for(event, now=11.5) == f"{REMOTE}/right"
    assert router.button_for({**event, "device_ieee": "aa"}, now=20.0) is None
