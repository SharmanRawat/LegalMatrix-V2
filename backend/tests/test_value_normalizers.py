"""Unit tests for app/services/value_normalizers.py — the canonical
legal-equivalence primitives shared by the audit, merge, rules and classifier
code.

Contract under test: two surface forms of a statutory field are legally
equivalent iff their canonical key is equal (₹150/- == Rs. 150 == INR 150,
JAN 2028 == 01/2028, Ltd. == Limited, 250 g == 250 grams).
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))  # for pipeline_audit import

from app.services import value_normalizers as vn  # noqa: E402


# ── mrp / usp ────────────────────────────────────────────────────────────────
def test_parse_price_currency_forms_equivalent():
    assert vn.parse_price("₹265/-") == (265.0, True, None)
    assert vn.parse_price("Rs. 265") == (265.0, True, None)
    assert vn.parse_price("INR 265") == (265.0, True, None)
    assert vn.parse_price("rupees 265") == (265.0, True, None)
    # the canonical key is identical -> legally equivalent
    assert (vn.parse_price("₹265/-") == vn.parse_price("Rs. 265")
            == vn.parse_price("INR 265"))


def test_parse_price_missing_currency_is_distinguishable():
    # Rule 6(1)(e): MRP without a currency marker is an offence; the key must
    # keep that signal so callers can tell "265" from "₹265".
    assert vn.parse_price("265") == (265.0, False, None)
    assert vn.parse_price("Rs. 265") != vn.parse_price("265")


def test_parse_price_decimal_and_unit():
    assert vn.parse_price("USP Rs. 5.89 per g") == (5.89, True, "g")
    assert vn.parse_price("USP Rs. 5.89/g") == (5.89, True, "g")
    assert vn.parse_price("MRP ₹410.00") == (410.0, True, None)
    assert vn.parse_price("Rs. 5.89 per 100 g") == (5.89, True, "g")


def test_parse_price_separators_and_no_amount():
    assert vn.amount("Rs. 10,000") == 10000.0          # western grouping
    assert vn.parse_price("abc") == (None, False, None)
    assert vn.amount("no numbers here") is None


# ── net_quantity ─────────────────────────────────────────────────────────────
def test_parse_quantity_units_normalized():
    assert vn.parse_quantity("500 g") == [(500.0, "g")]
    assert vn.parse_quantity("5 pieces") == [(5.0, "pc")]     # plural -> pc
    assert vn.parse_quantity("2 kilograms") == [(2.0, "kg")]


def test_parse_quantity_dual_units():
    assert vn.parse_quantity("250 ml (228 g)") == [(250.0, "ml"), (228.0, "g")]


def test_parse_quantity_skips_incidental_tokens():
    assert vn.parse_quantity("NETQTY 250 ml") == [(250.0, "ml")]   # 'netqty' skipped
    assert vn.parse_quantity("GLYCEMIC 25 g") == [(25.0, "g")]     # 'glycemic' skipped


def test_quantity_key_equivalence():
    assert vn.quantity_key("250 ml") == vn.quantity_key("250 millilitres")
    assert vn.quantity_key("500 g") == vn.quantity_key("500 grams")
    assert vn.quantity_key("0 g") == ((0.0, "g"),)                 # 0 signals nutrition-row leak


# ── manufacturing / expiry dates ─────────────────────────────────────────────
def test_parse_date_equivalences():
    assert vn.parse_date("JAN 2028") == (2028, 1)
    assert vn.parse_date("01/2028") == (2028, 1)
    assert vn.parse_date("JANUARY 2028") == (2028, 1)
    assert (vn.parse_date("JAN 2028") == vn.parse_date("01/2028")
            == vn.parse_date("JANUARY 2028"))


def test_parse_date_noise_and_bare_year():
    assert vn.parse_date("BEST BEFORE JAN 2028") == (2028, 1)   # heading noise stripped
    assert vn.parse_date("MFG: 3/2026") == (2026, 3)
    assert vn.parse_date("2028") == (2028, None)


def test_parse_date_two_digit_year_and_impossible_month():
    assert vn.parse_date("06/04/27") == (2027, 4)               # dd/mm/yy
    # impossible months are SURFACED (13), not silently dropped, so strict
    # callers can flag them — this is what triage relies on.
    assert vn.parse_date("13/2028") == (2028, 13)


def test_parse_date_no_space_and_compact_ocr_forms():
    # OCR frequently drops the space: '07MAR/2025' must read March, not
    # day-as-month; 'JUN25'/'FEB25'/'JAN27' must keep their month. This was a
    # word-boundary bug (\b fails between a digit and the month word).
    assert vn.parse_date("07MAR/2025") == (2025, 3)
    assert vn.parse_date("04AUG/2025") == (2025, 8)
    assert vn.parse_date("JUN25") == (2025, 6)
    assert vn.parse_date("FEB25") == (2025, 2)
    assert vn.parse_date("JAN27") == (2027, 1)
    assert vn.parse_date("AUG26") == (2026, 8)
    assert vn.parse_date("JAN25") == (2025, 1)
    assert vn.parse_date("AUG25") == (2025, 8)
    # ...but words that merely CONTAIN a month must not false-match
    assert vn.parse_date("MARCHING") == (None, None)
    assert vn.parse_date("JANITOR") == (None, None)
    assert vn.parse_date("DECOR") == (None, None)


def test_parse_date_empty():
    assert vn.parse_date("") == (None, None)
    assert vn.parse_date("not a date") == (None, None)


# ── product_name / manufacturer ──────────────────────────────────────────────
def test_name_tokens_corporate_suffix_equivalence():
    assert vn.name_tokens("Patanjali Foods Limited") == vn.name_tokens(
        "PATANJALI FOODS PVT. LTD.")
    assert vn.name_tokens("Tata Chemicals Limited") == vn.name_tokens(
        "Tata Chemicals Pvt Ltd")
    assert "ltd" not in vn.name_tokens("Acme Ltd")
    assert vn.name_tokens("Acme Ltd") == frozenset({"acme"})


def test_name_tokens_keeps_brand_content():
    s = vn.name_tokens("FIGARO IMPORTED EXTRA VIRGIN OLIVE OIL")
    assert not (s - {"figaro", "imported", "extra", "virgin", "olive", "oil"})


# ── consumer_care ────────────────────────────────────────────────────────────
def test_care_key_email_phone():
    assert vn.care_key("care@figaro.com 1800-123-456") == "care@figaro.com+tel"
    assert vn.care_key("1800-123-456") == "+tel"
    assert vn.care_key("care@figaro.com") == "care@figaro.com"
    assert vn.care_key("") == ""


def test_care_key_phone_spelling_equivalent():
    assert vn.care_key("1800 123 456") == vn.care_key("1800-123-456")


def test_care_key_emails_sorted():
    assert vn.care_key("b@x.com a@x.com") == "a@x.comb@x.com"


def test_emails_and_phones():
    assert vn.emails("call a@b.com or c@d.com") == {"a@b.com", "c@d.com"}
    assert vn.phones("98765 43210") == {"9876543210"}
    assert vn.phones("no digits here") == set()


# ── dimensions ───────────────────────────────────────────────────────────────
def test_dimensions_key():
    assert vn.dimensions_key("10 cm X 5 cm X 20 cm") == frozenset({"10", "5", "20"})
    assert vn.dimensions_key("10x5") == vn.dimensions_key("10 cm X 5 cm")
    assert vn.dimensions_key("") == frozenset()


# ── edible ───────────────────────────────────────────────────────────────────
def test_edibility_key():
    assert vn.edibility_key("yes") == "yes"
    assert vn.edibility_key("Yes.") == "yes"
    assert vn.edibility_key("no") == "no"
    assert vn.edibility_key("maybe") == "maybe"
    assert vn.edibility_key("") == ""


# ── tokens ───────────────────────────────────────────────────────────────────
def test_tokens():
    assert vn.tokens("FIGARO Imported Oil!") == frozenset({"figaro", "imported", "oil"})


# ── single source of truth: the audit must use the SAME functions ────────────
def test_pipeline_audit_imports_the_canonical_module():
    import pipeline_audit as pa

    assert pa._parse_price is vn.parse_price
    assert pa._parse_quantity is vn.parse_quantity
    assert pa._parse_date is vn.parse_date
    assert pa._tokens is vn.tokens
    assert pa._phones is vn.phones
    assert pa._care_key is vn.care_key
    assert pa._name_tokens is vn.name_tokens
    assert pa._edibility_key is vn.edibility_key