"""Compliance scoring model — turns rule results into a weighted radar chart
plus an overall grade (A/B/C) that non-technical officials can read at a glance.

Axis definitions (0-100 each):
  declarations  — presence of all 7 statutory declarations
  pricing       — MRP format + USP consistency
  process_dates — manufacturing/expiry dates
  consumer_care — consumer contact presence
  readability   — OCR confidence/legibility proxy
"""
from typing import Dict, List, Optional


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _pct(condition: bool) -> float:
    return 100.0 if condition else 0.0


def build_radar(
    declarations: Dict,
    missing: List[str],
    violations: List[Dict],
    ocr_meta: Optional[Dict] = None,
) -> Dict:
    REQUIRED = {
        "manufacturer_name_address", "generic_commodity_name", "net_quantity",
        "month_year_manufacture", "mrp", "consumer_care_details",
    }
    present = len(REQUIRED - set(missing))
    declarations_score = _clamp(round(present * 100.0 / len(REQUIRED), 1))

    mrp = str(declarations.get("mrp", "") or "")
    usp = str(declarations.get("usp", "") or "")
    mrp_ok = bool(mrp) and ("₹" in mrp or "rs" in mrp.lower() or "inr" in mrp.lower())
    usp_ok = bool(usp)
    pricing_score = _clamp(round(mrp_ok * 55.0 + usp_ok * 45.0, 1)) if (mrp or usp) else 0.0

    mfg = str(declarations.get("manufacturing_date", "") or "")
    exp = str(declarations.get("expiry_date", "") or "")
    date_score = _clamp(round(_pct(bool(mfg)) * 0.6 + _pct(bool(exp)) * 0.4, 1))

    care = str(declarations.get("consumer_care", "") or "")
    care_score = _clamp(round(60.0 + (40.0 if ("@" in care or care.strip()) else 0.0), 1))

    avg_conf = (ocr_meta or {}).get("confidence")
    if isinstance(avg_conf, (int, float)) and avg_conf > 0:
        readability_score = _clamp(round(avg_conf * 100.0, 1))
    else:
        readability_score = 50.0

    # Weights rescaled proportionally after the font-size axis was removed,
    # keeping the same relative importance of the remaining axes (sum = 1.0).
    axes = [
        {"axis": "Declarations", "score": round(declarations_score, 1), "weight": 0.375},
        {"axis": "Pricing", "score": round(pricing_score, 1), "weight": 0.25},
        {"axis": "Dates", "score": round(date_score, 1), "weight": 0.125},
        {"axis": "Consumer Care", "score": round(care_score, 1), "weight": 0.125},
        {"axis": "Readability", "score": round(readability_score, 1), "weight": 0.125},
    ]
    known = [a for a in axes if a["score"] is not None]
    total_w = sum(a["weight"] for a in known) or 1e-6
    overall = sum(a["score"] * a["weight"] for a in known) / total_w
    overall = round(_clamp(overall), 1)

    rule_score = round(overall, 1)

    if overall >= 85:
        grade = "A"
        grade_label = "Highly Compliant"
    elif overall >= 70:
        grade = "B"
        grade_label = "Minor Violations"
    elif overall >= 50:
        grade = "C"
        grade_label = "Significant Violations"
    else:
        grade = "D"
        grade_label = "Non-Compliant"

    return {
        "overall": overall,
        "grade": grade,
        "grade_label": grade_label,
        "axes": axes,
    }