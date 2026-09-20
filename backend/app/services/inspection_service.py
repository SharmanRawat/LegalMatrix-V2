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

# A consumer-care line must expose one of these contact channels to count.
_CARE_CONTACT_RE = re.compile(r"@|toll\s*free|tollfree|1800|1?\d{10}")


def next_inspection_id() -> str:
    import secrets
    return f"LGM-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"


def merge_extractions(results: List[Dict]) -> Dict:
    """Merge per-photo extractions.

    MRP / USP / net quantity must reflect one printed declaration, so the three
    are taken together from the single photo that carries the most statutory
    price fields (the back-label block), never mixed across photos. Other fields
    (name, manufacturer, dates…) fall back to longest-string-wins.
    """
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
        merged.update(_block_from_best(results, date_keys, 2))

    for result in results:
        if not result:
            continue
        for key, value in result.items():
            if not value:
                continue
            if key in stat_keys and key in merged:
                continue
            if key in date_keys and key in merged:
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
        if r and re.search(_CARE_CONTACT_RE, str(_filled(r).get("consumer_care", "")))
    ]
    care_candidates = [c for c in care_candidates if c]
    if care_candidates:
        merged["consumer_care"] = max(care_candidates, key=len)
    elif "consumer_care" in merged and not re.search(
        _CARE_CONTACT_RE, str(merged.get("consumer_care", ""))
    ):
        merged["consumer_care"] = ""
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

    bad = [k for k in overrides if k not in EXPECTED_KEYS]
    if bad:
        raise ValueError(f"Unknown fields: {', '.join(sorted(bad))}")

    declarations = {k: (str(v).strip() if v else "") for k, v in inspection.get("declarations", {}).items()}
    meta = dict(inspection.get("meta") or {})
    # _row_to_dict flattens meta_json to the top level; re-collect those keys.
    for flat_key in ("compliance_radar", "grade", "font_measurement", "ocr_engine",
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
) -> Dict:
    """Full pipeline: preprocess → extract → merge → compliance → font →
    heat-map → radar → persist."""
    ocr = ocr or _get_default_ocr()

    individual_results = []
    for path in image_paths:
        individual_results.append(ocr.extract_structured(path))

    text_boxes = _collect_text_boxes(individual_results)

    merged = merge_extractions(individual_results)
    safe_decl = {key: merged.get(key, "") for key in EXPECTED_KEYS}
    missing = compute_missing(safe_decl)
    field_evidence = _field_evidence(individual_results, safe_decl)
    extraction_confidence = _extraction_confidence(individual_results, safe_decl, missing)

    # Resource-adaptive cascade: escalation to a VLM when confidence is low.
    if VLM_RESCUE_ENABLED and extraction_confidence["overall"] < VLM_RESCUE_CONFIDENCE_THRESHOLD:
        rescued = _vlm_rescue(image_paths, individual_results, ocr)
        if rescued:
            individual_results = rescued
            merged = merge_extractions(individual_results)
            safe_decl = {key: merged.get(key, "") for key in EXPECTED_KEYS}
            missing = compute_missing(safe_decl)
            field_evidence = _field_evidence(individual_results, safe_decl)
            extraction_confidence = _extraction_confidence(individual_results, safe_decl, missing)

    overall_status = compute_overall_status(missing)
    currency_verified = _verify_mrp_currency(
        ocr, image_paths, individual_results, safe_decl.get("mrp", "")
    )
    compliance = rule_engine.evaluate_compliance(
        safe_decl, missing, currency_verified=currency_verified
    )

    net_qty_g = _parse_net_quantity_g(safe_decl)
    required_mm = measurement_service_get_required(net_qty_g)

    token_lists = _per_image_tokens(individual_results)
    field_maps = [r.get("field_map", {}) for r in individual_results]

    inspection_id = next_inspection_id()

    font_measurement = None
    first_unmeasurable = None
    per_image_cal_bbox: Dict[int, Optional[List[float]]] = {}
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

    misleading_checks = _check_misleading(safe_decl, compliance, currency_verified)

    heatmaps = _render_heatmaps(
        image_paths, token_lists, field_maps, per_image_cal_bbox,
        compliance["violations"], inspection_id,
    )

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

    meta = {
        "compliance_radar": radar,
        "grade": radar.get("grade", "D") if radar else "D",
        "font_measurement": font_measurement,
        "heatmaps": heatmaps,
        "ocr_engine": ocr_engine_name,
        "classifier": _classifier_label(ocr),
        "field_evidence": field_evidence,
        "extraction_confidence": extraction_confidence,
    }

    result = {
        "inspection_id": inspection_id,
        "timestamp": datetime.now().isoformat(),
        "method": method,
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