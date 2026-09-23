#!/usr/bin/env python3
"""Pipeline-vs-7B-VLM oracle audit.

Runs the REAL web-app pipeline per product group
    preprocessing -> RapidOCR -> qwen2.5:3b SLM classifier (+regex merge)
and compares every extracted field against the qwen2.5vl:7b VLM read of the
same photos (the oracle). Prints per-product diffs + per-field agreement and
writes machine-readable reports (JSON + CSV) to --out-dir.

Both the OCR token pass and the oracle reads are disk-cached (keyed by image
mtime so edited images re-run). Re-running after you tune the SLM prompt /
regex / preprocessor is therefore near-free: only the classifier + merge
re-execute.

Usage (from backend/):
    python scripts/pipeline_audit.py [--images-dir PATH] [--product 6]
        [--oracle qwen2.5vl:7b] [--classifier qwen2.5:3b]
        [--no-ocr-cache] [--out-dir /tmp/pipeline_audit]
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Set env BEFORE importing app modules (config reads these at import time).
os.environ.setdefault("OCR_ENGINE", "auto")
os.environ.setdefault("VLM_RESCUE_ENABLED", "0")          # measure the CPU+SLM path
os.environ.setdefault("OCR_ENHANCE_ENABLED", "1")
os.environ.setdefault("OCR_MULTI_PASS_ENABLED", "1")
os.environ.setdefault("OCR_MULTI_PASS_ON_FAIL", "1")

from app.services.ocr_engine import SmartOCRService  # noqa: E402

FIELDS = [
    "mrp", "usp", "net_quantity", "product_name", "manufacturer",
    "manufacturing_date", "expiry_date", "consumer_care", "dimensions", "edible",
]

OCR_CACHE_PATH = Path("/tmp/pipeline_audit_ocr_cache.json")
VLM_CACHE_PATH = Path("/tmp/pipeline_audit_oracle_cache.json")
# Per-photo pipeline (classifier) results, keyed by image path+mtime+size and
# classifier model. The audit re-runs the merge/routing on identical OCR+SLM
# inputs every time, so routing changes can be measured deterministically.
# Invalidate with --no-extract-cache when tuning the SLM prompt/preprocessor.
PIPE_CACHE_PATH = Path("/tmp/pipeline_audit_pipe_cache.json")


# ── disk caches (loaded once, flushed on write) ─────────────────────────────
class DiskCache:
    def __init__(self, path: Path):
        self.path = path
        try:
            self._data = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            # A killed run can leave a half-written cache — start fresh
            # rather than crashing the next run.
            self._data = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        try:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False))
            # Atomic replace: a crash never leaves a half-written cache file.
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __len__(self):
        return len(self._data)


def _fstat_key(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{path}|{st.st_mtime:.3f}|{st.st_size}"
    except OSError:
        return f"{path}|?"


# ── pipeline side (cached OCR, real classification) ─────────────────────────
class CachedSmartOCR(SmartOCRService):
    """Subclasses SmartOCRService with disk-cached token passes.

    The actual classifier / merge / post-processing logic is the production
    code (SmartOCRService.extract_structured) — only the expensive raw OCR
    passes are cached, so tuning the SLM prompt or regexes re-runs just the
    cheap classification steps.
    """

    def __init__(self, ocr_cache: DiskCache, variant_cache: DiskCache,
                 extract_cache: DiskCache = None):
        super().__init__()
        self._ocr_cache = ocr_cache
        self._variant_cache = variant_cache
        self._extract_cache = extract_cache

    def extract_cached(self, image_path: str, extra: str = "") -> dict:
        """extract_structured with the classifier call itself disk-cached.

        The 3B SLM read is deterministic (temperature 0) but ~5-10s per photo;
        keying the result by path+mtime+size+model makes audit re-runs of the
        merge/routing instant while keeping per-photo extraction consistent.
        """
        key = "pipe|" + _fstat_key(image_path) + "|" + extra
        if self._extract_cache is not None:
            hit = self._extract_cache.get(key)
            if hit is not None:
                return hit
        out = self.extract_structured(image_path)
        if self._extract_cache is not None:
            self._extract_cache.set(key, out)
        return out

    def _ocr_tokens(self, image_path: str):
        key = "ocr|" + _fstat_key(image_path)
        hit = self._ocr_cache.get(key)
        if hit is not None:
            return hit if not isinstance(hit, dict) else hit.get("tokens", [])
        out = super()._ocr_tokens(image_path)
        self._ocr_cache.set(key, out)
        return out

    def _ocr_tokens_with_raw(self, image_path: str):
        key = "ocr|" + _fstat_key(image_path)
        hit = self._ocr_cache.get(key)
        if hit is not None:
            if isinstance(hit, dict) and "tokens" in hit:
                return hit["tokens"], hit.get("raw", hit["tokens"])
            # Legacy cache entry: a plain token list (no transcript data).
            return hit, hit
        out, raw = super()._ocr_tokens_with_raw(image_path)
        self._ocr_cache.set(key, {"tokens": out, "raw": raw})
        return out, raw

    def _ocr_variant_tokens(self, image_path: str):
        key = "var|" + _fstat_key(image_path)
        hit = self._variant_cache.get(key)
        if hit is not None:
            return hit
        out = super()._ocr_variant_tokens(image_path)
        self._variant_cache.set(key, out)
        return out


def _run_pipeline(svc: CachedSmartOCR, paths: list, cache_extra: str = "") -> list:
    return [svc.extract_cached(p, cache_extra) for p in paths]


# ── oracle side (7B VLM, cached) ────────────────────────────────────────────
def _oracle_read(path: str, model: str, cache: DiskCache):
    key = "vlm|" + _fstat_key(path) + "|" + model
    hit = cache.get(key)
    if hit is not None:
        return hit
    print(f"  oracle: {Path(path).name}...", end=" ", flush=True)
    t0 = time.time()
    from app.services.vlm_rescuer import VLMRescuer
    rescuer = VLMRescuer(model=model)
    bare = {f: "" for f in FIELDS}
    bare["tokens"] = []
    bare["ocr_meta"] = {"classifier": "regex"}
    out = rescuer.rescue(path, bare)
    print(f"{time.time()-t0:.1f}s")
    result = {f: (out.get(f, "") if out else "") for f in FIELDS}
    cache.set(key, result)
    return result


# ── merge (production logic) ────────────────────────────────────────────────
# Filename-embedded label types (image1_front.jpg → front; _top → top) and
# the manual override manifest backend/data/label_types.json together decide
# each photo's label type, which routes fields to their strongest source.
_EMBED_LABEL = {
    "front": "front", "back": "back", "side": "side",
    "other": "other", "top": "top", "bottom": "other",
}
LABEL_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "label_types.json"


def _load_label_manifest() -> dict:
    try:
        return json.loads(LABEL_MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _label_type_for(path: str, manifest: dict):
    """Effective label type for a photo: manifest override wins over the
    type embedded in the filename ('top' is a first-class type, routed just
    below 'back' for statutory declarations). Unknown → None."""
    name = Path(path).name
    if name in manifest:
        return manifest[name]
    m = re.match(r"(?:image|product)\d+_([A-Za-z0-9]+)\.jpg$", name, re.IGNORECASE)
    if m:
        return _EMBED_LABEL.get(m.group(1).lower())
    return None


def _merge(results: list, label_types: list = None) -> dict:
    from app.services.inspection_service import merge_extractions
    lt = label_types if label_types is not None else [None] * len(results)
    return {k: (merge_extractions([r for r in results], lt).get(k) or "") for k in FIELDS}


# ── comparison ──────────────────────────────────────────────────────────────
# Canonical legal-equivalence primitives live in
# app/services/value_normalizers.py — the single source of truth shared with
# the merge / rules / classifier code. The audit only adds the comparison
# layer on top: per-component notes and the fuzzy token fallback. The private
# aliases below keep every call site in this file unchanged.
from app.services.value_normalizers import (  # noqa: E402
    EMAIL_RE as _EMAIL_RE,
    care_key as _care_key,
    dimensions_key as _dimensions_key,
    edibility_key as _edibility_key,
    fmt_num as _g,
    name_tokens as _name_tokens,
    parse_date as _parse_date,
    parse_price as _parse_price,
    parse_quantity as _parse_quantity,
    phones as _phones,
    tokens as _tokens,
)


def _fuzzy_sets(tp: set, to: set, label: str) -> tuple:
    """Set-based compare: exact, full containment, else Jaccard >= 0.6 -> ok."""
    if not tp and not to:
        return True, f"{label} both-absent"
    if tp == to:
        return True, f"{label} equal"
    inter = tp & to
    smaller = min(len(tp), len(to))
    if smaller and len(inter) == smaller:  # one side fully contained in the other
        rel = "subset" if len(tp) < len(to) else "superset"
        return True, f"{label} {rel} ({len(inter)}/{smaller})"
    jac = len(inter) / len(tp | to) if (tp | to) else 0.0
    if jac >= 0.6:
        return True, f"{label} fuzzy jaccard {jac:.2f} ({len(inter)}/{len(tp | to)})"
    return False, f"{label} jaccard {jac:.2f} ({len(inter)}/{len(tp | to)})"


def _cmp_fuzzy(p: str, o: str, label: str) -> tuple:
    return _fuzzy_sets(_tokens(p), _tokens(o), label)


def _cmp_name(p: str, o: str, label: str) -> tuple:
    return _fuzzy_sets(_name_tokens(p), _name_tokens(o), label)


def _cmp_price(p: str, o: str) -> tuple:
    pa, pc, pu = _parse_price(p)
    oa, oc, ou = _parse_price(o)
    if pa is None or oa is None:
        if pa is None and oa is None:
            return _cmp_fuzzy(p, o, "price")
        side = "oracle" if pa is not None else "pipeline"
        return False, f"amount not parsed ({side} side): {p!r} vs {o!r}"
    if round(pa, 2) != round(oa, 2):
        return False, f"amount {_g(pa)} vs {_g(oa)}"
    if pc != oc:
        side = "oracle" if pc else "pipeline"
        return False, f"amount {_g(pa)} ok; currency missing ({side})"
    if (pu or ou) and pu != ou:
        return False, f"amount {_g(pa)} ok; unit {pu or '?'} vs {ou or '?'}"
    return True, f"price {'₹' if pc else ''}{_g(pa)}{'/' + pu if pu else ''}"


def _cmp_quantity(p: str, o: str) -> tuple:
    pp, op = _parse_quantity(p), _parse_quantity(o)
    if not pp or not op:
        if not pp and not op:
            return _cmp_fuzzy(p, o, "qty")
        side = "oracle" if pp else "pipeline"
        return False, f"quantity not parsed ({side} side): {p!r} vs {o!r}"
    if round(pp[0][0], 2) != round(op[0][0], 2) or pp[0][1] != op[0][1]:
        return False, f"qty {_g(pp[0][0])} {pp[0][1]} vs {_g(op[0][0])} {op[0][1]}"
    detail = f"qty {_g(pp[0][0])} {pp[0][1]}"
    if len(pp) > 1 or len(op) > 1:
        p2 = tuple(pp[1]) if len(pp) > 1 else None
        o2 = tuple(op[1]) if len(op) > 1 else None
        if p2 != o2:
            pdesc = f"({_g(p2[0])} {p2[1]})" if p2 else None
            odesc = f"({_g(o2[0])} {o2[1]})" if o2 else None
            return False, f"dual qty {pdesc} vs {odesc}"
        detail += f" ({_g(p2[0])} {p2[1]})"
    return True, detail


def _cmp_date(p: str, o: str) -> tuple:
    py, pm = _parse_date(p)
    oy, om = _parse_date(o)
    issues = []
    if py is not None and oy is not None:
        if py != oy:
            issues.append(f"year {py} vs {oy}")
    elif (py is None) != (oy is None):
        issues.append(f"year missing ({'pipeline' if py is None else 'oracle'})")
    if pm is not None and om is not None:
        if pm != om:
            issues.append(f"month {pm} vs {om}")
    elif (pm is None) != (om is None):
        issues.append(f"month missing ({'pipeline' if pm is None else 'oracle'})")
    if issues:
        return False, "; ".join(issues)
    if py or pm:
        return True, f"date {py}" + (f"-{pm:02d}" if pm else "")
    return True, "date both-absent"


def _warn_impossible_golden_dates(answers: dict) -> list:
    """Golden-file sanity: a compliant label never has expiry before mfg.

    p23's golden entry ('mfg 25/12/26, exp 28/06/26') is a physically
    impossible pair — suspected data-entry swap. Warn at load (never fix: the
    golden file is untouchable) so the corruption surfaces in every run log
    instead of silently skewing the metric. Partial readings ('2026') are
    skipped — only fully-ordered pairs are judged.
    """
    out = []
    for pid, row in answers.items():
        mfg = (row.get("manufacturing_date") or "").strip()
        exp = (row.get("expiry_date") or "").strip()
        if not mfg or not exp:
            continue
        my, mm = _parse_date(mfg)
        ey, em = _parse_date(exp)
        if my is None or ey is None:
            continue
        if (ey, em or 0) < (my, mm or 0):
            out.append(
                f"product {pid}: expiry {exp!r} is earlier than mfg {mfg!r} "
                f"(impossible pair — suspected entry swap, verified by hand)")
    return out


_CARE_LABEL_PFX = re.compile(r"^(?:e[-_. ]?ma?l{1,2}|mail)[.:_-]?", re.I)


def _care_emails(value: str) -> list:
    out = []
    for em in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", str(value or "")):
        local = em.split("@", 1)[0]
        stripped = _CARE_LABEL_PFX.sub("", local)
        if stripped:
            out.append(stripped + "@" + em.split("@", 1)[1])
        else:
            out.append(em)
    return out


def _care_fuzzy_equal(p: str, o: str) -> bool:
    """True when the two care lines carry the same channels up to OCR noise."""
    from difflib import SequenceMatcher

    pe, oe = _care_emails(p), _care_emails(o)
    if len(pe) != len(oe):
        return False
    if pe and not all(
        max(SequenceMatcher(None, a, b).ratio() for b in oe) >= 0.8
        for a in pe
    ):
        return False
    if oe and not all(
        max(SequenceMatcher(None, a, b).ratio() for b in pe) >= 0.8
        for a in oe
    ):
        return False
    dn = len(re.sub(r"\D", "", p or "")) >= 8
    on = len(re.sub(r"\D", "", o or "")) >= 8
    return dn == on


def _cmp_care(p: str, o: str) -> tuple:
    dp, do = _care_key(p), _care_key(o)
    if dp == do:
        return True, "care equal" if dp else "care both-absent"
    # Exact contact keys differ, but OCR noise can split an otherwise
    # identical address ('sugestion@…' vs 'suggestion@…'). Fall back to
    # fuzzy equivalence when the email set overlaps strongly and the phone
    # presence matches.
    if _care_fuzzy_equal(p, o):
        return True, f"care fuzzy-equal (OCR noise): pipe[{dp}]"
    return False, f"care pipeline[{dp}] vs oracle[{do}]"


def _cmp_dimensions(p: str, o: str) -> tuple:
    pn, on = _dimensions_key(p), _dimensions_key(o)
    if pn or on:
        if pn != on:
            return False, f"dims {sorted(pn, key=float)} vs {sorted(on, key=float)}"
        return True, "x".join(sorted(pn, key=float))
    return _cmp_fuzzy(p, o, "dims")


def _cmp_edible(p: str, o: str) -> tuple:
    if _edibility_key(p) == _edibility_key(o):
        return True, f"edible {_edibility_key(p) or 'both-absent'}"
    return False, f"edible {_edibility_key(p)} vs {_edibility_key(o)}"


_TYPED_COMPARERS = {
    "mrp": _cmp_price,
    "usp": _cmp_price,
    "net_quantity": _cmp_quantity,
    "manufacturing_date": _cmp_date,
    "expiry_date": _cmp_date,
    "product_name": lambda p, o: _cmp_name(p, o, "name"),
    "manufacturer": lambda p, o: _cmp_name(p, o, "mfr"),
    "consumer_care": _cmp_care,
    "dimensions": _cmp_dimensions,
    "edible": _cmp_edible,
}


def compare_field(field: str, pipe: str, oracle: str) -> tuple:
    """Returns (status, detail) with status in ok|missing|wrong|extra.

    ``field`` selects the typed comparer so a "wrong" row names the broken
    component (amount / unit / month / tokens) instead of just 'strings differ'.
    """
    p, o = str(pipe or "").strip(), str(oracle or "").strip()
    if o and not p:
        return "missing", "oracle-only"
    if p and not o:
        return "extra", "pipeline-only"
    if not o and not p:
        return "ok", "both-absent"
    if p.lower() == o.lower():
        return "ok", "exact"
    ok, detail = _TYPED_COMPARERS[field](p, o)
    return ("ok" if ok else "wrong", detail)


# ── oracle triage: WHO looks wrong on a disagreement ─────────────────────────
# The 7B VLM oracle is a strong reference, not ground truth — it can
# hallucinate. For every disagreement, sanity-check BOTH answers structurally
# (via the typed parsers above) and classify who is the more likely culprit,
# so you never tune the pipeline toward an oracle hallucination.

_JUNK_RES = (re.compile(r"\?{3,}|\*{3,}|%{3,}|#{3,}|!{3,}"),)


def _looks_junk(s: str) -> bool:
    s = str(s or "").strip()
    if not s or any(r.search(s) for r in _JUNK_RES):
        return True
    body = re.sub(r"\s", "", s.lower())
    odd = re.sub(r"[a-z0-9₹\.\-/:(),@+_]", "", body)
    if odd and len(odd) / max(len(body), 1) >= 0.5:
        return True
    # whole words made of one repeated char ('zzzzz', 'qqqqq') are OCR garbage
    if any(len(w) >= 4 and len(set(w)) == 1 for w in re.findall(r"[a-z]+", s.lower())):
        return True
    return False


# Tokens that may legitimately appear in a money string; anything else means
# the "price" isn't actually a price (e.g. the 3B hallucination
# "MRP: 100% PURE COFFEE").
_ALLOWED_MONEY_WORDS = {
    "mrp", "max", "retail", "price", "rs", "inr", "rupee", "rupees",
    "incl", "including", "of", "all", "taxes", "inc", "gst", "only",
    "per", "g", "kg", "ml", "l", "actual", "net",
}


def _price_shape_ok(s: str) -> bool:
    return not (set(re.findall(r"[a-z]+", str(s or "").lower())) - _ALLOWED_MONEY_WORDS)


# Label-section headings that must never win product_name / manufacturer.
_NAME_NOISE = {
    "nutritional information", "ingredients", "directions for use", "uses",
    "storage instructions", "storage", "fssai license", "fssai licence",
    "fssai", "customer care", "customer support", "manufactured by",
    "marketed by", "imported by", "packed by", "best before", "batch number",
    "batch no", "net quantity", "maximum retail price", "recipe", "servings",
}
_NAME_NOISE_TOKENS = set().union(*(set(p.split()) for p in _NAME_NOISE))


def _field_plausible(field: str, value: str) -> tuple:
    """Structural sanity of one side's answer. (plausible, reason)."""
    s = str(value or "").strip()
    if not s:
        return False, "empty"
    low = s.lower()
    if _looks_junk(low):
        return False, f"junk text ({s!r})"
    if field in ("mrp", "usp"):
        if not _price_shape_ok(s):
            return False, f"not price-shaped ({s!r})"
        amt, cur, unit = _parse_price(s)
        if amt is None or amt <= 0:
            return False, f"no positive amount ({s!r})"
        if amt > 1e8:
            return False, f"implausibly large amount {_g(amt)}"
        note = f"amount {_g(amt)}"
        if unit:
            note += f" /{unit}"
        elif field == "usp":
            note += " (no unit)"
        return True, note
    if field == "net_quantity":
        q = _parse_quantity(s)
        if not any(a > 0 and u for a, u in q):
            return False, f"no valid quantity ({s!r})"
        return True, "qty " + " ".join(f"{_g(a)} {u}" for a, u in q)
    if field in ("manufacturing_date", "expiry_date"):
        y, m = _parse_date(s)
        if y is None:
            return False, f"no year ({s!r})"
        if not 2000 <= y <= 2035:
            return False, f"implausible year {y}"
        if m is not None and not 1 <= m <= 12:
            return False, f"month {m} out of range"
        return True, f"year {y}" + (f" month {m}" if m else "")
    if field in ("product_name", "manufacturer"):
        toks = _tokens(s)
        if not toks:
            return False, "no word tokens"
        if toks <= _NAME_NOISE_TOKENS:
            return False, f"label heading ({s!r})"
        if len(s) > 120:
            return False, f"too long ({len(s)} chars)"
        alpha = sum(1 for t in toks if re.fullmatch(r"[a-z]+", t))
        if alpha / len(toks) < 0.5:
            return False, f"mostly non-alpha tokens ({s!r})"
        return True, f"{len(toks)} tokens"
    if field == "consumer_care":
        if _EMAIL_RE.search(s) or _phones(s):
            return True, "contact present"
        return False, f"no email/phone ({s!r})"
    if field == "dimensions":
        nums = re.findall(r"\d+(?:\.\d+)?", s)
        if not nums:
            return False, f"no numeric dimension ({s!r})"
        return True, f"{len(nums)} numbers"
    if field == "edible":
        if low[:1] in ("y", "n"):
            return True, low[:3]
        return False, f"not yes/no ({s!r})"
    return True, "unchecked"


_TRIAGE_LABELS = ("agree", "pipeline_wrong", "oracle_wrong", "ambiguous")


def triage_field(field: str, status: str, pv: str, ov: str) -> tuple:
    """Classify who looks wrong when the pipeline and 7B oracle disagree.

    A side whose value is structurally garbage (no amount, impossible month,
    no contact info, junk text) is the more likely culprit; a structurally
    sound value on one side suggests the other side missed or invented it.
    Both-plausible disagreement -> ambiguous: needs a human eye.
    """
    if status == "ok":
        return "agree", ""
    if status == "missing":  # oracle read a value, pipeline blank
        ok, why = _field_plausible(field, ov)
        tag = "pipeline_wrong" if ok else "oracle_wrong"
        return tag, f"oracle read {'plausible' if ok else 'implausible: ' + why}; pipeline blank"
    if status == "extra":  # pipeline read a value, oracle blank
        ok, why = _field_plausible(field, pv)
        tag = "oracle_wrong" if ok else "pipeline_wrong"
        return tag, f"pipeline read {'plausible' if ok else 'implausible: ' + why}; oracle blank"
    # status == "wrong": both sides have values
    p_ok, p_why = _field_plausible(field, pv)
    o_ok, o_why = _field_plausible(field, ov)
    if p_ok and o_ok:
        return "ambiguous", "both plausible; needs human eye"
    if p_ok:
        return "oracle_wrong", f"oracle implausible: {o_why}"
    if o_ok:
        return "pipeline_wrong", f"pipeline implausible: {p_why}"
    return "ambiguous", f"neither plausible (p: {p_why}; o: {o_why})"


# ── image grouping (ignore *.enhanced artifacts) ────────────────────────────
def _group_images(images_dir: Path) -> dict:
    groups = defaultdict(list)
    # Legacy + label-type-embedded naming: image1_1.jpg / image1_front.jpg.
    for p in sorted(images_dir.glob("image*.jpg")):
        m = re.fullmatch(r"image(\d+)_[A-Za-z0-9]+", p.stem)
        if m:
            groups[m.group(1)].append(str(p))
    # New-images naming: product1_front.jpg etc. → prefix "productN" (kept
    # distinct from the numeric image ids so golden keys never collide).
    for p in sorted(images_dir.glob("product*.jpg")):
        m = re.fullmatch(r"product(\d+)_[A-Za-z0-9]+", p.stem, re.IGNORECASE)
        if m:
            groups[f"product{m.group(1)}"].append(str(p))

    def _sort_key(item):
        key = item[0]
        if key.isdigit():
            return (0, int(key), "")
        return (1, int(re.sub(r"\D", "", key) or 0), key)

    return dict(sorted(groups.items(), key=_sort_key))


def _fmt(v: str, limit: int = 40) -> str:
    v = str(v or "")
    return v if len(v) <= limit else v[: limit - 1] + "…"


_ROW_KEYS = ["product", "field", "pipeline", "oracle_7b", "status", "note", "triage", "triage_note"]


def _write_reports(out_dir: Path, rows, tally, groups, t_start) -> tuple:
    csv_path = out_dir / "pipeline_vs_oracle.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_ROW_KEYS)
        w.writerows(rows)
    json_path = out_dir / "pipeline_vs_oracle.json"
    json_path.write_text(json.dumps({
        "fields": FIELDS,
        "tally": {f: dict(tally[f]) for f in FIELDS},
        "triage": dict(tally["*triage*"]),
        "rows": [dict(zip(_ROW_KEYS, r)) for r in rows],
        "products": len(groups),
        "elapsed_s": round(time.time() - t_start, 1),
    }, indent=1))
    return csv_path, json_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", default="/mnt/e/SIH_installation_files/images")
    ap.add_argument("--product", default=None, help="single product number, e.g. 6")
    ap.add_argument("--products", default=None,
                    help="comma-separated product numbers, e.g. '3,6,10'")
    ap.add_argument("--oracle", default="qwen2.5vl:7b")
    ap.add_argument("--classifier", default="qwen2.5:3b")
    ap.add_argument("--no-ocr-cache", action="store_true")
    ap.add_argument("--no-extract-cache", action="store_true",
                    help="re-run the 3B classifier per photo (needed when "
                         "tuning the SLM prompt/preprocessor, which the cached "
                         "extraction would otherwise freeze)")
    ap.add_argument("--no-labels", action="store_true",
                    help="merge without label types (pure heuristics) — use to "
                         "measure the routing's impact on frozen per-photo data")
    ap.add_argument("--out-dir", default="/tmp/pipeline_audit")
    ap.add_argument("--answers", default=None,
                    help="file of prior 7B VLM reads -> use it as the oracle "
                         "(fast, fully offline, no VLM calls)")
    ap.add_argument("--generate-answers", default=None, metavar="PATH",
                    help="write the 7B VLM reads for every product to PATH as "
                         "ground-truth answers.json (skips the pipeline) and exit")
    args = ap.parse_args()

    os.environ["FIELD_CLASSIFIER_MODEL"] = args.classifier
    # modules already imported by helpers above; re-read the module attribute
    # so the SLM model the classifier instantiates is the requested one.
    import app.config as cfg
    cfg.FIELD_CLASSIFIER_MODEL = args.classifier

    images_dir = Path(args.images_dir)
    if not images_dir.exists():
        repo_images = ROOT.parent / "images"
        if args.images_dir == ap.get_default("images-dir") and repo_images.exists():
            images_dir = repo_images
            print(f"  (default E-drive path {args.images_dir} not mounted; "
                  f"using repo images at {images_dir})")
    if not images_dir.exists():
        ap.error(f"images dir not found: {images_dir}")
    groups = _group_images(images_dir)
    if args.product:
        groups = {k: v for k, v in groups.items() if k == args.product}
    elif args.products:
        wanted = {p.strip() for p in args.products.split(",")}
        groups = {k: v for k, v in groups.items() if k in wanted}

    answers_from_file = {}
    if args.answers:
        answers_from_file = json.loads(Path(args.answers).read_text())
        for warn in _warn_impossible_golden_dates(answers_from_file):
            print(f"  !! golden sanity: {warn}")

    ocr_cache = DiskCache(OCR_CACHE_PATH if not args.no_ocr_cache else Path("/tmp/nocache-ocr.json"))
    vlm_cache = DiskCache(VLM_CACHE_PATH)
    extract_cache = None if args.no_extract_cache else DiskCache(PIPE_CACHE_PATH)
    svc = CachedSmartOCR(ocr_cache, vlm_cache, extract_cache)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tally = defaultdict(lambda: defaultdict(int))
    rows = []
    generated_answers = {}
    t_start = time.time()
    src_label = "golden answers" if args.answers else "7B VLM oracle"
    label_manifest = _load_label_manifest()

    for prefix, paths in groups.items():
        print(f"\n{'='*78}\nPRODUCT {prefix}  ({len(paths)} images: "
              f"{', '.join(Path(p).name for p in paths)})\n{'='*78}")

        oracle_merged = None
        if prefix in answers_from_file:
            t0 = time.time()
            oracle_merged = {f: (answers_from_file.get(prefix, {}).get(f, "") or "") for f in FIELDS}
            print(f"  (oracle from answers.json, {time.time()-t0:.1f}s)")
        elif args.generate_answers is not None or not args.answers:
            t0 = time.time()
            oracle_per = [_oracle_read(p, args.oracle, vlm_cache) for p in paths]
            oracle_merged = _merge(oracle_per)
            print(f"  (7B VLM oracle {time.time()-t0:.1f}s for {len(paths)} images)")
        else:
            oracle_merged = {f: "" for f in FIELDS}

        if args.generate_answers is not None:
            generated_answers[prefix] = oracle_merged
            continue

        t0 = time.time()
        pipe_per = _run_pipeline(svc, paths, args.classifier)
        label_types = None if args.no_labels else \
            [_label_type_for(p, label_manifest) for p in paths]
        pipe_merged = _merge(pipe_per, label_types)
        print(f"  (pipeline {time.time()-t0:.1f}s for {len(paths)} images)" +
              ("  [no-labels: heuristic merge]" if args.no_labels else ""))

        diffs = 0
        for f in FIELDS:
            pv, ov = pipe_merged.get(f, ""), oracle_merged.get(f, "")
            status, note = compare_field(f, pv, ov)
            triage, triage_note = triage_field(f, status, pv, ov)
            tally[f][status] += 1
            tally[f]["oracle_present"] += 1 if (ov or "").strip() else 0
            tally["*triage*"][triage] += 1
            tick = {"ok": " ✓", "missing": " ✗ MISSING", "wrong": " ≈ WRONG",
                    "extra": " ? EXTRA(over-read)"}[status]
            marker = "    " if (status == "ok" and not (ov or "").strip()) else tick
            rows.append([prefix, f, pv, ov, status, note, triage, triage_note])
            if status != "ok":
                diffs += 1
            print(f"  {f:18s}{marker}")
            if status == "ok" and (ov or "").strip():
                pass
            if status in ("missing", "wrong", "extra"):
                print(f"      pipeline: {_fmt(pv)!r}")
                print(f"      oracle  : {_fmt(ov)!r}")
                if note:
                    print(f"      note    : {note}")
                print(f"      triage  : {triage} — {triage_note}")
        if diffs == 0:
            print(f"  → all fields match the {src_label}")

        # Persist incrementally so an interrupted run never loses earlier
        # products (re-running resumes from the on-disk OCR cache).
        _write_reports(out_dir, rows, tally, groups, t_start)

    if args.generate_answers is not None:
        gen_path = Path(args.generate_answers)
        gen_path.parent.mkdir(parents=True, exist_ok=True)
        gen_path.write_text(json.dumps(generated_answers, ensure_ascii=False, indent=1))
        print(f"\nSaved 7B VLM ground-truth answers for {len(generated_answers)} products "
              f"to {gen_path}")
        print(f"Next: python scripts/pipeline_audit.py --answers {gen_path}  "
              f"(validates the pipeline offline, no VLM calls)")
        return

    csv_path, json_path = _write_reports(out_dir, rows, tally, groups, t_start)

    print(f"\n{'#'*78}\nFIELD AGREEMENT vs {src_label.upper()}  ({len(groups)} products)\n{'#'*78}")
    print(f"  {'field':18s} {'oracle':>7s} {'match':>7s} {'miss':>6s} {'wrong':>7s} {'extra':>7s}  recall")
    for f in FIELDS:
        t = tally[f]
        op = t["oracle_present"]
        ok = t["ok"]
        rec = f"{ok/op:5.1%}" if op else "   n/a"
        print(f"  {f:18s} {op:7d} {ok:7d} {t['missing']:6d} {t['wrong']:7d} {t['extra']:7d}  {rec}")
    ok_all = sum(tally[f]["ok"] for f in FIELDS)
    op_all = sum(tally[f]["oracle_present"] for f in FIELDS)
    print(f"  {'TOTAL':18s} {op_all:7d} {ok_all:7d} "
          f"{sum(tally[f]['missing'] for f in FIELDS):6d} "
          f"{sum(tally[f]['wrong'] for f in FIELDS):7d} "
          f"{sum(tally[f]['extra'] for f in FIELDS):7d}  "
          f"{ok_all/op_all:5.1%}" if op_all else "")
    tri = {k: tally["*triage*"].get(k, 0) for k in _TRIAGE_LABELS}
    tot = sum(tri.values())
    print(f"\n  TRIAGE — who looks wrong on disagreements ({tot} total)")
    for label in _TRIAGE_LABELS:
        pct = f"  {tri[label]/tot:4.1%}" if tot else ""
        hint = ""
        if label == "pipeline_wrong":
            hint = "  <- fix the pipeline (regex/SLM/heuristic)"
        elif label == "oracle_wrong":
            hint = f"  <- trust the pipeline; fix the {src_label.lower()} read, don't tune to the oracle"
        elif label == "ambiguous":
            hint = "  <- eyeball these rows"
        print(f"    {label:15s} {tri[label]:5d}{pct}{hint}")
    print(f"\n  reports: {csv_path}  {json_path}")
    print(f"  total elapsed {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()