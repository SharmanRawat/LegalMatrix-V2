import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

ENV = os.getenv("ENV", "development")


def get_data_dir() -> Path:
    """Resolve at call-time so tests can point each invocation at a fresh dir."""
    return Path(os.getenv("LEGALMATRIX_DATA_DIR", BASE_DIR / "data"))


def get_database_path() -> Path:
    return get_data_dir() / "legalmatrix.db"


def get_evidence_dir() -> Path:
    path = get_data_dir() / "evidence"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Backwards-compatible aliases (still resolve the configured values)
DATA_DIR = get_data_dir()
DATABASE_PATH = get_database_path()
EVIDENCE_DIR = get_data_dir() / "evidence"
os.makedirs(EVIDENCE_DIR, exist_ok=True)

# Auth
AUTH_TOKEN_SECRET = os.getenv("LEGALMATRIX_AUTH_SECRET", "change-me-in-production-legalmatrix")
AUTH_TOKEN_TTL_HOURS = int(os.getenv("LEGALMATRIX_AUTH_TTL_HOURS", "12"))

# Ollama
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
QWN_MODEL = os.getenv("QWN_MODEL", "qwen2.5vl:7b")
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "180"))

# New fast pipeline (OCR + lightweight LLM classifier)
# OCR engine: "auto" | "rapidocr" | "paddleocr" | "vlm"
OCR_ENGINE = os.getenv("OCR_ENGINE", "auto")
# Script for OCR recognition: "en" (default, bundled PP-OCRv3 ch+en) or
# "hi"/"hindi"/"devanagari" (swaps in the vendored Devanagari rec model —
# same PP-OCRv3 det/cls, rec-only change) or "bilingual"/"both"/"bi"
# (ch + Devanagari rec passes over the same boxes, for dual-script labels).
# Default path stays byte-identical.
OCR_LANG = os.getenv("OCR_LANG", "en")
HINDI_LANGS = {"hi", "hindi", "devanagari"}
BILINGUAL_LANGS = {"bilingual", "both", "bi"}
DEVA_REC_MODEL_PATH = os.getenv(
    "DEVA_REC_MODEL_PATH",
    str(BASE_DIR / "app" / "assets" / "models" / "devanagari_PP-OCRv3_rec.onnx"),
)
DEVA_REC_KEYS_PATH = os.getenv(
    "DEVA_REC_KEYS_PATH",
    str(BASE_DIR / "app" / "assets" / "models" / "devanagari_dict.txt"),
)
# Lightweight text-only classifier (already pulled locally, ~2GB Q4)
FIELD_CLASSIFIER_MODEL = os.getenv("FIELD_CLASSIFIER_MODEL", "qwen2.5:3b")
FIELD_CLASSIFIER_ENABLED = os.getenv("FIELD_CLASSIFIER_ENABLED", "1") == "1"
# Resource-adaptive cascade: when confidence is low AND enabled, the pipeline
# escalates hard images to a vision-language model rescue path.
# 0 = pure CPU (frugal/offline demo), 1 = VLM rescue enabled (needs GPU).
VLM_RESCUE_ENABLED = os.getenv("VLM_RESCUE_ENABLED", "0") == "1"
VLM_RESCUE_MODEL = os.getenv("VLM_RESCUE_MODEL", "qwen2.5vl:7b")
VLM_RESCUE_CONFIDENCE_THRESHOLD = float(os.getenv("VLM_RESCUE_CONFIDENCE_THRESHOLD", "55"))
OCR_ENHANCE_ENABLED = os.getenv("OCR_ENHANCE_ENABLED", "1") == "1"
OCR_ENHANCE_MAX_SIDE = int(os.getenv("OCR_ENHANCE_MAX_SIDE", "1920"))
# CPU-only multi-pass OCR escalation: on-demand extra preprocessing
# variants (grayscale / Otsu / inverted / CLAHE / 2x) whose detection boxes
# are fused back into the token stream. Triggers only when a critical
# statutory digit field (mrp / mfg / expiry) came back empty from the single
# pass. Pane-zoom (per-region 3x + binarize re-read) helps one in ~7
# products but is expensive, so it defaults off.
OCR_MULTI_PASS_ENABLED = os.getenv("OCR_MULTI_PASS_ENABLED", "1") == "1"
OCR_MULTI_PASS_ON_FAIL = os.getenv("OCR_MULTI_PASS_ON_FAIL", "1") == "1"
OCR_PANE_ZOOM_ENABLED = os.getenv("OCR_PANE_ZOOM_ENABLED", "0") == "1"
# Calibration: "auto" (credit-card -> barcode -> exif) | "credit_card" | "barcode" | "exif"
FONT_CALIBRATION = os.getenv("FONT_CALIBRATION", "auto")

# CORS
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]