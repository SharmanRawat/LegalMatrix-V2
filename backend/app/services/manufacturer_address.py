"""Deterministic manufacturer-address extraction — a pure side channel.

Reads **only** the raw OCR token stream (plus the already-merged
``manufacturer`` value as a fallback) to produce a separate
``manufacturer_address`` declaration. It never modifies any of the ten
existing extraction fields, the merge, or the compliance pipeline, so the
frozen golden-statutory audit stays byte-identical.

Address signal (Legal Metrology context, Rule 6(1)(a) + Rule 10 Explanation):
an address block must carry a PIN code and/or a street / city / state marker.
Licence-number lines (``Lic.No.100120...``) are explicitly excluded — their
digit runs masquerade as PINs.

Design: score every raw OCR token for address salience, group the selected
tokens into visual runs (y-proximity) and return the highest-total-score run
that carries a PIN. Token-level scoring avoids gluing unrelated columns that
share a visual row on dense nutrition-grid labels.
"""
import re
from typing import Dict, List, Optional

_PIN = re.compile(r"(?<![\dA-Za-z])[1-9]\d{5}(?![\dA-Za-z])")
_SPACED_PIN = re.compile(r"(?<![\dA-Za-z])([1-9]\d{2})\s+(\d{3})(?![\dA-Za-z])")
_LICENCE = re.compile(r"lic\.?|\bno\.\d{4,}\b", re.IGNORECASE)

_STREET = re.compile(
    r"\b(road|rd|street|st|marg|nagar|layout|chowk|circle|basti|building|complex|"
    r"sector|phase|block|tower|bhawan|bhavan|compound|estate|colony|market|cross|"
    r"main|highway)\b",
    re.IGNORECASE,
)
_CITY = re.compile(
    r"\b(mumbai|bombay|delhi|kolkata|calcutta|chennai|madras|bengaluru|bangalore|"
    r"hyderabad|pune|ahmedabad|mysore|noida|gurgaon|gurugram|faridabad|ghaziabad|"
    r"jaipur|lucknow|kanpur|indore|bhopal|nagpur|kochi|thrissur|kerala|karnataka|"
    r"maharashtra|gujarat|rajasthan|punjab|haryana|west bengal|andhra pradesh|"
    r"telangana|madhya pradesh|bihar|odisha|goa|chandigarh|india|andheri|powai|"
    r"chakala|bandra|thane|navi mumbai|hosur)\b",
    re.IGNORECASE,
)
_OFFICE = re.compile(
    r"\b(regd|registered|corporate|cnt|centre|center|works|factory|plant|office|"
    r"ground floor|g/f|p\.?o\.?|box|bag|dist|tehsil|taluk|pin)\b",
    re.IGNORECASE,
)

_JOIN_WS = re.compile(r"\s+")
_TRIM = re.compile(r"^[\s,;|·•\-–—.]+|[\s,;|·•\-–—.]+$")
_MAX_LEN = 420


def _has_pin(text: str) -> bool:
    return bool(_PIN.search(text) or _SPACED_PIN.search(text))


def _pin_literal(text: str) -> bool:
    return bool(re.search(r"\bPIN\b", text, re.IGNORECASE))


def _token_score(text: str) -> int:
    """Address salience of a single OCR token."""
    score = 0
    if _has_pin(text) and not _LICENCE.search(text):
        score += 6
    score += 4 * min(2, len(_CITY.findall(text)))
    score += 3 * min(2, len(_STREET.findall(text)))
    score += 2 * min(2, len(_OFFICE.findall(text)))
    return score


def _clean(text: str) -> str:
    text = _JOIN_WS.sub(" ", text)
    text = _TRIM.sub("", text)
    if len(text) > _MAX_LEN:
        return text[: _MAX_LEN - 1] + "…"
    return text


def _best_address_run(tokens: List[Dict]) -> Optional[str]:
    """Best PIN-bearing run of address-marker tokens (one visual band)."""
    if not tokens:
        return None

    heights = []
    geo = []
    for t in tokens:
        b = t.get("box")
        text = str(t.get("text", ""))
        if b and len(b) == 4:
            y0, y2 = float(b[1]), float(b[3])
            heights.append(max(1.0, y2 - y0))
        else:
            y0 = y2 = len(geo) * 30.0  # box-less fallback: sequence order
        geo.append({
            "yc": (y0 + y2) / 2,
            "text": text,
            "score": _token_score(text),
        })
    median_h = sorted(heights)[len(heights) // 2] if heights else 30.0

    sel = [(i, g) for i, g in enumerate(geo) if g["score"] >= 4 and (
        _has_pin(g["text"]) or _pin_literal(g["text"])
        or _CITY.search(g["text"]) or _STREET.search(g["text"])
    )]
    if not sel:
        return None

    # Runs = maximal groups of selected tokens whose y-centres stay within
    # ~1.6 token-heights of the previous selected token (visual adjacency).
    tol = 1.6 * median_h
    runs: List[List[Dict]] = []
    for _i, g in sel:
        if runs and abs(g["yc"] - runs[-1][-1]["yc"]) <= tol:
            runs[-1].append(g)
        else:
            runs.append([g])

    best = None
    for run in runs:
        texts = [r["text"] for r in run]
        if not any(_has_pin(t) or _pin_literal(t) for t in texts):
            continue
        # Reject runs whose only address signal is a bare PIN — date
        # fragments and margins also look like 6-digit numbers.
        if not any(
            _pin_literal(t) or _CITY.search(t) or _STREET.search(t) or _OFFICE.search(t)
            for t in texts
        ):
            continue
        total = sum(r["score"] for r in run)
        if best is None or total > best[0]:
            best = (total, texts)
    if best is None:
        return None
    return _clean(" ".join(best[1]))


def _split_manufacturer_fallback(manufacturer: str) -> str:
    """If the merged manufacturer value already embeds an address ('Regd.
    Office: …'), return its tail when it carries address signals."""
    for m in re.finditer(
        r"\b(regd\.?|registered|corporate|office|works|factory|plant|p\.?o\.?|"
        r"box|bag)\b",
        manufacturer,
        re.IGNORECASE,
    ):
        tail = manufacturer[m.end():].strip(" ,;:|\t")
        if tail and (_has_pin(tail) or _CITY.search(tail) or _STREET.search(tail)):
            return _clean(tail)
    if _has_pin(manufacturer) and (_CITY.search(manufacturer) or _STREET.search(manufacturer)):
        return _clean(manufacturer)
    return ""


def extract_manufacturer_address(
    individual_results: List[Dict], manufacturer_value: str = ""
) -> str:
    """Return the label's manufacturer-address text, or '' when none is found.

    ``individual_results``: the per-image extraction dicts (raw ``tokens``
    read only). ``manufacturer_value``: the merged manufacturer declaration,
    used as a fallback when the raw token pass finds nothing.
    """
    best: Optional[str] = None
    for result in individual_results:
        run = _best_address_run(result.get("tokens") or [])
        if run and (best is None or len(run) > len(best)):
            best = run
    if best:
        return best
    return _split_manufacturer_fallback(manufacturer_value or "")