"""MRP-only guarded VLM rescue (vlm_rescuer.guarded_mrp_rescue / parse_mrp_answer).

Guards under test:
1. parse_mrp_answer accepts ONLY a price with a currency marker, no per-unit
   suffix, amount >= MRP_PLAUSIBLE_FLOOR (₹1); everything else -> None.
2. guarded_mrp_rescue fires ONLY when MRP is empty / sub-rupee.
3. It writes ONLY the mrp cell — dates / care / manufacturer never touched.
4. It probes photos in declaration-face order and never mutates its input.
"""
import pytest

from app.services.vlm_rescuer import (
    guarded_mrp_rescue,
    parse_mrp_answer,
)


# ── parse_mrp_answer ────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("Rs. 119/-", "MRP Rs. 119"),
    ("MRP ₹ 440.00", "MRP Rs. 440"),
    ("180 RS", "MRP Rs. 180"),
    ("MRP Rs. 49.50", "MRP Rs. 49.50"),
    ('  "MRP Rs. 35"  ', "MRP Rs. 35"),   # stray quotes/whitespace
    ("MRP ₹ 83.00", "MRP Rs. 83"),
])
def test_parse_mrp_answer_accepts_valid_prices(raw, expected):
    assert parse_mrp_answer(raw) == expected


@pytest.mark.parametrize("raw", [
    "",                   # empty
    "NONE",               # explicit no-price escape
    "none",               # case-insensitive
    "no printed price",   # prose refusal
    "some random text",   # no amount at all
    "440",                # bare amount, no currency marker (Rule 6(1)(e))
    "Rs. 2/g",            # per-unit USP line, not an MRP
    "Rs. 0.31",           # sub-rupee — structurally implausible (p23 digit loss)
    "MRP Rs. 0",
    "₹ 0.50",
])
def test_parse_mrp_answer_rejects_non_mrp(raw):
    assert parse_mrp_answer(raw) is None


# ── guarded_mrp_rescue ──────────────────────────────────────────────────────
FRONT = "/imgs/x_front.jpg"
BACK = "/imgs/x_back.jpg"


def test_leave_plausible_mrp_untouched():
    merged = {"mrp": "MRP Rs. 50.00", "expiry_date": "31/12/2027"}
    out = guarded_mrp_rescue(merged, [FRONT, BACK], ["front", "back"],
                             read_mrp=lambda p: "MRP Rs. 999.00")
    assert out["mrp"] == "MRP Rs. 50.00"


def test_fill_empty_mrp_and_never_touch_other_fields():
    merged = {"mrp": "", "expiry_date": "08/2026", "manufacturer": "ACME Ltd"}
    def fake(path):
        return "MRP Rs. 119" if path == BACK else None
    out = guarded_mrp_rescue(merged, [FRONT, BACK], ["front", "back"],
                             read_mrp=fake)
    assert out["mrp"] == "MRP Rs. 119"
    assert out["expiry_date"] == "08/2026"
    assert out["manufacturer"] == "ACME Ltd"


def test_back_photo_probed_before_front():
    merged = {"mrp": ""}
    probed = []
    def fake(path):
        probed.append(path)
        return None
    guarded_mrp_rescue(merged, [FRONT, BACK], ["front", "back"], read_mrp=fake)
    assert probed == [BACK, FRONT]  # declaration face first


def test_unknown_label_types_probed_last():
    merged = {"mrp": ""}
    probed = []
    def fake(path):
        probed.append(path)
        return None
    guarded_mrp_rescue(merged, [FRONT, BACK], [None, "back"], read_mrp=fake)
    assert probed == [BACK, FRONT]


def test_input_not_mutated():
    merged = {"mrp": ""}
    out = guarded_mrp_rescue(merged, [BACK], ["back"],
                             read_mrp=lambda p: "MRP Rs. 119")
    assert merged == {"mrp": ""}
    assert out["mrp"] == "MRP Rs. 119"


def test_no_photos_returns_unchanged():
    merged = {"mrp": ""}
    assert guarded_mrp_rescue(merged, [], None, read_mrp=lambda p: "MRP Rs. 1") == merged


def test_sub_rupee_mrp_triggers_rescue():
    # p23 baseline read 'MRP Rs. 0.31/' (digit loss) — structurally implausible.
    merged = {"mrp": "MRP Rs. 0.31/"}
    out = guarded_mrp_rescue(merged, [BACK], ["back"],
                             read_mrp=lambda p: "MRP Rs. 109.00")
    assert out["mrp"] == "MRP Rs. 109.00"


def test_all_reads_rejected_keeps_original():
    merged = {"mrp": ""}
    out = guarded_mrp_rescue(merged, [BACK, FRONT], ["back", "front"],
                             read_mrp=lambda p: None)
    assert out["mrp"] == ""


def test_read_error_returns_none():
    def boom(path):
        raise RuntimeError("vlm down")
    merged = {"mrp": ""}
    out = guarded_mrp_rescue(merged, [BACK], ["back"], read_mrp=boom)
    assert out["mrp"] == ""