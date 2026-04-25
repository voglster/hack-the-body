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
    macros = Macros(
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
    return Food(
        name=name,
        brand=brand,
        barcode=barcode,
        category="food",
        # FDC has servingSize but it's per-product; nutrient values are per
        # 100g. Mirror our OFF behavior: store per-100g macros with a 100g
        # serving so quantity scaling is uniform across sources.
        serving_g=100.0,
        serving_label="100 g",
        per_serving=macros,
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
