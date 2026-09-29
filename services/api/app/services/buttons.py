"""Physical buttons (IKEA remotes via Home Assistant) → captures.

A press arrives as `<remote>/<button>` (e.g. `habit_remote_1/right`). The
mapping lives in `capture_buttons` so remapping never touches HA. Each press
returns a short line for the office speaker, because a button has no screen.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.services import capture as cap
from app.services.coach.habits import mark_status

BUTTONS = "capture_buttons"
UNDO_WINDOW = timedelta(minutes=15)
WATER_OZ_G = 29.5735

# ZHA commands from an IKEA TRADFRI 5-button remote, keyed (command, first arg).
TRADFRI_BUTTONS: dict[tuple[str, int | None], str] = {
    ("toggle", None): "center",
    ("step_with_on_off", 0): "up",
    ("step", 1): "down",
    ("press", 257): "left",
    ("press", 256): "right",
}

DEFAULT_REMOTE = "habit_remote_1"


def decode_tradfri(command: str, args: list[Any] | None) -> str | None:
    first = args[0] if args else None
    return TRADFRI_BUTTONS.get((command, first)) or TRADFRI_BUTTONS.get((command, None))


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("TZ") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


async def ensure_default_buttons(db: AsyncDatabase) -> None:
    """Seed the kitchen remote once; later edits are the user's."""
    if await db[BUTTONS].count_documents({}):
        return
    shake = await db["foods"].find_one({"name": "Vanilla Premier Protein Shake"})
    r = DEFAULT_REMOTE
    defaults = [
        {"button": f"{r}/center", "action": "habit", "habit": "Vitamins", "label": "Vitamins"},
        {"button": f"{r}/up", "action": "water", "oz": 16, "label": "Water"},
        {"button": f"{r}/left", "action": "placeholder", "label": "Ate something"},
        {"button": f"{r}/down", "action": "undo", "label": "Undo"},
    ]
    if shake:
        defaults.append(
            {
                "button": f"{r}/right",
                "action": "food",
                "food_id": str(shake["_id"]),
                "quantity_g": shake.get("serving_g", 325.3085),
                "label": "Shake",
            }
        )
    await db[BUTTONS].insert_many(defaults)


async def _water_food_id(db: AsyncDatabase) -> str:
    doc = await db["foods"].find_one({"name": "Water"})
    if doc:
        return str(doc["_id"])
    res = await db["foods"].insert_one(
        {
            "name": "Water",
            "category": "drink",
            "serving_g": 236.588,
            "serving_label": "1 cup",
            "per_serving": {},
            "micros": {},
            "source": "builtin",
            "created_at": datetime.now(UTC),
        }
    )
    return str(res.inserted_id)


async def _water_today_oz(db: AsyncDatabase) -> int:
    start = cap.local_day_start(datetime.now(UTC))
    total = 0.0
    async for e in db["meal_entries"].find({"ts": {"$gte": start}, "food_name": "Water"}):
        total += e.get("quantity_g") or 0
    return round(total / WATER_OZ_G)


async def _undo_last(db: AsyncDatabase) -> str:
    since = datetime.now(UTC) - UNDO_WINDOW
    last = await db[cap.CAPTURES].find_one(
        {"source": "button", "created_at": {"$gte": since}},
        sort=[("created_at", -1)],
    )
    if not last:
        return "Nothing to undo."
    await cap.undo_capture(db, str(last["_id"]))
    return f"Undid {last.get('label') or 'the last press'}."


async def _habit(db: AsyncDatabase, mapping: dict[str, Any], label: str) -> str:
    habit = await db["habits"].find_one({"name": mapping["habit"]})
    if not habit:
        return f"No habit called {mapping['habit']}."
    tz = _tz()
    await mark_status(
        db, str(habit["_id"]), datetime.now(tz).date(), status="done", source="manual", tz=tz
    )
    return f"{label} done."


async def _placeholder(db: AsyncDatabase, button: str, label: str) -> str:
    c = await cap.create_capture(
        db, source="button", device="ha", status="placeholder", payload={"button": button}
    )
    await cap.set_fields(db, c["id"], label=label)
    return "Got it. Tell me what it was later."


async def _log(db: AsyncDatabase, mapping: dict[str, Any], button: str, label: str) -> str:
    is_water = mapping["action"] == "water"
    if is_water:
        food_id, qty = await _water_food_id(db), mapping.get("oz", 16) * WATER_OZ_G
    else:
        food_id, qty = mapping["food_id"], mapping["quantity_g"]
    c = await cap.create_capture(
        db,
        source="button",
        device="ha",
        status="resolved",
        payload={"button": button, "food_id": food_id, "quantity_g": qty},
    )
    now = datetime.now(UTC)
    entry = await cap.log_food(db, food_id=food_id, quantity_g=qty, ts=now, capture_id=c["id"])
    await cap.set_fields(db, c["id"], entry_ids=[entry["id"]], resolved_at=now, label=label)
    if is_water:
        return f"Water. {await _water_today_oz(db)} ounces today."
    return f"{label} logged."


async def _log_usual(db: AsyncDatabase, mapping: dict[str, Any], button: str, label: str) -> str:
    tpl = await db["meal_templates"].find_one({"_id": ObjectId(mapping["template_id"])})
    if not tpl:
        return f"{label} isn't a saved usual any more."
    c = await cap.create_capture(
        db,
        source="button",
        device="ha",
        status="resolved",
        payload={"button": button, "template_id": mapping["template_id"]},
    )
    now = datetime.now(UTC)
    ids = [
        (
            await cap.log_food(
                db,
                food_id=i["food_id"],
                quantity_g=i["quantity_g"],
                ts=now,
                capture_id=c["id"],
                template_id=mapping["template_id"],
            )
        )["id"]
        for i in tpl["items"]
    ]
    await cap.set_fields(db, c["id"], entry_ids=ids, resolved_at=now, label=label)
    return f"{label} logged."


async def press(db: AsyncDatabase, button: str) -> dict[str, Any]:
    mapping = await db[BUTTONS].find_one({"button": button})
    if not mapping:
        return {"say": "That button isn't set up.", "button": button}
    action = mapping["action"]
    label = mapping.get("label") or action
    if action == "undo":
        say = await _undo_last(db)
    elif action == "habit":
        say = await _habit(db, mapping, label)
    elif action == "placeholder":
        say = await _placeholder(db, button, label)
    elif action == "usual":
        say = await _log_usual(db, mapping, button, label)
    else:
        say = await _log(db, mapping, button, label)
    return {"say": say, "button": button}
