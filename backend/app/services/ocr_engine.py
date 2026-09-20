"""Fast CPU OCR engine — RapidOCR (PP-OCR models, onnxruntime) + a lightweight
LLM field classifier.

Pipeline per image:
  enhance -> OCR (word boxes + confidence) -> classify fields (LLM w/ regex
  fallback) -> canonical result + token boxes + normalized regions.

Implements the same interface as the legacy vision service
(extract_structured / verify_currency_symbol / prompt_fingerprint) so the
inspection pipeline and its tests keep working unchanged. When no CPU OCR
engine is importable it transparently delegates to the legacy VLM service.
"""
import hashlib
import logging
import re
import time
from typing import Dict, List

import cv2
import numpy as np

from app.config import (
    FIELD_CLASSIFIER_ENABLED,
    OCR_ENHANCE_ENABLED,
    OCR_ENGINE,
    OCR_MULTI_PASS_ENABLED,
    OCR_MULTI_PASS_ON_FAIL,
)
from app.services import preprocessing
from app.services.field_classifier import (
    _ADDRESS_LINE_RE,
    _leading_number,
    _looks_like_address,
    _strip_company,
    edible_supported,
    LLMFieldClassifier,
    RegexFieldClassifier,
)

logger = logging.getLogger(__name__)

EXPECTED_KEYS = [
    "mrp", "usp", "net_quantity", "product_name",
    "manufacturer", "manufacturing_date", "expiry_date",
    "consumer_care", "dimensions", "edible",
]

FIELD_LABELS = {
    "mrp": ["mrp", "max retail", "maximum retail", "price"],
    "net_quantity": ["net", "quantity", "wt", "weight", "content", "qty"],
    "consumer_care": ["care", "consumer", "toll", "1800", "@", "email"],
}

# ── OCR text post-processing ────────────────────────────────────────────
# RapidOCR often misreads the rupee symbol as CJK '于', joins words without
# spaces ('ForConsumerComplaints'), and glues two dates together. These fixes
# make both the LLM classifier and the regex fallback see the label the way a
# human would.
# RapidOCR misreads the rupee symbol as many different CJK glyphs; the most
# common are 于, ¥, 天, 舌, 曰.  All are normalized to ₹ before matching.
_CURRENCY_GLYPH_FIX = {
    "于": "₹", "¥": "₹", "天": "₹", "舌": "₹", "曰": "₹", "元": "₹",
}
_CAMEL_BOUNDS = re.compile(r"([a-z])([A-Z])")
_ALNUM_BOUNDS = re.compile(r"([a-z])(\d)")

_MONTH_FN = r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)"
_MONTH_YEAR = re.compile(
    r"(?<![A-Za-z])" + _MONTH_FN + r"[\s/.\-]*(\d{1,4})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _expand_year(digits: str) -> str:
    if len(digits) == 2:
        return "20" + digits
    if len(digits) == 3:
        return "20" + digits[1:]
    return digits


def _normalize_month_year(text: str) -> str:
    """Turn 'SEP125-MAR/27' into 'SEP/2025-MAR/2027' so date extraction works
    even when RapidOCR mangles a 4-digit year ('2025' -> '125', '27')."""
    return _MONTH_YEAR.sub(
        lambda m: f"{m.group(1).upper()}/{_expand_year(m.group(2))}", text
    )


def _fix_glued_dates(text: str) -> str:
    """Split two dates that RapidOCR ran together without a separator.

    Common on Indian food labels where 'MFD 07/04/26 EXP 06/04/27' is captured
    as one token. Handles the space-dropped case and the fully-glued case.
    """
    m = re.match(r"^(\d{1,2}/\d{1,2}/\d{2})(\d{1,2}/\d{1,2}/\d{2})$", text)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = re.match(r"^(\d{1,2}/\d{1,2}/\d{2})(\d{2})(\d{2})/(\d{2})$", text)
    if m:
        return f"{m.group(1)} {m.group(2)}/{m.group(3)}/{m.group(4)}"
    return text


# OCR confuses certain glyphs inside month abbreviations (H<->A, 1<->I);
# a mangled month ('JHN 2028') kills date extraction downstream, so restore
# the canonical month before anything else looks at the text.
_MONTH_GLYPH_FIX = [
    (re.compile(r"\bJHN\b", re.IGNORECASE), "JAN"),
    (re.compile(r"\bJU[1I]\b", re.IGNORECASE), "JUL"),
    (re.compile(r"\bFE8\b", re.IGNORECASE), "FEB"),
    (re.compile(r"\bAU6\b", re.IGNORECASE), "AUG"),
]


def _fix_month_glyphs(text: str) -> str:
    for pat, repl in _MONTH_GLYPH_FIX:
        text = pat.sub(repl, text)
    return text


def _postprocess_text(text: str) -> str:
    t = "".join(_CURRENCY_GLYPH_FIX.get(ch, ch) for ch in text)
    # Full-width CJK colon from the OCR model is a normal label colon.
    t = t.replace("：", ":").replace("；", ";")
    t = _fix_month_glyphs(t)
    t = _normalize_month_year(t)
    t = _CAMEL_BOUNDS.sub(r"\1 \2", t)
    t = _ALNUM_BOUNDS.sub(r"\1 \2", t)
    t = _fix_glued_dates(t)
    if "://" not in t and "www." not in t:
        t = re.sub(r"(?<=[A-Za-z0-9])/(?=[A-Za-z0-9])", " / ", t)
    return " ".join(t.split())


# Structured numeric fields the regex parser resolves reliably (MRP, net
# quantity, dates…); the LLM is better at names/edible/usp but sometimes
# leaves these blank when OCR text is fragmented.
_REGEX_PREFERRED = {"mrp", "usp", "net_quantity", "dimensions", "consumer_care", "product_name"}


def _norm(s: str) -> str:
    """Lowercase, unify the rupee glyph, and strip all non-alphanumeric chars.
    A decimal point is kept so '2.10g' and '210g' stay distinct.
    Used to compare a classifier value against the raw OCR lines."""
    s = (s or "").lower().replace("\u20b9", "rs")
    return re.sub(r"[^a-z0-9.]", "", s)


def _value_supported(value: str, lines: List[Dict]) -> bool:
    v = _norm(value)
    if not v:
        return True
    norm_lines = [_norm(ln.get("text", "")) for ln in lines]
    if any(v in ln for ln in norm_lines):
        return True
    raw_lines = [
        (ln.get("text", "") or "").lower().replace("\u20b9", "rs") for ln in lines
    ]
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower().replace("\u20b9", "rs"))
    meaningful = [t for t in tokens if len(t) >= 3 or t.isdigit()]
    for t in meaningful:
        if t.isdigit():
            # A number must appear standalone in some line, never inside a longer
            # digit run or a decimal like '2.10g' standing in for '210g'.
            if not any(
                re.search(r"(?<!\d)" + re.escape(t) + r"(?!\d)", ln)
                for ln in raw_lines
            ):
                return False
        elif not any(t in ln for ln in norm_lines):
            return False
    return True


_NO_VALIDATE = {"edible"}  # semantic verdicts, not printed label text


# OCR glues address words together ('Parkadarthaakaroad'), defeating
# word-boundary matching — so LLM product names are screened for address
# FRAGMENTS (imported from field_classifier). Two distinct hits are required
# to keep real names like 'Park Avenue' alive.
_DATE_MONTH_NAME_RE = re.compile(
    r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b", re.I
)
_DATE_MONTH_NUM_RE = re.compile(r"\b(\d{1,2})\s*[/.-]\s*(?:19|20)\d{2}\b")


def _date_has_month(value: str) -> bool:
    """True when a date string carries a month (name, or m/yyyy pair with a
    plausible month 1-12) — i.e. it is more complete than a bare year."""
    if _DATE_MONTH_NAME_RE.search(value):
        return True
    m = _DATE_MONTH_NUM_RE.search(value)
    return bool(m and 1 <= int(m.group(1)) <= 12)


def _merge_classifiers(llm: Dict, regex: Dict, lines: List[Dict]) -> Dict:
    """Merge LLM + regex extraction, preferring the regex for structured
    numeric fields and filling any LLM-empty field from the regex result."""
    llm_fields = dict(llm.get("fields", {}))
    regex_fields = regex.get("fields", {})
    merged_map = dict(llm.get("line_map", {}))
    regex_values = {str(v).strip() for v in regex_fields.values() if str(v).strip()}
    source = {key: "llm" for key in EXPECTED_KEYS}

    for key in EXPECTED_KEYS:
        llm_val = str(llm_fields.get(key, "") or "").strip()
        regex_val = str(regex_fields.get(key, "") or "").strip()
        if not llm_val and regex_val:
            llm_fields[key] = regex_val
            merged_map[key] = regex.get("line_map", {}).get(key, [])
            source[key] = "regex"
        elif llm_val and key in _REGEX_PREFERRED and regex_val:
            llm_fields[key] = regex_val
            merged_map[key] = regex.get("line_map", {}).get(key, [])
            source[key] = "regex"

    for key in EXPECTED_KEYS:
        if key in _REGEX_PREFERRED:
            continue
        val = str(llm_fields.get(key, "") or "").strip()
        if val and val in regex_values and str(regex_fields.get(key, "") or "").strip() != val:
            llm_fields[key] = ""
            merged_map.pop(key, None)

    for key in EXPECTED_KEYS:
        if source[key] == "regex" or key in _NO_VALIDATE:
            continue
        val = str(llm_fields.get(key, "") or "").strip()
        if val and not _value_supported(val, lines):
            llm_fields[key] = ""
            merged_map.pop(key, None)

    # Hard semantic guards for fields the LLM tends to over-read.  These run
    # even when the value is OCR-supported, because labels carry plenty of
    # numbers/lines that "look like" a price or a care contact.
    for key in ("mrp", "usp", "dimensions", "consumer_care", "product_name"):
        val = str(llm_fields.get(key, "") or "").strip()
        if not val:
            continue
        low = val.lower()
        if key == "mrp" and not re.search(r"[₹rs]|inr|\bmrp\b|\bretail\b", low):
            # A price with no currency symbol and no "MRP" keyword is not an
            # MRP declaration (OCR often mangles sticker numerals into e.g.
            # '841018'); never let that become the statutory MRP.
            llm_fields[key] = ""
            merged_map.pop(key, None)
        elif key == "usp" and not re.search(
            r"\bper\b|\d\s*/|\d\s*(g|gm|kg|ml|l|litre|cm|m|pcs|pieces|nos?)\b",
            low,
        ):
            # Unit sale price must state a per-unit rate; otherwise it is just
            # another price (usually the MRP) being repeated.
            llm_fields[key] = ""
            merged_map.pop(key, None)
        elif key == "dimensions" and re.search(
            r"\b(hdpe|ldpe|pp|pet|pbt|abs|polymer|cap|pourer|recycl|material)\b",
            low,
        ):
            # Material/lid/recycling lines are never physical dimensions.
            llm_fields[key] = ""
            merged_map.pop(key, None)
        elif key == "consumer_care" and not (
            re.search(r"@|toll\s*free|tollfree|1800", low)
            or len(re.sub(r"\D", "", low)) in (10, 11, 12)
        ):
            # A care line must contain a contact channel; disclaimers like
            # "All pictures shown are for illustration" are not consumer care.
            # Phones may carry separators ('91-22-25259915' -> 12 digits — the
            # old raw '1?\d{10}' blanked every hyphenated STD-code phone, e.g.
            # image27's care row); FSSAI (14-17) / barcode (13) runs stay out.
            llm_fields[key] = ""
            merged_map.pop(key, None)
        elif key == "product_name" and _ADDRESS_LINE_RE.search(val):
            # The LLM glues manufacturer-address lines into the name
            # ('Herbal Park ... Laksar Road ...'); an address is never the
            # commodity name.
            llm_fields[key] = ""
            merged_map.pop(key, None)
        elif key == "product_name" and _looks_like_address(val):
            llm_fields[key] = ""
            merged_map.pop(key, None)

    # Dimensions are only meaningful for non-edible commodities (rule 6(1)(g) —
    # see inspection_service._dimensions_relevant).  Drop any value the LLM
    # invented for edible products.
    edible = str(llm_fields.get("edible", "") or "").strip().lower()
    if edible in ("yes", "true", "1", "y", "edible"):
        if llm_fields.get("dimensions"):
            llm_fields["dimensions"] = ""
            merged_map.pop("dimensions", None)

    # Zero prices/quantities are never valid declarations: an LLM '0 g' read
    # off a nutrition row must not survive just because the regex found
    # nothing (the classifier already screens its own regex values).
    for key in ("mrp", "usp", "net_quantity"):
        if source.get(key) == "regex":
            continue
        v = str(llm_fields.get(key, "") or "").strip()
        if v and _leading_number(v) == 0.0:
            llm_fields[key] = ""
            merged_map.pop(key, None)

    # An LLM edibility verdict needs label evidence: 'yes' requires a food
    # word on the label, 'no' an explicit non-edible marker. An unevidenced
    # guess is cleared so it cannot poison single-photo inspections.
    if source.get("edible") != "regex":
        ev = str(llm_fields.get("edible", "") or "").strip()
        if ev and not edible_supported(ev, lines):
            llm_fields["edible"] = ""
            merged_map.pop("edible", None)

    # Canonicalize punctuation/spacing so the same value compares equal
    # downstream ('1kg' vs '1 kg', '06 / 02 / 27' vs '06/02/27').
    for key in ("net_quantity",):
        v = str(llm_fields.get(key, "") or "").strip()
        if v:
            llm_fields[key] = re.sub(
                r"(\d+(?:\.\d+)?)\s*(g|kg|gm|mg|ml|cl|l)\b(?![0-9/])",
                r"\1 \2", v, flags=re.IGNORECASE,
            )
    # The LLM copies licence prefixes into the company name
    # ('fssai Patanjali Foods ...'); the regex path already strips these.
    if llm_fields.get("manufacturer"):
        llm_fields["manufacturer"] = _strip_company(llm_fields["manufacturer"])
    for key in ("manufacturing_date", "expiry_date"):
        v = str(llm_fields.get(key, "") or "").strip()
        if v:
            llm_fields[key] = re.sub(r"\s*([/-])\s*", r"\1", v)

    return {"fields": llm_fields, "line_map": merged_map, "engine": "llm+regex"}


class SmartOCRService:
    def __init__(self):
        self.engine_name = "none"
        self._engine = self._load_engine()
        self.legacy = None
        if self._engine is None:
            try:
                from app.services.ocr_service import get_ocr_service
                self.legacy = get_ocr_service()
                self.engine_name = self.legacy.model
            except Exception as e:
                logger.error("no OCR engine available: %s", e)
        self.classifier = None
        self.regex_classifier = RegexFieldClassifier()
        self._prompt_hash = ""

    def _load_engine(self):
        mode = OCR_ENGINE
        if mode in ("auto", "rapidocr"):
            try:
                from rapidocr_onnxruntime import RapidOCR  # type: ignore
                engine = RapidOCR()
                self.engine_name = "rapidocr"
                logger.info("RapidOCR engine ready")
                return engine
            except Exception as e:
                logger.warning("RapidOCR unavailable (%s); trying paddle", e)
        if mode in ("auto", "paddleocr"):
            try:
                from paddleocr import PaddleOCR  # type: ignore
                engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
                self.engine_name = "paddleocr"
                return engine
            except Exception as e:
                logger.warning("PaddleOCR unavailable: %s", e)
        return None

    @property
    def engine(self):
        return self._engine

    def ocr_engine(self) -> str:
        return self.engine_name

    def prompt_fingerprint(self) -> str:
        if not self._prompt_hash:
            prompt = " | ".join(
                [LLMFieldClassifier().prompt_fingerprint(),
                 (preprocessing.__doc__ or "")[:200], OCR_ENGINE]
            )
            self._prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return self._prompt_hash

    # ── main entry point (same contract as the vision service) ────────────
    def extract_structured(self, image_path: str) -> Dict:
        started = time.time()
        if self._engine is None and self.legacy is not None:
            result = self.legacy.extract_structured(image_path)
            result["ocr_meta"] = {"engine": self.legacy.model, "delegate": True}
            return result

        tokens = self._ocr_tokens(image_path)
        if not tokens:
            return {k: "" for k in EXPECTED_KEYS} | {
                "ocr_meta": {"engine": self.engine_name, "error": "no_text_found"},
                "tokens": [],
                "regions": {},
            }

        lines = [{"text": t["text"], "box": t["box"]} for t in tokens]
        use_llm = FIELD_CLASSIFIER_ENABLED
        classification = None
        if use_llm:
            try:
                if self.classifier is None:
                    self.classifier = LLMFieldClassifier()
                classification = self.classifier.classify(lines)
            except Exception as e:
                logger.warning("LLM classifier failed (%s); using regex", e)
        if classification is None:
            classification = self.regex_classifier.classify(lines)
        elif classification.get("engine") == "llm" and not any(
            (classification.get("fields", {}).get(k) or "") for k in EXPECTED_KEYS
        ):
            classification = self.regex_classifier.classify(lines)
        else:
            classification = _merge_classifiers(
                classification, self.regex_classifier.classify(lines), lines
            )

        fields = classification["fields"]
        line_map = classification.get("line_map", {})
        escalated = False
        if OCR_MULTI_PASS_ENABLED and OCR_MULTI_PASS_ON_FAIL and tokens:
            def _effectively_empty(k):
                v = str(fields.get(k, "") or "").strip()
                if not v:
                    return True
                if k in ("mrp", "manufacturing_date", "expiry_date"):
                    return not any(ch.isdigit() for ch in v)
                return False
            critical_empty = [k for k in ("mrp", "manufacturing_date", "expiry_date")
                              if _effectively_empty(k)]
            if critical_empty and self.engine_name in ("rapidocr", "paddleocr"):
                extra = self._ocr_variant_tokens(image_path)
                added_digits = any(
                    any(ch.isdigit() for ch in str(c.get("text", "") or ""))
                    for c in extra
                )
                if extra and added_digits:
                    fused = self._fuse_tokens(tokens, extra)
                    if len(fused) > len(tokens):
                        lines2 = [{"text": t["text"], "box": t["box"]} for t in fused]
                        classification2 = None
                        try:
                            classification2 = self.classifier.classify(lines2) if use_llm else None
                        except Exception as e:
                            logger.warning("LLM reclassify failed (%s); regex", e)
                        if classification2 is None:
                            classification2 = self.regex_classifier.classify(lines2)
                        else:
                            classification2 = _merge_classifiers(
                                classification2,
                                self.regex_classifier.classify(lines2), lines2,
                            )
                        fields2 = classification2["fields"]
                        for k in EXPECTED_KEYS:
                            v1 = str(fields.get(k, "") or "").strip()
                            v2 = str(fields2.get(k, "") or "").strip()
                            if not v1 and v2:
                                fields[k] = fields2[k]
                                line_map[k] = classification2.get("line_map", {}).get(k, [])
                            elif (
                                k in ("manufacturing_date", "expiry_date")
                                and v1 and v2
                                and re.fullmatch(r"(?:19|20)\d{2}", v1)
                                and _date_has_month(v2)
                            ):
                                # Primary pass read only the year of a date line
                                # ('2020'); the escalated pass read the full
                                # month+year ('8 / 2020'). Upgrade the degenerate
                                # read instead of keeping it just because it isn't
                                # empty (p2 mfg '2020' vs golden '08/2020').
                                fields[k] = fields2[k]
                                line_map[k] = classification2.get("line_map", {}).get(k, [])
                            elif (
                                k in ("manufacturing_date", "expiry_date")
                                and re.fullmatch(r"(?:19|20)\d{2}", v1)
                            ):
                                # The escalated SLM read can be flakier/emptier than
                                # the first pass, so also upgrade deterministically
                                # from the fused token stream: the fuse replaced the
                                # bare-year line with a fuller month+year read at the
                                # same index (p2: '2020' -> '8 / 2020'), and the
                                # first-pass line_map still points at that line.
                                lid = (line_map.get(k) or classification2.get("line_map", {}).get(k, []) or [])
                                if lid and lid[0] < len(lines2):
                                    fused_text = str(lines2[lid[0]].get("text", "") or "").strip()
                                    if _date_has_month(fused_text):
                                        fields[k] = re.sub(r"\s*([/-])\s*", r"\1", fused_text)
                                        line_map[k] = [lid[0]]
                        tokens = fused
                        escalated = True

        result = {k: (fields.get(k, "") or "") for k in EXPECTED_KEYS}
        result["regions"] = self._regions_for_norm(tokens, line_map)
        result["tokens"] = tokens
        result["ocr_meta"] = {
            "engine": self.engine_name,
            "classifier": classification.get("engine", "regex"),
            "lines": len(tokens),
            "elapsed_s": round(time.time() - started, 2),
            "escalated": escalated,
            "confidence": round(sum(t["conf"] for t in tokens) / max(1, len(tokens)), 3),
        }
        self._attach_field_tokens(result, tokens, line_map)
        return result

    # ── OCR + preprocessing ────────────────────────────────────────────────
    @staticmethod
    def _box_iou(a, b) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / (area_a + area_b - inter)

    @staticmethod
    def _token_quality(tok: Dict) -> float:
        """Semantic score added on top of OCR confidence when fusing competing
        reads of the same region. Prefer tokens that look like the fields that
        actually matter: dates, prices with decimals, years."""
        text = str(tok.get("text", "") or "")
        score = 0.0
        if re.search(
            r"\d{1,2}[\s./-](?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
            r"[\s./-]\d{2,4}", text, re.IGNORECASE,
        ):
            score += 0.35
        # A numeric month+year ('8 / 2020', '10.2024') is the full date value
        # and must beat a bare high-conf year from the primary pass, or the
        # escalation keeps the degenerate read (p2 mfg '2020' vs '08/2020').
        if re.search(r"(?<!\d)\d{1,2}\s*[/.-]\s*(?:19|20)\d{2}(?!\d)", text):
            score += 0.35
        if re.search(r"\b\d{1,3}[.,]\d{2}\b", text):
            score += 0.25
        if re.search(r"\b20\d{2}\b", text):
            score += 0.15
        if any(ch.isdigit() for ch in text):
            score += 0.05
        return score

    def _fuse_tokens(self, tokens: List[Dict], extra: List[Dict]) -> List[Dict]:
        """Fuse two token streams: keep the best read of a box. 'Best' is
        OCR confidence plus a semantic bonus (valid date / decimal price),
        so a cleaner date read can beat a higher-confidence garbled one.
        Distinct non-overlapping tokens are all kept — ₹ glyph and price
        digits are separate detection boxes."""
        def _score(t):
            return t["conf"] + self._token_quality(t)

        def _improves(cand, keep):
            return _score(cand) > _score(keep) + 0.05 or (
                _score(cand) >= _score(keep) and len(cand["text"]) > len(keep["text"])
            )

        merged = list(tokens)
        for cand in sorted(extra, key=_score, reverse=True):
            best_i, best_iou = -1, 0.0
            for i, k in enumerate(merged):
                iou = self._box_iou(cand["box"], k["box"])
                if iou > best_iou:
                    best_i, best_iou = i, iou
            if best_i < 0:
                merged.append(cand)
                continue
            if best_iou >= 0.55 and _improves(cand, merged[best_i]):
                merged[best_i] = cand
            elif best_iou < 0.2 and abs(_score(cand) - _score(merged[best_i])) > 0.3:
                merged.insert(best_i + 1, cand)
        return merged

    def _ocr_variant_tokens(self, image_path: str) -> List[Dict]:
        """Extra OCR passes over preprocessing variants of the ORIGINAL photo.
        Boxes are scaled back to original-pixel coordinates and only
        confident reads are returned."""
        orig = cv2.imread(image_path)
        if orig is None:
            return []
        gray = cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        lab = cv2.cvtColor(orig, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
        variants = [
            ("otsu", cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR), 1.0, 1.0),
            ("invert", cv2.cvtColor(255 - gray, cv2.COLOR_GRAY2BGR), 1.0, 1.0),
            ("clahe4", cv2.merge((clahe.apply(l_chan), a_chan, b_chan)), 1.0, 1.0),
        ]
        h, w = gray.shape[:2]
        up = cv2.resize(orig, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        variants.append(("up2", up, 0.5, 0.5))
        out = []
        for name, arr, sx, sy in variants:
            try:
                raw_results, _elapse = self._engine(arr)
            except Exception as e:
                logger.warning("multi-pass [%s] OCR failed: %s", name, e)
                continue
            for line in raw_results or []:
                try:
                    if len(line) < 3:
                        continue
                    pts = line[0]
                    text = _postprocess_text(str(line[1] or ""))
                    conf = float(line[2])
                except (TypeError, ValueError):
                    continue
                if not text or conf < 0.45:
                    continue
                try:
                    xs = [float(p[0]) for p in pts]
                    ys = [float(p[1]) for p in pts]
                except (TypeError, IndexError, ValueError):
                    continue
                x1, x2 = min(xs) * sx, max(xs) * sx
                y1, y2 = min(ys) * sy, max(ys) * sy
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                out.append({
                    "text": text,
                    "box": [int(x1), int(y1), int(x2), int(y2)],
                    "conf": conf,
                    "variant": name,
                })
        return out

    def _ocr_threadsafe(self, image_path):  # convenience alias
        return self._ocr_tokens(image_path)

    def _ocr_tokens(self, image_path: str) -> List[Dict]:
        target = image_path
        applied = []
        diagnostics = {}
        if OCR_ENHANCE_ENABLED:
            try:
                target, applied, diagnostics = preprocessing.enhance_image(image_path)
            except Exception as e:
                logger.warning("preprocessing failed: %s", e)

        orig = cv2.imread(image_path)
        if orig is None:
            try:
                with __import__("PIL").Image.open(image_path) as _pil:
                    orig = cv2.cvtColor(np.array(_pil), cv2.COLOR_RGB2BGR)
            except Exception:
                return []
        o_h, o_w = orig.shape[:2]

        enh = cv2.imread(target)
        e_h, e_w = (enh.shape[0], enh.shape[1]) if enh is not None else (o_h, o_w)
        scale_x = o_w / max(1, e_w)
        scale_y = o_h / max(1, e_h)

        def _extract(target_img, sx, sy):
            try:
                raw_results, _elapse = self._engine(target_img)
            except Exception as e:
                logger.error("OCR failed: %s", e)
                return []
            out = []
            for line in raw_results or []:
                try:
                    if len(line) < 3:
                        continue
                    pts = line[0]
                    text = _postprocess_text(str(line[1] or ""))
                    conf = float(line[2])
                except (TypeError, ValueError):
                    continue
                if not text or conf < 0.4:
                    continue
                try:
                    xs = [float(p[0]) for p in pts]
                    ys = [float(p[1]) for p in pts]
                except (TypeError, IndexError, ValueError):
                    continue
                x1, x2 = min(xs) * sx, max(xs) * sx
                y1, y2 = min(ys) * sy, max(ys) * sy
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                out.append({
                    "text": text,
                    "box": [int(x1), int(y1), int(x2), int(y2)],
                    "conf": conf,
                })
            return out

        tokens = _extract(target, scale_x, scale_y)
        if len(tokens) < 5:
            best = tokens
            for angle in [90, 180, 270]:
                if angle == 90:
                    rotated = cv2.rotate(orig, cv2.ROTATE_90_CLOCKWISE)
                elif angle == 180:
                    rotated = cv2.rotate(orig, cv2.ROTATE_180)
                else:
                    rotated = cv2.rotate(orig, cv2.ROTATE_90_COUNTERCLOCKWISE)
                r_h, r_w = rotated.shape[:2]
                rot_path = "/tmp/opencode/_rot_retry.jpg"
                cv2.imwrite(rot_path, rotated, [cv2.IMWRITE_JPEG_QUALITY, 95])
                try:
                    r_target, _, _ = preprocessing.enhance_image(rot_path)
                except Exception:
                    r_target = rot_path
                r_enh = cv2.imread(r_target)
                r_eh, r_ew = (r_enh.shape[0], r_enh.shape[1]) if r_enh is not None else (r_h, r_w)
                r_sx = r_w / max(1, r_ew)
                r_sy = r_h / max(1, r_eh)
                rot_tokens = _extract(r_target, r_sx, r_sy)
                if len(rot_tokens) > len(best):
                    best = rot_tokens
            tokens = best
        return tokens

    def _regions_for_norm(self, tokens: List[Dict], line_map: Dict) -> Dict:
        """Normalized (0-1000) boxes for mrp / net_quantity, for the legacy
        font-measurement path."""
        if not tokens:
            return {}
        max_x = max(t["box"][2] for t in tokens)
        max_y = max(t["box"][3] for t in tokens)
        if max_x <= 0 or max_y <= 0:
            return {}
        regions = {}
        for field, id_list in line_map.items():
            if field not in ("mrp", "net_quantity"):
                continue
            boxes = [tokens[i]["box"] for i in id_list if 0 <= i < len(tokens)]
            if not boxes:
                continue
            x1 = min(b[0] for b in boxes)
            y1 = min(b[1] for b in boxes)
            x2 = max(b[2] for b in boxes)
            y2 = max(b[3] for b in boxes)
            regions[field] = [
                round(x1 * 1000 / max_x, 1),
                round(y1 * 1000 / max_y, 1),
                round(x2 * 1000 / max_x, 1),
                round(y2 * 1000 / max_y, 1),
            ]
        return regions

    def _attach_field_tokens(self, result: Dict, tokens: List[Dict], line_map: Dict) -> None:
        field_map = {}
        for field, id_list in line_map.items():
            if field in EXPECTED_KEYS:
                field_map[field] = [
                    tokens[i] for i in id_list if 0 <= i < len(tokens)
                ]
        result["field_map"] = field_map

    # ── currency symbol verification ─────────────────────────────────────
    def verify_currency_symbol(self, image_path: str, value: str):
        """If OCR clearly read a ₹/Rs. glyph beside the price value, the print
        is confirmed even if the classifier dropped the symbol."""
        tokens = self._ocr_tokens(image_path)
        if not tokens:
            if self.legacy is not None:
                return self.legacy.verify_currency_symbol(image_path, value)
            return False
        value_norm = str(value or "").lower()
        value_digits = [c for c in value_norm if c.isdigit()]
        for token in tokens:
            text = str(token.get("text", "") or "").lower()
            token_digits = [c for c in text if c.isdigit()]
            if not token_digits:
                continue
            if value_digits and not set(value_digits).intersection(token_digits):
                continue
            if "₹" in text or "rs" in text or "inr" in text:
                return True
        return False

    def get_field_tokens(self, result: Dict) -> Dict:
        return result.get("field_map", {})


_ocr_instance = None


def get_ocr_service():
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = SmartOCRService()
    return _ocr_instance