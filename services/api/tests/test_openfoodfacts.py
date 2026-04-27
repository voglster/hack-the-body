"""Mapper tests for the Open Food Facts client.

`_to_food` is private but small enough that a few targeted tests catch
the brand-prefix logic without dragging in HTTP mocks.
"""
from __future__ import annotations

from app.services.openfoodfacts import _to_food


def test_brand_prefixed_when_brand_missing_from_product_name():
    raw = {
        "product_name": "Total 5% Milkfat",
        "brands": "Fage",
        "serving_quantity": "150",
        "serving_size": "150 g",
        "nutriments": {
            "energy-kcal_100g": 80,
            "proteins_100g": 10,
        },
    }
    food = _to_food(raw, barcode="0123")
    assert food.brand == "Fage"
    assert food.name == "Fage Total 5% Milkfat"


def test_brand_not_doubled_when_already_in_product_name():
    raw = {
        "product_name": "Fage Total 5% Milkfat",
        "brands": "Fage",
        "nutriments": {},
    }
    food = _to_food(raw, barcode="0123")
    assert food.name == "Fage Total 5% Milkfat"  # no "Fage Fage Total ..."


def test_no_brand_keeps_plain_name():
    raw = {
        "product_name": "Generic Yogurt",
        "brands": "",
        "nutriments": {},
    }
    food = _to_food(raw, barcode="0123")
    assert food.name == "Generic Yogurt"
    assert food.brand is None


def test_multiple_brands_uses_first():
    raw = {
        "product_name": "Total 5% Milkfat",
        "brands": "Fage, FAGE Total",
        "nutriments": {},
    }
    food = _to_food(raw, barcode="0123")
    assert food.brand == "Fage"
    assert food.name == "Fage Total 5% Milkfat"


def test_falls_back_to_unknown_product_name():
    raw = {"brands": "ACME", "nutriments": {}}
    food = _to_food(raw, barcode="0123")
    assert food.name == "ACME Unknown product"
