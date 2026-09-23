import json
from pathlib import Path
import re
from typing import Dict, List, Optional


class RuleEngine:
    RULE_DETAILS = {
        "manufacturer_name_address": {
            "rule_no": "Rule 6(1)(a)",
            "description": "Name and address of the manufacturer, importer, or marketer must be declared on the principal display panel.",
            "severity": "CRITICAL",
            "remediation": "Add the full name and registered address of the manufacturer/importer on the label.",
        },
        "generic_commodity_name": {
            "rule_no": "Rule 6(1)(b)",
            "description": "Generic name of the commodity (e.g. 'Honey', 'Sunflower Oil') must be printed on the label.",
            "severity": "CRITICAL",
            "remediation": "Print the common/commodity name prominently on the principal display panel.",
        },
        "net_quantity": {
            "rule_no": "Rule 6(1)(c)",
            "description": "Net quantity by weight, measure, or number must be declared. For liquids, volume at 20°C.",
            "severity": "CRITICAL",
            "remediation": "Declare net quantity using SI/metric units (g, kg, ml, L) on the label.",
        },
        "month_year_manufacture": {
            "rule_no": "Rule 6(1)(d)",
            "description": "Month and year of manufacture or preponement/combination must be declared.",
            "severity": "HIGH",
            "remediation": "Add manufacturing date in 'MMM/YYYY' or 'MM/YYYY' format on the label.",
        },
        "mrp": {
            "rule_no": "Rule 6(1)(e)",
            "description": "Maximum Retail Price inclusive of all taxes must be declared. Format: 'MRP Rs.XX' or 'MRP ₹XX'.",
            "severity": "CRITICAL",
            "remediation": "Print MRP in Indian Rupees (₹) including all applicable taxes.",
        },
        "consumer_care_details": {
            "rule_no": "Rule 6(2)",
            "description": "Consumer care details including name, address, email, and/or phone number must be provided.",
            "severity": "HIGH",
            "remediation": "Add consumer complaint email and/or toll-free phone number on the label.",
        },
        "dimensions_where_relevant": {
            "rule_no": "Rule 6(1)(f)",
            "description": "Dimensions (length, width, height) must be declared where the sizes of the commodity are relevant (operationalized: non-edible commodities sold by length or area, e.g. garments, cables, electronics). Commodities sold by count (N/nos/pcs) or by weight/volume are exempt; edible products are exempt.",
            "severity": "MEDIUM",
            "remediation": "Declare dimensions in cm/inches for non-edible commodities sold by length or area.",
        },
    }

    def __init__(self):
        self.rules = self._load_rules()
        self.version = self.rules.get("rule_version", "unknown")

    def _load_rules(self):
        rules_path = Path(__file__).resolve().parent.parent / "data" / "rules.json"
        with open(rules_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_required_declarations(self):
        return self.rules.get("declarations_required", [])

    def evaluate_compliance(
        self,
        declarations: Dict[str, str],
        missing: List[str],
        currency_verified: Optional[Dict[str, bool]] = None,
    ) -> Dict:
        """Return compliance_score, violations list, and summary.

        currency_verified: {field: True} for price fields whose currency
        symbol was visually confirmed on the label (VLM dropped the ₹/Rs.
        glyph during OCR though the print carries it)."""
        total_rules = len(self.get_required_declarations())
        if total_rules == 0:
            return {"compliance_score": 100, "violations": [], "passed_count": 0, "total_rules": 0}

        violations = []
        for req in self.get_required_declarations():
            detail = self.RULE_DETAILS.get(req, {})
            field = self._rule_to_field(req)
            value = declarations.get(field, "") if field else ""

            if req in missing:
                violations.append({
                    "rule_id": req,
                    "rule_no": detail.get("rule_no", "N/A"),
                    "severity": detail.get("severity", "HIGH"),
                    "status": "MISSING",
                    "field": field,
                    "extracted_value": value,
                    "description": detail.get("description", req.replace("_", " ").title()),
                    "remediation": detail.get("remediation", ""),
                })
            else:
                # Field present — do format checks
                fmt_issues = self._check_format(req, value, currency_verified=currency_verified)
                if fmt_issues:
                    violations.append({
                        "rule_id": req,
                        "rule_no": detail.get("rule_no", "N/A"),
                        "severity": detail.get("severity", "MEDIUM"),
                        "status": "FORMAT_ISSUE",
                        "field": field,
                        "extracted_value": value,
                        "description": fmt_issues,
                        "remediation": detail.get("remediation", ""),
                    })

        passed = total_rules - len(violations)
        score = round((passed / total_rules) * 100, 1) if total_rules > 0 else 100

        return {
            "compliance_score": score,
            "passed_count": passed,
            "total_rules": total_rules,
            "violations": violations,
        }

    @staticmethod
    def _rule_to_field(req: str) -> Optional[str]:
        mapping = {
            "manufacturer_name_address": "manufacturer",
            "generic_commodity_name": "product_name",
            "net_quantity": "net_quantity",
            "month_year_manufacture": "manufacturing_date",
            "mrp": "mrp",
            "consumer_care_details": "consumer_care",
            "dimensions_where_relevant": "dimensions",
        }
        return mapping.get(req)

    def _check_format(self, rule_id: str, value: str, currency_verified: Optional[Dict[str, bool]] = None) -> Optional[str]:
        if not value or not value.strip():
            return None

        if rule_id == "mrp":
            ok, msg = self.validate_mrp_format(
                value, symbol_verified=bool((currency_verified or {}).get("mrp"))
            )
            if not ok:
                return msg

        if rule_id == "net_quantity":
            if not re.search(r'\d', value):
                return "Net quantity should contain a numeric value"
            # SI mass/volume units (weight, measure) or count units (number):
            # rule 6(1)(c) accepts net quantity by weight, measure OR number.
            if not re.search(
                r'(g|kg|ml|l|gm|cm|m|ml|ltr|litre)', value, re.IGNORECASE
            ) and not re.search(r'\d\s*(?:n|nos?|no\.?|pcs?|pieces?|count)\b', value, re.IGNORECASE):
                return "Net quantity should specify a unit (g, kg, ml, L) or count unit (N, nos)"

        if rule_id == "month_year_manufacture":
            if not re.search(r'\d{4}', value) and not re.search(r'\d{2}/\d{2}', value):
                return "Manufacturing date should include month and year"

        return None

    def get_font_requirements(self, net_quantity: float):
        numerals = self.rules.get("font_size_requirements", {}).get("numerals_weight_volume", [])
        for rule in numerals:
            condition = rule.get("condition", "")
            if "<= " in condition:
                _, limit = condition.split("<= ")
                if net_quantity <= float(limit):
                    return {"normal": rule.get("normal"), "embossed": rule.get("embossed")}
            elif "> " in condition and "<=" in condition:
                parts = condition.split("AND")
                lower = float(parts[0].split("> ")[1])
                upper = float(parts[1].split("<= ")[1])
                if lower < net_quantity <= upper:
                    return {"normal": rule.get("normal"), "embossed": rule.get("embossed")}
        return {"normal": None, "embossed": None}

    def validate_mrp_format(self, mrp_text, symbol_verified=False):
        if not mrp_text:
            return False, "MRP not found"
        has_symbol = "₹" in mrp_text or "rs" in mrp_text.lower() or "inr" in mrp_text.lower()
        if not symbol_verified and not has_symbol:
            return False, "MRP should use Indian currency symbol (₹ or Rs.)"
        if not re.search(r'\d+', mrp_text):
            return False, "MRP should contain a numeric value"
        return True, "MRP format is correct"

    def validate_usp_format(self, usp_text):
        if not usp_text:
            return False, "USP not found"
        if not re.search(r'\d+', usp_text):
            return False, "USP should contain a numeric value"
        if not re.search(r'(g|ml|kg|l|gm|cm|m)', usp_text, re.IGNORECASE):
            return False, "USP should specify the unit"
        return True, "USP format is correct"


rule_engine = RuleEngine()
