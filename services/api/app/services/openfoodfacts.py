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


HTTP_OK = 200


def _g(d: dict[str, Any], key: str) -> float | None:
    v = d.get(key)
    return float(v) if v is not None else None


def _g_to_mg(grams: float | None) -> float | None:
    return grams * 1000.0 if grams is not None else None


def _to_food(off_product: dict[str, Any], barcode: str) -> Food:
    """Map an OFF product dict to our Food. Prefer the product's published
    serving size (e.g. "1 BOTTLE (507 ml)" → serving_g=507) when present
    so quantity inputs can be expressed in real-world servings instead
    of arbitrary 100g units."""
    n = off_product.get("nutriments") or {}
    per_100g = Macros(
        calories=_g(n, "energy-kcal_100g") or _g(n, "energy-kcal"),
        protein_g=_g(n, "proteins_100g"),
        carbs_g=_g(n, "carbohydrates_100g"),
        fat_g=_g(n, "fat_100g"),
        fiber_g=_g(n, "fiber_100g"),
        sugar_g=_g(n, "sugars_100g"),
        sodium_mg=_g_to_mg(_g(n, "sodium_100g")),
    )

    # Resolve serving from OFF if it published one. serving_quantity is in
    # grams (or ml — we treat as g for calorie scaling, fluid weights ~1g/ml).
    serving_q_raw = off_product.get("serving_quantity")
    serving_size_str = off_product.get("serving_size")
    serving_g = 100.0
    serving_label = "100 g"
    per_serving = per_100g
    try:
        sq = float(serving_q_raw) if serving_q_raw else 0.0
    except (TypeError, ValueError):
        sq = 0.0
    if sq > 0:
        serving_g = sq
        serving_label = serving_size_str or f"{sq:.0f} g"
        factor = sq / 100.0
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

    product_name = (
        off_product.get("product_name")
        or off_product.get("product_name_en")
        or "Unknown product"
    )
    brand = (off_product.get("brands") or "").split(",")[0].strip() or None
    # OFF stores brand and product_name separately, but the product_name is
    # often the parent SKU only (e.g. "Total 5% Milkfat"). Without the brand
    # prefix the dashboard reads as anonymous yogurt. Prefix it here so every
    # downstream snapshot already includes the brand. Skip the prefix if the
    # name already starts with the brand (case-insensitive) to avoid
    # "Fage Fage Total ...".
    if brand and not product_name.lower().startswith(brand.lower()):
        display_name = f"{brand} {product_name}"
    else:
        display_name = product_name

    return Food(
        name=display_name,
        brand=brand,
        barcode=barcode,
        category="food",
        serving_g=serving_g,
        serving_label=serving_label,
        per_serving=per_serving,
        source="off",
        source_ref=str(off_product.get("code") or barcode),
    )


def _barcode_variants(barcode: str) -> list[str]:
    """Generate plausible OFF lookup keys for a scanned/typed code.

    OFF stores most US products as EAN-13 (leading 0 prefix on the UPC-A).
    Some products are stored UPC-A. Some scanners drop leading zeros. So
    we try the as-given code first, then a stripped version, then 12- and
    13-digit zero-padded variants. De-duplicated, ordered so most likely
    hits go first.
    """
    raw = barcode.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    candidates: list[str] = []
    for v in (raw, digits, digits.lstrip("0"), digits.zfill(12), digits.zfill(13)):
        if v and v not in candidates:
            candidates.append(v)
    return candidates


async def fetch_off_product(barcode: str) -> Food | None:
    headers = {"User-Agent": UA}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as c:
            for variant in _barcode_variants(barcode):
                url = f"https://world.openfoodfacts.org/api/v2/product/{variant}.json"
                r = await c.get(url)
                if r.status_code != HTTP_OK:
                    continue
                body = r.json()
                if body.get("status") != 1:
                    continue
                # Use the original input as the canonical barcode in our DB
                # so future lookups against the same scanned code hit cache.
                return _to_food(body["product"], barcode)
        return None
    except (httpx.HTTPError, ValueError) as e:
        log.warning("OFF fetch failed for %s: %s", barcode, e)
        return None
