"""Raw-OCR two-date reconciliation gate tests (inspection_service.py).

Scenario (PS 26034 golden-audit discipline): the SLM can return an inverted
mfg/exp pair (mfg after expiry), file the expiry into mfg leaving expiry blank,
or miss a clearly-printed second date — while the raw OCR token stream carries
both dates. _reconcile_date_ordering repairs these from the raw tokens using the
physical invariant 'manufacture before expiry'.

Guards enforced (0-regression discipline):
  * a healthy ordered pair is never touched;
  * nutrition decimals / times / license numbers never qualify as dates;
  * products with fewer than two clean date tokens are left alone;
  * an impossible golden pair (expiry before mfg) is NOT 'repaired' to match —
    the gate only acts on what the raw OCR physically read and ordered.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.services.inspection_service import merge_extractions  # noqa: E402


def _res(d: dict, tokens: list = None):
    out = {k: v for k, v in d.items() if v is not None}
    if tokens is not None:
        out["tokens"] = [{"text": t, "conf": 0.9, "box": [0, 0, 1, 1]} for t in tokens]
    return out


def _tok(text):
    return {"text": text, "conf": 0.9, "box": [0, 0, 1, 1]}


# ── recovery cases (measured +5 on the golden audit) ─────────────────────────

def test_inverted_pair_repaired_from_raw_ocr_tokens():
    """p15: mfg '12/2025' + exp '01/2025' is physically inverted; raw OCR has
    '01 / 2025' and '12 / 2027' -> repaired to the ordered pair."""
    results = [
        _res({"manufacturing_date": "12/2025", "expiry_date": "01/2025"},
             tokens=["M.R.P.Rs.150.00", "01 / 2025", "12 / 2027"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert merged["manufacturing_date"] == "01/2025"
    assert merged["expiry_date"] == "12/2027"


def test_missing_expiry_filled_from_later_token_date():
    """p20: mfg correct, expiry blank; token stream has Pkd date + a later date
    (OCR mis-tags 'Ue By' vs 'Use By') -> expiry filled from the later date."""
    results = [
        _res({"manufacturing_date": "19/08/26", "expiry_date": ""},
             tokens=["Pkd:19 / 08 / 26", "Ue By:17 / 12 / 26", "MRP55.00"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert merged["manufacturing_date"] == "19/08/26"
    assert merged["expiry_date"] == "17/12/26"


def test_mis_filed_expiry_corrected():
    """p24: mfg holds the expiry date ('15/05/2026') and expiry is blank; raw
    OCR has '16/02/2026' (earlier) + '15/05/2026' (later) -> mfg moved to the
    earlier date, expiry gets the later one."""
    results = [
        _res({"manufacturing_date": "15/05/2026", "expiry_date": ""},
             tokens=["16 / 02 / 2026", "15 / 05 / 2026", "M.R.P.Rs.40.00"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert merged["manufacturing_date"] == "16/02/2026"
    assert merged["expiry_date"] == "15/05/2026"


# ── no-touch guards (0-regression discipline) ────────────────────────────────

def test_healthy_ordered_pair_untouched():
    """A correct mfg < exp pair must never be modified, even with date tokens
    present."""
    results = [
        _res({"manufacturing_date": "07/04/26", "expiry_date": "06/04/27"},
             tokens=["Pkd 07 / 04 / 26 06 / 04 / 27", "MRP ₹100"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert merged["manufacturing_date"] == "07/04/26"
    assert merged["expiry_date"] == "06/04/27"


def test_single_date_token_leaves_pair_alone():
    """Only one clean date in the token stream -> cannot order a pair, no-op."""
    results = [
        _res({"manufacturing_date": "2023", "expiry_date": ""},
             tokens=["Regd.Office&Consumerell:8 / 3", "Toll Free: 1800-103-1644"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert (merged.get("manufacturing_date") or "") == "2023"
    assert (merged.get("expiry_date") or "") == ""


def test_no_tokens_no_effect():
    """Result dicts without a tokens key (all existing test stubs) no-op."""
    results = [
        {"manufacturing_date": "12/2025", "expiry_date": "01/2025"},
    ]
    merged = merge_extractions(results, ["back"])
    assert merged["manufacturing_date"] == "12/2025"
    assert merged["expiry_date"] == "01/2025"


def test_nutrition_decimals_never_qualify_as_dates():
    """0.71 / 2.68g / 46.00g must not become date candidates (they have no
    numeric month in 1-12 after parse_date)."""
    results = [
        _res({"manufacturing_date": "", "expiry_date": ""},
             tokens=["0.71", "2.68g", "46.00g", "15.00perkgin Maarashtraonly"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert (merged.get("manufacturing_date") or "") == ""
    assert (merged.get("expiry_date") or "") == ""


def test_batch_glue_and_times_not_dates():
    """'0626LC001662450 / 00' (batch), '10:00am' (time) and '85/8' (junk pairs)
    must not qualify — no month name, no 4-digit year, no date keyword."""
    results = [
        _res({"manufacturing_date": "", "expiry_date": ""},
             tokens=["0626LC001662450 / 00", "Tlme:10:00am to 5:00pm",
                     "Net Wt.:145g / 5.110z"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert (merged.get("manufacturing_date") or "") == ""
    assert (merged.get("expiry_date") or "") == ""


def test_impossible_golden_pair_not_forced_from_no_evidence():
    """p23-style: golden says exp before mfg (physical impossibility); raw OCR
    has no keyword/4-digit-year-qualified dates -> gate stays silent rather than
    inventing values that contradict the label evidence."""
    results = [
        _res({"manufacturing_date": "", "expiry_date": ""},
             tokens=["25.12.26", "28.06.26", "Rs.109.00"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert (merged.get("manufacturing_date") or "") == ""
    assert (merged.get("expiry_date") or "") == ""


def test_month_name_dates_qualify_without_keyword():
    """Month-name forms ('MAR / 2025', 'AUG / 2027') qualify on their own and
    can drive a repair."""
    results = [
        _res({"manufacturing_date": "MAR/2027", "expiry_date": "MAR/2025"},
             tokens=["07MAR / 2025", "06MAR / 2027", "MRP ₹120"]),
    ]
    merged = merge_extractions(results, ["back"])
    assert merged["manufacturing_date"] == "MAR/2025"
    assert merged["expiry_date"] == "MAR/2027"


def test_longer_string_wins_unaffected_when_ordered():
    """Sanity: many-date recipes still merge by longest-wins; the gate only
    adjusts the pair, never other fields."""
    results = [
        {"product_name": "short", "manufacturing_date": "01/2026",
         "expiry_date": "01/2027", "mrp": "MRP Rs.50"},
        {"product_name": "The Long Product Name", "manufacturing_date": "01/2026",
         "expiry_date": "01/2027"},
    ]
    merged = merge_extractions(results)
    assert merged["product_name"] == "The Long Product Name"
    assert merged["manufacturing_date"] == "01/2026"
    assert merged["expiry_date"] == "01/2027"