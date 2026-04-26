"""USDA FoodData Central client.

FDC has ~1M Branded foods that Open Food Facts often lacks (especially US
grocery items). We hit the public search endpoint by UPC; nutrients are
returned per 100g, same shape as our OFF mapping.

Free key from https://api.data.gov/signup/. With no key the client is a
no-op so the rest of the food pipeline still works.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.models.food import Food, Macros

log = logging.getLogger(__name__)

UA = "hack-the-body/0.1 (https://github.com/voglster/hack-the-body)"
TIMEOUT = httpx.Timeout(8.0, connect=4.0)
SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# FDC nutrient IDs we care about. Values are per 100g for Branded foods.
N_PROTEIN = 1003
N_FAT = 1004
N_CARBS = 1005
N_ENERGY_KCAL = 1008
N_FIBER = 1079
N_SUGARS = 2000
N_SODIUM = 1093

HTTP_OK = 200


def _nutrient(food_nutrients: list[dict[str, Any]], nutrient_id: int) -> float | None:
    for n in food_nutrients:
        if n.get("nutrientId") == nutrient_id:
            v = n.get("value")
            return float(v) if v is not None else None
    return None


def _to_food(fdc: dict[str, Any], barcode: str) -> Food:
    nutrients = fdc.get("foodNutrients") or []
    per_100g = Macros(
        calories=_nutrient(nutrients, N_ENERGY_KCAL),
        protein_g=_nutrient(nutrients, N_PROTEIN),
        carbs_g=_nutrient(nutrients, N_CARBS),
        fat_g=_nutrient(nutrients, N_FAT),
        fiber_g=_nutrient(nutrients, N_FIBER),
        sugar_g=_nutrient(nutrients, N_SUGARS),
        sodium_mg=_nutrient(nutrients, N_SODIUM),
    )
    name = (
        fdc.get("description")
        or fdc.get("brandName")
        or "Unknown product"
    ).title()
    brand = (fdc.get("brandName") or fdc.get("brandOwner") or "").strip() or None

    # FDC publishes `servingSize` (number) and `servingSizeUnit` ("GRM",
    # "MLT"). When present, use that as the canonical serving so the
    # quantity input can speak the user's language ("1 bar = 50g").
    serving_g = 100.0
    serving_label = "100 g"
    per_serving = per_100g
    try:
        ss = float(fdc.get("servingSize") or 0)
    except (TypeError, ValueError):
        ss = 0.0
    if ss > 0:
        unit = (fdc.get("servingSizeUnit") or "").upper()
        # FDC nutrient values are per-100g (GRM) or per-100ml (MLT). Treat
        # both as the per-unit denominator; we store the numeric value and
        # let serving_label carry the human unit ("11 fl oz").
        serving_g = ss
        household = fdc.get("householdServingFullText")
        unit_label = "ml" if unit in {"MLT", "ML"} else "g"
        serving_label = (
            f"{household} ({serving_g:.0f} {unit_label})" if household
            else f"{serving_g:.0f} {unit_label}"
        )
        factor = serving_g / 100.0
        def _s(v: float | None) -> float | None:
            return round(v * factor, 2) if v is not None else None
        per_serving = Macros(
            calories=_s(per_100g.calories),
            protein_g=_s(per_100g.protein_g),
            carbs_g=_s(per_100g.carbs_g),
            fat_g=_s(per_100g.fat_g),
            fiber_g=_s(per_100g.fiber_g),
            sugar_g=_s(per_100g.sugar_g),
            sodium_mg=_s(per_100g.sodium_mg),
        )
    return Food(
        name=name,
        brand=brand,
        barcode=barcode,
        category="food",
        serving_g=serving_g,
        serving_label=serving_label,
        per_serving=per_serving,
        source="usda_fdc",
        source_ref=str(fdc.get("fdcId") or barcode),
    )


def _barcode_variants(barcode: str) -> list[str]:
    """FDC stores GTIN-12/13 — same padding logic as OFF helps here too."""
    raw = barcode.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    out: list[str] = []
    for v in (raw, digits, digits.lstrip("0"), digits.zfill(12), digits.zfill(13)):
        if v and v not in out:
            out.append(v)
    return out


async def fetch_fdc_by_barcode(barcode: str, api_key: str) -> Food | None:
    """Look up a Branded food by UPC. Returns None on any failure (no key,
    network, missing match) so callers can chain to other sources."""
    if not api_key:
        return None
    headers = {"User-Agent": UA}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as c:
            for variant in _barcode_variants(barcode):
                params = {
                    "api_key": api_key,
                    "query": variant,
                    "dataType": "Branded",
                    "pageSize": 5,
                }
                r = await c.get(SEARCH_URL, params=params)
                if r.status_code != HTTP_OK:
                    continue
                body = r.json()
                # FDC search is text-fuzzy; require exact UPC match before
                # claiming we found the right product.
                for hit in body.get("foods") or []:
                    gtin = (hit.get("gtinUpc") or "").lstrip("0")
                    if gtin and gtin == variant.lstrip("0"):
                        return _to_food(hit, barcode)
        return None
    except (httpx.HTTPError, ValueError) as e:
        log.warning("FDC fetch failed for %s: %s", barcode, e)
        return None
