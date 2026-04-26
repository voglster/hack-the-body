"""Freeform-text → structured food items via local LLM.

Users paste either a structured breakdown ("Crepe Shell: 250\n2 Eggs: 150")
or a casual description ("had a crepe with eggs and salmon, ~700 cal"),
and we get back a list of items with macros where present. Macros are
TOTAL for the item (not per-serving), so logging them is just creating
a Food + MealEntry where quantity_g == serving_g (factor 1).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

PARSE_PROMPT = """You are a food log parser. Read the user's text and \
return ONLY a JSON array (no prose, no code fences) of food items.

Schema for each item:
{
  "name": string (required, the food name, e.g. "Scrambled Eggs"),
  "servings": number or null (count of items if given like "2 eggs", default 1),
  "calories": number or null (TOTAL calories for this item, not per serving),
  "protein_g": number or null,
  "carbs_g": number or null,
  "fat_g": number or null
}

Rules:
- Macros are TOTAL for the line, not per-serving.
  "2 Eggs: 150" means 150 total calories for the pair.
- If quantity is weight/volume ("2oz salmon"), set servings=1
  and put the weight in the name.
- If macros aren't in the text, leave them null. Only estimate
  calories when no numbers appear anywhere.
- Skip greetings, questions, meta-commentary. Only food items.
- Return [] if nothing food-like is present.

Text to parse:
{TEXT}

JSON:"""


@dataclass
class ParsedItem:
    name: str
    servings: float = 1.0
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        n = float(v)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """LLMs sometimes wrap output in code fences or add a sentence before the
    array. Find the first `[` and the matching `]`."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    blob = text[start : end + 1]
    # Strip trailing commas before ] and } which json.loads rejects.
    blob = re.sub(r",(\s*[}\]])", r"\1", blob)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        log.warning("food parse: JSON decode failed: %s", e)
        return []
    return data if isinstance(data, list) else []


async def parse_food_text(settings: Settings, text: str) -> list[ParsedItem]:
    if not text.strip():
        return []
    prompt = PARSE_PROMPT.replace("{TEXT}", text.strip())
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.1, "num_predict": 1500},
    }
    async with httpx.AsyncClient(timeout=settings.coach_timeout_s) as c:
        r = await c.post(f"{settings.ollama_url}/api/generate", json=payload)
        r.raise_for_status()
        body = r.json()
    raw = body.get("response") or ""
    items = _extract_json_array(raw)
    out: list[ParsedItem] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        out.append(ParsedItem(
            name=name,
            servings=_coerce_float(it.get("servings")) or 1.0,
            calories=_coerce_float(it.get("calories")),
            protein_g=_coerce_float(it.get("protein_g")),
            carbs_g=_coerce_float(it.get("carbs_g")),
            fat_g=_coerce_float(it.get("fat_g")),
        ))
    return out
