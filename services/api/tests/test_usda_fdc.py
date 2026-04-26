"""USDA FDC client + fallback chain in /foods/barcode."""
from unittest.mock import patch

import httpx

from app.models.food import Food, Macros
from app.services.usda_fdc import _barcode_variants, fetch_fdc_by_barcode

HEADERS = {"X-API-Key": "test-key"}


def test_barcode_variants_pads_and_dedupes():
    out = _barcode_variants("749826126487")
    # original + 13-digit zero-pad should both appear
    assert "749826126487" in out
    assert "0749826126487" in out
    assert len(out) == len(set(out))


async def test_fdc_returns_none_without_key():
    food = await fetch_fdc_by_barcode("749826126487", "")
    assert food is None


def _fdc_hit(upc: str = "0749826126487") -> dict:
    return {
        "foods": [
            {
                "fdcId": 999,
                "description": "TEST PROTEIN BAR",
                "brandName": "TESTCO",
                "brandOwner": "Testco Brands",
                "gtinUpc": upc,
                "servingSize": 50.0,
                "foodNutrients": [
                    {"nutrientId": 1003, "value": 40.0},
                    {"nutrientId": 1004, "value": 12.0},
                    {"nutrientId": 1005, "value": 32.0},
                    {"nutrientId": 1008, "value": 380.0},
                ],
            },
        ],
    }


async def test_fdc_maps_a_branded_food():
    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return _fdc_hit()

    async def _fake_get(_self, _url, **_kw):
        return _R()

    with patch.object(httpx.AsyncClient, "get", _fake_get):
        food = await fetch_fdc_by_barcode("749826126487", "key")

    assert food is not None
    assert food.barcode == "749826126487"
    assert food.source == "usda_fdc"
    # per_serving is scaled to the published servingSize (50g), not per-100g.
    assert food.serving_g == 50.0
    assert food.per_serving.calories == 190.0  # 380 * 0.5
    assert food.per_serving.protein_g == 20.0  # 40 * 0.5


async def test_fdc_skips_non_matching_upc():
    class _R:
        status_code = 200
        def raise_for_status(self): pass
        # Same hit but the UPC inside doesn't match what we asked for.
        def json(self): return _fdc_hit(upc="0000000000000")

    async def _fake_get(_self, _url, **_kw):
        return _R()

    with patch.object(httpx.AsyncClient, "get", _fake_get):
        food = await fetch_fdc_by_barcode("749826126487", "key")
    assert food is None


async def test_barcode_route_falls_back_to_fdc(client, settings):
    # OFF returns nothing; FDC returns the bar. The route should chain
    # them and persist the FDC result. Patch the service functions
    # directly so we don't accidentally intercept the test client's own
    # httpx call to FastAPI.
    settings.usda_fdc_api_key = "key"

    async def _no_off(_barcode):
        return None

    async def _fdc_hit_fn(barcode, _key):
        return Food(
            name="Test Protein Bar", brand="Testco", barcode=barcode,
            category="food", serving_g=100.0, serving_label="100 g",
            per_serving=Macros(calories=380.0, protein_g=40.0, carbs_g=32.0, fat_g=12.0),
            source="usda_fdc", source_ref="999",
        )

    with (
        patch("app.routers.foods.fetch_off_product", _no_off),
        patch("app.routers.foods.fetch_fdc_by_barcode", _fdc_hit_fn),
    ):
        r = await client.get("/foods/barcode/749826126487", headers=HEADERS)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "usda_fdc"
    assert body["per_serving"]["protein_g"] == 40.0
