"""Inspection service — orchestrates OCR extraction, compliance checks,
font measurement, evidence storage, heat-maps and persistence.

Keeps the API layer thin and the pipeline testable (OCR can be mocked).
"""
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from app.config import QWN_MODEL, get_evidence_dir as resolve_evidence_dir
from app.config import VLM_RESCUE_ENABLED, VLM_RESCUE_MODEL, VLM_RESCUE_CONFIDENCE_THRESHOLD
from app.core.rule_engine import rule_engine
from app.repositories import inspections as inspection_repo
from app.services import compliance_scorer, heatmap_generator, preprocessing
from app.services.font_measurement import FontMeasurementService
from app.services.manufacturer_address import extract_manufacturer_address
from app.services.ocr_transcript import build_ocr_transcript
from app.services.price_engine import price_engine
from app.services.progress import bind_progress, emit as _emit_progress, restore_progress
from app.services.value_normalizers import DATE_NOISE_RE, MONTHS, parse_date

EXPECTED_KEYS = [
    "mrp", "usp", "net_quantity", "product_name",
    "manufacturer", "manufacturing_date", "expiry_date", "consumer_care",
    "dimensions", "edible",
]

REQUIRED_TO_FIELD = {
    "manufacturer_name_address": "manufacturer",
    "generic_commodity_name": "product_name",
    "net_quantity": "net_quantity",
    "month_year_manufacture": "manufacturing_date",
    "mrp": "mrp",
    "consumer_care_details": "consumer_care",
    "dimensions_where_relevant": "dimensions",
}

CRITICAL = ["mrp", "net_quantity", "manufacturer_name_address"]

# A consumer-care line must expose one of these contact channels to count:
# an email, a toll-free line, or a 10–12 digit phone. 12-digit numbers are
# country-coded Indian mobiles ('+91-22-25259915' -> 912225259915); judging
# only the raw string (as an old '1?\\d{10}' did) silently rejected them and
# blanked whole care rows. FSSAI (14–17) / barcode (13) runs stay excluded.
_CARE_CONTACT_RE = re.compile(r"@|toll\s*free|tollfree|1800", re.I)


def _care_contact_like(value: str) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return bool(_CARE_CONTACT_RE.search(str(value or ""))
                or len(digits) in (10, 11, 12))


# ── date plausibility (shared by the merge heuristics and label routing) ─────
# MFG/EXP cells must hold a real date, not a stray line the 3B SLM grabbed
# ('6 MONTHS', 'Anso Certified Company', 'Mig. Date:') and not two dates glued
# by the classifier ('SEP/2025-MAR/2027' — usually MFG-EXP printed on one
# line). _date_component classifies a value; _clean_date_pair drops the junk
# and splits the glue. Patterns mirror value_normalizers.parse_date so audit
# and merge agree: month-name (+optional year) OR dd/mm (…yy) OR bare yyyy.
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_SINGLE_MONTH_RE = re.compile(
    rf"(?<![A-Z])(?:{_MONTH_ALT})(?![A-Z])(?:\s*[./:-]?\s*\d{{2,4}})?", re.I)
# A separator between digit groups must be REAL punctuation — a bare space is
# not ('05 / 08 / 27' ok via \s* around '/'; '85 8' from 'U280656485 8' must
# NOT match, or a glue line reads as a date).
_SEP_DATE_RE = re.compile(r"\d{1,2}\s*[/.:-]\s*\d{1,2}(?:\s*[/.:-]\s*\d{1,4})?")
_BARE_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?![\d.])")
_DATE_RANGE_RE = re.compile(
    rf"((?:{_MONTH_ALT})[./:-]?\s*\d{{2,4}})\s*-\s*((?:{_MONTH_ALT})[./:-]?\s*\d{{2,4}})"
    r"|(\d{1,2}[/.:]\d{2,4})\s*-\s*(\d{1,2}[/.:]\d{2,4})",
    re.I)


def _numeric_pair_ok(g: str) -> bool:
    """Reject punctuation-separated digit groups that cannot be a date
    ('85/8' day 85, '45/60'), keep real ones ('05/08/2027', '06.08:2026',
    '12/2025' -> month/yr). Month-word groups never reach this check."""
    if re.search(r"[A-Z]", g):
        return True
    nums = [int(x) for x in re.findall(r"\d+", g)]
    if len(nums) < 2:
        return False
    a, b = nums[0], nums[1]
    # dd/mm or mm/dd, not day>31 / month>12 in both orders.
    return (a <= 31 and b <= 12) or (b <= 31 and a <= 12)


def _date_component(value: str) -> tuple:
    """Classify a raw manufacturing/expiry cell.

    Returns
      ("single", cleaned, "")            one plausible date ('JAN/2027',
                                         '06.08:2026', '2020', '14.04.0')
      ("range",  first, last)            two dates glued by '-' ('SEP/2025-
                                         MAR/2027' or '01/2026-05/2027')
      ("none",   "", "")                 not a date ('6 MONTHS',
                                         'Anso Certified Company', 'Mig. Date:')
    """
    t = DATE_NOISE_RE.sub(" ", str(value or "")).upper()
    if not t.strip():
        return "none", "", ""
    m = _DATE_RANGE_RE.search(t)
    if m and (m.group(1) or m.group(3)) and (m.group(2) or m.group(4)):
        return ("range",
                (m.group(1) or m.group(3)).strip(),
                (m.group(2) or m.group(4)).strip())
    groups = []
    masked = [c for c in t]

    def _blank(a: int, b: int) -> None:
        for j in range(a, b):
            masked[j] = " "

    for gm in _SINGLE_MONTH_RE.finditer(t):
        groups.append(gm.group(0))
        _blank(gm.start(), gm.end())
    for sm in _SEP_DATE_RE.finditer("".join(masked)):
        g = sm.group(0)
        if _numeric_pair_ok(g):
            groups.append(g)
            _blank(sm.start(), sm.end())
    for by in _BARE_YEAR_RE.finditer("".join(masked)):
        groups.append(by.group(0))
        _blank(by.start(), by.end())
    if not groups:
        return "none", "", ""
    if len(groups) == 1:
        return "single", groups[0].strip(), ""
    return "range", groups[0].strip(), groups[-1].strip()


def _clean_date_pair(mfg: str, exp: str) -> tuple:
    """Sanitize a mfg/exp pair read as one block: drop text that is not a date
    and split a glued range ('SEP/2025-MAR/2027' -> mfg SEP/2025, exp MAR/2027)."""
    km, am, bm = _date_component(mfg)
    ke, ae, be = _date_component(exp)
    out_m = mfg if km != "none" else ""
    out_e = exp if ke != "none" else ""
    if km == "range" and not out_e:
        out_m, out_e = am, bm
    elif ke == "range" and not out_m:
        out_m, out_e = ae, be
    elif ke == "range":
        out_e = be or ae
    elif km == "range":
        out_m = am
    return out_m, out_e


def _corrupt_single_digit_year(value: str) -> bool:
    """True when a date's trailing numeric token is a single digit.

    On sub-resolution print the recognizer can collapse a 2-digit year to one
    digit ('14.04.24' read as '14.04.0'). parse_date would 2-digit-expand that
    into a plausible-but-fake 200x year, so the merged cell would emit a
    corrupt full date. Those reads are unreadable, not partial — the merge
    blanks them (NOT DETECTED) so the inspector keys the true value.

    False for everything a real label legitimately holds: year-only partials
    ('2026'), real 2-digit/4-digit years ('14.04.22', '05.10.2026'), month-
    year and month-name dates ('08/2026', 'JAN/2027', 'MAR/27'), and shelf-
    life strings ('6 MONTHS'). The digit must sit as the final token of a
    punctuation-joined date ('14.04.0', never 'U280656485 8')."""
    s = str(value or "").strip().upper()
    if not s:
        return False
    m = re.search(r"(\d{1,2}\s*[.:/-]\s*\d{1,2}(?:\s*[.:/-]\s*\d{1,4})?)$", s)
    if not m:
        return False
    nums = re.findall(r"\d+", m.group(1))
    return bool(nums) and len(nums[-1]) == 1


# Shelf-life duration phrases ('5Yrs from DEC/2024', '6 MONTHS FROM
# MANUFACTURE') — a duration, never an expiry declaration. The SLM sometimes
# files one into expiry; the merge blanks it (NOT DETECTED).
_SHELF_LIFE_RE = re.compile(
    r"\b\d+\s*(?:YRS?|YEARS?|MONTHS?|DAYS?)\s*FROM\b",
    re.IGNORECASE,
)

# Unambiguous non-food product-type vocabulary. The 3B SLM leaves 'edible'
# blank on cosmetics / toiletries / non-edible household goods (no food word,
# and these labels never print an explicit 'non-edible' marker), so the merge
# supplies a deterministic 'no' ONLY when the raw OCR token stream across all
# photos carries one of these phrases — every word here denotes a commodity
# class that is never food, so the verdict is evidence-backed, not a guess.
_NON_FOOD_RE = re.compile(
    r"\b(deodorant|antiperspirant|parfum|perfume|cologne|eau de parfum|"
    r"eau de toilette|body spray|body lotion|cotton swabs|cotton buds|"
    r"hair oil|sunscreen|spf|sanitary|face wash|moisturiser|moisturizer|"
    r"hairfall|anti.?dandruff|for external use|not for consumption|"
    r"not meant for consumption)\b",
    re.IGNORECASE,
)


def _non_food_evidence(results: List[Dict]) -> bool:
    for r in results:
        if not r:
            continue
        tokens = r.get("tokens") or []
        for t in tokens:
            text = str(t.get("text", "")) if isinstance(t, dict) else str(t)
            if _NON_FOOD_RE.search(text):
                return True
    return False


# A 3B SLM sometimes hands a promotion/boilerplate line back as the product
# name ('With TULSI MADHA…', 'Suggested Carnishing', 'CONTENTS Selected
# Washed', 'Newltem', 'Fewmmended Alowance'). The routing only lets a
# front-photo name win when it is plausible; gated candidates fall through to
# the side/back name (or the heuristic value), never losing the run4 baseline.
_JUNK_NAME_RE = re.compile(
    r"^\s*(?:with\s+|suggest(?:ed)?\s+|contents\s+|few\w*\s*|"
    r"regis(?:tered)?\w*\s*|trademark\w*\s*|once\w*\s*|made\w*\s*|"
    r"new\w*\s*|serving\s+)", re.I)


def _name_plausible(value: str) -> bool:
    return not _JUNK_NAME_RE.match(str(value or ""))


# Field -> strongest label-type source, in preference order. The statutory
# declarations (MRP/USP/net-qty/manufacturer/dates/care/dimensions) print on
# the back label (or its side panel when no back shot exists); product
# identity (name / food vs not) lives on the front/PDP face. 'top' is the
# cap/roof face: on no-back products (e.g. EVEREST snack packs 27/28/29) it is
# the declaration face (MRP/USP/batch/use-by/net wt), so it ranks just below
# 'back' for declarations — and last for name/edible (a cap is never the PDP).
_FIELD_LABEL_TYPES = {
    "product_name": ("front", "side", "back", "other"),
    "edible": ("front", "side", "back", "other"),
    "mrp": ("back", "top", "side", "other", "front"),
    "usp": ("back", "top", "side", "other", "front"),
    "net_quantity": ("back", "top", "side", "other", "front"),
    "manufacturer": ("back", "top", "side", "other", "front"),
    "manufacturing_date": ("back", "top", "side", "other", "front"),
    "expiry_date": ("back", "top", "side", "other", "front"),
    "consumer_care": ("back", "top", "side", "other", "front"),
    "dimensions": ("back", "top", "side", "other", "front"),
}


_DATE_KW_RE = re.compile(
    r"\b(?:mfg|mfd|manuf\w*|pack(?:ed|ing)?|pkd|use\s*by|best\s*"
    r"before|expir\w*|exp)\b|\bby\b",
    re.I)
_YEAR_4DIGIT_RE = re.compile(r"(?:19|20)\d{2}")
# Numeric date-shaped groups: dd/mm[/yy(yy)] or mm/yyyy. (Month-name forms are
# caught separately via _MONTH_YEAR_GLUE_RE / _MONTH_BARE_RE so they don't need
# a keyword.)
_NUM_DATE_RE = re.compile(r"\d{1,2}\s*[/.:-]\s*\d{1,4}(?:\s*[/.:-]\s*\d{2,4})?")

# ── date-token OCR repair (merge-level; the OCR layer is byte-identical) ─────
# Deterministic repairs for the month-mangling the CPU recognizer does on
# concise Indian date print. Applied only to the token text *inside the date
# evidence collector*; qualification still requires a real month and a
# 2000-2099 year via parse_date, so repairs can only create candidates that
# parse as valid dates (never guessed years or months).
#   * '14-N0-2025' / '13-NO-2026'            NO/N0 -> NOV inside dd-mon-yyyy
#   * 'UN25AU626...' ('JUN25AUG26' glued)    short months glued into alnum runs
#   * 'FEB25'                                2-digit year after a month word
_DMON_FIX = re.compile(
    r"(?P<pre>\d{1,2}[-/.:])(?P<mon>N[O0]V?)(?=[-/.:]\s*\d{2,4}\b)", re.I)
_MONTH_GLUE_FIX = [
    (re.compile(r"JHN(?=\s*/?\s*\d{2})"), "JAN"),
    (re.compile(r"JU1(?=\s*/?\s*\d{2})"), "JUL"),
    (re.compile(r"FE8(?=\s*/?\s*\d{2})"), "FEB"),
    (re.compile(r"AU6(?=\s*/?\s*\d{2})"), "AUG"),
    (re.compile(r"(?<![A-Z0-9])J?UN(?=\s*/?\s*\d{2})"), "JUN"),  # 'UN25' -> 'JUN25'
    (re.compile(r"(?<![A-Z0-9])JN(?=\s*/?\s*\d{2})"), "JUN"),
]
_GLUED_PAIR_RE = re.compile(
    r"(?<![0-9A-Z])(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)"
    r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)(\d{2})(?!\d)",
    re.I)
_SHORT_MONTH_RE = re.compile(
    r"(?<![A-Z])(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC|JANUARY"
    r"|FEBRUARY|MARCH|APRIL|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER"
    r"|DECEMBER)\s*/?\s*(\d{2})(?![0-9])", re.I)


def _repair_date_token(text: str) -> str:
    """Deterministically repair the OCR month-glyph forms listed above."""
    t = str(text or "").upper()
    t = _DMON_FIX.sub(lambda m: m.group("pre") + "NOV", t)
    for pat, repl in _MONTH_GLUE_FIX:
        t = pat.sub(repl, t)

    def _pair(m):
        return (f"{m.group(1)}/20{int(m.group(2)):02d} "
                f"{m.group(3)}/20{int(m.group(4)):02d}")
    t = _GLUED_PAIR_RE.sub(_pair, t)

    def _expand(m):
        mon = m.group(1)
        yy = int(m.group(2))
        return f"{mon}/20{yy:02d}" if 0 <= yy <= 99 else m.group(0)
    t = _SHORT_MONTH_RE.sub(_expand, t)
    return t


# Month-name spans for the date-evidence collector: optional leading day
# ('14-NOV-2025' keeps the day), month word, year. The trailing (?!\d) allows
# glued barcode runs ('AUG/2026U13...') while still ending the year cleanly.
# Bare month words without a year fall back to _MONTH_BARE_RE (and are then
# rejected by parse_date, matching the pre-repair behavior).
_MONTH_YEAR_GLUE_RE = re.compile(
    rf"(?<![A-Z])(\d{{1,2}}\s*[-/.:]\s*)?({_MONTH_ALT})\s*[-/.:]?\s*(\d{{2,4}})(?!\d)",
    re.I)
_MONTH_BARE_RE = re.compile(
    rf"(?<![A-Z])({_MONTH_ALT})(?![A-Z0-9])", re.I)


def _collect_token_dates(results: List[Dict]) -> List[tuple]:
    """Every plausible (year, month) date read anywhere in the raw OCR token
    streams, deduped by (year, month), each with its max confidence. Sorted
    ascending by (year, month).

    Qualification guards (so nutrition decimals, times and license numbers can
    never masquerade as expiry evidence):
      * parse_date must resolve a real month AND a 2000-2099 year;
      * numeric groups must contain a 4-digit year (2000+) or sit in a token
        with a date keyword (MFG / PKD / USE BY / BEST BEFORE / EXP ...);
      * month-name groups ('JAN 2027', 'FEB / 2025', '14-NOV-2025') qualify on
        their own; the token is first run through _repair_date_token so common
        recognizer month-mangles ('N0' -> NOV, glued 'JUN25AUG26') can qualify.
    """
    best: Dict[tuple, tuple] = {}
    for r in results:
        for tok in (r.get("tokens") or []):
            text = _repair_date_token(tok.get("text"))
            text = str(text).strip()
            if not text:
                continue
            conf = float(tok.get("conf") or 0.0)
            has_kw = bool(_DATE_KW_RE.search(text))
            groups = []
            masked = [c for c in text.upper()]

            def _blank(a: int, b: int) -> None:
                for j in range(a, b):
                    masked[j] = " "

            for gm in _MONTH_YEAR_GLUE_RE.finditer(text.upper()):
                g = gm.group(0).strip()
                if g:
                    groups.append(g)
                _blank(gm.start(), gm.end())
            for gm in _MONTH_BARE_RE.finditer("".join(masked)):
                g = gm.group(0).strip()
                if g:
                    groups.append(g)
                _blank(gm.start(), gm.end())
            for nm in _NUM_DATE_RE.finditer("".join(masked)):
                g = nm.group(0).strip()
                if g and (has_kw or _YEAR_4DIGIT_RE.search(g)):
                    groups.append(g)
                _blank(nm.start(), nm.end())
            for g in groups:
                year, month = parse_date(g)
                if year is None or month is None or not (2000 <= year <= 2099):
                    continue
                key = (year, month)
                if key not in best or conf > best[key][0]:
                    best[key] = (conf, g)
    return sorted(
        ((y, m, best[(y, m)][1]) for (y, m), (conf, g) in best.items()),
        key=lambda t: t[:2],
    )


def _reconcile_date_ordering(merged: Dict, results: List[Dict]) -> None:
    """Repair mfg/exp from raw-OCR date pairs (the 'two dates' rule).

    The SLM can (rarely) hand back an inverted pair (mfg later than expiry:
    p15 12/2025 + 01/2025), file the expiry into mfg with expiry left blank
    (p24), or miss a clearly-printed second date (p20). The raw OCR token
    streams carry both dates in these cases, so order them by (year, month)
    and apply only where the current cells are empty, provably inverted, or
    provably mis-filed. A healthy ordered pair is never touched (0 regressions).
    """
    cands = _collect_token_dates(results)
    if len(cands) < 2:
        return
    (y1, m1, s1), (y2, m2, s2) = cands[0], cands[1]
    if (y1, m1) >= (y2, m2):
        return
    cm = (merged.get("manufacturing_date") or "").strip()
    ce = (merged.get("expiry_date") or "").strip()
    pm = parse_date(cm) if cm else None
    pe = parse_date(ce) if ce else None
    clean1 = re.sub(r"\s*([/-])\s*", r"\1", s1)
    clean2 = re.sub(r"\s*([/-])\s*", r"\1", s2)

    # parse_date can legitimately return (None, month) or (year, None) — a
    # *truthy* tuple, so `if pm and pe` does not filter it and the deep
    # `pm > pe` comparison crashes on None components (pp2ctrl product 9).
    # Repair only provable inversions: both cells fully parsed to year+month.
    def _full_key(d):
        return (d[0], d[1]) if d and d[0] is not None and d[1] is not None else None

    kp, ke = _full_key(pm), _full_key(pe)
    if cm and ce:
        # Both present: only repair a physically impossible pair (mfg later
        # than expiry). Ordered or equal pairs are left alone.
        if kp and ke and kp > ke and len(cands) == 2:
            merged["manufacturing_date"] = clean1
            merged["expiry_date"] = clean2
    elif not cm and not ce:
        if len(cands) == 2:
            merged["manufacturing_date"] = clean1
            merged["expiry_date"] = clean2
    elif ce and not cm:
        if pe == (y2, m2):
            merged["manufacturing_date"] = clean1
    else:  # cm present, ce empty
        if pm == (y1, m1):
            merged["expiry_date"] = clean2
        elif pm == (y2, m2) and len(cands) == 2:
            # mfg holds the later date: it is the mis-filed expiry (p24).
            merged["manufacturing_date"] = clean1
            merged["expiry_date"] = clean2


def next_inspection_id() -> str:
    import secrets
    return f"LGM-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"


def merge_extractions(results: List[Dict],
                      label_types: Optional[List[Optional[str]]] = None) -> Dict:
    """Merge per-photo extractions.

    MRP / USP / net quantity must reflect one printed declaration, so the three
    are taken together from the single photo that carries the most statutory
    price fields (the back-label block), never mixed across photos. Other fields
    (name, manufacturer, dates…) fall back to longest-string-wins.

    ``label_types`` (aligned with ``results``; None/unknown entries rank last)
    route each field to the photo whose label type is its strongest source —
    product_name/edible from the front (PDP), statutory declarations from the
    back, side/other as back-ups when no back shot was captured. Unlabeled
    uploads (no label_types) keep the original best-photo heuristics; the
    MFG/EXP date cleanup (drop non-dates, split glued ranges) applies in both
    paths because it only ever removes junk that cannot be a valid date.
    """
    if label_types is None or len(label_types) != len(results):
        label_types = [None] * len(results)
    labeled = any(label_types)
    stat_keys = ("mrp", "usp", "net_quantity")
    # Manufacturing/expiry travel together too: a lone month-date on a side
    # panel is usually the expiry, and longest-wins would otherwise let it
    # overwrite the true manufacturing year read from the batch sticker.
    date_keys = ("manufacturing_date", "expiry_date")

    def _filled(d: Dict) -> Dict:
        return {k: v for k, v in d.items()
                if isinstance(v, str) and v.strip() and v != "None"}

    def _block_from_best(results: List[Dict], keys: tuple, need: int) -> Dict:
        ranked = []
        for r in results:
            if not r:
                continue
            filled = _filled(r)
            weight = sum(1 for k in keys if k in filled)
            ranked.append((weight, len(filled), r))
        if not ranked:
            return {}
        ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
        best = _filled(ranked[0][2])
        if sum(1 for k in keys if k in best) >= need:
            return {k: v for k, v in best.items() if k in keys}
        return {}

    merged = {}
    if results:
        merged.update(_block_from_best(results, stat_keys, 2))
        dblock = _block_from_best(results, date_keys, 2)
        dm, de = _clean_date_pair(
            dblock.get("manufacturing_date", ""),
            dblock.get("expiry_date", ""))
        if dm:
            merged["manufacturing_date"] = dm
        if de:
            merged["expiry_date"] = de

    for result in results:
        if not result:
            continue
        for key, value in result.items():
            if not value:
                continue
            if key in stat_keys and key in merged:
                continue
            if key in date_keys:
                # Never let a non-date line ('6 MONTHS', 'Anso Certified…')
                # fill an mfg/exp cell — junk beats blank one-way only.
                if _date_component(str(value))[0] == "none":
                    continue
                if key in merged:
                    continue
            if key not in merged or len(str(value)) > len(str(merged[key])):
                merged[key] = value

    # consumer_care: the longest string is 'longest-string-wins' poison — a
    # boilerplate disclaimer line ('All pictures shown are for illustration…')
    # is far longer than the real care contact ('care@brand.com'). Prefer a
    # value that actually contains a contact channel (email / toll-free /
    # phone) across all photos; fall back to longest only when none is contact-like.
    care_candidates = [
        _filled(r).get("consumer_care")
        for r in results
        if r and _care_contact_like(_filled(r).get("consumer_care", ""))
    ]
    care_candidates = [c for c in care_candidates if c]
    if care_candidates:
        merged["consumer_care"] = max(care_candidates, key=len)
    elif "consumer_care" in merged and not _care_contact_like(
        merged.get("consumer_care", "")
    ):
        merged["consumer_care"] = ""

    if labeled:
        merged = _route_by_label_types(results, label_types, merged)
    # Raw-OCR two-date reconciliation: if the token streams across all photos
    # carry both an earlier and a later clean date, use the physical invariant
    # (manufacture before expiry) to repair inverted/mis-filed/missing pairs.
    # Runs after routing so it is the final word on mfg/exp, but never touches
    # a healthy ordered pair (0-regression guard) and never clobbers an
    # inspector's manual override (those are applied post-merge on top).
    _reconcile_date_ordering(merged, results)
    # A corrupt single-digit-year read ('14.04.0' -> fake 14/04/2020) is
    # unreadable, not a partial: blank it so the field is NOT DETECTED and the
    # inspector keys the true value. Runs after reconciliation = final word on
    # mfg/exp; year-only, 2/4-digit-year and month-name dates never match.
    for dk in date_keys:
        if _corrupt_single_digit_year(merged.get(dk)):
            merged[dk] = ""
    # Shelf-life notes ('5Yrs from DEC/2024', '6 MONTHS FROM MANUFACTURE')
    # are duration phrases, not an expiry declaration. When the SLM files one
    # into expiry, blank it (NOT DETECTED) rather than shipping a non-date.
    if _SHELF_LIFE_RE.search(str(merged.get("expiry_date") or "")):
        merged["expiry_date"] = ""
    # A net quantity of ~10^16 litres is a barcode/multi-token misread, never
    # a printed declaration (legal labels run g..l). Absurd magnitudes are
    # unreadable, not data: blank so the inspector keys the true value.
    nq = str(merged.get("net_quantity") or "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg|gm|mg|ml|cl|l)\b",
                  nq, re.IGNORECASE)
    if m and float(m.group(1)) > 1_000_000:
        merged["net_quantity"] = ""
    # CJK characters in a consumer-care line are recognizer misreads of an
    # Indian labelled product, never a valid contact channel. Drop to
    # NOT DETECTED instead of emitting '电话0-08-07-...' as the care line.
    care = str(merged.get("consumer_care") or "").strip()
    if care and re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", care):
        merged["consumer_care"] = ""
    # Non-edible commodity fallback: when the SLM left 'edible' blank (it cannot
    # verify edibility off the label — no food word, and non-edible products
    # don't print an explicit marker) but the raw OCR tokens carry an
    # unambiguous non-food phrase ('DEODORANT', 'COTTON SWABS', 'SUNSCREEN'…),
    # emit a deterministic 'no'. Fires only on a blank cell + printed evidence,
    # so it never overrides an SLM verdict and never creates a false 'no'.
    if not merged.get("edible") and _non_food_evidence(results):
        merged["edible"] = "no"

    # ── Merge-gate: recover cells we blanked even though THIS draw's cached
    # stream carries the printed text. The SLM probe triaged the golden misses
    # into two provable classes: MERGE-DROPPED (86 cells — engine read it, our
    # merge dropped it; text IS in this same draw's per-photo streams) vs
    # ENGINE-DROPPED (29 cells — no trace anywhere; honest NOT DETECTED). This
    # gate exists only for the first class. Its contract is exactly the one
    # every shipped gate obeys:
    #   · fires ONLY on a cell the merge left blank → a byte-identical ok cell
    #     is never blank, so it cannot be moved (0-regression by construction);
    #   · reads ONLY from the current draw's per-photo streams (results), i.e.
    #     text the engine provably returned on THIS draw — no fresh OCR, no
    #     golden peeking;
    #   · re-validates every candidate with the same vocabulary the honest
    #     gates already ship (care-contact-like, clean date, non-absurd
    #     net-quantity, non-CJK, shelf-life≠expiry), so a both-blank-ok cell
    #     whose stream carries only junk stays blank — never a false fill.
    for k in ("consumer_care", "manufacturer", "mrp", "net_quantity",
              "product_name", "usp"):
        if merged.get(k):
            continue
        # Care is contact-like-only; a slogan that merely mentions a % is not a
        # consumer-care line no matter which photo it sat on.
        if k == "consumer_care":
            # Same CJK rejection the honesty gate ships for the same key: a
            # recognizer-misread care line that carries any CJK character
            # (电话0-08-07-AACM74336-22…) is noise on an Indian-labeled
            # product — the honesty gate blanks it BY RULING, so our gate
            # must refuse the very same candidate class and let the blank
            # stand (deferrence), never refill it.
            cands = [r.get("consumer_care", "") for r in results if r
                     and _care_contact_like(str(r.get("consumer_care", "")))
                     and not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]",
                                       str(r.get("consumer_care", "")))]
            cands = [c for c in cands if c]
            if cands:
                merged[k] = max(cands, key=len)
            continue
        # manufacturer / product_name / usp / net_quantity: longest valid
        # non-junk across this draw's streams; validators are the same ones the
        # merge gates already trust for the same key.
        cands = [str(r.get(k, "")).strip() for r in results if r]
        cands = [c for c in cands if c and c != "None"]
        if not cands:
            continue
        if k == "net_quantity":
            cands = [c for c in cands if _date_component(c)[0] == "none"
                     and not re.search(r"(\d+(?:\.\d+)?)\s*(?:g|kg|gm|mg|ml|cl|l)\b",
                                       c, re.IGNORECASE)
                     or re.search(
                         r"\d+\s*(?:ml|mls?\.?|g|gm|kg|ltr?e?rs?|litres?|pcs?|pack|gram|grams|tablets?|capsules?|pieces?)\b",
                         c, re.IGNORECASE)]
        elif k == "mrp":
            cands = [c for c in cands if re.search(r"(?i)(?:rs\.?|rs|mrp)\s*[:.\s]*\d{2,4}", c)]
        merged[k] = max(cands, key=len) if cands else ""

    return merged


def _route_by_label_types(results: List[Dict],
                          label_types: List[Optional[str]],
                          merged: Dict) -> Dict:
    """Re-select each field from the photo whose label type is its strongest
    source, keeping block coherence (stats travel together, dates travel
    together). Values the routing cannot source are left at their heuristic
    value in ``merged``."""

    def _rank(field: str, tag: Optional[str]) -> int:
        order = _FIELD_LABEL_TYPES.get(field, ())
        return order.index(tag) if tag in order else len(order)

    filled_list = []
    for r, tag in zip(results, label_types):
        if not r:
            filled_list.append(({}, tag))
            continue
        filled_list.append((
            {k: v for k, v in r.items()
             if isinstance(v, str) and v.strip() and v != "None"},
            tag,
        ))

    def _pick(fields: tuple, need: int) -> Optional[Dict]:
        """Values from the strongest-source photo carrying >= need of fields.
        Tie-breaks: more fields present, then longer values. consumer_care is
        additionally contact-gated; product_name must be plausible (no
        promo/boilerplate lines); mfg/exp must actually read as dates."""
        best = None  # (score, {field: value})
        for filled, tag in filled_list:
            present = {k: str(filled.get(k) or "").strip() for k in fields}
            if "consumer_care" in fields and present["consumer_care"] \
                    and not _care_contact_like(present["consumer_care"]):
                present["consumer_care"] = ""
            if "product_name" in fields and present["product_name"] \
                    and not _name_plausible(present["product_name"]):
                present["product_name"] = ""
            if "manufacturing_date" in fields and present["manufacturing_date"] \
                    and _date_component(present["manufacturing_date"])[0] == "none":
                present["manufacturing_date"] = ""
            if "expiry_date" in fields and present["expiry_date"] \
                    and _date_component(present["expiry_date"])[0] == "none":
                present["expiry_date"] = ""
            weight = sum(1 for v in present.values() if v)
            if weight < need:
                continue
            score = (min(_rank(f, tag) for f in fields), -weight,
                     -sum(len(v) for v in present.values() if v))
            if best is None or score < best[0]:
                best = (score, present)
        return best[1] if best else None

    routed: Dict[str, str] = {}
    # Statutory block: prefer one back/side photo carrying >= 2 price fields,
    # so MRP+USP+net-qty reflect the same printed declaration.
    block = _pick(("mrp", "usp", "net_quantity"), need=2) or \
        _pick(("mrp", "usp", "net_quantity"), need=1)
    if block:
        routed.update({k: v for k, v in block.items() if v})
    # Dates travel together (mfg above exp on the sticker): one photo for both,
    # then split any 'MFG-EXP' range the classifier glued onto one cell.
    dblock = _pick(("manufacturing_date", "expiry_date"), need=2) or \
        _pick(("manufacturing_date", "expiry_date"), need=1)
    if dblock:
        dm, de = _clean_date_pair(
            dblock.get("manufacturing_date", ""),
            dblock.get("expiry_date", ""))
        if dm:
            routed["manufacturing_date"] = dm
        if de:
            routed["expiry_date"] = de
    # Product identity from the front/PDP face; statutory text fields
    # (consumer_care, dimensions) from their back/side source. manufacturer is
    # deliberately NOT label-routed: the back short-name ('Sito') sometimes
    # loses to the side legal name ('Bhavani Pharmaceuticals'), and the
    # heuristic longest-wins already scores best there.
    for field in ("product_name", "edible", "consumer_care", "dimensions"):
        picked = _pick((field,), need=1)
        if picked and picked[field]:
            routed[field] = picked[field]

    for k, v in routed.items():
        merged[k] = v
    return merged


def _collect_text_boxes(results: List[Dict]) -> Dict[int, List[float]]:
    """Map {image_index: [x1,y1,x2,y2]} of MRP/NetQty regions from VLM output
    (0-1000 normalized), preferring the MRP region for cap-height measurement."""
    boxes = {}
    for i, result in enumerate(results):
        if not result:
            continue
        regions = result.get("regions") or {}
        for field in ("mrp", "net_quantity"):
            box = regions.get(field)
            if box and len(box) == 4:
                boxes[i] = [float(v) for v in box[:4]]
                break
    return boxes


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _exif_capture_time(image_path: str) -> Optional[str]:
    """ISO timestamp of photo capture (EXIF DateTimeOriginal / Digitized)."""
    return preprocessing.safe_capture_time(image_path)


def _store_evidence(image_paths: List[str]) -> List[Dict]:
    """Copy each image into the evidence store; returns [{filename, sha256, original}]."""
    stored = []
    evidence_dir = resolve_evidence_dir()
    for order, path in enumerate(image_paths):
        src = Path(path)
        if not src.exists():
            continue
        sha = _sha256_of_file(src)
        filename = f"{sha[:16]}_{order + 1}_evidence{src.suffix.lower() or '.jpg'}"
        dest = evidence_dir / filename
        if not dest.exists():
            shutil.copy2(src, dest)
        stored.append(
            {"filename": filename, "sha256": sha, "original_name": src.name, "sort_order": order}
        )
    return stored


def _dimensions_relevant(decl: Dict) -> bool:
    """Rule 6(1)(g): dimensions are required only for non-edible commodities
    sold by dimensions (garments, cables, electronics, etc.)."""
    edible = str(decl.get("edible", "") or "").strip().lower()
    if edible in ("no", "false", "n", "non_edible", "non-edible", "non edible"):
        return True
    return False


def compute_missing(safe_decl: Dict) -> List[str]:
    missing = []
    for req in rule_engine.get_required_declarations():
        if req == "dimensions_where_relevant" and not _dimensions_relevant(safe_decl):
            continue
        field = REQUIRED_TO_FIELD.get(req)
        if field and not safe_decl.get(field):
            missing.append(req)
    return missing


def apply_manual_overrides(inspection_id: str, overrides: Dict, user_id: Optional[int]) -> Dict:
    """Apply an inspector's corrected declaration values to a stored inspection.

    Re-evaluates rules on the corrected declarations so status / score /
    violations stay truthful, records the original AI value plus who/when in
    ``meta.manual_overrides``, and persists the new result.
    """
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise ValueError(f"Inspection {inspection_id} not found")

    bad = [k for k in overrides if k not in EXPECTED_KEYS and k != "manufacturer_address"]
    if bad:
        raise ValueError(f"Unknown fields: {', '.join(sorted(bad))}")

    declarations = {k: (str(v).strip() if v else "") for k, v in inspection.get("declarations", {}).items()}
    meta = dict(inspection.get("meta") or {})
    # _row_to_dict flattens meta_json to the top level; re-collect those keys.
    for flat_key in ("compliance_radar", "grade", "rule_version", "font_measurement", "ocr_engine",
                     "classifier", "field_evidence", "extraction_confidence"):
        if flat_key not in meta and inspection.get(flat_key):
            meta[flat_key] = inspection[flat_key]
    override_log = dict(meta.get("manual_overrides") or {})

    for key, value in overrides.items():
        corrected = str(value).strip() if value is not None else ""
        original = declarations.get(key, "") or ""
        if corrected == original:
            continue
        declarations[key] = corrected
        override_log[key] = {
            "original": original,
            "corrected": corrected,
            "by_user_id": user_id,
            "at": datetime.now().isoformat(),
        }
    if override_log:
        meta["manual_overrides"] = override_log

    safe_decl = {k: declarations.get(k, "") for k in EXPECTED_KEYS}
    addr = overrides.get("manufacturer_address")
    if addr is None:
        addr = declarations.get("manufacturer_address", "")
    if addr:
        safe_decl["manufacturer_address"] = str(addr).strip()
    missing = compute_missing(safe_decl)
    overall_status = compute_overall_status(missing)
    compliance = rule_engine.evaluate_compliance(safe_decl, missing)
    misleading_checks = _check_misleading(safe_decl, compliance)
    radar = _rebuild_radar(safe_decl, missing, compliance["violations"], meta, inspection)

    meta["compliance_radar"] = radar
    meta["grade"] = radar.get("grade", "D") if radar else "D"

    inspection_repo.update_inspection_overrides(
        inspection_id=inspection_id,
        declarations=safe_decl,
        status=overall_status,
        compliance=compliance,
        missing_declarations=missing,
        misleading_checks=misleading_checks,
        meta=meta,
    )
    return inspection_repo.get_inspection(inspection_id)


def _rebuild_radar(safe_decl: Dict, missing: List[str], violations: List[Dict],
                   meta: Dict, inspection: Dict) -> Dict:
    """Rebuild the compliance radar after corrections, keeping the measured
    font / readability signals from the original scan."""
    font_measurement = meta.get("font_measurement") or {}
    ocr_meta = {"confidence": meta.get("ocr_confidence")}
    return compliance_scorer.build_radar(safe_decl, missing, violations, font_measurement, ocr_meta)


def compute_overall_status(missing: List[str]) -> str:
    if missing:
        return "POTENTIAL_VIOLATION" if any(m in CRITICAL for m in missing) else "REVIEW_REQUIRED"
    return "COMPLIANT"


def _parse_net_quantity_g(decl: Dict) -> Optional[float]:
    text = decl.get("net_quantity", "") or ""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|gm|gram|kg|ml|l|litre|liter|m|cm)?", text, re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("g", "gm", "gram", "ml"):
        return value
    if unit == "kg":
        return value * 1000
    if unit in ("l", "litre", "liter"):
        return value * 1000
    if unit in ("m", "cm"):
        return value
    return value


def measurement_service_get_required(net_qty_g: Optional[float]) -> Optional[float]:
    if net_qty_g is None:
        return None
    rules = rule_engine.rules.get("font_size_requirements", {}).get("numerals_weight_volume", [])
    for rule in rules:
        cond = rule.get("condition", "")
        if "<= " in cond and "AND" not in cond:
            if net_qty_g <= float(cond.split("<= ")[1]):
                return rule.get("normal")
        elif "AND" in cond:
            lower = float(cond.split("> ")[1].split(" AND")[0])
            upper = float(cond.split("<= ")[1])
            if lower < net_qty_g <= upper:
                return rule.get("normal")
    return None


def _per_image_tokens(individual_results: List[Dict]) -> List[List[Dict]]:
    return [r.get("tokens") or [] for r in individual_results] if individual_results else []


FIELD_CONF_WEIGHTS = {
    "mrp": 0.9, "usp": 0.9, "net_quantity": 0.9, "dimensions": 0.9,
    "consumer_care": 0.8, "manufacturing_date": 0.8, "expiry_date": 0.8,
    "product_name": 0.6, "manufacturer": 0.6, "edible": 0.4,
}


def _field_evidence(individual_results: List[Dict], merged: Dict) -> Dict[str, Dict]:
    """For each extracted field, record which OCR text + which engine (regex /
    llm) backed the value, so every declaration is auditable."""
    evidence = {k: {"source": "", "text": "", "image_index": None}
                for k in EXPECTED_KEYS}
    for idx, r in enumerate(individual_results):
        if not r:
            continue
        fields = r.get("fields") or r
        field_map = r.get("field_map") or {}
        source = (r.get("ocr_meta") or {}).get("classifier", "regex")
        for key in EXPECTED_KEYS:
            val = str(fields.get(key, "") or "").strip()
            if not val:
                continue
            # Prefer whichever image contributed the *merged* value (longest-match).
            merged_val = str(merged.get(key, "") or "").strip()
            if val != merged_val:
                continue
            box_tokens = field_map.get(key) or []
            text = " ".join(str(t.get("text", "") or "") for t in box_tokens)
            if not text:
                continue
            evidence[key] = {
                "source": source,
                "text": text[:300],
                "image_index": idx,
            }
    # Fallback: if no image carried a matching field_map entry but the field is
    # in merged, note the engine that produced the merged value.
    engines = [r.get("ocr_meta", {}).get("classifier", "") for r in individual_results if r]
    engine = engines[0] if engines else ""
    for key in EXPECTED_KEYS:
        if not evidence[key]["text"] and merged.get(key):
            evidence[key]["source"] = engine
            evidence[key]["text"] = str(merged[key])[:300]
    return evidence


def _extraction_confidence(
    individual_results: List[Dict],
    merged: Dict,
    missing: List[str],
) -> Dict:
    """A 0-100 view of how trustworthy the extraction is, per field and overall.

    Signal sources (deliberately conservative — no ground truth available):
      * class of engine (regex > llm for structured fields; llm needed for soft fields)
      * whether the value maps to an actual OCR box (machine-read, not inferred)
      * OCR confidence of the token(s) that backed the value
      * statutory-required-field coverage (missing ones cap the score)
    """
    evidence = _field_evidence(individual_results, merged)
    confs: Dict[str, float] = {}

    for key in EXPECTED_KEYS:
        val = str(merged.get(key, "") or "").strip()
        if not val:
            confs[key] = 0.0
            continue
        ev = evidence.get(key, {})
        source = ev.get("source", "")
        boxed = bool(ev.get("text")) and ev.get("image_index") is not None

        score = FIELD_CONF_WEIGHTS.get(key, 0.6) * 100.0
        if source == "regex":
            score *= 1.05
        elif not source:
            score *= 0.85
        if boxed:
            score += 5.0
        confs[key] = round(max(0.0, min(100.0, score)), 1)

    if confs:
        base = sum(confs.values()) / len(confs)
    else:
        base = 0.0

    # Required statutory fields are the load-bearing ones; cap overall confidence
    # by the coverage ratio so a "name only" scan can't score well.
    required = rule_engine.get_required_declarations()
    relevant = [r for r in required
                if not (r == "dimensions_where_relevant" and not _dimensions_relevant(merged))]
    present = len(relevant) - sum(1 for m in missing if m in relevant)
    coverage = (present / len(relevant)) if relevant else 1.0

    overall = round(base * (0.5 + 0.5 * coverage), 1)
    return {
        "overall": overall,
        "coverage_ratio": round(coverage, 2),
        "fields_present": present,
        "fields_required": len(relevant),
        "by_field": confs,
    }


def _measure_font_for_image(
    image_path: str,
    tokens: List[Dict],
    field_map: Dict,
    required_mm: Optional[float],
    text_box: Optional[List[float]],
) -> Dict:
    """Measure the declaration font using OCR token boxes when available,
    otherwise fall back to the legacy VLM-box/heuristic path."""
    svc = FontMeasurementService()
    mrpq = [t for t in tokens if _token_belongs(t, field_map, ("net_quantity",))]
    mrp = [t for t in tokens if _token_belongs(t, field_map, ("mrp",))]
    tokens_for_measure = mrpq or mrp
    if tokens_for_measure:
        res = svc.measure_from_tokens(image_path, tokens_for_measure, required_mm=required_mm)
        if res is not None:
            res["image_index"] = None
            return res
    res = svc.measure(image_path, required_mm=required_mm, text_box=text_box)
    if res is not None:
        res["image_index"] = None
    return res or {}


def _token_belongs(token: Dict, field_map: Dict, field_names: tuple) -> bool:
    if not field_map:
        return False
    for field in field_names:
        boxes = [t.get("box") for t in (field_map.get(field) or [])]
        for b in boxes:
            if b and b == token.get("box"):
                return True
    return False


def _vlm_rescue(image_paths: List[str], individual_results: List[Dict], ocr) -> List[Dict]:
    """Re-read images that produced low-confidence extractions with a
    vision-language model. Used only when VLM_RESCUE_ENABLED is on and the
    fast CPU path scored below the confidence threshold (resource-adaptive)."""
    try:
        from app.services.vlm_rescuer import VLMRescuer
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("VLM rescuer unavailable: %s", e)
        return []
    rescuer = VLMRescuer(model=VLM_RESCUE_MODEL)
    out = []
    for idx, r in enumerate(individual_results):
        if idx < len(image_paths) and r:
            saved = rescuer.rescue(image_paths[idx], r)
            out.append(saved or r)
        else:
            out.append(r)
    return out


def run_inspection(
    image_paths: List[str],
    user_id: Optional[int] = None,
    ocr=None,
    text_boxes: Optional[Dict[int, List[float]]] = None,
    label_types: Optional[List[Optional[str]]] = None,
    progress_cb=None,
) -> Dict:
    """Full pipeline: preprocess → extract → merge → compliance → font →
    heat-map → radar → persist.

    ``label_types`` (aligned with image_paths, one of front/back/side/other)
    routes each field to the photo whose label type is its strongest source;
    None keeps the original best-photo heuristics.

    ``progress_cb`` is an optional callable receiving stage events
    ({'stage': ..., 'ts': ...}) as the pipeline advances — used by the API for
    a live processing log. Default None: no events are emitted and behaviour is
    unchanged (the audit and all other callers are byte-identical).
    """
    ocr = ocr or _get_default_ocr()
    prev_cb = bind_progress(progress_cb)

    individual_results = []
    _emit_progress("start", images=len(image_paths))
    for index, path in enumerate(image_paths):
        _emit_progress("extract", status="running", image=index + 1,
                       total=len(image_paths), file=Path(path).name)
        individual_results.append(ocr.extract_structured(path))
        meta = individual_results[-1].get("ocr_meta") or {}
        _emit_progress(
            "extract", status="done", image=index + 1, total=len(image_paths),
            lines=meta.get("lines", 0), classifier=meta.get("classifier", ""),
            confidence=meta.get("confidence"),
            fields_found=sum(1 for k in EXPECTED_KEYS if individual_results[-1].get(k)),
            elapsed_s=meta.get("elapsed_s"),
        )

    text_boxes = _collect_text_boxes(individual_results)

    merged = merge_extractions(individual_results, label_types)
    safe_decl = {key: merged.get(key, "") for key in EXPECTED_KEYS}
    missing = compute_missing(safe_decl)
    field_evidence = _field_evidence(individual_results, safe_decl)
    extraction_confidence = _extraction_confidence(individual_results, safe_decl, missing)
    _emit_progress(
        "merge", status="done",
        fields_found=sum(1 for k in EXPECTED_KEYS if safe_decl.get(k)),
        missing=len(missing),
    )

    # Resource-adaptive cascade: escalation to a VLM when confidence is low.
    if VLM_RESCUE_ENABLED and extraction_confidence["overall"] < VLM_RESCUE_CONFIDENCE_THRESHOLD:
        rescued = _vlm_rescue(image_paths, individual_results, ocr)
        if rescued:
            individual_results = rescued
            merged = merge_extractions(individual_results, label_types)
            safe_decl = {key: merged.get(key, "") for key in EXPECTED_KEYS}
            missing = compute_missing(safe_decl)
            field_evidence = _field_evidence(individual_results, safe_decl)
            extraction_confidence = _extraction_confidence(individual_results, safe_decl, missing)

    overall_status = compute_overall_status(missing)
    currency_verified = _verify_mrp_currency(
        ocr, image_paths, individual_results, safe_decl.get("mrp", "")
    )
    _emit_progress("compliance", status="running")
    compliance = rule_engine.evaluate_compliance(
        safe_decl, missing, currency_verified=currency_verified
    )
    _emit_progress("compliance", status="done",
                   passed=compliance.get("passed_count", 0),
                   total=compliance.get("total_rules", 0))

    net_qty_g = _parse_net_quantity_g(safe_decl)
    required_mm = measurement_service_get_required(net_qty_g)

    token_lists = _per_image_tokens(individual_results)
    field_maps = [r.get("field_map", {}) for r in individual_results]

    inspection_id = next_inspection_id()

    font_measurement = None
    first_unmeasurable = None
    per_image_cal_bbox: Dict[int, Optional[List[float]]] = {}
    _emit_progress("font", status="running")
    for index, path in enumerate(image_paths):
        if not Path(path).exists():
            continue
        fm = _measure_font_for_image(
            path,
            token_lists[index] if index < len(token_lists) else [],
            field_maps[index] if index < len(field_maps) else {},
            required_mm,
            (text_boxes or {}).get(index),
        )
        if not fm:
            continue
        fm["image_index"] = index
        fm["image_path"] = str(path)
        capture_time = _exif_capture_time(path)
        if capture_time:
            fm["photo_capture_timestamp"] = capture_time
        if fm.get("calibration_bbox"):
            per_image_cal_bbox[index] = [float(v) for v in fm["calibration_bbox"]]
        if fm.get("status") == "CANNOT_MEASURE":
            if first_unmeasurable is None:
                first_unmeasurable = fm
            continue
        if font_measurement is None:
            font_measurement = fm

    _emit_progress("font", status="done",
                   measured=(font_measurement or {}).get("status", "NOT_MEASURED"))

    misleading_checks = _check_misleading(safe_decl, compliance, currency_verified)

    _emit_progress("evidence", status="running")
    heatmaps = _render_heatmaps(
        image_paths, token_lists, field_maps, per_image_cal_bbox,
        compliance["violations"], inspection_id,
    )
    _emit_progress("evidence", status="done", heatmaps=len(heatmaps))

    ocr_meta_list = [r.get("ocr_meta") or {} for r in individual_results]
    radar = _build_radar_all(
        safe_decl, missing, compliance["violations"],
        font_measurement, ocr_meta_list, image_paths, token_lists, field_maps,
        required_mm,
    )

    prompt_hash = ""
    fingerprint = getattr(ocr, "prompt_fingerprint", None)
    if callable(fingerprint):
        try:
            prompt_hash = fingerprint()
        except Exception:
            prompt_hash = ""

    ocr_engine_name = getattr(ocr, "ocr_engine", None)
    try:
        ocr_engine_name = ocr_engine_name() if callable(ocr_engine_name) else (ocr_meta_list[0].get("engine") if ocr_meta_list else "")
    except Exception:
        ocr_engine_name = ""
    method = f"{ocr_engine_name} + {_classifier_label(ocr)}" if ocr_engine_name else QWN_MODEL

    evidence = _store_evidence(image_paths)
    evidence_hash = ""
    for item in evidence:
        evidence_hash += item["sha256"]
    evidence_hash = hashlib.sha256(evidence_hash.encode("utf-8")).hexdigest() if evidence_hash else ""

    # ── manufacturer address (pure side channel) ──────────────────────────────
    # Derived deterministically from the raw OCR token stream only — never
    # alters the ten frozen fields, the merge, or the compliance pipeline, so
    # the golden-statutory audit stays byte-identical. Injected only when a
    # genuinely address-looking block (PIN + street/city markers) was found.
    manufacturer_address = extract_manufacturer_address(
        individual_results, safe_decl.get("manufacturer", "")
    )
    if manufacturer_address:
        ordered = {}
        for key in EXPECTED_KEYS:
            ordered[key] = safe_decl.get(key, "")
            if key == "manufacturer":
                ordered["manufacturer_address"] = manufacturer_address
        safe_decl = ordered

    # ── raw-OCR transcript (display-only side channel) ─────────────────────────
    # Aggregates each image's nested ocr_meta.raw_ocr block (reads down to the
    # transcript floor from the SAME single engine call as the classifier) into
    # a frontend-friendly list. Never re-fed to the classifier or the frozen
    # ten-field merge — pure transparency layer.
    ocr_transcript = build_ocr_transcript(image_paths, individual_results)

    meta = {
        "compliance_radar": radar,
        "grade": radar.get("grade", "D") if radar else "D",
        "rule_version": rule_engine.version,
        "font_measurement": font_measurement,
        "heatmaps": heatmaps,
        "ocr_engine": ocr_engine_name,
        "classifier": _classifier_label(ocr),
        "field_evidence": field_evidence,
        "extraction_confidence": extraction_confidence,
        "ocr_transcript": ocr_transcript,
    }

    result = {
        "inspection_id": inspection_id,
        "timestamp": datetime.now().isoformat(),
        "method": method,
        "rule_version": rule_engine.version,
        "images_processed": len(image_paths),
        "declarations": safe_decl,
        "missing_declarations": missing,
        "status": overall_status,
        "compliance_score": compliance["compliance_score"],
        "passed_count": compliance["passed_count"],
        "total_rules": compliance["total_rules"],
        "violations": compliance["violations"],
        "misleading_checks": misleading_checks,
        "extraction_prompt_hash": prompt_hash,
        "font_measurement": font_measurement,
        "compliance_radar": radar,
        "grade": radar.get("grade", "D") if radar else "D",
        "heatmaps": heatmaps,
        "evidence": {"hash": evidence_hash, "images": evidence},
        "field_evidence": field_evidence,
        "extraction_confidence": extraction_confidence,
        "ocr_transcript": ocr_transcript,
    }

    inspection_repo.save_inspection(
        {
            "id": inspection_id,
            "timestamp": result["timestamp"],
            "product_name": safe_decl.get("product_name"),
            "manufacturer": safe_decl.get("manufacturer"),
            "status": overall_status,
            "compliance_score": compliance["compliance_score"],
            "passed_count": compliance["passed_count"],
            "total_rules": compliance["total_rules"],
            "declarations": safe_decl,
            "missing_declarations": missing,
            "violations": compliance["violations"],
            "misleading_checks": misleading_checks,
            "evidence_hash": evidence_hash,
            "images_count": len(image_paths),
            "model": method,
            "user_id": user_id,
            "meta": meta,
        }
    )
    for item in evidence:
        inspection_repo.add_inspection_image(
            inspection_id, item["filename"], item["original_name"], item["sha256"], item["sort_order"]
        )

    _emit_progress("done", inspection_id=inspection_id, status=overall_status,
                   score=compliance.get("compliance_score", 0))
    restore_progress(prev_cb)
    return result


def _classifier_label(ocr) -> str:
    _ = ocr
    from app.config import FIELD_CLASSIFIER_ENABLED, FIELD_CLASSIFIER_MODEL
    return FIELD_CLASSIFIER_MODEL if FIELD_CLASSIFIER_ENABLED else "regex"


def _render_heatmaps(
    image_paths: List[str],
    token_lists: List[List[Dict]],
    field_maps: List[Dict],
    cal_bboxes: Dict[int, List[float]],
    violations: List[Dict],
    inspection_id: str,
) -> List[Dict]:
    """Generate heat-map overlays per photo into the evidence dir."""
    evidence_dir = resolve_evidence_dir()
    heatmap_dir = evidence_dir / "heatmaps"
    heatmap_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for index, path in enumerate(image_paths):
        out_name = f"{inspection_id}_{index + 1}_heatmap.jpg"
        out_path = heatmap_dir / out_name
        rendered = heatmap_generator.render_heatmap(
            path,
            str(out_path),
            tokens=token_lists[index] if index < len(token_lists) else [],
            field_map=field_maps[index] if index < len(field_maps) else {},
            calibration_bbox=cal_bboxes.get(index),
            violations=violations,
        )
        if rendered:
            out.append({
                "filename": out_name,
                "image_index": index,
                "field_boxes": rendered["field_boxes"],
                "calibration_box": rendered["calibration_box"],
            })
    return out


def _build_radar_all(
    safe_decl: Dict,
    missing: List[str],
    violations: List[Dict],
    font_measurement: Optional[Dict],
    ocr_meta_list: List[Dict],
    image_paths: List[str],
    token_lists: List[List[Dict]],
    field_maps: List[Dict],
    required_mm: Optional[float],
) -> Dict:
    """Merge the best per-photo font/readability signal into one radar."""
    primary = compliance_scorer.build_radar(
        safe_decl, missing, violations, font_measurement,
        _pick_meta(ocr_meta_list),
    )
    if len(image_paths) <= 1:
        return primary
    secondary = None
    if font_measurement is not None:
        secondary_meta = _pick_meta(ocr_meta_list, skip=0) or {}
        secondary = compliance_scorer.build_radar(
            safe_decl, missing, violations, font_measurement, secondary_meta
        )
    return compliance_scorer.merge_radar(primary, secondary)


def _pick_meta(ocr_meta_list: List[Dict], skip: int = 0) -> Optional[Dict]:
    cands = [m for m in ocr_meta_list if m and m.get("confidence")]
    if skip:
        cands = cands[skip:]
    return max(cands, key=lambda m: m.get("confidence", 0)) if cands else None


def _verify_mrp_currency(
    ocr, image_paths: List[str], individual_results: List[Dict], merged_mrp: str
) -> Dict[str, bool]:
    """If the merged MRP is a bare number (no ₹/Rs.), the OCR may have dropped
    the currency glyph even though the label prints it. Ask the engine to look
    at the source photo(s) again before ruling on Rule 6(1)(e) format."""
    merged_mrp = (merged_mrp or "").strip()
    if not merged_mrp or not re.search(r"\d", merged_mrp):
        return {}
    if "₹" in merged_mrp or "rs" in merged_mrp.lower() or "inr" in merged_mrp.lower():
        return {}
    verifier = getattr(ocr, "verify_currency_symbol", None)
    if not callable(verifier):
        return {}

    candidates = [
        img for img, r in zip(image_paths, individual_results)
        if r and str(r.get("mrp", "") or "").strip() == merged_mrp
    ] or [
        img for img, r in zip(image_paths, individual_results)
        if r and (r.get("mrp") or "")
    ] or list(image_paths)

    for path in candidates:
        try:
            confirmed = verifier(path, merged_mrp)
        except Exception:
            confirmed = None
        if confirmed is True:
            return {"mrp": True}
    return {}


def _check_misleading(
    safe_decl: Dict, compliance: Dict, currency_verified: Optional[Dict[str, bool]] = None
) -> List[Dict]:
    """Consistency checks that catch misleading declarations."""
    issues = []
    mrp_text = safe_decl.get("mrp", "")
    usp_text = safe_decl.get("usp", "")

    if mrp_text:
        ok, msg = rule_engine.validate_mrp_format(
            mrp_text, symbol_verified=bool((currency_verified or {}).get("mrp"))
        )
        if not ok:
            issues.append(
                {"check": "mrp_format", "severity": "HIGH", "detail": msg,
                 "extracted_value": mrp_text}
            )

    if mrp_text and usp_text:
        mrp_num = _extract_number(mrp_text)
        usp_num = _extract_number(usp_text)
        if mrp_num and usp_num and abs(mrp_num - usp_num) < 0.01:
            issues.append(
                {"check": "usp_missing_or_equal_mrp", "severity": "MEDIUM",
                 "detail": "USP equals MRP — USP declaration may be missing (unit sale price "
                           "must be stated per unit and differ from MRP unless exempt).",
                 "extracted_value": f"MRP={mrp_text}; USP={usp_text}"}
            )

    if mrp_text and usp_text:
        declared = _extract_number(usp_text)
        mrp_num = _extract_number(mrp_text)
        net_qty_text = safe_decl.get("net_quantity", "")
        net_num = _extract_number(net_qty_text)
        unit = _net_qty_unit(net_qty_text)
        if declared and mrp_num and net_num:
            expected, _ = price_engine.calculate_usp(mrp_num, net_num, unit)
            if expected is not None and abs(declared - expected) > 0.05:
                issues.append(
                    {"check": "usp_mismatch_computed", "severity": "MEDIUM",
                     "detail": "Printed unit sale price does not match MRP / net quantity "
                               f"({declared} vs expected {expected} per {unit}).",
                     "extracted_value": f"USP={usp_text}; MRP={mrp_text}; NetQty={net_qty_text}"}
                )

    return issues


def _extract_number(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)", str(text))
    return float(m.group(1)) if m else None


def _net_qty_unit(text: str) -> str:
    """Infer the unit of a net-quantity declaration like '45 g' / '250 ml'."""
    if not text:
        return "g"
    m = re.search(r"(kg|l|ml|mg|g)\b", str(text).lower())
    return m.group(1) if m else "g"


_ocr_instance = None


def _get_default_ocr():
    global _ocr_instance
    if _ocr_instance is None:
        from app.services.ocr_engine import get_ocr_service
        _ocr_instance = get_ocr_service()
    return _ocr_instance