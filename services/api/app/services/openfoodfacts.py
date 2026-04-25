"""Thin Open Food Facts client.

OFF is free, public, doesn't require auth, and has 3M+ products.
We hit the v2 product endpoint by barcode and map the relevant fields onto
our `Food` model. Results are cached by upserting them into the `foods`
collection with `source="off"`.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.models.food import Food, Macros

log = logging.getLogger(__name__)

UA = "hack-the-body/0.1 (https://github.com/voglster/hack-the-body)"
TIMEOUT = httpx.Timeout(8.0, connect=4.0)


def _g(d: dict[str, Any], key: str) -> float | None:
    v = d.get(key)
    return float(v) if v is not None else None


def _to_food(off_product: dict[str, Any], barcode: str) -> Food:
    """Map an OFF product dict to our Food. OFF stores nutrients per 100g."""
    n = off_product.get("nutriments") or {}
    macros = Macros(
        calories=_g(n, "energy-kcal_100g") or _g(n, "energy-kcal"),
        protein_g=_g(n, "proteins_100g"),
        carbs_g=_g(n, "carbohydrates_100g"),
        fat_g=_g(n, "fat_100g"),
        fiber_g=_g(n, "fiber_100g"),
        sugar_g=_g(n, "sugars_100g"),
        sodium_mg=(lambda v: v * 1000.0 if v is not None else None)(_g(n, "sodium_100g")),
    )
    return Food(
        name=(
            off_product.get("product_name")
            or off_product.get("product_name_en")
            or "Unknown product"
        ),
        brand=(off_product.get("brands") or "").split(",")[0].strip() or None,
        barcode=barcode,
        category="food",
        serving_g=100.0,
        serving_label="100 g",
        per_serving=macros,
        source="off",
        source_ref=str(off_product.get("code") or barcode),
    )


async def fetch_off_product(barcode: str) -> Food | None:
    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
    headers = {"User-Agent": UA}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as c:
            r = await c.get(url)
        if r.status_code != 200:
            return None
        body = r.json()
        if body.get("status") != 1:
            return None
        return _to_food(body["product"], barcode)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("OFF fetch failed for %s: %s", barcode, e)
        return None
