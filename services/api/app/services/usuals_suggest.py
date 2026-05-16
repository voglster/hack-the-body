"""Suggest 'usual' meal templates using a deterministic pattern miner.

Pipeline:
1. Load last 30 days of meal_entries + current meal_templates +
   dismissed signatures.
2. Hand them to `usuals_miner.mine_candidates` — pure Python, no LLM.
3. Cap at 5 results combined (new + augment), return.

An LLM naming pass can be layered later — that's a separate concern from
detection. Keeping detection deterministic makes it testable and stops the
"LLM hallucinated a usual" failure mode that motivated this rewrite.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.services.usuals_miner import mine_candidates, signature

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
MAX_SUGGESTIONS = 5


async def suggest_usuals(
    settings: Any, db: AsyncDatabase,  # noqa: ARG001 (settings reserved for future LLM pass)
) -> dict[str, Any]:
    """Return up to MAX_SUGGESTIONS deterministic candidates from the log.

    Filters dismissed signatures and existing templates. New candidates come
    first, then augmentation suggestions for existing templates.
    """
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
        return {"new": [], "augment": [], "generated_at": now.isoformat()}

    result = mine_candidates(entries, templates, dismissed_sigs)

    # Combined cap — keep all augments + fill remainder with new
    augment = result["augment"][:MAX_SUGGESTIONS]
    remaining = max(0, MAX_SUGGESTIONS - len(augment))
    new = result["new"][:remaining]

    return {
        "new": new,
        "augment": augment,
        "generated_at": now.isoformat(),
    }


async def dismiss_signature(
    db: AsyncDatabase, sig: str, days: int = 7,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    until = now + timedelta(days=days)
    await db["usuals_suggest_dismissed"].update_one(
        {"signature": sig},
        {"$set": {"signature": sig, "dismissed_until": until,
                  "updated_at": now}},
        upsert=True,
    )
    return {"signature": sig, "dismissed_until": until.isoformat()}


# Re-exported for tests / external callers.
__all__ = ["dismiss_signature", "signature", "suggest_usuals"]
