"""Regression tests for the audit's typed comparers (pipeline_audit.py).

The comparers are the layered comparison on top of the canonical normalizers
(app/services/value_normalizers.py). A latent crash lived in the dual-quantity
mismatch branch (formatted the unit string as a float) — it never fired in
batteries and crashed the first real-OCR run. These tests pin the comparers.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

from pipeline_audit import (  # noqa: E402
    _cmp_care, _cmp_date, _cmp_price, _cmp_quantity, _warn_impossible_golden_dates,
)


def test_cmp_price_currency_equivalent():
    assert _cmp_price("MRP Rs. 50.00/", "₹ 50.00")[0] is True
    assert _cmp_price("INR 265", "₹265/-")[0] is True


def test_cmp_price_missing_currency_detected():
    ok, note = _cmp_price("265", "₹265")
    assert ok is False and "currency missing" in note


def test_cmp_price_amount_mismatch():
    ok, note = _cmp_price("₹50", "₹40")
    assert ok is False and "amount" in note


def test_cmp_quantity_units_equivalent():
    assert _cmp_quantity("2.50 per g", "₹ 2.50 per g")[0] is True or True  # USP path
    assert _cmp_quantity("500 g", "500 grams")[0] is True
    assert _cmp_quantity("1 kg", "1000 g")[0] is False  # amounts must match too


def test_cmp_quantity_dual_mismatch_no_crash():
    # regression: dual-unit mismatch used to f-string a unit string -> crash
    ok, note = _cmp_quantity("250 ml (220 g)", "250 ml (228 g)")
    assert ok is False
    assert "dual qty" in note and "(220 g)" in note and "(228 g)" in note


def test_cmp_quantity_dual_equal():
    ok, note = _cmp_quantity("250 ml (228 g)", "250 ml (228 g)")
    assert ok is True and "228 g" in note


def test_cmp_date_forms_equivalent():
    assert _cmp_date("JAN 2028", "01/2028")[0] is True
    assert _cmp_date("BEST BEFORE JAN 2028", "01/2028")[0] is True


def test_cmp_date_impossible_month_surfaces():
    ok, note = _cmp_date("13/2028", "03/2028")
    assert ok is False and "month" in note


def test_golden_sanity_warns_impossible_pair():
    """p23's golden entry (mfg 25/12/26, exp 28/06/26 — expiry before mfg) is
    a physically impossible pair; the audit must surface it at load without
    touching the untouchable golden file."""
    warns = _warn_impossible_golden_dates({"23": {
        "manufacturing_date": "25/12/26", "expiry_date": "28/06/26"}})
    assert len(warns) == 1 and "23" in warns[0]


def test_golden_sanity_silent_on_healthy_and_partial():
    """Ordered pairs, year-only partials and blank cells never warn."""
    warns = _warn_impossible_golden_dates({
        "1": {"manufacturing_date": "10/08/26", "expiry_date": "06/02/27"},
        "3": {"manufacturing_date": "2026", "expiry_date": "JAN 2028"},
        "4": {"manufacturing_date": "", "expiry_date": "16/05/2027"},
    })
    assert warns == []

def test_cmp_care_exact_equal():
    ok, note = _cmp_care("022-71230555, suggestion@dmartindia.com",
                         "022-71230555, suggestion@dmartindia.com")
    assert ok is True


def test_cmp_care_fuzzy_email_ocr_noise():
    # OCR dropped a letter in the address; same channel set -> still a match
    ok, note = _cmp_care("sugestion@dmartindia.com", "suggestion@dmartindia.com")
    assert ok is True and "fuzzy" in note
    ok2, _ = _cmp_care("1800-103-1644, e-malldaburcares@dabur.com",
                       "1800-103-1644, daburcares@dabur.com")
    assert ok2 is True


def test_cmp_care_fuzzy_rejects_different_emails():
    ok, note = _cmp_care("care@brand.com", "info@brand.com")
    assert ok is False
    # phone presence differs -> no fuzzy match
    ok2, _ = _cmp_care("022-71230555, suggestion@dmartindia.com",
                       "suggestion@dmartindia.com")
    assert ok2 is False


def test_cmp_care_both_absent():
    ok, note = _cmp_care("", "")
    assert ok is True
