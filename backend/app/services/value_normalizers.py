#!/usr/bin/env python3
"""Canonical legal-metrology value normalizers — the single source of truth.

Every subsystem that must decide whether two surface forms of a statutory
field are "the same" — the pipeline audit (=oracle/self-check), the merge
logic (inspection_service.merge_extractions), the rule engine, the classifier
prompt post-processing — should use these primitives, so that

    ₹150/-   ==  Rs. 150   ==  INR 150
    JAN 2028 ==  01/2028
    250 g    ==  250 grams
    Ltd.     ==  Limited
    EXP 01/2028 == BEST BEFORE JAN 2028

everywhere at once, instead of each consumer silently re-deriving its own
equivalence rules and drifting apart.

Contract: two values are *legally equivalent* iff their canonical key is equal.

    field               canonical key
    ------------------  ------------------------------------------------
    mrp / usp           parse_price(s)      -> (amount|None, has_currency, unit|None)
    net_quantity        quantity_key(s)     -> ((amount, unit), ...)
    mfg / exp dates     parse_date(s)       -> (year|None, month|None)
    product / mfr       name_tokens(s)      -> frozenset (alnum tokens − BRAND_NOISE)
    consumer_care       care_key(s)         -> emails (sorted, concatenated) + "+tel"
    dimensions          dimensions_key(s)   -> frozenset of numeric strings
    edible              edibility_key(s)    -> "yes" | "no" | raw text

Parsing is deliberately permissive because labels are OCR'd, not typed: units
are case-insensitive and stemmed (grams→g, kilograms→kg), month names accept
abbreviations, currency may be symbol or word, amounts may carry separators or
a trailing "/-". Strictness lives in the CALLERS (the audit's plausibility
check, the merge's contact gate); this module only decides sameness.
"""

import re

# ── unit & month tables ──────────────────────────────────────────────────────
QTY_UNIT_NORM = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "kgm": "kg", "kilogram": "kg", "kilograms": "kg",
    "ml": "ml", "mls": "ml", "milliliter": "ml", "milliliters": "ml",
    "millilitre": "ml", "millilitres": "ml",
    "l": "l", "lt": "l", "ltr": "l", "litre": "l", "litres": "l",
    "liter": "l", "liters": "l",
    "m": "m", "mt": "m", "meter": "m", "metre": "m",
    "cm": "cm", "cms": "cm", "centimeter": "cm",
    "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc",
    "nos": "pc", "no": "pc", "count": "pc", "counts": "pc",
}

MONTHS = {
    "JAN": 1, "JANUARY": 1, "FEB": 2, "FEBRUARY": 2, "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4, "MAY": 5, "JUN": 6, "JUNE": 6, "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8, "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "OCT": 10,
    "OCTOBER": 10, "NOV": 11, "NOVEMBER": 11, "DEC": 12, "DECEMBER": 12,
}

# Corporate-form suffixes are legally identical regardless of spelling
# (Limited/Ltd, Private/Pvt, Incorporated/Inc): name_tokens() strips them
# before any name comparison.
BRAND_NOISE = {"limited", "ltd", "private", "pvt", "incorporated", "inc",
               "llp", "corporation", "corp"}

# ── compiled patterns (public: reuse anywhere) ───────────────────────────────
CURRENCY_RE = re.compile(r"\brs\.?\b|inr\b|rupees?\b|\u20b9", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.?\d*")
PRICE_UNIT_RE = re.compile(
    r"per\s+(?:\d+\s+)?(grams?|g|kilos?|kg|millilitres?|ml|litres?|l)\b"
    r"|/(grams?|g|kilos?|kg|ml|litres?|l)\b",
    re.I,
)
DATE_NOISE_RE = re.compile(
    r"\b(MFG\.?|M\.D\.?|EXP\.?|EXPIRY|BEST\s+BEFORE|USE\s+BY|BATCH|B\.?N\.?|LOT|DATE)\b",
    re.I,
)


def tokens(s: str) -> frozenset:
    """Case-insensitive alnum tokens of a free-text value (fuzzy compare)."""
    return frozenset(re.findall(r"[a-z0-9]+", str(s or "").lower()))


def amount(s: str) -> float | None:
    """First number found (thousand separators removed), else None."""
    m = AMOUNT_RE.search(str(s or ""))
    return float(m.group(0).replace(",", "")) if m else None


def emails(s: str) -> set:
    return set(EMAIL_RE.findall(str(s or "").lower()))


def phones(s: str) -> set:
    """10/11/12-digit numbers, or any 1800 toll-free string."""
    digs = {"".join(re.findall(r"\d", n)) for n in re.findall(r"\d[\d\s\-]*\d", str(s or ""))}
    return {d for d in digs if len(d) in (10, 11, 12) or d.startswith("1800")}


def fmt_num(x: float) -> str:
    return f"{x:g}"


# ── typed canonical keys ─────────────────────────────────────────────────────
def parse_price(s: str) -> tuple:
    """(amount|None, has_currency, unit|None) — the canonical MRP/USP key.

    '' or a non-numeric string -> (None, False, None). A missing currency
    marker is a CIVIL offence under Rule 6(1)(e) for MRP, so callers may
    distinguish (amount, False, ...) from (amount, True, ...).
    """
    low = str(s or "").lower().replace("\u20b9", "rs ")  # pad: '₹265' -> 'rs 265' keeps \brs\b
    u = PRICE_UNIT_RE.search(low)
    return (amount(s), bool(CURRENCY_RE.search(low)),
            None if not u else (u.group(1) or u.group(2)).lower())


def parse_quantity(s: str) -> list:
    """Ordered (amount, unit) pairs: '250 ml (228 g)' -> [(250,'ml'), (228,'g')].

    Units are normalized via QTY_UNIT_NORM; incidental long tokens with no
    recognized unit (e.g. 'netqty') are skipped.
    """
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([a-z]+)", str(s or "").lower()):
        raw = m.group(2)
        unit = QTY_UNIT_NORM.get(raw)
        if unit is None and len(raw) > 5:  # skip incidental tokens like 'netqty'
            continue
        out.append((float(m.group(1)), unit or raw))
    return out


def quantity_key(s: str) -> tuple:
    """Hashable canonical quantity: ((amount, unit), ...) — 250 ml == 250 millilitres."""
    return tuple(parse_quantity(s))


def parse_date(s: str) -> tuple:
    """(year|None, month|None) — the canonical MFG/EXP key.

    'JAN 2028' -> (2028, 1); '01/2028' -> (2028, 1); '2028' -> (2028, None);
    '06/04/27' -> (2027, 4) (dd/mm/yy). Impossible numeric months are surfaced
    ('13/2028' -> month 13) so strict callers can flag them.
    """
    s = DATE_NOISE_RE.sub("", str(s or "")).upper()
    nums = [int(x) for x in re.findall(r"\d{1,4}", s)]
    year = next((n for n in nums if n >= 1900), None)
    # Month words tolerate adjacent digits / punctuation but not letters:
    # '07 MAR 2025' and OCR-no-space forms '07MAR/2025', 'FEB25', 'JAN27' all
    # resolve, while 'MARCHING'/'JANITOR'/'DECOR' never false-match.
    month = next(
        (MONTHS[w] for w in MONTHS
         if re.search(rf"(?<![A-Z]){w}(?![A-Z])", s)),
        None)
    if year is not None:
        # numeric month immediately before a 4-digit year: '01/2026' -> 1
        # (candidate kept even when > 12 — '13/2028' -> month 13 — so strict
        # callers can flag impossible months)
        for i, n in enumerate(nums):
            if n >= 1900 and i >= 1 and 1 <= nums[i - 1] <= 99:
                month = month or nums[i - 1]
                break
    elif nums and nums[-1] <= 99:  # two-digit year: dd/mm/yy -> 27 -> 2027
        year = 2000 + nums[-1]
        if len(nums) >= 2 and 1 <= nums[-2] <= 12:
            month = month or nums[-2]
    return year, month


def name_tokens(s: str) -> frozenset:
    """Canonical name token set: alnum tokens minus corporate suffixes.

    'Patanjali Foods Limited' and 'PATANJALI FOODS PVT. LTD.' both ->
    frozenset({'patanjali', 'foods'}). Use for product_name / manufacturer.
    """
    return tokens(s) - BRAND_NOISE


def care_key(s: str) -> str:
    """Canonical consumer-care key: emails concatenated sorted + '+tel' if any
    phone. 'care@x.com 1800-123-456' -> 'care@x.com+tel'."""
    es = "".join(sorted(emails(s)))
    return es + ("+tel" if phones(s) else "")


def dimensions_key(s: str) -> frozenset:
    """Numeric values as a set: '10 cm X 5 cm' -> frozenset({'10','5'})."""
    return frozenset(re.findall(r"\d+(?:\.\d+)?", str(s or "")))


def edibility_key(s: str) -> str:
    """'yes'/ 'no' prefix-normalized; anything else verbatim. 'Yes.' -> 'yes'."""
    x = str(s or "").strip().lower()
    return "yes" if x.startswith("y") else "no" if x.startswith("n") else x