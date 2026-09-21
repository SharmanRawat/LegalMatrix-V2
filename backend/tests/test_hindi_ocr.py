"""Unit tests for the Devanagari/Hindi OCR wiring (lang→model swap)."""
import onnxruntime

from app.config import (
    DEVA_REC_KEYS_PATH,
    DEVA_REC_MODEL_PATH,
    HINDI_LANGS,
    OCR_LANG,
)
from app.services.ocr_engine import SmartOCRService


class TestDevanagariConfig:
    def test_hindi_lang_mapping(self):
        for token in ("hi", "hindi", "devanagari"):
            assert token in HINDI_LANGS, token
        assert "en" not in HINDI_LANGS

    def test_devanagari_models_vendored(self):
        # Both model artifacts ship in the repo so OCR_LANG=hi works offline.
        assert DEVA_REC_MODEL_PATH.endswith("devanagari_PP-OCRv3_rec.onnx")
        assert DEVA_REC_KEYS_PATH.endswith("devanagari_dict.txt")

    def test_devanagari_dict_has_devanagari_script(self):
        with open(DEVA_REC_KEYS_PATH, encoding="utf-8") as fh:
            chars = [ln.rstrip("\r\n") for ln in fh]
        assert any("\u0900" <= c <= "\u097f" for c in chars)
        # PP-OCRv3 devanagari dict carries the 169-class output ordering.
        assert len(chars) >= 150

    def test_devanagari_rec_onnx_loads(self):
        sess = onnxruntime.InferenceSession(
            DEVA_REC_MODEL_PATH, providers=["CPUExecutionProvider"])
        inputs = [(i.name, i.shape) for i in sess.get_inputs()]
        outputs = [(o.name, o.shape) for o in sess.get_outputs()]
        assert inputs and inputs[0][0] == "x"  # rapidocr-v3 rec input convention
        assert outputs and outputs[0][1][-1] == 169  # devanagari class count


class TestDevanagariEngineSwap:
    def test_lang_hi_swaps_in_deva_recognizer(self, monkeypatch):
        """OCR_LANG=hi must swap the main recognizer for the Devanagari one."""
        import rapidocr_onnxruntime as ro
        from rapidocr_onnxruntime import ch_ppocr_v3_rec
        import app.services.ocr_engine as oe

        monkeypatch.setattr(oe, "OCR_LANG", "hi")

        class FakeRec:
            def __init__(self, cfg):
                self.cfg = cfg

        class FakeEngine:
            def __init__(self):
                self.text_recognizer = None

        monkeypatch.setattr(ro, "RapidOCR", FakeEngine)
        monkeypatch.setattr(
            ch_ppocr_v3_rec.text_recognize, "TextRecognizer", FakeRec)

        svc = SmartOCRService()
        assert svc.engine_name == "rapidocr-hi"
        assert isinstance(svc._engine.text_recognizer, FakeRec)
        assert svc._engine.text_recognizer.cfg["keys_path"] == DEVA_REC_KEYS_PATH
        assert svc._engine.text_recognizer.cfg["model_path"] == DEVA_REC_MODEL_PATH

    def test_lang_bilingual_keeps_ch_main_and_attaches_deva(self, monkeypatch):
        """OCR_LANG=bilingual keeps the ch (en) main engine and adds the
        devanagari recognizer as a second pass over the same det boxes."""
        import rapidocr_onnxruntime as ro
        from rapidocr_onnxruntime import ch_ppocr_v3_rec
        import app.services.ocr_engine as oe

        monkeypatch.setattr(oe, "OCR_LANG", "bilingual")

        class FakeRec:
            def __init__(self, cfg):
                self.cfg = cfg

        class FakeEngine:
            def __init__(self):
                self.text_recognizer = "ch-recognizer"

        monkeypatch.setattr(ro, "RapidOCR", FakeEngine)
        monkeypatch.setattr(
            ch_ppocr_v3_rec.text_recognize, "TextRecognizer", FakeRec)

        svc = SmartOCRService()
        assert svc.engine_name == "rapidocr-bilingual"
        assert svc._engine.text_recognizer == "ch-recognizer"  # main untouched
        assert isinstance(svc._second_recognizer, FakeRec)  # deva pass attached

    def test_default_lang_keeps_bare_constructor(self, monkeypatch):
        """OCR_LANG=en must construct RapidOCR() with no args (byte-identical)."""
        import rapidocr_onnxruntime as ro
        import app.services.ocr_engine as oe

        monkeypatch.setattr(oe, "OCR_LANG", "en")
        calls = {}

        class FakeEngine:
            def __init__(self, **kwargs):
                calls["kwargs"] = kwargs

        monkeypatch.setattr(ro, "RapidOCR", FakeEngine)

        svc = SmartOCRService()
        assert svc.engine_name == "rapidocr"
        assert calls["kwargs"] == {}


def test_env_default_lang_is_en():
    assert OCR_LANG == "en"