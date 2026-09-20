"""Compliance heat-map generator — draws the verdicts back onto the product
photo so an enforcement officer can SEE where each declaration sits and which
regions fail.

Color legend (drawn on the image):
  green  — declaration present and compliant
  red    — declaration present but failed a format/compliance check
  yellow — present but low OCR confidence (manual review)
  cyan   — calibration reference (credit card / barcode) used for font scale
"""
import logging
from typing import Dict, List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

GREEN = (60, 179, 113)
RED = (60, 60, 230)
YELLOW = (0, 200, 255)
CYAN = (230, 216, 0)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

VIOLATION_FIELDS = {"mrp", "net_quantity", "manufacturer", "product_name",
                    "manufacturing_date", "expiry_date", "consumer_care",
                    "dimensions", "usp"}


def _field_color(field: str, violations_by_field: List[str], low_conf: bool) -> tuple:
    if field in VIOLATION_FIELDS and field in violations_by_field:
        return RED
    if low_conf:
        return YELLOW
    return GREEN


def _draw_legend(image: np.ndarray) -> None:
    h, w = image.shape[:2]
    legend_items = [
        ("COMPLIANT", GREEN),
        ("VIOLATION", RED),
        ("LOW CONFIDENCE", YELLOW),
        ("CALIBRATION REF", CYAN),
    ]
    line_h = 26
    legend_w = 220
    total_h = len(legend_items) * line_h + 20
    x0 = max(0, w - legend_w - 12)
    y0 = max(0, h - total_h - 12)
    overlay = image.copy()
    cv2.rectangle(overlay, (x0, y0), (w - 8, y0 + total_h), (30, 30, 30), -1)
    image[:] = cv2.addWeighted(overlay, 0.55, image, 0.45, 0)
    for i, (label, color) in enumerate(legend_items):
        yy = y0 + 10 + i * line_h + 8
        cv2.rectangle(image, (x0 + 10, yy - 12), (x0 + 30, yy + 2), color, -1)
        cv2.putText(image, label, (x0 + 40, yy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, WHITE, 1, cv2.LINE_AA)


def render_heatmap(
    image_path: str,
    out_path: str,
    tokens: Optional[List[Dict]] = None,
    field_map: Optional[Dict] = None,
    calibration_bbox: Optional[List[float]] = None,
    violations: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """Overlay the compliance verdict on the original photo.

    field_map: {field_key: [ocr token dicts]} from the extraction step.
    violations: rule-engine violations (list) for red flags.
    Returns metadata {out_path, field_boxes, calibration_box} or None.
    """
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None
    except Exception as e:
        logger.error("heatmap load failed: %s", e)
        return None

    violations_by_field = {v.get("field", "") for v in (violations or [])}
    field_map = field_map or {}

    drawn = {}
    for field, toks in field_map.items():
        boxes = [t.get("box") for t in toks if t and len(t.get("box", [])) == 4]
        if not boxes:
            continue
        xs1 = min(b[0] for b in boxes)
        ys1 = min(b[1] for b in boxes)
        xs2 = max(b[2] for b in boxes)
        ys2 = max(b[3] for b in boxes)
        low_conf = all(float(t.get("conf", 1.0)) < 0.65 for t in toks)
        color = _field_color(field, violations_by_field, low_conf)
        cv2.rectangle(image, (xs1, ys1), (xs2, ys2), color, 2)
        label = field.replace("_", " ").upper()
        cv2.rectangle(image, (xs1, max(0, ys1 - 16)), (xs1 + len(label) * 7 + 8, ys1), color, -1)
        cv2.putText(image, label, (xs1 + 4, max(8, ys1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, BLACK, 1, cv2.LINE_AA)
        drawn[field] = [xs1, ys1, xs2, ys2]

    cal_meta = None
    if calibration_bbox and len(calibration_bbox) == 4:
        x1, y1, x2, y2 = (int(v) for v in calibration_bbox)
        cv2.rectangle(image, (x1, y1), (x2, y2), CYAN, 2)
        cv2.putText(image, "CALIBRATION REF", (x1 + 4, max(16, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, CYAN, 1, cv2.LINE_AA)
        cal_meta = [x1, y1, x2, y2]

    _draw_legend(image)
    try:
        cv2.imwrite(out_path, image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    except Exception as e:
        logger.error("heatmap write failed: %s", e)
        return None
    return {"out_path": out_path, "field_boxes": drawn, "calibration_box": cal_meta}


def render_calibration_image(
    image_path: str, out_path: str, calibration_bbox: List[float], calibration: str
) -> Optional[str]:
    """Debug image that marks the detected calibration reference."""
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None
    except Exception:
        return None
    if calibration_bbox and len(calibration_bbox) == 4:
        x1, y1, x2, y2 = (int(v) for v in calibration_bbox)
        cv2.rectangle(image, (x1, y1), (x2, y2), CYAN, 3)
        cv2.putText(image, calibration.upper(), (x1 + 4, max(16, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, CYAN, 2, cv2.LINE_AA)
    cv2.imwrite(out_path, image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out_path