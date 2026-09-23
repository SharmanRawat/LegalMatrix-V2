"""Post-merge sanity gates (inspection_service.py merge_extractions):
shelf-life notes are not expiries, absurd net quantities are misreads, and
CJK consumer-care lines are recognizer noise — all blank to NOT DETECTED.
Every gate was scan-verified 0-hit against the frozen 72-image cache before
shipping, so the 238-cell golden baseline cannot move.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.services.inspection_service import merge_extractions  # noqa: E402


def test_shelf_life_not_expiry():
    """'5Yrs from DEC/2024' / '6 MONTHS FROM MANUFACTURE' are durations, not
    an expiry declaration -> blanked."""
    results = [
        {"expiry_date": "5Yrs from DEC/2024", "manufacturing_date": "DEC/2024"},
    ]
    merged = merge_extractions(results, ["back"])
    assert merged.get("expiry_date", "") == ""
    assert merged.get("manufacturing_date", "") == "DEC/2024"

    results = [{"expiry_date": "6 MONTHS FROM MANUFACTURE"}]
    merged = merge_extractions(results, ["back"])
    assert merged.get("expiry_date", "") == ""


def test_real_expiry_survives():
    results = [{"expiry_date": "12/2026"}]
    merged = merge_extractions(results, ["back"])
    assert merged["expiry_date"] == "12/2026"


def test_absurd_net_quantity_blanked():
    """'81904117114016321 l' is a barcode misread, not a declaration."""
    results = [{"net_quantity": "81904117114016321 l"}]
    merged = merge_extractions(results, ["back"])
    assert merged.get("net_quantity", "") == ""


def test_legitimate_net_quantity_survives():
    results = [{"net_quantity": "200 ml (182 g)"}]
    merged = merge_extractions(results, ["back"])
    assert merged["net_quantity"] == "200 ml (182 g)"


def test_count_unit_net_quantity_survives():
    # Rule 6(1)(c) count-unit declarations ('200 N' cotton swabs) must not be
    # confused with the absurd magnitude misreads that the gate blanks.
    results = [{"net_quantity": "200N"}]
    merged = merge_extractions(results, ["back"])
    assert merged.get("net_quantity", "") == "200N"


def test_cjk_consumer_care_blanked():
    """'电话0-08-07-...' is recognizer noise on an Indian label, not a valid
    contact channel."""
    results = [{"consumer_care": "电话0-08-07-AACM74336-22"}]
    merged = merge_extractions(results, ["back"])
    assert merged.get("consumer_care", "") == ""


def test_valid_consumer_care_survives():
    results = [{"consumer_care": "9356594585, info@sawariya.in"}]
    merged = merge_extractions(results, ["back"])
    assert merged["consumer_care"] == "9356594585, info@sawariya.in"