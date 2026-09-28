"""Deterministic pattern miner for 'usual' meal candidates.

Finds groups of foods consistently logged together at the same meal slot
across the recent window. No LLM in the loop — pure Python + counters.

Two candidate kinds:
- "new": a frequent food group that isn't already saved as a template.
- "augment": an existing template's foods + one or more extra foods that
  co-occur with it most of the time → suggest adding the extras.

Names are heuristic ("Yogurt + Granola + Chia +1" or "Add Chia to Yogurt
Breakfast"). An LLM naming pass can be layered on top later.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from typing import Any

# Singletons we never want to bundle — water has its own card, vitamins are
# habit-managed.
EXCLUDED_NAMES = frozenset({"Water", "Vitamins"})

MIN_GROUP_SIZE = 2
NAMED_FOODS_LIMIT = 3

SLOT_LABEL = {
    "breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner",
    "snack": "Snack", "supplement": "Supplement",
}

DaySlotGroups = dict[tuple[str, str], list[dict[str, Any]]]
TemplateKeys = dict[tuple[str, frozenset[str]], dict[str, Any]]


def signature(slot: str, food_ids: list[str]) -> str:
    return slot + ":" + ",".join(sorted(food_ids))


def _is_maximal(s: frozenset[str], n: int, pool: dict[frozenset[str], int]) -> bool:
    """A subset is 'maximal' if no superset survives at almost the same count.

    Tolerance of 1 occurrence handles a single outlier day (e.g., user
    forgot one food once) without inventing fake patterns.
    """
    return all(not (s2 > s and (n - n2) <= 1) for s2, n2 in pool.items())


def _heuristic_new_name(food_names: list[str]) -> str:
    """Build a compact label from the food names — first 3 joined with ' + ',
    rest collapsed into a '+N' suffix. Mirrors the inline save-as-usual UI
    so naming is consistent across surfaces."""
    if not food_names:
        return "New Usual"
    if len(food_names) <= NAMED_FOODS_LIMIT:
        return " + ".join(food_names)
    shown = " + ".join(food_names[:NAMED_FOODS_LIMIT])
    return f"{shown} +{len(food_names) - NAMED_FOODS_LIMIT}"


def _group_by_day_slot(
    entries: list[dict[str, Any]],
) -> tuple[DaySlotGroups, dict[str, dict[str, list[float]]], dict[str, str]]:
    """Bucket entries by (date, slot) — UTC date is fine; we want intra-meal
    co-occurrence. Also returns per-slot quantity samples and a
    food_id → name lookup."""
    by_day_slot: DaySlotGroups = defaultdict(list)
    qty_samples: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    name_of: dict[str, str] = {}
    for e in entries:
        ts = e.get("ts")
        if not isinstance(ts, datetime):
            continue
        if e.get("food_name") in EXCLUDED_NAMES:
            continue
        slot = e.get("slot", "snack")
        fid = e.get("food_id")
        if not fid:
            continue
        day = ts.date().isoformat()
        by_day_slot[(day, slot)].append({
            "food_id": fid, "food_name": e.get("food_name", ""), "slot": slot,
            "quantity_g": float(e.get("quantity_g") or 0),
        })
        qty_samples[slot][fid].append(float(e.get("quantity_g") or 0))
        name_of[fid] = e.get("food_name", "")
    return by_day_slot, qty_samples, name_of


def _multi_food_sets_by_slot(
    by_day_slot: DaySlotGroups,
) -> dict[str, list[tuple[str, frozenset[str]]]]:
    sets_by_slot: dict[str, list[tuple[str, frozenset[str]]]] = defaultdict(list)
    for (day, slot), es in by_day_slot.items():
        ids = frozenset(it["food_id"] for it in es)
        if len(ids) >= MIN_GROUP_SIZE:
            sets_by_slot[slot].append((day, ids))
    return sets_by_slot


def _frequent_subsets(
    day_sets: list[tuple[str, frozenset[str]]], min_occurrences: int,
) -> dict[frozenset[str], int]:
    """Count every food subset (size 2..N) across a slot's days — these are
    the candidate groups — keeping those seen at least `min_occurrences`
    times."""
    food_count: Counter[str] = Counter()
    for _, ids in day_sets:
        for fid in ids:
            food_count[fid] += 1
    frequent_foods = {fid for fid, n in food_count.items() if n >= min_occurrences}
    if len(frequent_foods) < MIN_GROUP_SIZE:
        return {}

    subset_count: Counter[frozenset[str]] = Counter()
    for _, ids in day_sets:
        filtered = ids & frequent_foods
        if len(filtered) < MIN_GROUP_SIZE:
            continue
        for r in range(MIN_GROUP_SIZE, len(filtered) + 1):
            for combo in combinations(sorted(filtered), r):
                subset_count[frozenset(combo)] += 1

    return {s: n for s, n in subset_count.items() if n >= min_occurrences}


def _largest_template_subset(
    slot: str, foods: frozenset[str], template_keys: TemplateKeys,
) -> tuple[str, frozenset[str]] | None:
    """The largest existing template in `slot` whose foods are a strict
    subset of `foods` — the one an augmentation would extend."""
    best: tuple[str, frozenset[str]] | None = None
    for (eslot, efoods) in template_keys:
        if eslot != slot or not efoods:
            continue
        if efoods < foods and (best is None or len(efoods) > len(best[1])):
            best = (eslot, efoods)
    return best


def _augment_candidate(
    base: dict[str, Any],
    existing: dict[str, Any],
    extra_ids: list[str],
    name_of: dict[str, str],
) -> dict[str, Any]:
    extra_names = [name_of.get(fid, "") for fid in extra_ids]
    return {
        **base,
        "kind": "augment",
        "template_id": str(existing.get("_id", existing.get("id", ""))),
        "template_name": existing.get("name", ""),
        "add_food_ids": extra_ids,
        "add_food_names": extra_names,
        "name": (
            f"Add {', '.join(extra_names)} to {existing.get('name', '')}"
            if extra_names else existing.get("name", "")
        ),
    }


def mine_candidates(
    entries: list[dict[str, Any]],
    templates: list[dict[str, Any]],
    dismissed_sigs: set[str],
    *,
    min_occurrences: int = 3,
    min_confidence: float = 0.4,
) -> dict[str, list[dict[str, Any]]]:
    """Mine 'usual' candidates from raw entries.

    `entries`: list of meal_entry docs (with `ts`, `food_id`, `food_name`,
    `slot`, `quantity_g`). `templates`: existing meal_template docs.
    `dismissed_sigs`: signatures (slot:sorted-ids) to skip.

    Returns dict with `new` and `augment` lists, each sorted by occurrence
    descending. `signature` is included on every candidate so the FE can
    dismiss it deterministically.
    """
    by_day_slot, qty_samples, name_of = _group_by_day_slot(entries)

    existing_template_keys: TemplateKeys = {
        (t.get("default_slot", "snack"),
         frozenset(i["food_id"] for i in t.get("items", []))): t
        for t in templates
    }

    new_candidates: list[dict[str, Any]] = []
    augmentations: list[dict[str, Any]] = []

    for slot, day_sets in _multi_food_sets_by_slot(by_day_slot).items():
        frequent_subsets = _frequent_subsets(day_sets, min_occurrences)
        slot_total = len(day_sets)

        for foods, occurrences in frequent_subsets.items():
            if not _is_maximal(foods, occurrences, frequent_subsets):
                continue
            confidence = occurrences / slot_total if slot_total else 0
            if confidence < min_confidence:
                continue
            sig = signature(slot, list(foods))
            if sig in dismissed_sigs:
                continue
            # Exact-match existing template → skip
            if (slot, foods) in existing_template_keys:
                continue
            items = [
                {
                    "food_id": fid,
                    "food_name": name_of.get(fid, ""),
                    "quantity_g": round(statistics.median(qty_samples[slot][fid]), 1),
                }
                for fid in sorted(foods)
            ]
            base = {
                "signature": sig,
                "slot": slot,
                "items": items,
                "occurrences": occurrences,
                "total_days_with_slot": slot_total,
                "confidence": round(confidence, 2),
                "rationale": (
                    f"Logged together {occurrences} of {slot_total} "
                    f"{SLOT_LABEL[slot].lower()}s"
                ),
            }
            best_subset = _largest_template_subset(slot, foods, existing_template_keys)
            if best_subset is not None:
                augmentations.append(_augment_candidate(
                    base,
                    existing_template_keys[best_subset],
                    sorted(foods - best_subset[1]),
                    name_of,
                ))
            else:
                new_candidates.append({
                    **base,
                    "kind": "new",
                    "name": _heuristic_new_name([it["food_name"] for it in items]),
                })

    new_candidates.sort(key=lambda c: (-c["occurrences"], -c["confidence"]))
    augmentations.sort(key=lambda c: (-c["occurrences"], -c["confidence"]))

    return {"new": new_candidates, "augment": augmentations}
