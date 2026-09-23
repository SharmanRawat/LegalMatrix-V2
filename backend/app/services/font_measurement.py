"""font_measurement.py — font size / readability analysis.

Calibration chain (in priority order)
-------------------------------------
1. "credit_card" — a credit/debit card photographed beside the product is
   ISO/IEC 7810 ID-1 (85.60 x 53.98 mm), an exact universal reference.
2. "barcode" — product barcode on the same focal plane; magnification is not
   fixed so uncertainty is higher.
3. "exif" — camera-metric calibration from phone EXIF (35 mm-equivalent focal
   length -> horizontal FOV, and SubjectDistance).
4. None usable -> measure() returns CANNOT_MEASURE with an auditable reason.
   We never fabricate a figure from an uncalibrated image.

Measurement
-----------
- If OCR token boxes are supplied (new pipeline), each recognised token's
  pixel height is converted to mm via the calibration reference and compared
  against the LM-PCR minimum.
- If a VLM text region box is supplied (legacy path), measure the CAP-HEIGHT
  of glyphs inside it (vertical height of the dominant capital/digit stroke
  cluster, so descenders do not inflate the reading).
- Otherwise fall back to heuristic component heights in the lower half of the
  image (median), excluding the barcode region; this is UNVALIDATED so it is
  always reported as REVIEW_REQUIRED (informational only).

Defensibility gates
-------------------
- A box/token must pass geometric + glyph sanity checks before its reading is
  trusted.
- A measured mm outside [0.3, 10.0] x required_mm is implausible and forces
  REVIEW_REQUIRED.
- The lower-half heuristic never produces an automated verdict.
"""

import logging
import os
import statistics
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from app.services.scale_calibrator import (
    ScaleCalibrator,
    calibration_rejected_reason,
    detect_credit_card,
    compute_ppm_from_barcode as _scan_barcode,
    _ppm_from_focal,
    _exif_calibration_with_reason,
)

logger = logging.getLogger(__name__)

BARCODE_UNCERTAINTY = 0.15

BOX_MAX_AREA_FRACTION = 0.15
BOX_MIN_AREA_FRACTION = 0.002
BOX_MIN_WIDTH_PX = 10
BOX_MIN_HEIGHT_PX = 10
BOX_ASPECT_MIN = 1.2
BOX_ASPECT_MAX = 12.0
BOX_MIN_GLYPHS = 3
BOX_MAX_HEIGHT_REL_STDDEV = 0.4

IMPLAUSIBLE_LOW_FACTOR = 0.3
IMPLAUSIBLE_HIGH_FACTOR = 10.0

ImageOrPath = Union[str, np.ndarray]


def _load_image(image: ImageOrPath) -> Optional[np.ndarray]:
    if isinstance(image, np.ndarray):
        return image
    return cv2.imread(str(image))


class FontMeasurementService:
    def compute_ppm_from_barcode(self, image_path: str):
        img = cv2.imread(str(image_path))
        if img is None:
            return None
        return _scan_barcode(img)

    def compute_ppm_from_credit_card(self, image_path: str):
        img = cv2.imread(str(image_path))
        if img is None:
            return None
        card = detect_credit_card(img)
        if card:
            ppm, bbox, _info = card
            return ppm, bbox
        return None

    def calibrate(self, image_path: str) -> Optional[Dict]:
        calibrator = ScaleCalibrator()
        return calibrator.calibrate(image_path)
        # Fallbacks (barcode/exif) are handled inside ScaleCalibrator.

    def _calibration_rejected_reason(self, image_path: str) -> str:
        if not os.path.exists(image_path):
            return "image_unreadable"
        return calibration_rejected_reason(image_path)

    def _normalize_box(
        self,
        box: List[float],
        img_w: int,
        img_h: int,
        box_format: str = "normalized",
    ) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = (float(v) for v in box[:4])
        if box_format == "px":
            pass
        else:
            x1, x2 = x1 * img_w / 1000.0, x2 * img_w / 1000.0
            y1, y2 = y1 * img_h / 1000.0, y2 * img_h / 1000.0
        xi1, yi1 = int(round(min(x1, x2))), int(round(min(y1, y2)))
        xi2, yi2 = int(round(max(x1, x2))), int(round(max(y1, y2)))
        pad = max(2, int((xi2 - xi1) * 0.05))
        xi1 = max(0, xi1 - pad)
        yi1 = max(0, yi1 - pad)
        xi2 = min(img_w, xi2 + pad)
        yi2 = min(img_h, yi2 + pad)
        return xi1, yi1, xi2, yi2

    def _glyph_heights_in_region(self, image: ImageOrPath, box: Tuple[int, int, int, int]) -> Optional[List[int]]:
        try:
            img = _load_image(image)
            if img is None:
                return None
            x1, y1, x2, y2 = box
            if x2 - x1 < 4 or y2 - y1 < 4:
                return None
            region = img[y1:y2, x1:x2]
            region_h, region_w = y2 - y1, x2 - x1
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            gray = cv2.bilateralFilter(gray, 5, 30, 30)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            if region_h >= 40:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

            n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary)
            heights = []
            for i in range(1, n):
                area = stats[i, cv2.CC_STAT_AREA]
                h = stats[i, cv2.CC_STAT_HEIGHT]
                wid = stats[i, cv2.CC_STAT_WIDTH]
                if (
                    region_h * 0.06 <= h <= region_h
                    and 1 <= wid <= region_w * 0.8
                    and h < region_h
                    and area >= max(6, h * 1.5)
                ):
                    heights.append(int(h))
            return heights or None
        except Exception as e:
            logger.error(f"Glyph region measurement failed: {e}")
            return None

    @staticmethod
    def _box_geometry_ok(box: Tuple[int, int, int, int], img_w: int, img_h: int) -> Tuple[bool, Optional[str]]:
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        if bw < BOX_MIN_WIDTH_PX or bh < BOX_MIN_HEIGHT_PX:
            return False, "too_small"
        area_frac = (bw * bh) / (img_w * img_h)
        if area_frac > BOX_MAX_AREA_FRACTION:
            return False, "area_too_large"
        if area_frac < BOX_MIN_AREA_FRACTION:
            return False, "area_too_small"
        aspect = bw / max(1, bh)
        if not (BOX_ASPECT_MIN <= aspect <= BOX_ASPECT_MAX):
            return False, "bad_aspect_ratio"
        return True, None

    @staticmethod
    def _box_is_plausible(box: Tuple[int, int, int, int], img_w: int, img_h: int, heights_px: List[int]) -> Tuple[bool, Optional[str]]:
        ok, reason = FontMeasurementService._box_geometry_ok(box, img_w, img_h)
        if not ok:
            return False, reason
        if len(heights_px) < BOX_MIN_GLYPHS:
            return False, "too_few_glyphs"
        mean_h = statistics.mean(heights_px)
        sd_h = statistics.stdev(heights_px) if len(heights_px) > 1 else 0.0
        if mean_h > 0 and (sd_h / mean_h) > BOX_MAX_HEIGHT_REL_STDDEV:
            return False, "multimodal_heights"
        return True, None

    def cap_height_px(self, heights: List[int]) -> int:
        if not heights:
            return 0
        bin_w = max(1, int(statistics.median(heights) // 10))
        bins: Dict[int, List[int]] = {}
        for h in heights:
            bins.setdefault((h // bin_w) * bin_w, []).append(h)
        majority = max(bins.values(), key=len)
        return int(round(statistics.median(majority)))

    def _text_component_heights(self, image: ImageOrPath, exclude_bbox=None) -> Optional[List[int]]:
        try:
            img = _load_image(image)
            if img is None:
                return None
            h, w = img.shape[:2]
            lower = img[int(h * 0.5):, :]
            off_y = int(h * 0.5)
            gray = cv2.cvtColor(lower, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            if exclude_bbox:
                x1, y1, x2, y2 = [int(v) for v in exclude_bbox]
                x1 = max(0, x1 - 10)
                x2 = min(w, x2 + 10)
                y1 = max(0, y1 - off_y - 10)
                y2 = min(h - off_y, y2 + 10)
                if y2 > y1 and x2 > x1:
                    binary[y1:y2, x1:x2] = 0
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

            n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary)
            heights = []
            for i in range(1, n):
                area = stats[i, cv2.CC_STAT_AREA]
                height = stats[i, cv2.CC_STAT_HEIGHT]
                width = stats[i, cv2.CC_STAT_WIDTH]
                if 3 <= height <= h * 0.25 and 2 <= width <= w * 0.8 and area > 5:
                    heights.append(int(height))
            return heights or None
        except Exception as e:
            logger.error(f"Text component measurement failed: {e}")
            return None

    @staticmethod
    def _cannot_measure(required_mm: Optional[float], reason: str) -> Dict:
        return {
            "status": "CANNOT_MEASURE",
            "calibration": "none",
            "calibration_rejected_reason": reason,
            "measured_mm": None,
            "uncertainty": None,
            "required_mm": required_mm,
            "ppm": None,
            "method": "none",
            "glyph_count": None,
            "height_px": None,
        }

    def measure(
        self,
        image_path: str,
        required_mm: Optional[float] = None,
        text_box: Optional[List[float]] = None,
    ) -> Optional[Dict]:
        cal = self.calibrate(image_path)
        if not cal:
            return self._cannot_measure(required_mm, self._calibration_rejected_reason(image_path))

        ppm = cal["ppm"]
        uncertainty_factor = cal["uncertainty_factor"]

        heights_px: Optional[List[int]] = None
        method = "heuristic_lower_half"
        box_rejected_reason: Optional[str] = None
        if text_box:
            img = cv2.imread(image_path)
            if img is None:
                return self._cannot_measure(required_mm, "image_unreadable")
            ih, iw = img.shape[:2]
            box = self._normalize_box(text_box, iw, ih)
            geo_ok, geo_reason = self._box_geometry_ok(box, iw, ih)
            if not geo_ok:
                box_rejected_reason = geo_reason
            else:
                heights_px = self._glyph_heights_in_region(img, box)
                if not heights_px:
                    box_rejected_reason = "no_glyphs_found"
                else:
                    ok, reason = self._box_is_plausible(box, iw, ih, heights_px)
                    if ok:
                        method = "cap_height"
                    else:
                        box_rejected_reason = reason
                        heights_px = None

        if heights_px is None:
            heights_px = self._text_component_heights(image_path, exclude_bbox=cal.get("bbox"))
            if not heights_px:
                return self._cannot_measure(required_mm, "no_text_components_found")

        if method == "cap_height":
            height_px = self.cap_height_px(heights_px)
        else:
            height_px = int(round(statistics.median(heights_px)))

        measured_mm = height_px / ppm
        uncertainty = measured_mm * uncertainty_factor

        result = {
            "measured_mm": round(measured_mm, 2),
            "uncertainty": round(uncertainty, 2),
            "required_mm": required_mm,
            "calibration": cal["calibration"],
            "ppm": round(ppm, 2),
            "method": method,
            "glyph_count": len(heights_px),
            "height_px": height_px,
        }
        if cal.get("info"):
            result["calibration_info"] = cal["info"]
        if cal.get("bbox"):
            result["calibration_bbox"] = [int(v) for v in cal["bbox"]]
        if box_rejected_reason:
            result["box_rejected_reason"] = box_rejected_reason

        if required_mm is None:
            result["status"] = "REVIEW_REQUIRED"
            return result

        low = IMPLAUSIBLE_LOW_FACTOR * required_mm
        high = IMPLAUSIBLE_HIGH_FACTOR * required_mm
        if not (low <= measured_mm <= high):
            result["status"] = "REVIEW_REQUIRED"
            result["implausible"] = True
            return result

        if method != "cap_height":
            result["status"] = "REVIEW_REQUIRED"
            return result

        if cal["calibration"] == "exif":
            # Camera-metric EXIF reference (focal length + subject distance) is
            # never an automated verdict — informational review only.
            result["status"] = "REVIEW_REQUIRED"
            return result

        lower = measured_mm - uncertainty
        if lower >= required_mm:
            status = "COMPLIANT"
        elif measured_mm + uncertainty < required_mm:
            status = "POTENTIAL_VIOLATION"
        else:
            status = "REVIEW_REQUIRED"
        result["status"] = status
        return result

    def measure_from_tokens(
        self,
        image_path: str,
        tokens: List[Dict],
        required_mm: Optional[float] = None,
        match_substrings: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """Measure font size in mm from OCR token boxes (new pipeline).

        tokens: [{"text": str, "box": [x1,y1,x2,y2] (px, axis-aligned)}].
        When match_substrings is given only tokens whose text contains one of
        them (case-insensitive) are measured; otherwise the median of all
        token heights is used.
        """
        cal = self.calibrate(image_path)
        if not cal:
            return self._cannot_measure(required_mm, self._calibration_rejected_reason(image_path))

        ppm = cal["ppm"]
        uncertainty_factor = cal["uncertainty_factor"]

        matched = []
        lower = [s.lower() for s in (match_substrings or [])]
        for token in tokens or []:
            text = str(token.get("text", "") or "").strip()
            box = token.get("box")
            if not text or not box or len(box) != 4:
                continue
            x1, y1, x2, y2 = (float(v) for v in box[:4])
            h_px = y2 - y1
            if h_px < 2:
                continue
            if lower:
                if not any(s in text.lower() for s in lower):
                    continue
            matched.append((text, h_px, box))

        if not matched:
            return self._cannot_measure(required_mm, "no_matching_tokens")

        heights_px = [h for _t, h, _b in matched]
        height_px = int(round(statistics.median(heights_px)))
        measured_mm = height_px / ppm
        uncertainty = measured_mm * uncertainty_factor

        result = {
            "measured_mm": round(measured_mm, 2),
            "uncertainty": round(uncertainty, 2),
            "required_mm": required_mm,
            "calibration": cal["calibration"],
            "ppm": round(ppm, 2),
            "method": "ocr_token_height",
            "glyph_count": len(matched),
            "height_px": height_px,
            "tokens_measured": [t for t, _h, _b in matched],
        }
        if cal.get("info"):
            result["calibration_info"] = cal["info"]
        if cal.get("bbox"):
            result["calibration_bbox"] = [int(v) for v in cal["bbox"]]

        if required_mm is None:
            result["status"] = "REVIEW_REQUIRED"
            return result

        low = IMPLAUSIBLE_LOW_FACTOR * required_mm
        high = IMPLAUSIBLE_HIGH_FACTOR * required_mm
        if not (low <= measured_mm <= high):
            result["status"] = "REVIEW_REQUIRED"
            result["implausible"] = True
            return result

        if "credit_card" not in cal["calibration"] and "barcode" not in cal["calibration"]:
            result["status"] = "REVIEW_REQUIRED"
            return result

        lower_bound = measured_mm - uncertainty
        if lower_bound >= required_mm:
            status = "COMPLIANT"
        elif measured_mm + uncertainty < required_mm:
            status = "POTENTIAL_VIOLATION"
        else:
            status = "REVIEW_REQUIRED"
        result["status"] = status
        return result


_font_service = None


def get_font_measurement_service():
    global _font_service
    if _font_service is None:
        _font_service = FontMeasurementService()
    return _font_service