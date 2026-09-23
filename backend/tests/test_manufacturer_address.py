"""Tests for the deterministic manufacturer-address side channel.

Fixtures are hand-built OCR token dicts (box = [x1, y1, x2, y2]) — no OCR,
no classifier — so these tests are fully deterministic and fast.
"""
import pytest

from app.services.manufacturer_address import extract_manufacturer_address


def _tok(text: str, y: float = 100.0, h: float = 40.0) -> dict:
    return {"text": text, "box": [0.0, y, 400.0, y + h]}


def test_pin_and_city_run_selected():
    """The DMart-style block: garbled street + city + PIN is captured."""
    addr = extract_manufacturer_address([{"tokens": [
        _tok("Regd. Office:"),
        _tok("Fnundation School, Powai, Mumbai, Pin-400076, Maharasha", y=140),
    ]}])
    assert "400076" in addr
    assert "Mumbai" in addr
    assert "Office" not in addr  # label words alone are not an address


def test_licence_numbers_excluded():
    """Lic.No. digit runs must not be mistaken for PINs."""
    addr = extract_manufacturer_address([{"tokens": [
        _tok("Lic.No.10016022005492"),
        _tok("P.0.BAG2.NEW DELHI-110 001", y=130),
    ]}])
    assert "Lic" not in addr
    assert "110 001" in addr


def test_nutrition_junk_not_glued():
    """Nutrition-grid neighbours on the same visual band are not merged in."""
    addr = extract_manufacturer_address([{"tokens": [
        _tok("TOTAL SUGARS"),
        _tok("0g", y=100),
        _tok("WALL ST., CHAKALA", y=105),
        _tok("0%", y=100),
        _tok("-400093,INDIA", y=110),
    ]}])
    assert "SUGARS" not in addr
    assert "0g" not in addr
    assert "400093" in addr


def test_bare_pin_rejected():
    """A lone 6-digit number with no street/city context is not an address."""
    assert extract_manufacturer_address([{"tokens": [_tok("841018")]}]) == ""


def test_empty_when_no_address():
    assert extract_manufacturer_address([], "") == ""
    assert extract_manufacturer_address([{"tokens": [_tok("Cloves"), _tok("20g")]}]) == ""


def test_fallback_splits_manufacturer_value():
    addr = extract_manufacturer_address(
        [], "XYZ Ltd, Regd. Office: 12 MG Road, Bengaluru 560001"
    )
    assert "560001" in addr
    assert "MG Road" in addr


def test_fallback_empty_for_name_only():
    assert extract_manufacturer_address([], "XYZ Pvt Ltd") == ""


def test_run_spanning_two_pin_lines():
    """Adjacent address lines merge into one block (image3-style)."""
    addr = extract_manufacturer_address([{"tokens": [
        _tok("Business Centre, G/F, Wall St., Chakala", y=100),
        _tok("Andheri East, Mumbai - 400093, India", y=140),
    ]}])
    assert "400093" in addr
    assert "Chakala" in addr