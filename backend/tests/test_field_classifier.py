"""Regression tests for RegexFieldClassifier consumer_care union extraction.

These mirror REAL rapidocr token strings observed in the golden-set audit's
OCR cache (e.g. '@:022-71230555:suggestion@dmartindia.com',
'Calluson+919825588822'), where the old per-line matcher kept only ONE email
or one 1800 number and dropped every ordinary phone.
"""
from app.services.field_classifier import RegexFieldClassifier


def _line(text: str) -> dict:
    return {"text": text, "box": [0, 0, 100, 10]}


def _care(texts):
    return RegexFieldClassifier()._collect_care(texts)


def test_phone_and_email_same_line():
    out = _care(["@:022-71230555:suggestion@dmartindia.com"])
    assert "022-71230555" in out
    assert "suggestion@dmartindia.com" in out
    assert len(out.split(", ")) == 2


def test_phone_on_own_line_email_elsewhere_reading_order():
    out = _care([
        "FOR CONSUMER CARE 022-71230555",
        "suggestion@dmartindia.com",
    ])
    assert out == "022-71230555, suggestion@dmartindia.com"


def test_tollfree_and_email_one_line():
    out = _care(["TEL:1800-103-0494·E-MAIL:INDIA@DEOLEO.COM"])
    assert "1800-103-0494" in out
    assert "india@deoleo.com" in out


def test_grouped_mobile_without_dash():
    assert "91069 80469" in _care(["Customer Care No.:91069 80469"])
    assert "022 71230555" in _care(["PHONE NO.: 022 71230555"])


def test_phone_glued_to_callus_hint_line():
    # no inner separator, but the line carries the contact hint 'CALL US'
    out = _care(["Calluson+919825588822"])
    assert "919825588822" in out


def test_double_phone_plus91_separator():
    out = _care(["T:+91 7082134999,7082135999"])
    assert "7082134999" in out  # the +91-grouped phone is kept (digits matter)


def test_bare_digit_runs_excluded():
    # barcode / FSSAI / batch numbers on plain lines must NOT become phones
    assert _care(["9040041200779"]) == ""
    assert _care(["FSSAI LIC NO 10015022004173"]) == ""
    assert _care(["BATCH NO: 47719"]) == ""
    assert _care(["7082134999"]) == ""  # bare 10-digit run, no hint, no separator


def test_email_junk_not_glued_from_next_line():
    out = _care(["CUSTOMERCARE@EVERESTSPICES.COM", "WWW.EVERESTFOODS."])
    assert out == "customercare@everestspices.com"


def test_date_line_fragment_not_a_phone():
    # 'JAN / 2027 U280656485 8' is a date/batch line, NOT a consumer phone
    assert _care(["JAN / 2027 U280656485 8"]) == ""


def test_email_label_prefix_glue_stripped():
    # OCR glued the printed 'E-MAIL:' label onto the address
    assert "daburcares@dabur.com" in _care(["E-MAlldaburcares@dabur.com"])
    assert "info@ramdev.co.in" in _care(["mail.info@ramdev.co.in"])
    # …but a mailbox that IS the label word, with nothing after it, survives
    assert _care(["email@x.com"]) == "email@x.com"
    assert _care(["mail@x.com"]) == "mail@x.com"


def test_country_coded_phone_kept():
    assert "91-22-25259915" in _care(["Maharashtra.Ph.No.:+91-22-25259915"])


def test_bare_1800_run_kept():
    assert "18001804109" in _care(["TEL:18001804109"])


def test_classify_sets_union_care():
    cls = RegexFieldClassifier()
    res = cls.classify([_line("DMART PREMIA LAWANG"),
                        _line("FOR CONSUMER CARE 022-71230555"),
                        _line("suggestion@dmartindia.com")])
    assert res["fields"]["consumer_care"] == "022-71230555, suggestion@dmartindia.com"


def test_classify_no_contacts_leaves_care_empty():
    cls = RegexFieldClassifier()
    res = cls.classify([_line("9040041200779"), _line("NET WT 40G")])
    assert res["fields"]["consumer_care"] == ""


# ── count-unit net quantity (Rule 6(1)(c) 'by number') ─────────────────────
# Product 1 of new_images prints 'Net Qty. 200 N' but RapidOCR returns the
# mangled reading '200N' + 'Net Uty.' (value printed before the keyword).
# The frozen golden corpus must stay byte-identical, so recovery is scoped to
# the mangled 'UTY' keyword form: product 16 in the golden set has a CLEAN
# 'NET QUANTITY:' keyword and must stay untouched.


def test_net_quantity_count_unit_value_before_mangled_keyword():
    cls = RegexFieldClassifier()
    res = cls.classify([_line("200N"), _line("Net Uty.")])
    assert res["fields"]["net_quantity"] == "200N"


def test_net_quantity_count_unit_keyword_first():
    cls = RegexFieldClassifier()
    res = cls.classify([_line("NET QTY.: 200 N")])
    assert res["fields"]["net_quantity"] == "200 N"


def test_net_quantity_clean_quantity_keyword_stays_inert():
    # Frozen-corpus product 16 shape: '50N' + clean 'NET QUANTITY:' must NOT be
    # extracted — the count-unit recovery is deliberately scoped to mangled
    # 'UTY' so the golden baseline stays byte-identical.
    cls = RegexFieldClassifier()
    res = cls.classify([_line("PAPER NAPKIN"), _line("50N"),
                        _line("NET QUANTITY:"),
                        _line("(50 N x 2 Ply each) (Usable Sheets)")])
    assert res["fields"]["net_quantity"] == ""


def test_net_quantity_bare_count_unit_needs_mangled_keyword():
    cls = RegexFieldClassifier()
    res = cls.classify([_line("50N"), _line("NET QUANTITY:")])
    assert res["fields"]["net_quantity"] == ""