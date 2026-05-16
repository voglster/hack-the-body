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

SLOT_LABEL = {
    "breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner",
    "snack": "Snack", "supplement": "Supplement",
}


def signature(slot: str, food_ids: list[str]) -> str:
    return slot + ":" + ",".join(sorted(food_ids))


def _is_maximal(s: frozenset[str], n: int, pool: dict[frozenset[str], int]) -> bool:
    """A subset is 'maximal' if no superset survives at almost the same count.

    Tolerance of 1 occurrence handles a single outlier day (e.g., user
    forgot one food once) without inventing fake patterns.
    """
    for s2, n2 in pool.items():
        if s2 > s and (n - n2) <= 1:
            return False
    return True


def _heuristic_new_name(food_names: list[str]) -> str:
    """Build a compact label from the food names — first 3 joined with ' + ',
    rest collapsed into a '+N' suffix. Mirrors the inline save-as-usual UI
    so naming is consistent across surfaces."""
    if not food_names:
        return "New Usual"
    if len(food_names) <= 3:
        return " + ".join(food_names)
    return f"{' + '.join(food_names[:3])} +{len(food_names) - 3}"


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
    # Group by (date, slot) — UTC date is fine; we want intra-meal co-occurrence
    by_day_slot: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
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

    sets_by_slot: dict[str, list[tuple[str, frozenset[str]]]] = defaultdict(list)
    for (day, slot), es in by_day_slot.items():
        ids = frozenset(it["food_id"] for it in es)
        if len(ids) >= 2:
            sets_by_slot[slot].append((day, ids))

    existing_template_keys: dict[
        tuple[str, frozenset[str]], dict[str, Any],
    ] = {
        (t.get("default_slot", "snack"),
         frozenset(i["food_id"] for i in t.get("items", []))): t
        for t in templates
    }

    new_candidates: list[dict[str, Any]] = []
    augmentations: list[dict[str, Any]] = []

    for slot, day_sets in sets_by_slot.items():
        # Per-food count in this slot
        food_count: Counter[str] = Counter()
        for _, ids in day_sets:
            for fid in ids:
                food_count[fid] += 1
        frequent_foods = {fid for fid, n in food_count.items() if n >= min_occurrences}
        if len(frequent_foods) < 2:
            continue

        subset_count: Counter[frozenset[str]] = Counter()
        for _, ids in day_sets:
            filtered = ids & frequent_foods
            if len(filtered) < 2:
                continue
            # Count every subset (size 2..N) — these are the candidate groups
            for r in range(2, len(filtered) + 1):
                for combo in combinations(sorted(filtered), r):
                    subset_count[frozenset(combo)] += 1

        frequent_subsets = {
            s: n for s, n in subset_count.items() if n >= min_occurrences
        }
        if not frequent_subsets:
            continue

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
            food_id_list = sorted(foods)
            items = [
                {
                    "food_id": fid,
                    "food_name": name_of.get(fid, ""),
                    "quantity_g": round(statistics.median(qty_samples[slot][fid]), 1),
                }
                for fid in food_id_list
            ]
            food_names_ordered = [it["food_name"] for it in items]
            # Exact-match existing template → skip
            if (slot, frozenset(food_id_list)) in existing_template_keys:
                continue
            # Augmentation: the largest existing template whose foods are
            # a strict subset of this group
            best_subset: tuple[str, frozenset[str]] | None = None
            for (eslot, efoods) in existing_template_keys:
                if eslot != slot or not efoods:
                    continue
                if efoods < frozenset(food_id_list):
                    if best_subset is None or len(efoods) > len(best_subset[1]):
                        best_subset = (eslot, efoods)
            base = {
                "signature": sig,
                "slot": slot,
                "items": items,
                "occurrences": occurrences,
                "total_days_with_slot": slot_total,
                "confidence": round(confidence, 2),
            }
            if best_subset is not None:
                existing = existing_template_keys[best_subset]
                extra_ids = sorted(set(food_id_list) - best_subset[1])
                extra_names = [name_of.get(fid, "") for fid in extra_ids]
                augmentations.append({
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
                    "rationale": (
                        f"Logged together {occurrences} of {slot_total} "
                        f"{SLOT_LABEL[slot].lower()}s"
                    ),
                })
            else:
                new_candidates.append({
                    **base,
                    "kind": "new",
                    "name": _heuristic_new_name(food_names_ordered),
                    "rationale": (
                        f"Logged together {occurrences} of {slot_total} "
                        f"{SLOT_LABEL[slot].lower()}s"
                    ),
                })

    new_candidates.sort(key=lambda c: (-c["occurrences"], -c["confidence"]))
    augmentations.sort(key=lambda c: (-c["occurrences"], -c["confidence"]))

    return {"new": new_candidates, "augment": augmentations}
