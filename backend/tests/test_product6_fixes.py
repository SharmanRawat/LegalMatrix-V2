"""Regression tests for the product-6 (Figaro olive oil) fixes.

Covers: month-glyph OCR repair, parenthesised net quantity, batch-sticker
MRP/USP rescue (incl. the Rs-symbol-misread-as-3 disambiguation), bare-year
manufacturing-date fallback, and nutrition/address leak guards for
product_name.
"""
from app.services.field_classifier import RegexFieldClassifier
from app.services.ocr_engine import _postprocess_text


def _lines(*texts):
    return [{"text": t, "box": [0, 0, 10, 10]} for t in texts]


def test_month_glyph_jhn_becomes_jan():
    assert "JHN" not in _postprocess_text("JHN 2028")
    assert "JAN" in _postprocess_text("JHN 2028")


def test_net_quantity_parenthesised_dual():
    rc = RegexFieldClassifier()
    out = rc.classify(_lines("NETQTY.:2", "250 ml (228 g)"))
    assert out["fields"]["net_quantity"] == "250 ml (228 g)"


def test_net_quantity_stray_digit_skipped():
    assert (RegexFieldClassifier._match_net_quantity("NETQTY.:2 250 ml (228 g)")
            == "250 ml (228 g)")


def test_sticker_prices_mrp_usp_with_de3():
    rc = RegexFieldClassifier()
    texts = ["L66280", "2026", "JAN 2028", "599.00", "32.40"]
    mrp, usp, _, _ = rc._match_sticker_prices(texts, "250 ml (228 g)")
    assert mrp == "MRP Rs. 599.00"
    assert usp == "USP Rs. 2.40/ml"


def test_sticker_prices_need_date_cue():
    rc = RegexFieldClassifier()
    mrp, usp, _, _ = rc._match_sticker_prices(["73.75", "599.00"], "")
    assert mrp == "" and usp == ""


def test_sticker_single_price_is_mrp_only():
    rc = RegexFieldClassifier()
    texts = ["JUL 2026", "499.00"]
    mrp, usp, _, _ = rc._match_sticker_prices(texts, "1 kg")
    assert mrp == "MRP Rs. 499.00"
    assert usp == ""


def test_bare_year_mfg_near_batch():
    rc = RegexFieldClassifier()
    texts = ["L66280", "2026", "JAN 2028"]
    mfg, exp, _, _ = rc._match_bare_year_dates(texts, "", "JAN/2028")
    assert mfg == "2026"
    assert exp == ""


def test_product_name_kills_nutrition_and_address():
    rc = RegexFieldClassifier()
    out = rc.classify(_lines(
        "N-N, KM 388, 14610. ALCOLEA (CORDOBA) - SPAIN.",
        "FIGARO",
        "IMPORTED EXTRA VIRGIN OLIVE OIL",
    ))
    assert "KM" not in out["fields"]["product_name"]
    assert "ALCOLEA" not in out["fields"]["product_name"]
    out2 = rc.classify(_lines(
        "TO RECOMMENDED DIETARY ALLOWANCE.", "FIGARO OLIVE"))
    assert "RECOMMENDED" not in out2["fields"]["product_name"]


def test_mrp_keyword_distant_price_rescue():
    rc = RegexFieldClassifier()
    out = rc.classify(_lines(
        "MRPE", "(ind. of all taxes", "MADE INBHARAT", "410.00"))
    assert out["fields"]["mrp"] == "MRP Rs. 410.00"
    assert out["fields"]["usp"] == ""


def test_product_name_address_line_skipped():
    rc = RegexFieldClassifier()
    out = rc.classify(_lines(
        "Padartra. Laksar Road. Hardwex - 249404 (Utarakhand)",
        "PATANJALI",
        "HONEY",
    ))
    assert "Road" not in out["fields"]["product_name"]
    assert "Laksar" not in out["fields"]["product_name"]


def test_fullwidth_colon_normalized():
    assert _postprocess_text("Net Quantity ： 1 kg") == "Net Quantity : 1 kg"


def test_glued_address_name_rejected():
    from app.services.field_classifier import _looks_like_address
    assert _looks_like_address("Herbal Parkadarthaakaroad Hariwar")
    assert not _looks_like_address("Park Avenue")
    assert not _looks_like_address("FIGARO IMPORTED EXTRA VIRGIN OLIVE OIL")


def test_manufacturer_leading_fssai_stripped():
    from app.services.field_classifier import _strip_company
    assert _strip_company("fssai Patanjali Foods Linmited") == "Patanjali Foods Linmited"


def test_zero_net_quantity_from_nutrition_rows_rejected():
    """image6_3: bare '0g' nutrition rows must never become the net quantity."""
    rc = RegexFieldClassifier()
    out = rc.classify(_lines(
        "NUTRITIONAL INFORMATION", "Per 100 g", "PROTEIN", "0g",
        "TOTAL SUGARS", "0g", "0%", "NETQTY", "FIG",
    ))
    assert out["fields"]["net_quantity"] == ""


def test_zero_mrp_and_usp_rejected():
    rc = RegexFieldClassifier()
    out = rc.classify(_lines("MRP Rs. 0.00", "USP Rs. 0.00/ml"))
    assert out["fields"]["mrp"] == ""
    assert out["fields"]["usp"] == ""
    # ... while small-but-nonzero values survive.
    out2 = rc.classify(_lines("MRP Rs. 99.00", "USP Rs. 0.24 per g"))
    assert out2["fields"]["mrp"] != ""
    assert out2["fields"]["usp"] != ""


def test_merge_kills_llm_zero_quantity_without_regex_support():
    """The SLM read '0 g' off image6_3's nutrition table while the regex found
    nothing — the merge must drop the unevidenced zero, not ship it."""
    from app.services.ocr_engine import _merge_classifiers
    lines = _lines("NUTRITIONAL INFORMATION", "0g", "Per 100 g")
    llm = {
        "fields": {
            "mrp": "", "usp": "", "net_quantity": "0 g", "product_name": "",
            "manufacturer": "", "manufacturing_date": "", "expiry_date": "",
            "consumer_care": "", "dimensions": "", "edible": "",
        },
        "line_map": {"net_quantity": [1]},
        "engine": "llm",
    }
    regex = RegexFieldClassifier().classify(lines)
    assert regex["fields"]["net_quantity"] == ""
    merged = _merge_classifiers(llm, regex, lines)
    assert merged["fields"]["net_quantity"] == ""


def test_merge_kills_unevidenced_llm_edible_no():
    """The SLM guessed edible='no' on image6_3 although no non-edible marker
    is printed — the merge must clear it."""
    from app.services.ocr_engine import _merge_classifiers
    lines = _lines("NUTRITIONAL INFORMATION", "0g", "IMPORTED BY: DELE")
    llm = {
        "fields": {
            "mrp": "", "usp": "", "net_quantity": "", "product_name": "",
            "manufacturer": "", "manufacturing_date": "", "expiry_date": "",
            "consumer_care": "", "dimensions": "", "edible": "no",
        },
        "line_map": {},
        "engine": "llm",
    }
    regex = RegexFieldClassifier().classify(lines)
    merged = _merge_classifiers(llm, regex, lines)
    assert merged["fields"]["edible"] == ""


def test_merge_keeps_evidenced_edible_yes():
    """... while a 'yes' backed by a food word ('OLIVE OIL') survives."""
    from app.services.ocr_engine import _merge_classifiers
    lines = _lines("IMPORTED EXTRA VIRGIN OLIVE OIL", "250 ml")
    llm = {
        "fields": {
            "mrp": "", "usp": "", "net_quantity": "", "product_name": "",
            "manufacturer": "", "manufacturing_date": "", "expiry_date": "",
            "consumer_care": "", "dimensions": "", "edible": "yes",
        },
        "line_map": {},
        "engine": "llm",
    }
    regex = RegexFieldClassifier().classify(lines)
    merged = _merge_classifiers(llm, regex, lines)
    assert merged["fields"]["edible"] == "yes"


def test_manufacturer_trailing_batch_number_stripped():
    rc = RegexFieldClassifier()
    assert rc._match_manufacturer("MANUFACTURED BY: DEA 789") == ""
    assert (rc._match_manufacturer("MANUFACTURED BY: ABC FOODS 400093")
            == "ABC FOODS")


def test_glued_caps_blob_not_product_name():
    """image6_3's 'HOWRAHWESTBENGL' address residue must not win the name."""
    rc = RegexFieldClassifier()
    out = rc.classify(_lines(
        "NUTRITIONAL INFORMATION", "HOWRAHWESTBENGL", "FIGARO"))
    assert "HOWRAH" not in out["fields"]["product_name"]
    assert out["fields"]["product_name"] == "FIGARO"


def test_packaging_part_words_not_product_name():
    """image6_3's 'POURER LABEL' / 'CAP' print is packaging, not the name."""
    rc = RegexFieldClassifier()
    out = rc.classify(_lines("CAP", "POURER LABEL", "FIGARO"))
    assert out["fields"]["product_name"] == "FIGARO"
