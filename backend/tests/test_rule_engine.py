"""Tests for the Legal Metrology rule engine."""
import pytest

from app.core.rule_engine import rule_engine


class TestRequiredDeclarations:
    def test_seven_required_declarations_present(self):
        required = rule_engine.get_required_declarations()
        assert len(required) == 7
        assert "mrp" in required
        assert "net_quantity" in required
        assert "manufacturer_name_address" in required
        assert "month_year_manufacture" in required
        assert "generic_commodity_name" in required
        assert "consumer_care_details" in required
        assert "dimensions_where_relevant" in required


class TestComplianceEvaluation:
    def test_all_compliant_returns_perfect_score(self):
        decl = {
            "manufacturer": "A Pvt Ltd",
            "product_name": "Biscuit",
            "net_quantity": "200 g",
            "manufacturing_date": "MFG: 12/2025",
            "mrp": "MRP Rs. 100/-",
            "consumer_care": "care@a.com",
            "dimensions": "",
        }
        result = rule_engine.evaluate_compliance(decl, missing=[])
        assert result["compliance_score"] == 100.0
        assert result["passed_count"] == result["total_rules"] == 7
        assert result["violations"] == []

    def test_missing_critical_mrp_flags_violation(self):
        decl = {k: "" for k in rule_engine.get_required_declarations()}
        result = rule_engine.evaluate_compliance(decl, missing=["mrp", "net_quantity"])
        assert result["compliance_score"] < 100
        severities = [v["severity"] for v in result["violations"]]
        assert "CRITICAL" in severities

    def test_mrp_without_rupee_symbol_is_format_issue(self):
        decl = {
            "mrp": "MRP 100/-",
            "product_name": "X",
            "manufacturer": "Y",
            "net_quantity": "1 kg",
            "manufacturing_date": "01/2026",
            "consumer_care": "c@y.com",
            "dimensions": "10 cm x 5 cm",
        }
        result = rule_engine.evaluate_compliance(decl, missing=[])
        mrp_violations = [v for v in result["violations"] if v["rule_id"] == "mrp"]
        assert mrp_violations
        assert mrp_violations[0]["status"] == "FORMAT_ISSUE"
        assert "rupee" in mrp_violations[0]["description"].lower() or \
               "currency" in mrp_violations[0]["description"].lower()

    def test_net_quantity_without_unit_is_format_issue(self):
        decl = {
            "mrp": "MRP Rs. 100/-",
            "product_name": "X", "manufacturer": "Y",
            "net_quantity": "100",
            "manufacturing_date": "01/2026",
            "consumer_care": "c@y.com", "dimensions": "",
        }
        result = rule_engine.evaluate_compliance(decl, missing=[])
        nq = [v for v in result["violations"] if v["rule_id"] == "net_quantity"]
        assert nq and nq[0]["status"] == "FORMAT_ISSUE"


class TestMrpValidation:
    def test_accepts_rupee_symbol(self):
        assert rule_engine.validate_mrp_format("MRP ₹ 100/-")[0]
        assert rule_engine.validate_mrp_format("MRP Rs. 100/-")[0]
        assert rule_engine.validate_mrp_format("MRP INR 100")[0]

    def test_rejects_missing_currency(self):
        ok, msg = rule_engine.validate_mrp_format("MRP 100/-")
        assert not ok
        assert "currency" in msg.lower()

    def test_rejects_missing_number(self):
        ok, msg = rule_engine.validate_mrp_format("MRP Rs. only")
        assert not ok
        assert "numeric" in msg.lower()


class TestFontRequirements:
    def test_small_pack_requires_1mm(self):
        rules = rule_engine.rules["font_size_requirements"]["numerals_weight_volume"]
        assert rules[0]["normal"] == 1.0
        assert rules[0]["condition"] == "net_quantity <= 200"

    def test_large_pack_requires_4mm(self):
        rules = rule_engine.rules["font_size_requirements"]["numerals_weight_volume"]
        assert rules[-1]["normal"] == 4.0

class TestMisleadingChecks:
    """USP (unit sale price) cross-checks in the misleading-consistency pass."""

    def test_usp_not_reported_when_matches_mrp_divided_by_qty(self):
        from app.services.inspection_service import _check_misleading

        issues = _check_misleading(
            {
                "mrp": "Rs. 265",
                "usp": "Rs. 5.89 per g",
                "net_quantity": "45 g",
            },
            {},
        )
        checks = [i["check"] for i in issues]
        assert "usp_mismatch_computed" not in checks

    def test_usp_equals_mrp_is_flagged_missing(self):
        from app.services.inspection_service import _check_misleading

        issues = _check_misleading(
            {"mrp": "Rs. 265", "usp": "Rs. 265", "net_quantity": "45 g"}, {}
        )
        assert any(i["check"] == "usp_missing_or_equal_mrp" for i in issues)

    def test_printed_usp_far_off_computed_is_flagged(self):
        from app.services.inspection_service import _check_misleading

        issues = _check_misleading(
            {
                "mrp": "Rs. 265",
                "usp": "USP 1.00/ml",
                "net_quantity": "45 g",
            },
            {},
        )
        assert any(i["check"] == "usp_mismatch_computed" for i in issues)


class TestMergeExtractions:
    """Statutory price block (MRP/USP/net qty) must come from one photo."""

    def test_statutory_block_kept_within_one_photo(self):
        from app.services.inspection_service import merge_extractions

        front = {"mrp": "", "usp": "", "net_quantity": "100 g",
                 "product_name": "NESCAFE CLASSIC"}
        back = {"mrp": "Rs. 265", "usp": "Rs. 5.89 per g", "net_quantity": "45 g",
                "product_name": "NESCAFE CLASSIC"}
        merged = merge_extractions([front, back])
        assert merged["net_quantity"] == "45 g"
        assert merged["mrp"] == "Rs. 265"
        assert merged["usp"] == "Rs. 5.89 per g"

    def test_single_photo_falls_back_to_longest_win(self):
        from app.services.inspection_service import merge_extractions

        a = {"mrp": "", "usp": "", "net_quantity": "45 g"}
        merged = merge_extractions([a])
        assert merged["net_quantity"] == "45 g"
        assert "mrp" not in merged

    def test_no_coherent_block_uses_longest_win(self):
        from app.services.inspection_service import merge_extractions

        a = {"mrp": "Rs. 265", "usp": "", "net_quantity": ""}
        b = {"mrp": "", "usp": "", "net_quantity": "45 g"}
        merged = merge_extractions([a, b])
        assert merged["mrp"] == "Rs. 265"
        assert merged["net_quantity"] == "45 g"
