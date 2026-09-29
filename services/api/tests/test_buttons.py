from app.config import Settings
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
    assert (await _press(client, "up"))["say"] == "Water. 32 ounces today."


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


async def test_usual_button_logs_every_item_and_undoes_together(client, mock_db):
    await _seed(client, mock_db)
    yogurt = (
        await client.post(
            "/foods",
            headers=H,
            json={
                "name": "Greek yogurt",
                "serving_g": 170,
                "per_serving": {"calories": 100, "protein_g": 18},
            },
        )
    ).json()
    chia = (
        await client.post(
            "/foods",
            headers=H,
            json={"name": "Chia", "serving_g": 10, "per_serving": {"calories": 53, "protein_g": 2}},
        )
    ).json()
    tpl = (
        await client.post(
            "/meals/templates",
            headers=H,
            json={
                "name": "Breakfast Yogurt",
                "items": [
                    {"food_id": yogurt["id"], "quantity_g": 170},
                    {"food_id": chia["id"], "quantity_g": 10},
                ],
            },
        )
    ).json()
    await client.put(
        "/capture/buttons/habit_remote_2/left",
        headers=H,
        json={"action": "usual", "label": "Yogurt bowl", "template_id": tpl["id"]},
    )
    r = await client.post("/capture/button", headers=H, json={"button": "habit_remote_2/left"})
    assert r.json()["say"] == "Yogurt bowl logged."
    assert (await client.get("/capture/today", headers=H)).json()["totals"]["calories"] == 153
    await client.put(
        "/capture/buttons/habit_remote_2/down", headers=H, json={"action": "undo", "label": "Undo"}
    )
    await client.post("/capture/button", headers=H, json={"button": "habit_remote_2/down"})
    assert (await client.get("/capture/today", headers=H)).json()["totals"]["calories"] == 0


def test_both_remotes_are_bridged_by_default():
    names = Settings().ha_remote_names
    assert names["00:0b:57:ff:fe:98:2b:ea"] == "habit_remote_2"
    assert names["d0:cf:5e:ff:fe:23:62:6c"] == REMOTE
