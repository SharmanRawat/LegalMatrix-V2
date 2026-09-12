"""Tests for the price engine (USP validation)."""
from app.services.price_engine import price_engine


class TestCalculateUsp:
    def test_grams_below_1kg_price_per_g(self):
        usp, unit = price_engine.calculate_usp(mrp=100, net_quantity=200, unit="g")
        assert unit == "g"
        assert usp == 0.5

    def test_kg_and_above(self):
        usp, unit = price_engine.calculate_usp(mrp=200, net_quantity=1000, unit="g")
        assert unit == "kg"
        assert usp == 200

    def test_ml(self):
        usp, unit = price_engine.calculate_usp(mrp=50, net_quantity=250, unit="ml")
        assert unit == "ml"
        assert usp == 0.2

    def test_invalid_quantity(self):
        usp, msg = price_engine.calculate_usp(mrp=10, net_quantity=0, unit="g")
        assert usp is None
        assert "Invalid" in msg


class TestValidateUsp:
    def test_match_within_tolerance(self):
        assert price_engine.validate_usp(0.5, 0.5)[0]

    def test_mismatch(self):
        is_valid, diff, status = price_engine.validate_usp(3.0, 0.5)
        assert not is_valid
        assert status == "MISMATCH"

    def test_missing_usp(self):
        assert price_engine.validate_usp(None, 0.5)[2] == "MISSING_USP"


class TestUspExemption:
    def test_mrp_equals_usp_is_exempt(self):
        assert price_engine.check_usp_exemption(100, 100)
        assert not price_engine.check_usp_exemption(100, 99.5)


class TestUspTextParsing:
    def test_extract_number(self):
        assert price_engine.calculate_usp_from_text("USP ₹0.50/g", None) == 0.50

    def test_extract_unit(self):
        assert price_engine.extract_unit_from_usp("USP ₹0.50/g") == "g"
        assert price_engine.extract_unit_from_usp("USP ₹100 per ml") == "ml"
        assert price_engine.extract_unit_from_usp("USP ₹100") is None