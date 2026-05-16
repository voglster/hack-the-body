"""LLM-powered suggestion of meal templates ('usuals') from recent food log.

Pipeline:
1. Pull last 30 days of meal_entries + current meal_templates.
2. Keep only foods that appear >=3 times in the window — drop one-offs.
3. Build a compact prompt + call Ollama (glm-4.7-flash by default).
4. Parse JSON, validate every food_id still exists, cap at 5.
5. Filter out dismissed signatures.
"""
from __future__ import annotations

import json
import logging
import re
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
MIN_FOOD_OCCURRENCES = 3
MAX_SUGGESTIONS = 5

SYSTEM_PROMPT = """You analyze a personal food log and suggest 'usual' meals — \
groups of foods consistently eaten together at the same meal slot — that the \
user has NOT already saved as a template.

Return ONLY a JSON object with key "suggestions" containing an array. Each item:
{
  "name": "short label, 2-4 words, Title Case",
  "slot": "breakfast" | "lunch" | "dinner" | "snack" | "supplement",
  "items": [{"food_id": "<id from input>", "quantity_g": <median grams>}],
  "rationale": "one short sentence with frequency evidence"
}

Rules:
- Only suggest groups of 2+ foods (single-item is not a 'usual').
- Skip groups that closely match an existing template (same foods).
- Skip foods named exactly "Water" or "Vitamins" — those are auto-managed.
- Prefer high-frequency, same-slot, same-hour-ish groupings.
- Use median quantity_g from the user's history.
- Max 5 suggestions, best first.
- Return ONLY the JSON object, no prose, no markdown fences.
"""


def _bucket_entries(entries: list[dict]) -> dict[str, list[dict]]:
    """Group entries by (local-ish) date → list of {food_id, food_name, slot, hour, qty}."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        ts = e.get("ts")
        if not isinstance(ts, datetime):
            continue
        day = ts.date().isoformat()
        by_day[day].append({
            "food_id": e["food_id"],
            "food_name": e.get("food_name", ""),
            "slot": e.get("slot", "snack"),
            "hour": ts.hour,
            "qty": float(e.get("quantity_g") or 0.0),
        })
    return by_day


def _frequent_foods(entries: list[dict]) -> set[str]:
    counts: dict[str, int] = defaultdict(int)
    for e in entries:
        counts[e["food_id"]] += 1
    return {fid for fid, n in counts.items() if n >= MIN_FOOD_OCCURRENCES}


def _build_user_prompt(
    entries: list[dict],
    templates: list[dict],
    dismissed_signatures: set[str],
) -> str:
    frequent = _frequent_foods(entries)
    by_day = _bucket_entries(entries)
    # Compact per-day, per-slot view: each line = "YYYY-MM-DD slot HH: food (id) Ng; ..."
    lines: list[str] = []
    for day in sorted(by_day):
        by_slot: dict[str, list[dict]] = defaultdict(list)
        for it in by_day[day]:
            if it["food_id"] in frequent:
                by_slot[it["slot"]].append(it)
        for slot, items in by_slot.items():
            if len(items) < 2:
                continue
            avg_hour = round(statistics.mean(it["hour"] for it in items))
            parts = [
                f"{it['food_name']} (id={it['food_id']}) {int(it['qty'])}g"
                for it in items
            ]
            lines.append(f"{day} {slot} ~{avg_hour:02d}h: " + "; ".join(parts))

    existing = [
        {
            "name": t["name"],
            "slot": t.get("default_slot"),
            "food_ids": sorted(i["food_id"] for i in t.get("items", [])),
        }
        for t in templates
    ]

    dismissed = sorted(dismissed_signatures)

    return (
        "Existing saved usuals (do NOT re-suggest these):\n"
        + json.dumps(existing, indent=2)
        + "\n\nDismissed signatures (do NOT re-suggest):\n"
        + json.dumps(dismissed)
        + "\n\nRecent log (one line per slot per day, only frequent foods):\n"
        + "\n".join(lines) + "\n"
    )


def _signature(item_food_ids: list[str], slot: str) -> str:
    """Stable signature for a suggestion: sorted food_ids + slot."""
    return slot + ":" + ",".join(sorted(item_food_ids))


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def _call_ollama(
    settings: Any, user_prompt: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.coach_timeout_s) as client:
        r = await client.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "format": "json",
                "stream": False,
            },
        )
        r.raise_for_status()
        data = r.json()
    content = ((data.get("message") or {}).get("content") or "").strip()
    if not content:
        return {"suggestions": []}
    content = _strip_fences(content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("usuals_suggest: LLM returned non-JSON: %s", content[:200])
        return {"suggestions": []}
    if isinstance(parsed, list):
        return {"suggestions": parsed}
    return parsed if isinstance(parsed, dict) else {"suggestions": []}


async def _valid_food_ids(db: AsyncDatabase, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    from bson import ObjectId
    oids = []
    for i in ids:
        try:
            oids.append(ObjectId(i))
        except Exception:  # noqa: BLE001
            continue
    cur = db["foods"].find({"_id": {"$in": oids}}, {"_id": 1})
    return {str(d["_id"]) async for d in cur}


async def suggest_usuals(
    settings: Any, db: AsyncDatabase,
) -> dict[str, Any]:
    """Return up to 5 suggested meal templates. Filters dismissals."""
    now = datetime.now(UTC)
    start = now - timedelta(days=WINDOW_DAYS)

    entries_cur = db["meal_entries"].find({"ts": {"$gte": start, "$lte": now}})
    entries = [e async for e in entries_cur]

    templates_cur = db["meal_templates"].find()
    templates = [t async for t in templates_cur]

    dismissed_cur = db["usuals_suggest_dismissed"].find(
        {"dismissed_until": {"$gt": now}},
    )
    dismissed_sigs: set[str] = {d["signature"] async for d in dismissed_cur}

    if not entries:
        return {"suggestions": [], "generated_at": now.isoformat()}

    user_prompt = _build_user_prompt(entries, templates, dismissed_sigs)

    try:
        raw = await _call_ollama(settings, user_prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("usuals_suggest: ollama call failed: %s", exc)
        return {"suggestions": [], "generated_at": now.isoformat(), "error": str(exc)}

    raw_suggestions = raw.get("suggestions") or []
    if not isinstance(raw_suggestions, list):
        return {"suggestions": [], "generated_at": now.isoformat()}

    # Validate food_ids
    all_ids: set[str] = set()
    for s in raw_suggestions:
        for it in s.get("items") or []:
            fid = it.get("food_id")
            if isinstance(fid, str):
                all_ids.add(fid)
    valid = await _valid_food_ids(db, all_ids)

    # Existing template signatures so we don't echo what already exists.
    existing_sigs: set[str] = {
        _signature(
            [i["food_id"] for i in t.get("items", [])],
            t.get("default_slot", "snack"),
        )
        for t in templates
    }

    out: list[dict[str, Any]] = []
    seen_sigs: set[str] = set()
    for s in raw_suggestions:
        slot = s.get("slot")
        if slot not in {"breakfast", "lunch", "dinner", "snack", "supplement"}:
            continue
        items = []
        for it in s.get("items") or []:
            fid = it.get("food_id")
            qty = it.get("quantity_g")
            if (
                isinstance(fid, str)
                and fid in valid
                and isinstance(qty, int | float)
                and qty > 0
            ):
                items.append({"food_id": fid, "quantity_g": float(qty)})
        if len(items) < 2:
            continue
        sig = _signature([i["food_id"] for i in items], slot)
        if sig in existing_sigs or sig in dismissed_sigs or sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        name = (s.get("name") or "").strip() or "Unnamed Usual"
        rationale = (s.get("rationale") or "").strip()
        out.append({
            "name": name[:80],
            "slot": slot,
            "items": items,
            "rationale": rationale[:240],
            "signature": sig,
        })
        if len(out) >= MAX_SUGGESTIONS:
            break

    return {"suggestions": out, "generated_at": now.isoformat()}


async def dismiss_signature(
    db: AsyncDatabase, signature: str, days: int = 7,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    until = now + timedelta(days=days)
    await db["usuals_suggest_dismissed"].update_one(
        {"signature": signature},
        {"$set": {"signature": signature, "dismissed_until": until,
                  "updated_at": now}},
        upsert=True,
    )
    return {"signature": signature, "dismissed_until": until.isoformat()}
