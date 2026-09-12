"""
font_measurement.py — font size / readability analysis.

Calibration chain (in priority order)
-------------------------------------
1. "barcode" — detect the product barcode (always present on the label, same
   focal plane as the text). Barcode printed magnification is NOT fixed, so
   we attach increased uncertainty instead of treating 20 mm as exact.
2. "exif" — camera-metric calibration from EXIF (35 mm-equivalent focal
   length -> horizontal FOV, and SubjectDistance).  No reference object is
   needed in the photo.  Higher uncertainty because SubjectDistance is an
   estimate.
3. Neither usable -> measure() returns a CANNOT_MEASURE status with an
   auditable reason. We NEVER fabricate a figure from an uncalibrated image.

Measurement
-----------
- If a text region box is supplied (from VLM localization, normalized 0-1000
  or absolute pixels), measure the CAP-HEIGHT of glyphs inside it: vertical
  height of the dominant capital/digit stroke cluster, so descenders
  ('g','p','q','y') do not inflate the reading.
- Otherwise fall back to heuristic component heights in the lower half of the
  image (median), excluding the barcode region. The heuristic is UNVALIDATED
  on our real dataset, so its results are reported as REVIEW_REQUIRED
  (informational only) unless backed by a clean VLM box.

Defensibility gates (what the critical review added)
----------------------------------------------------
- A VLM box must pass a geometric + glyph-cluster sanity check before its
  cap-height reading is trusted. A rejected box falls back to the heuristic.
- A measured mm outside [0.3, 10.0] x required_mm is implausible for the
  numerals of a label and forces REVIEW_REQUIRED.
- The heuristic lower-half method never produces an automated verdict.
"""

import logging
import os
import statistics
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Barcode symbols print at a magnification factor of ~0.8-2.0x, so this nominal
# width is a coarser reference than a fixed-dimension object would be.
BARCODE_WIDTH_MM = 20.0
BARCODE_UNCERTAINTY = 0.15
EXIF_UNCERTAINTY = 0.20

# Plausibility bounds for label close-ups. When phone EXIF SubjectDistance is
# missing/garbage we must NOT extrapolate a pixel->mm scale from nonsense
# values — declining (manual review) is the honest outcome.
EXIF_MIN_PPM = 1.0
EXIF_MAX_PPM = 300.0

# 35 mm film sensor width (the dimension used by 35mm-equivalent focal length).
SENSOR_WIDTH_35MM = 36.0

# VLM box sanity gate (no OCR, ~ms): a box pointing at a logo / the whole label
# must be rejected before we trust its cap-height reading.
BOX_MAX_AREA_FRACTION = 0.15
BOX_MIN_AREA_FRACTION = 0.002
BOX_MIN_WIDTH_PX = 10
BOX_MIN_HEIGHT_PX = 10
BOX_ASPECT_MIN = 1.2
BOX_ASPECT_MAX = 12.0
BOX_MIN_GLYPHS = 3
BOX_MAX_HEIGHT_REL_STDDEV = 0.4

# A numeral stroke of [0.3, 10.0] x the legal requirement is the only range we
# will report; anything outside is a wrong box / wrong region, not a real font.
IMPLAUSIBLE_LOW_FACTOR = 0.3
IMPLAUSIBLE_HIGH_FACTOR = 10.0

_EXIF_EXIF_IFD = 0x8769
_EXIF_FOCAL_LEN = 0x9205        # rational, mm
_EXIF_SUBJECT_DISTANCE = 0x920A  # rational, metres
_EXIF_FOCAL_35MM = 0xA405       # short, 35 mm-equivalent focal length

ImageOrPath = Union[str, np.ndarray]


def _load_image(image: ImageOrPath) -> Optional[np.ndarray]:
    """Accept an already-loaded BGR array or a path. Avoids double disk reads."""
    if isinstance(image, np.ndarray):
        return image
    return cv2.imread(str(image))


def _ppm_from_focal(focal_35: float, distance_m: float, image_width: int) -> Optional[float]:
    """Pure pixels-per-mm from 35 mm-equivalent focal length + subject distance.

    Horizontal FOV from the 35 mm sensor width, then physical width at the
    subject plane = 2 * D * tan(FOV/2).
    """
    if not focal_35 or focal_35 <= 0 or not distance_m or distance_m <= 0:
        return None
    focal_35 = float(focal_35)
    dist_mm = float(distance_m) * 1000.0
    half_angle = np.arctan((SENSOR_WIDTH_35MM / 2.0) / focal_35)
    width_at_plane_mm = 2.0 * dist_mm * np.tan(half_angle)
    if width_at_plane_mm <= 0:
        return None
    ppm = image_width / width_at_plane_mm
    return float(ppm) if ppm > 0 else None


def _exif_calibration_with_reason(
    image_path: str,
) -> Tuple[Optional[Tuple[float, Dict]], Optional[str]]:
    """Pixels-per-mm from EXIF: horizontal FOV from 35 mm-equivalent focal
    length and physical subject distance.

    Returns ((ppm, info), None) on success or (None, reason) when unusable.
    """
    try:
        with Image.open(image_path) as pil:
            if pil is None:
                return None, "image_unreadable"
            exif = pil.getexif()
        if not exif:
            return None, "exif_tags_missing"

        sub_ifd = exif.get_ifd(_EXIF_EXIF_IFD) or {}

        f35 = sub_ifd.get(_EXIF_FOCAL_35MM) or exif.get(_EXIF_FOCAL_35MM)
        if not f35:
            f35 = sub_ifd.get(_EXIF_FOCAL_LEN) or exif.get(_EXIF_FOCAL_LEN)
        if not f35:
            return None, "exif_focal_length_missing"

        dist_m = sub_ifd.get(_EXIF_SUBJECT_DISTANCE) or exif.get(_EXIF_SUBJECT_DISTANCE)
        if not dist_m or float(dist_m) <= 0:
            return None, "exif_subject_distance_missing"

        f35 = float(f35)

        img = cv2.imread(image_path)
        if img is None:
            return None, "image_unreadable"
        h, w = img.shape[:2]
        ppm = _ppm_from_focal(f35, float(dist_m), w)
        if ppm is None or not (EXIF_MIN_PPM <= ppm <= EXIF_MAX_PPM):
            logger.warning(
                f"EXIF calibration implausible (ppm={ppm}) — declining estimate "
                f"for {image_path}"
            )
            return None, f"exif_implausible(ppm={None if ppm is None else round(ppm, 2)})"
        info = {
            "focal_35mm_equiv": round(f35, 2),
            "subject_distance_m": round(float(dist_m), 2),
            "horizontal_fov_deg": round(
                float(np.degrees(2.0 * np.arctan((SENSOR_WIDTH_35MM / 2.0) / f35))), 2
            ),
        }
        return (ppm, info), None
    except Exception as e:
        logger.error(f"EXIF calibration failed: {e}")
        return None, "exif_parse_error"


def _exif_calibration(image_path: str) -> Optional[Tuple[float, Dict]]:
    """Backwards-compatible wrapper around _exif_calibration_with_reason."""
    result, _reason = _exif_calibration_with_reason(image_path)
    return result


class FontMeasurementService:
    def compute_ppm_from_barcode(
        self, image_path: str
    ) -> Optional[Tuple[float, Tuple[float, float, float, float]]]:
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            detector = cv2.barcode.BarcodeDetector()
            retval, _decoded, _dtype, points = detector.detectAndDecodeWithType(gray)
            if retval and len(points) > 0:
                pts = points[0].astype(np.float32)
                # A real 2D barcode/1D barcode detection yields >= 4 corner
                # points forming a convex quadrilateral; fewer/non-convex
                # detections are false positives we refused to scale from.
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
                    ppm = width_px / BARCODE_WIDTH_MM
                    return ppm, (x1, y1, x2, y2)
            return None
        except Exception as e:
            logger.error(f"Barcode detection failed: {e}")
            return None

    def calibrate(
        self, image_path: str
    ) -> Optional[Dict]:
        """Return a calibration dict with ppm + source + uncertainty factor."""
        barcode = self.compute_ppm_from_barcode(image_path)
        if barcode:
            ppm, bbox = barcode
            return {
                "calibration": "barcode",
                "ppm": float(ppm),
                "uncertainty_factor": BARCODE_UNCERTAINTY,
                "bbox": bbox,
            }

        exif = _exif_calibration(image_path)
        if exif:
            ppm, info = exif
            return {
                "calibration": "exif",
                "ppm": float(ppm),
                "uncertainty_factor": EXIF_UNCERTAINTY,
                "info": info,
            }

        return None

    def _calibration_rejected_reason(self, image_path: str) -> str:
        if not os.path.exists(image_path):
            return "image_unreadable"
        reasons = []
        if self.compute_ppm_from_barcode(image_path) is None:
            reasons.append("barcode_not_detected")
        _exif_result, exif_reason = _exif_calibration_with_reason(image_path)
        if _exif_result is None:
            reasons.append(exif_reason or "exif_unavailable")
        return "; ".join(dict.fromkeys(reasons)) or "calibration_failed"

    def _normalize_box(
        self,
        box: List[float],
        img_w: int,
        img_h: int,
        box_format: str = "normalized",
    ) -> Tuple[int, int, int, int]:
        """Accept box as [x1, y1, x2, y2].

        box_format:
          "normalized" -> 0-1000 (Qwen/VLM object-grounding convention)
          "px"         -> absolute pixels
        """
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

    def _glyph_heights_in_region(
        self, image: ImageOrPath, box: Tuple[int, int, int, int]
    ) -> Optional[List[int]]:
        """Capital/digit stroke heights inside a cropped text region."""
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
            _, binary = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )
            # Light open drops specks; no close so separate glyphs stay separate.
            # A fixed (2,2) kernel erodes ~1px-receiving strokes and SHATTERS
            # small glyphs (a 10px digit becomes fragments), so we only open
            # regions big enough that a 1px erosion is harmless.
            if region_h >= 40:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

            n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary)
            heights = []
            for i in range(1, n):
                area = stats[i, cv2.CC_STAT_AREA]
                h = stats[i, cv2.CC_STAT_HEIGHT]
                wid = stats[i, cv2.CC_STAT_WIDTH]
                # glyph-like strokes within the region's vertical band
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
    def _box_geometry_ok(
        box: Tuple[int, int, int, int], img_w: int, img_h: int
    ) -> Tuple[bool, Optional[str]]:
        """Size / area / aspect sanity for a VLM text box (no glyphs needed)."""
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
    def _box_is_plausible(
        box: Tuple[int, int, int, int], img_w: int, img_h: int, heights_px: List[int]
    ) -> Tuple[bool, Optional[str]]:
        """Geometric + glyph-cluster sanity check for a VLM text box.

        Returns (ok, reason). A logo / whole-label / multi-line-region box is
        rejected without another model call or any OCR dependency."""
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
        """Height of the dominant capital/digit stroke cluster.

        Bins are sized relative to the median stroke height (about 10%) instead
        of a fixed 2 px, so the estimate stays accurate at low resolutions
        where 1 mm may be only ~5 px tall."""
        if not heights:
            return 0
        bin_w = max(1, int(statistics.median(heights) // 10))
        bins: Dict[int, List[int]] = {}
        for h in heights:
            bins.setdefault((h // bin_w) * bin_w, []).append(h)
        majority = max(bins.values(), key=len)
        return int(round(statistics.median(majority)))

    def _text_component_heights(
        self,
        image: ImageOrPath,
        exclude_bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> Optional[List[int]]:
        """Heuristic fallback: median height of text components in the lower
        half of the image, excluding the barcode region."""
        try:
            img = _load_image(image)
            if img is None:
                return None
            h, w = img.shape[:2]
            lower = img[int(h * 0.5):, :]
            off_y = int(h * 0.5)
            gray = cv2.cvtColor(lower, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )
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
        """Measure font height (mm) with an honest, traceable calibration.

        text_box: VLM-localized [x1, y1, x2, y2] of the declaration text, in
                  0-1000 normalized or absolute pixels. When provided and
                  plausible, the cap-height method is used.
        """
        cal = self.calibrate(image_path)
        if not cal:
            return self._cannot_measure(
                required_mm, self._calibration_rejected_reason(image_path)
            )

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
            heights_px = self._text_component_heights(
                image_path, exclude_bbox=cal.get("bbox")
            )
            if not heights_px:
                return self._cannot_measure(
                    required_mm, "no_text_components_found"
                )

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
            # The lower-half heuristic is unvalidated on our dataset and
            # consistently underestimates — informational value only.
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


_font_service = None


def get_font_measurement_service():
    global _font_service
    if _font_service is None:
        _font_service = FontMeasurementService()
    return _font_service