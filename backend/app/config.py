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

# CORS
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]