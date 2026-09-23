"""Merge-level non-edible commodity fallback (inspection_service.py).

The 3B SLM leaves 'edible' blank on cosmetics / toiletries / non-edible
household goods: their labels never print an explicit 'non-edible' marker,
so the edibility honesty gate (ocr_engine) clears any unevidenced verdict and
the SLM itself usually returns ''. The merge supplies a deterministic 'no'
ONLY when the raw OCR token stream across all photos carries an unambiguous
non-food product-type phrase ('DEODORANT', 'PARFUM', 'COTTON SWABS',
'SUNSCREEN'...) — the verdict is evidence-backed, never a guess, and never
overrides an SLM verdict.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.services.inspection_service import (  # noqa: E402
    _NON_FOOD_RE,
    _non_food_evidence,
    merge_extractions,
)


def _res(d: dict):
    return {k: v for k, v in d.items() if v is not None}


def test_non_food_vocabulary_covers_the_new_product_class():
    """Every phrase from the new-images audit (perfume/deodorant/swabs/
    sunscreen) must be recognised."""
    for phrase in ("EAU DE PARFUM", "DEODORANT", "COTTON SWABS",
                   "Sunscreen Body Lotion", "Body lotion", "For external use",
                   "not meant for consumption"):
        assert _NON_FOOD_RE.search(phrase), phrase


def test_blank_edible_filled_no_when_vocabulary_present():
    """Empty verdict + 'DEODORANT' on the back panel -> 'no'."""
    results = [
        {"product_name": "BRUT ORIGINAL", "edible": "",
         "tokens": [{"text": "DEODORANT"}]},
        {"mrp": "MRP RS. 325.00", "expiry_date": "12/2024",
         "tokens": [{"text": "USE BEFORE: 12/2024"}]},
    ]
    merged = merge_extractions(results, ["front", "back"])
    assert merged["edible"] == "no"


def test_blank_edible_stays_blank_without_vocabulary():
    """A blank verdict and no non-food evidence must stay NOT DETECTED —
    the merge must not invent an edibility class."""
    results = [
        {"product_name": "Parachute Pure", "edible": "",
         "tokens": [{"text": "100% PURE COCONUT OIL"}]},
    ]
    merged = merge_extractions(results, ["front"])
    assert merged.get("edible", "") in ("", None)


def test_slm_yes_verdict_not_overridden():
    """A surviving 'yes' (food vocabulary on a food label) must never flip
    to 'no', even if a stray word matches the vocabulary."""
    results = [
        {"product_name": "Milk", "edible": "yes",
         "tokens": [{"text": "FRESH WHOLE MILK"}]},
    ]
    merged = merge_extractions(results, ["front"])
    assert merged["edible"] == "yes"


def test_slm_no_verdict_not_overridden():
    results = [
        {"product_name": "Soap", "edible": "no",
         "tokens": [{"text": "PURE SOAP BAR"}]},
    ]
    merged = merge_extractions(results, ["front"])
    assert merged["edible"] == "no"


def test_evidence_scanner_accepts_plain_string_tokens():
    """_non_food_evidence must tolerate both dict tokens and plain strings
    (the two shapes seen across OCR outputs)."""
    assert _non_food_evidence([{"tokens": ["SPF50", "SUNSCREEN"]}])
    assert not _non_food_evidence([{"tokens": ["COCONUT OIL"]}, None])
    assert not _non_food_evidence([{}])