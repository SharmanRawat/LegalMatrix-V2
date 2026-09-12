import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"


class FakeOCR:
    """Deterministic stand-in for the Qwen vision model."""

    def __init__(self, result=None):
        self.result = result or {
            "mrp": "MRP Rs. 100/-",
            "usp": "USP Rs. 0.50 per g",
            "net_quantity": "200 g",
            "product_name": "Test Commodity",
            "manufacturer": "Test Manufacturer Pvt Ltd",
            "manufacturing_date": "MFG: 01/2026",
            "expiry_date": "EXP: 01/2028",
            "consumer_care": "consumer.care@test.com 1800-123-456",
            "dimensions": "",
            "edible": "yes",
        }

    def extract_structured(self, image_path):
        return dict(self.result)


@pytest.fixture(scope="session")
def fake_ocr():
    return FakeOCR()


@pytest.fixture()
def monkey_ocr(monkeypatch, fake_ocr):
    import app.services.inspection_service as svc
    monkeypatch.setattr(svc, "_get_default_ocr", lambda: fake_ocr)
    return fake_ocr


@pytest.fixture()
def sample_image(tmp_path):
    from PIL import Image
    img_path = tmp_path / "label.jpg"
    Image.new("RGB", (400, 400), color=(255, 255, 255)).save(img_path, "JPEG")
    return str(img_path)


@pytest.fixture()
def client(monkey_ocr, tmp_path):
    """Each test gets an isolated app instance with its own data dir."""
    import app.config as config
    monkey_ocr
    os.environ["LEGALMATRIX_DATA_DIR"] = str(tmp_path / "data")
    # Force re-resolution of paths that config cached at import time.
    config.DATA_DIR = config.get_data_dir()
    config.DATABASE_PATH = config.get_database_path()
    config.EVIDENCE_DIR = config.get_evidence_dir()
    # Reset cached singletons that hold onto old paths.
    for mod in ("app.services.inspection_service", "app.database.models", "app.repositories.inspections"):
        pass

    from starlette.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin@123"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture()
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}