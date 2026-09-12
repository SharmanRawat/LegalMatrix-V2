"""Inspection service — orchestrates OCR extraction, compliance checks,
font measurement, evidence storage and persistence.

Keeps the API layer thin and the pipeline testable (OCR can be mocked).
"""
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from app.config import QWN_MODEL, get_evidence_dir as resolve_evidence_dir
from app.core.rule_engine import rule_engine
from app.repositories import inspections as inspection_repo
from app.services.font_measurement import FontMeasurementService
from app.services.price_engine import price_engine

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


def next_inspection_id() -> str:
    import secrets
    return f"LGM-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"


def merge_extractions(results: List[Dict]) -> Dict:
    """Merge per-photo VLM extractions.

    MRP / USP / net quantity must reflect one printed declaration, so the three
    are taken together from the single photo that carries the most statutory
    price fields (the back-label block), never mixed across photos. Other fields
    (name, manufacturer, dates…) fall back to longest-string-wins.
    """
    stat_keys = ("mrp", "usp", "net_quantity")

    def _filled(d: Dict) -> Dict:
        return {k: v for k, v in d.items()
                if isinstance(v, str) and v.strip() and v != "None"}

    if results:
        ranked = []
        for r in results:
            if not r:
                continue
            filled = _filled(r)
            stat_weight = sum(1 for k in stat_keys if k in filled)
            ranked.append((stat_weight, len(filled), r))
        if ranked:
            ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
            stat_photo = _filled(ranked[0][2])
            if sum(1 for k in stat_keys if k in stat_photo) >= 2:
                merged = {k: v for k, v in stat_photo.items() if k in stat_keys}
            else:
                merged = {}

    for result in results:
        if not result:
            continue
        for key, value in result.items():
            if not value:
                continue
            if key in stat_keys and key in merged:
                continue
            if key not in merged or len(str(value)) > len(str(merged[key])):
                merged[key] = value
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
    """ISO timestamp of photo capture (EXIF DateTimeOriginal / Digitized).

    Chain of custody needs the time the photo was taken, not the inspection run."""
    try:
        with Image.open(image_path) as pil:
            exif = pil.getexif()
        raw = exif.get(0x9003) or exif.get(0x9009)  # DateTimeOriginal, DateTimeDigitized
        if not raw:
            return None
        return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").isoformat()
    except Exception:
        return None


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
    sold by dimensions (garments, cables, electronics, etc.). Food/beverage and
    unknown products are exempt — food labels almost never print dimensions."""
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
    if unit in ("g", "gm", "gram"):
        return value
    if unit == "kg":
        return value * 1000
    if unit in ("ml",):
        return value  # g/ml font rules share the same thresholds
    if unit in ("l", "litre", "liter"):
        return value * 1000
    if unit in ("m",):
        return value
    return value


def run_inspection(
    image_paths: List[str],
    user_id: Optional[int] = None,
    ocr=None,
    text_boxes: Optional[Dict[int, List[float]]] = None,
) -> Dict:
    """Full pipeline: extract → merge → missing → compliance → font → persist.

    text_boxes: VLM-localized MRP/NetQty regions {image_index: [x1,y1,x2,y2]}
    in Qwen 0-1000 normalized coordinates, used for cap-height measurement."""
    ocr = ocr or _get_default_ocr()

    individual_results = []
    for path in image_paths:
        individual_results.append(ocr.extract_structured(path))

    text_boxes = _collect_text_boxes(individual_results)

    merged = merge_extractions(individual_results)
    safe_decl = {key: merged.get(key, "") for key in EXPECTED_KEYS}
    missing = compute_missing(safe_decl)
    overall_status = compute_overall_status(missing)
    compliance = rule_engine.evaluate_compliance(safe_decl, missing)

    # ── font size & readability (best-effort) ────────────────────────────
    font_measurement = None
    first_unmeasurable = None
    net_qty_g = _parse_net_quantity_g(safe_decl)
    required_mm = measurement_service_get_required(net_qty_g)
    for index, path in enumerate(image_paths):
        if not Path(path).exists():
            continue
        text_box = (text_boxes or {}).get(index)
        fm = FontMeasurementService().measure(
            path, required_mm=required_mm, text_box=text_box
        )
        if not fm:
            continue
        fm["image_index"] = index
        fm["image_path"] = str(path)
        capture_time = _exif_capture_time(path)
        if capture_time:
            fm["photo_capture_timestamp"] = capture_time
        if fm.get("status") == "CANNOT_MEASURE":
            if first_unmeasurable is None:
                first_unmeasurable = fm
            continue
        font_measurement = fm
        break
    if font_measurement is None:
        font_measurement = first_unmeasurable

    # ── misleading / consistency checks (USP vs MRP) ─────────────────────
    misleading_checks = _check_misleading(safe_decl, compliance)

    prompt_hash = ""
    fingerprint = getattr(ocr, "prompt_fingerprint", None)
    if callable(fingerprint):
        try:
            prompt_hash = fingerprint()
        except Exception:
            prompt_hash = ""

    evidence = _store_evidence(image_paths)
    evidence_hash = ""
    for item in evidence:
        evidence_hash += item["sha256"]
    evidence_hash = hashlib.sha256(evidence_hash.encode("utf-8")).hexdigest() if evidence_hash else ""

    inspection_id = next_inspection_id()

    result = {
        "inspection_id": inspection_id,
        "timestamp": datetime.now().isoformat(),
        "method": QWN_MODEL,
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
        "evidence": {"hash": evidence_hash, "images": evidence},
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
            "model": QWN_MODEL,
            "user_id": user_id,
        }
    )
    for item in evidence:
        inspection_repo.add_inspection_image(
            inspection_id, item["filename"], item["original_name"], item["sha256"], item["sort_order"]
        )

    return result


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


def _check_misleading(safe_decl: Dict, compliance: Dict) -> List[Dict]:
    """Consistency checks that catch misleading declarations."""
    issues = []
    mrp_text = safe_decl.get("mrp", "")
    usp_text = safe_decl.get("usp", "")

    if mrp_text:
        ok, msg = rule_engine.validate_mrp_format(mrp_text)
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

    # Cross-check the printed unit sale price against MRP / net quantity.
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

    # Already flagged missing declarations stay in `violations`; we only add extras here.
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
        from app.services.ocr_service import get_ocr_service
        _ocr_instance = get_ocr_service()
    return _ocr_instance