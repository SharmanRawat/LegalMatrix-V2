"""Physical scale calibration for font-size measurement.

Calibration chain (in priority order):
  1. credit_card — a credit/debit card is ISO/IEC 7810 ID-1: 85.60 x 53.98 mm
     (universal physical size). The inspector places one beside the product;
     the card gives an exact, traceable pixels-per-mm reference.
  2. barcode      — product barcode as a coarser reference (magnification is
     not fixed, so higher uncertainty).
  3. exif         — camera-metric estimate from phone EXIF (focal length +
     subject distance); never an automated verdict.

When no reference is available we decline to fabricate a measurement.
"""
import logging
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

CARD_WIDTH_MM = 85.60
CARD_HEIGHT_MM = 53.98
CARD_ASPECT = CARD_WIDTH_MM / CARD_HEIGHT_MM  # ~1.586
CARD_ASPECT_MIN = 1.30
CARD_ASPECT_MAX = 1.90
CARD_AREA_MIN_FRACTION = 0.015
CARD_AREA_MAX_FRACTION = 0.65
CARD_ANGLE_TOLERANCE_DEG = 18.0
CARD_UNCERTAINTY = 0.06
BARCODE_WIDTH_MM = 20.0
BARCODE_UNCERTAINTY = 0.15


def _order_points(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(d)]
    ordered[3] = pts[np.argmax(d)]
    return ordered


def _quad_geometry(pts: np.ndarray) -> Optional[dict]:
    """Side lengths, diagonal aspect and corner angles of a 4-point quad."""
    pts = _order_points(pts)
    p1, p2, p3, p4 = pts
    top = float(np.linalg.norm(p2 - p1))
    right = float(np.linalg.norm(p3 - p2))
    bottom = float(np.linalg.norm(p4 - p3))
    left = float(np.linalg.norm(p1 - p4))
    diag1 = float(np.linalg.norm(p3 - p1))
    diag2 = float(np.linalg.norm(p4 - p2))
    return {
        "pts": pts,
        "long_side": max(top, right, bottom, left),
        "short_side": min(top, right, bottom, left),
        "aspect": max(top, right, bottom, left) / max(1e-6, min(top, right, bottom, left)),
        "diag_ratio": max(diag1, diag2) / max(1e-6, min(diag1, diag2)),
    }


def _angles_ok(pts: np.ndarray, tolerance_deg: float = CARD_ANGLE_TOLERANCE_DEG) -> bool:
    pts = _order_points(pts)
    ok = True
    for i in range(4):
        a = pts[i]
        b = pts[(i + 1) % 4]
        c = pts[(i + 2) % 4]
        v1 = a - b
        v2 = c - b
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 == 0 or n2 == 0:
            ok = False
            break
        cos_a = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        angle = float(np.degrees(np.arccos(cos_a)))
        if abs(angle - 90.0) > tolerance_deg:
            ok = False
            break
    return ok


def _inside_uniformity(image: np.ndarray, pts: np.ndarray) -> float:
    """Std-dev of grey inside the quad, normalized by overall std-dev.

    A printed card is flat plastic; its interior edge texture is much lower
    than a busy product label, so a low ratio supports the card hypothesis.
    """
    h, w = image.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [_order_points(pts).astype(np.int32)], 255)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    inside = gray[mask == 255]
    outside = gray[mask == 0]
    if inside.size == 0 or outside.size == 0:
        return 1.0
    sd_in = float(np.std(inside))
    sd_out = float(np.std(outside))
    return sd_in / max(1e-6, sd_out)


def detect_credit_card(image: np.ndarray) -> Optional[Tuple[float, Tuple[float, float, float, float], dict]]:
    """Detect a credit/debit card anywhere in the image.

    Returns (ppm, (x1,y1,x2,y2), info) for the best candidate quad, or None.
    ppm is averaged over both physical axes for perspective resilience.
    """
    try:
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 5, 40, 40)
        edges = cv2.Canny(gray, 60, 180)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best = None
        min_area = CARD_AREA_MIN_FRACTION * h * w
        max_area = CARD_AREA_MAX_FRACTION * h * w
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            geom = _quad_geometry(approx)
            if geom["aspect"] < CARD_ASPECT_MIN or geom["aspect"] > CARD_ASPECT_MAX:
                continue
            if geom["diag_ratio"] > 1.35:
                continue
            if not _angles_ok(approx):
                continue
            uniformity = _inside_uniformity(image, approx)
            if uniformity > 0.55:
                continue

            dx, dy = geom["pts"][1] - geom["pts"][0], geom["pts"][2] - geom["pts"][3]
            width_px = (float(np.linalg.norm(dx)) + float(np.linalg.norm(dy))) / 2.0
            height_px = (geom["long_side"] + geom["short_side"]) / 2.0
            ppm_w = width_px / CARD_WIDTH_MM
            ppm_h = height_px / CARD_HEIGHT_MM
            ppm = (ppm_w + ppm_h) / 2.0
            if ppm <= 0:
                continue
            score = geom["aspect"] / CARD_ASPECT  # near-1 is good
            x1, y1 = float(np.min(approx[:, 0, 0])), float(np.min(approx[:, 0, 1]))
            x2, y2 = float(np.max(approx[:, 0, 0])), float(np.max(approx[:, 0, 1]))
            candidate = (ppm, (x1, y1, x2, y2), {
                "aspect": round(geom["aspect"], 3),
                "uniformity": round(uniformity, 3),
                "long_side_px": round(geom["long_side"], 1),
                "short_side_px": round(geom["short_side"], 1),
                "ppm_w": round(ppm_w, 2),
                "ppm_h": round(ppm_h, 2),
                "fit_score": round(score, 3),
            })
            if best is None or score < best[2]["fit_score"]:
                best = candidate
        return best
    except Exception as e:
        logger.error("credit card detection failed: %s", e)
        return None


def compute_ppm_from_barcode(image: np.ndarray) -> Optional[Tuple[float, Tuple[float, float, float, float]]]:
    try:
        detector = cv2.barcode.BarcodeDetector()
        retval, _decoded, _dtype, points = detector.detectAndDecodeWithType(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        )
        if retval and len(points) > 0:
            pts = points[0].astype(np.float32)
            if len(pts) < 4:
                return None
            hull = cv2.convexHull(pts)
            if hull is None or len(hull) < 4:
                return None
            x1 = float(min(pts[:, 0]))
            y1 = float(min(pts[:, 1]))
            x2 = float(max(pts[:, 0]))
            y2 = float(max(pts[:, 1]))
            width_px = x2 - x1
            if width_px > 0:
                return width_px / BARCODE_WIDTH_MM, (x1, y1, x2, y2)
        return None
    except Exception as e:
        logger.error("barcode detection failed: %s", e)
        return None


class ScaleCalibrator:
    """Resolves a pixels-per-mm reference from the calibration chain."""

    def calibrate(self, image_path: str, mode: str = "auto") -> Optional[Dict]:
        img = cv2.imread(image_path)
        if img is None:
            return None

        if mode in ("auto", "credit_card"):
            card = detect_credit_card(img)
            if card:
                ppm, bbox, info = card
                return {
                    "calibration": "credit_card",
                    "ppm": float(ppm),
                    "uncertainty_factor": CARD_UNCERTAINTY,
                    "bbox": bbox,
                    "info": info,
                }

        if mode in ("auto", "barcode"):
            barcode = compute_ppm_from_barcode(img)
            if barcode:
                ppm, bbox = barcode
                return {
                    "calibration": "barcode",
                    "ppm": float(ppm),
                    "uncertainty_factor": BARCODE_UNCERTAINTY,
                    "bbox": bbox,
                }

        if mode == "exif":
            return None

        return None


def calibration_rejected_reason(image_path: str, mode: str = "auto") -> str:
    img = cv2.imread(image_path)
    if img is None:
        return "image_unreadable"
    reasons = []
    if mode in ("auto", "credit_card") and detect_credit_card(img) is None:
        reasons.append("credit_card_not_detected")
    if mode in ("auto", "barcode") and compute_ppm_from_barcode(img) is None:
        reasons.append("barcode_not_detected")
    if mode in ("auto", "credit_card", "barcode"):
        reasons.append("exif_unavailable")
    return "; ".join(dict.fromkeys(reasons)) or "calibration_failed"