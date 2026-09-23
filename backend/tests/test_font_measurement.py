"""Font measurement tests — calibration gating, EXIF math, cap-height logic,
VLM box sanity gate, implausibility bounds, and synthetic ground-truth."""
import os

import cv2
import numpy as np
import pytest

from app.services.font_measurement import (
    FontMeasurementService,
    _ppm_from_focal,
)

DATASET_IMAGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "images", "image3_2.jpg",
)

TRUETYPE_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/Sarai-Regular.ttf",
]


def _find_truetype():
    for path in TRUETYPE_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class TestCalibration:
    def test_returns_none_without_barcode(self, tmp_path):
        plain = tmp_path / "plain.jpg"
        cv2.imwrite(str(plain), np.full((400, 400, 3), 255, dtype=np.uint8))
        svc = FontMeasurementService()
        assert svc.compute_ppm_from_barcode(str(plain)) is None
        res = svc.measure(str(plain), required_mm=1.0)
        assert res is not None
        assert res["status"] == "CANNOT_MEASURE"
        assert res["calibration"] == "none"
        assert res["calibration_rejected_reason"]

    def test_cannot_measure_reason_auditable(self, tmp_path):
        plain = tmp_path / "plain.jpg"
        cv2.imwrite(str(plain), np.full((400, 400, 3), 255, dtype=np.uint8))
        svc = FontMeasurementService()
        res = svc.measure(str(plain), required_mm=1.0)
        assert "barcode_not_detected" in res["calibration_rejected_reason"]
        assert "exif" in res["calibration_rejected_reason"]

    def test_missing_file_returns_cannot_measure(self, tmp_path):
        svc = FontMeasurementService()
        res = svc.measure(str(tmp_path / "nope.jpg"), required_mm=1.0)
        assert res["status"] == "CANNOT_MEASURE"
        assert "image_unreadable" in res["calibration_rejected_reason"]

    def test_calibrate_none_on_uncalibratable(self, tmp_path):
        plain = tmp_path / "plain.jpg"
        cv2.imwrite(str(plain), np.full((400, 400, 3), 255, dtype=np.uint8))
        svc = FontMeasurementService()
        assert svc.calibrate(str(plain)) is None


class TestExifCalibrationChain:
    """EXIF (focal length + subject distance) is the third rung of the
    calibration chain: no card, no barcode, but a phone camera EXIF block
    present → calibrate resolves to exif, and measure never auto-verdicts."""

    def _exif_image(self, tmp_path, width=4032, height=3024):
        from PIL import Image
        img = np.full((height, width, 3), 255, dtype=np.uint8)
        exif = Image.Exif()
        exif[0xA405] = 26          # FocalLengthIn35mmFilm = 26 mm
        exif[0x920A] = (3, 10)     # SubjectDistance = 0.3 m
        exif[0x9003] = "2026:09:23 10:00:00"
        path = str(tmp_path / "exif.jpg")
        Image.fromarray(img).save(path, exif=exif.tobytes())
        return path

    def test_calibrate_resolves_exif(self, tmp_path):
        path = self._exif_image(tmp_path)
        cal = FontMeasurementService().calibrate(path)
        assert cal is not None
        assert cal["calibration"] == "exif"
        assert cal["ppm"] > 1
        assert cal["uncertainty_factor"] == 0.20
        assert cal["info"]["focal_35mm_equiv"] == 26.0

    def test_measure_never_auto_verdicts_on_exif(self, tmp_path):
        path = self._exif_image(tmp_path)
        svc = FontMeasurementService()
        # Provide explicit text components via token path so cap-height runs.
        res = svc.measure_from_tokens(
            path,
            tokens=[{"text": "MRP Rs. 100", "box": [400, 100, 1000, 160]}],
            required_mm=1.0,
        )
        assert res is not None
        assert res["status"] == "REVIEW_REQUIRED"  # informational only
        assert res["calibration"] == "exif"


class TestExifMath:
    def test_ppm_physical_scale(self):
        # 50mm focal, 300mm distance, 4032px wide on a 35mm-equivalent sensor:
        # FOV ~39.6deg -> width at plane ~216mm -> ~18.6 px/mm
        ppm = _ppm_from_focal(50.0, 0.3, 4032)
        assert ppm is not None
        assert 10 < ppm < 25

    def test_ppm_inversely_scales_with_distance(self):
        near = _ppm_from_focal(50.0, 0.3, 4032)
        far = _ppm_from_focal(50.0, 0.6, 4032)
        assert near is not None and far is not None
        assert near > far
        assert abs(near / far - 2.0) < 1e-6

    def test_ppm_rejects_bad_inputs(self):
        assert _ppm_from_focal(0.0, 0.3, 4032) is None
        assert _ppm_from_focal(50.0, 0.0, 4032) is None
        assert _ppm_from_focal(-5.0, 0.3, 4032) is None


class TestCapHeight:
    def _glyph_image(self, tmp_path, cap_h=50, desc_h=80):
        """White canvas with cap bars and taller descender bars sharing the
        same top edge — descenders must not inflate the cap-height estimate."""
        img = np.full((200, 600, 3), 255, dtype=np.uint8)
        y0 = 50
        for i, x in enumerate([20, 90, 160, 230]):
            img[y0:y0 + cap_h, x:x + 20] = 0
        for i, x in enumerate([300, 370]):
            img[y0:y0 + desc_h, x:x + 20] = 0
        path = str(tmp_path / "glyphs.jpg")
        cv2.imwrite(path, img)
        return path, cap_h

    def test_glyph_heights_found(self, tmp_path):
        path, cap_h = self._glyph_image(tmp_path)
        svc = FontMeasurementService()
        heights = svc._glyph_heights_in_region(path, (10, 40, 500, 180))
        assert heights is not None
        assert cap_h in heights and 80 in heights

    def test_cap_height_ignores_descenders(self, tmp_path):
        path, cap_h = self._glyph_image(tmp_path)
        svc = FontMeasurementService()
        heights = svc._glyph_heights_in_region(path, (10, 40, 500, 180))
        assert svc.cap_height_px(heights) == cap_h

    def test_cap_height_majority_vote(self):
        svc = FontMeasurementService()
        assert svc.cap_height_px([50, 50, 50, 50, 48, 80, 80]) == 50

    def test_cap_height_relative_bin_at_low_resolution(self):
        svc = FontMeasurementService()
        # A 5px digit cluster must stay dominant (2px fixed bins used to blur it).
        assert svc.cap_height_px([5, 5, 5, 5, 3, 9, 9, 9]) == 5

    def test_measure_still_gates_without_calibration(self, tmp_path):
        path, _ = self._glyph_image(tmp_path)
        svc = FontMeasurementService()
        res = svc.measure(path, required_mm=1.0, text_box=[100, 100, 500, 500])
        assert res is not None
        assert res["status"] == "CANNOT_MEASURE"


class TestTextBoxNormalization:
    def _img(self, tmp_path):
        img = np.full((400, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (200, 150), (400, 250), (0, 0, 0), -1)
        path = str(tmp_path / "region.jpg")
        cv2.imwrite(path, img)
        return path

    def test_normalized_0_to_1000(self, tmp_path):
        svc = FontMeasurementService()
        # [250,375,500,625]/1000 on 800x400 -> px (200,150,400,250), padded 5%
        box = svc._normalize_box([250.0, 375.0, 500.0, 625.0], 800, 400)
        assert box == (190, 140, 410, 260)

    def test_absolute_pixels(self, tmp_path):
        svc = FontMeasurementService()
        box = svc._normalize_box([200.0, 150.0, 400.0, 250.0], 800, 400, box_format="px")
        assert box == (190, 140, 410, 260)  # padded by 5% of box width


class TestBoxPlausibility:
    def _svc(self):
        return FontMeasurementService()

    def test_accepts_clean_digit_cluster(self):
        ok, reason = self._svc()._box_is_plausible(
            (100, 100, 240, 150), 800, 600, [40, 40, 40, 40, 42]
        )
        assert ok is True and reason is None

    def test_rejects_whole_label_box(self):
        ok, reason = self._svc()._box_is_plausible(
            (10, 10, 300, 200), 400, 250, [40, 40, 40, 40]
        )
        assert ok is False and reason == "area_too_large"

    def test_rejects_tiny_box(self):
        ok, reason = self._svc()._box_is_plausible(
            (5, 5, 15, 12), 800, 600, [6, 6]
        )
        assert ok is False and reason in ("too_small", "too_few_glyphs")

    def test_rejects_multimodal_heights(self):
        ok, reason = self._svc()._box_is_plausible(
            (100, 100, 240, 150), 800, 600, [30, 30, 26, 15, 15, 50, 50]
        )
        assert ok is False and reason == "multimodal_heights"

    def test_rejects_too_few_glyphs(self):
        ok, reason = self._svc()._box_is_plausible(
            (100, 100, 240, 150), 800, 600, [40, 40]
        )
        assert ok is False and reason == "too_few_glyphs"


class TestGatingAndVerdicts:
    def _bars_image(self, tmp_path, cap_h=100, lower=False):
        """Four solid numeral bars on 400x800; bars span y=(y0)..(y0+cap_h)."""
        img = np.full((400, 800, 3), 255, dtype=np.uint8)
        y0 = 250 if lower else 100
        for x in [40, 110, 180, 250]:
            img[y0:y0 + cap_h, x:x + 25] = 0
        path = str(tmp_path / "bars.png")
        cv2.imwrite(path, img)
        return str(path)

    def _fake_barcode_cal(self, ppm=100.0):
        return {"calibration": "barcode", "ppm": ppm, "uncertainty_factor": 0.15}

    def _monkey_calibrate(self, monkeypatch, ppm=100.0):
        svc = FontMeasurementService()
        monkeypatch.setattr(svc, "calibrate", lambda p: self._fake_barcode_cal(ppm))
        return svc

    def test_cap_height_compliant_when_above_requirement(self, tmp_path, monkeypatch):
        svc = self._monkey_calibrate(monkeypatch)
        path = self._bars_image(tmp_path, cap_h=100)  # 1.0mm at 100 ppm
        # tight box around the bars, normalized 0-1000
        text_box = [43.75, 225.0, 356.25, 537.5]
        res = svc.measure(path, required_mm=0.8, text_box=text_box)
        assert res["method"] == "cap_height"
        assert res["measured_mm"] == 1.0
        assert res["status"] == "COMPLIANT"
        assert "implausible" not in res

    def test_implausible_low_reading_forced_review(self, tmp_path, monkeypatch):
        svc = self._monkey_calibrate(monkeypatch)
        path = self._bars_image(tmp_path, cap_h=8)  # ~0.08mm at 100 ppm
        text_box = [43.75, 230.0, 356.25, 290.0]
        res = svc.measure(path, required_mm=1.0, text_box=text_box)
        assert res["status"] == "REVIEW_REQUIRED"
        assert res.get("implausible") is True

    def test_heuristic_never_returns_automated_verdict(self, tmp_path, monkeypatch):
        svc = self._monkey_calibrate(monkeypatch)
        path = self._bars_image(tmp_path, cap_h=100, lower=True)  # 1.0mm, below 2.0mm req
        res = svc.measure(path, required_mm=2.0)
        assert res["method"] == "heuristic_lower_half"
        # bands would say POTENTIAL_VIOLATION (1.15 < 2.0) — but the heuristic
        # is unvalidated, so it must be forced to REVIEW_REQUIRED.
        assert res["status"] == "REVIEW_REQUIRED"
        assert res["measured_mm"] == 1.0

    def test_rejected_box_records_reason(self, tmp_path, monkeypatch):
        svc = self._monkey_calibrate(monkeypatch)
        path = self._bars_image(tmp_path, cap_h=100, lower=True)
        # box covering the whole upper-left = area_too_large -> rejected
        res = svc.measure(path, required_mm=1.0, text_box=[0.0, 0.0, 500.0, 400.0])
        assert res["method"] == "heuristic_lower_half"
        assert res["box_rejected_reason"] == "area_too_large"


class TestSyntheticGroundTruth:
    @pytest.fixture(autouse=True)
    def _font(self):
        if _find_truetype() is None:
            pytest.skip("no truetype font available for synthetic GT render")
        yield

    def _render(self, tmp_path, font_size, text="0123456789"):
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(_find_truetype(), font_size)
        x0, y0, x1, y1 = font.getbbox(text)
        ink_h = y1 - y0
        w = (x1 - x0) + font_size
        h = ink_h + font_size
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((font_size // 2 - x0, font_size // 2 - y0), text, font=font, fill=(0, 0, 0))
        path = tmp_path / "synth.png"
        img.save(path)
        return str(path), ink_h

    @pytest.mark.parametrize("font_size", [14, 24, 36])
    def test_recovers_known_digit_cap_height(self, tmp_path, font_size):
        svc = FontMeasurementService()
        path, gt_ink_h = self._render(tmp_path, font_size)
        img = cv2.imread(path)
        h, w = img.shape[:2]
        heights = svc._glyph_heights_in_region(img, (0, 0, w, h))
        assert heights is not None
        cap = svc.cap_height_px(heights)
        assert abs(cap - gt_ink_h) <= 2, f"cap={cap} gt={gt_ink_h}"


@ pytest.mark.skipif(
    not os.path.exists(DATASET_IMAGE), reason="real label image not in repo"
)
class TestRealLabelMeasurement:
    def test_barcode_calibration_found(self):
        svc = FontMeasurementService()
        ppm, bbox = svc.compute_ppm_from_barcode(DATASET_IMAGE)
        assert ppm is not None and ppm > 0
        assert bbox[0] < bbox[2] and bbox[1] < bbox[3]

    def test_measure_returns_sane_results(self):
        svc = FontMeasurementService()
        result = svc.measure(DATASET_IMAGE, required_mm=1.0)
        assert result is not None
        assert result["calibration"] in ("barcode", "exif")
        assert result["status"] == "REVIEW_REQUIRED"  # heuristic -> informational
        assert 0 < result["measured_mm"] < 500
        assert result["uncertainty"] > 0
        assert result["required_mm"] == 1.0