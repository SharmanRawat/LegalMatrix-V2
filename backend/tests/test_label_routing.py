"""Label-type routing tests for merge_extractions (inspection_service.py) and
the audit's filename/manifest label resolution (pipeline_audit.py).

Scenario: the app now lets users tag each photo as front/back/side/top/other
(and the audit dataset carries that as filenames + a manifest).
merge_extractions routes each field to the photo whose label type is its
strongest source:
    front -> product_name / edible
    back  -> MRP/USP/net-qty/manufacturer/dates/care/dimensions
    top   -> declaration back-up just below back (cap face on no-back packs)
    side  -> back-up for declarations; other -> last resort
Unlabeled uploads keep the original best-photo heuristics unchanged.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

from app.services.inspection_service import merge_extractions  # noqa: E402
from pipeline_audit import _label_type_for, _load_label_manifest  # noqa: E402


def _res(d: dict):
    return {k: v for k, v in d.items() if v is not None}


def test_unlabeled_keeps_heuristics():
    """Without label_types the merge must behave exactly as before."""
    results = [
        {"product_name": "surprise", "consumer_care": "hello@brand.com"},
        {"product_name": "The Real Product Name", "mrp": "MRP Rs.50", "usp": "50 ml"},
    ]
    merged = merge_extractions(results)
    # longest-string-wins for name, care contact-gated
    assert merged["product_name"] == "The Real Product Name"
    assert merged["consumer_care"] == "hello@brand.com"


def test_name_routed_to_front_photo():
    """Product name must come from the front (PDP) photo, not promo text."""
    results = [
        {"product_name": "PET JAR",
         "mrp": "MRP Rs. 265", "usp": "265 g", "net_quantity": "265 g"},
        {"product_name": "XYZ Green Tea - 100% Natural Premium",
         "mrp": "MRP Rs. 300", "expiry_date": "07/2027"},
    ]
    # photo 0 = back (loud promo string), photo 1 = front
    merged = merge_extractions(results, ["back", "front"])
    assert merged["product_name"] == "XYZ Green Tea - 100% Natural Premium"
    assert merged["mrp"] == "MRP Rs. 265"          # price block from back
    assert merged["net_quantity"] == "265 g"


def test_stat_block_single_photo_coherence():
    """MRP/USP/net-qty must reflect one printed declaration (block coherence)."""
    results = [
        {"mrp": "MRP Rs. 100", "usp": "100 ml", "net_quantity": "100 ml"},
        {"mrp": "MRP Rs. 999"},
    ]
    merged = merge_extractions(results, ["back", "front"])
    assert merged["mrp"] == "MRP Rs. 100"
    assert merged["usp"] == "100 ml" and merged["net_quantity"] == "100 ml"


def test_dates_travel_together_back_photo():
    """mfg+exp must come from the same photo (kills mfg/exp swaps)."""
    results = [
        {"manufacturing_date": "02/2025", "expiry_date": "02/2028"},
        {"manufacturing_date": "01/2026"},  # front sticker line, mfg looks like exp
    ]
    merged = merge_extractions(results, ["back", "front"])
    assert merged["manufacturing_date"] == "02/2025"
    assert merged["expiry_date"] == "02/2028"


def test_care_routed_to_back_not_front_dateline():
    """consumer_care restricted to back/side photos — a front-photo date line
    that smells like a phone must not win."""
    results = [
        {"consumer_care": "280656485 8",
         "product_name": "Brand X"},
        {"consumer_care": "care@brand.com, 1800-266-188",
         "mfg": "02/2025", "expiry_date": "02/2028"},
    ]
    merged = merge_extractions(results, ["front", "back"])
    assert "care@brand.com" in merged["consumer_care"]
    assert "1800-266-188" in merged["consumer_care"]


def test_no_back_photo_falls_back_to_side():
    """Products without a back photo still source declarations from side."""
    results = [
        {"product_name": "Brand X",
         "consumer_care": "hello@x.com 28256209"},   # side panel
        {"product_name": "Brand X Front LARGE MARKETING"},
    ]
    merged = merge_extractions(results, ["side", "front"])
    assert merged["consumer_care"] == "hello@x.com 28256209"


def test_unknown_photo_types_rank_last():
    """Tags outside the vocabulary behave like untagged (lowest priority)."""
    results = [
        {"product_name": "Right Name"},
        {"product_name": "Decoy"},
    ]
    merged = merge_extractions(results, ["none", "other"])
    # strong source = "other" (rank 3) vs "none" (rank 4): other wins
    assert merged["product_name"] == "Decoy"


def test_blank_routed_value_keeps_heuristic():
    """When the strongest source is blank/garbage for a field, fall back to the
    heuristic value rather than dropping it."""
    results = [
        {"mrp": "MRP Rs. 85", "usp": "85 g", "net_quantity": "85 g"},
        {"product_name": ""},
    ]
    merged = merge_extractions(results, ["back", "front"])
    assert merged["mrp"] == "MRP Rs. 85"


# ── date gate + range split (fixes p13/p7/p8 regressions) ────────────────────

def test_junk_date_not_routed_and_not_heuristic():
    """A non-date line must never fill mfg/exp — neither via routing nor via the
    block/longest-wins heuristics ('6 MONTHS', 'Anso Certified Company')."""
    results = [
        {"manufacturing_date": "Anso Certified Company"},       # side noise
        {"expiry_date": "6 MONTHS"},                            # back shelf-life
    ]
    merged = merge_extractions(results, ["side", "back"])
    assert (merged.get("manufacturing_date") or "") == ""
    assert (merged.get("expiry_date") or "") == ""


def test_glued_date_range_split_from_mfg():
    """'MFG 09/2025 EXP 03/2027' collapsed onto expiry ('SEP/2025-MAR/2027')
    must split: first half stays mfg, last half becomes expiry (p8)."""
    results = [
        {"manufacturing_date": "SEP/2025", "expiry_date": "SEP/2025-MAR/2027"},
        {"product_name": "NESCAFE CLASSIC"},
    ]
    merged = merge_extractions(results, ["back", "front"])
    assert merged["manufacturing_date"] == "SEP/2025"
    assert merged["expiry_date"] == "MAR/2027"


def test_range_date_without_mfg_splits_to_both():
    """A lone range on one cell fills both dates when the other is blank:
    '01/2026-05/2027' -> mfg 01/2026, exp 05/2027."""
    results = [{"expiry_date": "01/2026-05/2027"}]
    merged = merge_extractions(results, ["back"])
    assert merged["manufacturing_date"] == "01/2026"
    assert merged["expiry_date"] == "05/2027"


# ── name gate (fixes p15/p22 regressions) ────────────────────────────────────

def test_junk_front_name_falls_back_to_side():
    """Front promo line ('With TULSI MADHA…') must not beat the side/back name
    — the routing falls through to the next-strongest photo (p15)."""
    results = [
        {"product_name": "With TULSI MADHA ECT SITOPALADI"},    # front promo
        {"product_name": "Herbal Cough Syrup Sitoma MEDICINE"}, # side real name
    ]
    merged = merge_extractions(results, ["front", "side"])
    assert "Sitoma" in merged["product_name"]
    assert "TULSI" not in merged["product_name"]


def test_suggested_carnishing_falls_back_to_back():
    """'Suggested Carnishing' on the front must not override the back name
    (p22)."""
    results = [
        {"product_name": "Suggested Carnishing"},               # front
        {"product_name": "MAGGI Pazzta Mushroom Penne"},        # back
    ]
    merged = merge_extractions(results, ["front", "back"])
    assert merged["product_name"] == "MAGGI Pazzta Mushroom Penne"


def test_plausible_front_name_still_routed():
    """True PDP names ('NESCAFE CLASSIC', 'PREMIUM FARD DATES') are kept."""
    results = [
        {"product_name": "Reqistered Trademarkof Socereg Produits Nestle"},
        {"product_name": "NESCAFE CLASSIC"},
    ]
    merged = merge_extractions(results, ["back", "front"])
    assert merged["product_name"] == "NESCAFE CLASSIC"


# ── manufacturer stays heuristic (fixes p15 manufacturer regression) ─────────

def test_manufacturer_not_label_routed():
    """Back short-name ('Sito') must not override the longer side legal name
    ('Bhavani Pharmaceuticals') — manufacturer keeps longest-wins."""
    results = [
        {"manufacturer": "Sito"},                                         # back
        {"manufacturer": "Bhavani Pharmaceuticals"},                      # side
        {"product_name": "Bottle"},
    ]
    merged = merge_extractions(results, ["back", "side", "front"])
    assert merged["manufacturer"] == "Bhavani Pharmaceuticals"


# ── label resolution (audit) ─────────────────────────────────────────────────

def test_label_type_from_filename_embedded():
    assert _label_type_for("image1_front.jpg", {}) == "front"
    assert _label_type_for("image3_side.jpg", {}) == "side"
    assert _label_type_for("image7_top.jpg", {}) == "top"      # first-class type


def test_label_type_case_insensitive():
    assert _label_type_for("image27_Other.jpg", {}) == "other"
    assert _label_type_for("image28_Top.jpg", {}) == "top"


def test_label_type_manifest_overrides_filename():
    assert _label_type_for("image1_front.jpg", {"image1_front.jpg": "side"}) == "side"


def test_label_type_unknown_returns_none():
    assert _label_type_for("image1_weird.jpg", {}) is None
    assert _label_type_for("notes.txt", {}) is None


def test_manifest_file_loads():
    import pytest
    if not _load_label_manifest():
        pytest.skip("label_types.json not present (gitignored local dataset)")
    m = _load_label_manifest()
    # the dataset manifest should cover every current photo name in /images
    assert m, "label_types.json missing — run the tagger / manual renames first"
    assert set(m.values()) <= {"front", "back", "side", "top", "other"}


# ── date classifier primitive ────────────────────────────────────────────────

def _dc(v):
    from app.services.inspection_service import _date_component
    k, a, b = _date_component(v)
    return (k, a, b)


def test_date_component_singles():
    import pytest
    singles = ["JAN/2027", "AUG25", "FEB26", "07MAR/2025", "12/2025", "01/2025",
               "06.08:2026", "05.10.2026", "2020", "14.04.0", "MAY/2026",
               "BEST BEFORE 12/2028", "EXP 01/2028", "05-10-2026"]
    for s in singles:
        assert _dc(s)[0] == "single", f"{s!r} should be single"
        assert _dc(s)[0] != "none"


def test_date_component_ranges():
    assert _dc("SEP/2025-MAR/2027") == ("range", "SEP/2025", "MAR/2027")
    assert _dc("01/2026-05/2027") == ("range", "01/2026", "05/2027")


def test_date_component_junk():
    for s in ["6 MONTHS", "Anso Certified Company", "Mig. Date:", "Exp.Date:",
              "Trademark", ""]:
        assert _dc(s)[0] == "none", f"{s!r} should be none"


def test_batch_code_with_space_not_a_date():
    """p29: 'U280656485 8' (EVEREST batch + trailing digit) must not classify
    as a date via the '85 8' space-separator false positive."""
    assert _dc("U280656485 8") == ("none", "", "")
    # glue line from the top-cap photo: only the JAN/2027 date survives
    assert _dc("JAN/2027 U280656485 8") == ("single", "JAN/2027", "")
    # and another real batch/EAN code pattern
    assert _dc("190606611202477") == ("none", "", "")


def test_date_component_rejects_implausible_pairs():
    # day>31 / month>12 in both dd/mm and mm/dd readings
    for s in ["85/8", "45/60", "32/01", "13/45"]:
        assert _dc(s)[0] == "none", f"{s!r} should be none"
    # real dates still pass
    for s in ["05/08/2027", "05.10.2026", "06.08:2026", "12/2025", "01/2025",
              "30/02", "05/12", "12/05"]:
        assert _dc(s)[0] == "single", f"{s!r} should be single"


def test_date_component_month_with_surrounding_spaces():
    # 'JAN / 2027' is ONE date, not a 'JAN'..'2027' spurious range
    assert _dc("JAN / 2027")[0] == "single"
    assert _dc("JAN / 2027")[1].replace(" ", "") == "JAN/2027"
    assert _dc("BETTER AUG / 2026")[0] == "single"


# ── top label type (cap/roof face; no-back products 27/28/29) ───────────────

def test_top_routes_declarations_when_no_back():
    """EVEREST-style pack: no back face captured, the cap carries MRP/use-by/net wt."""
    results = [
        {"product_name": "NETWEIGHT",
         "mrp": "MRP Rs. 85", "net_quantity": "100 g", "expiry_date": "JAN/2027"},
        {"product_name": "Mixed Masala Powder Chaat Masala EVEREST",
         "edible": "yes"},
    ]
    merged = merge_extractions(results, ["top", "front"])
    assert merged["mrp"] == "MRP Rs. 85"
    assert merged["net_quantity"] == "100 g"
    assert merged["expiry_date"] == "JAN/2027"
    assert merged["product_name"] == "Mixed Masala Powder Chaat Masala EVEREST"


def test_back_outranks_top_for_declarations():
    """When both exist, the back declaration block still wins over the cap."""
    results = [
        {"mrp": "MRP Rs. 85", "net_quantity": "100 g"},
        {"mrp": "MRP Rs. 999", "net_quantity": "900 g"},
        {"product_name": "EVEREST Chaat Masala"},
    ]
    merged = merge_extractions(results, ["top", "back", "front"])
    assert merged["mrp"] == "MRP Rs. 999"
    assert merged["net_quantity"] == "900 g"


def test_top_never_wins_product_name():
    """The cap is never the PDP — the name still comes from front/side/back."""
    results = [
        {"product_name": "NETWEIGHT 100g", "mrp": "MRP Rs. 85"},
        {"product_name": "EVEREST Chaat Masala",
         "mrp": "MRP Rs. 999", "net_quantity": "900 g"},
    ]
    merged = merge_extractions(results, ["top", "front"])
    assert merged["product_name"] == "EVEREST Chaat Masala"


def test_audit_resolves_top_filename_and_manifest():
    """Filename '_top' and the manifest both resolve to the 'top' label type."""
    assert _label_type_for("/x/image29_top.jpg", {}) == "top"
    assert _label_type_for("/x/image29_front.jpg", {}) == "front"
    manifest = _load_label_manifest()
    assert manifest.get("image29_top.jpg") == "top"
    assert manifest.get("image26_top.jpg") == "top"
    assert _label_type_for("/x/image28_Top.jpg", manifest) == "top"