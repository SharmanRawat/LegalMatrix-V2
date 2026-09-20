"""API tests for the inspection pipeline (OCR mocked)."""
import io

from app.services.inspection_service import (
    _extraction_confidence,
    _field_evidence,
)


def _upload(client, path, headers):
    with open(path, "rb") as f:
        return client.post(
            "/api/inspect",
            files={"images": ("label.jpg", f, "image/jpeg")},
            headers=headers,
        )


class TestInspectEndpoint:
    def test_inspect_returns_full_schema(self, client, sample_image, auth_headers):
        r = _upload(client, sample_image, auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("COMPLIANT", "REVIEW_REQUIRED", "POTENTIAL_VIOLATION", "ERROR")
        assert data["inspection_id"].startswith("LGM-")
        assert data["images_processed"] == 1
        for key in ["mrp", "usp", "net_quantity", "product_name", "manufacturer",
                    "manufacturing_date", "expiry_date", "consumer_care", "dimensions"]:
            assert key in data["declarations"]
        assert "evidence" in data and data["evidence"]["hash"]
        assert "misleading_checks" in data
        assert isinstance(data["violations"], list)
        assert isinstance(data["compliance_score"], (int, float))
        # auditability contract: per-field evidence + extraction confidence
        assert "field_evidence" in data
        assert "extraction_confidence" in data
        conf = data["extraction_confidence"]
        assert isinstance(conf["overall"], (int, float)) and 0 <= conf["overall"] <= 100
        assert set(["overall", "coverage_ratio", "fields_present", "fields_required", "by_field"]) <= set(conf.keys())

    def test_inspect_persists_for_history(self, client, sample_image, auth_headers):
        r = _upload(client, sample_image, auth_headers)
        inspection_id = r.json()["inspection_id"]

        # Evidence file should be on disk
        assert r.json()["evidence"]["images"]

        # Retrievable by id
        got = client.get(f"/api/inspect/{inspection_id}", headers=auth_headers)
        assert got.status_code == 200
        assert got.json()["inspection_id"] == inspection_id
        assert got.json()["declarations"]["mrp"]

    def test_inspect_works_without_auth_in_demo_mode(self, client, sample_image):
        r = _upload(client, sample_image, None)
        assert r.status_code == 200

    def test_max_three_images_payload(self, client, sample_image, auth_headers):
        files = [("images", ("l.jpg", io.BytesIO(b"x"), "image/jpeg"))] * 4
        r = client.post("/api/inspect", files=files, headers=auth_headers)
        assert r.status_code == 400


class TestReportEndpoint:
    def test_pdf_report_matches_expected_schema(self, client, sample_image, auth_headers):
        with open(sample_image, "rb") as f:
            r = client.post(
                "/api/inspect/report",
                files={"images": ("label.jpg", f, "image/jpeg")},
                headers=auth_headers,
            )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 500


class TestMaxImageLimits:
    pass


class TestCurrencySymbolRecovery:
    """Rule 6(1)(e): a bare MRP number (VLM dropped the ₹) must not be a
    violation when the image re-verification confirms the symbol is printed."""

    def test_bare_mrp_confirmed_symbol_passes(self, client, sample_image, auth_headers, monkeypatch):
        import app.services.inspection_service as svc

        class BareOcr:
            def extract_structured(self, image_path):
                return {
                    "mrp": "50.00", "usp": "Rs. 1.00 per g", "net_quantity": "50 g",
                    "product_name": "Test Commodity",
                    "manufacturer": "Test Manufacturer Pvt Ltd",
                    "manufacturing_date": "MFG: 01/2026", "expiry_date": "EXP: 01/2028",
                    "consumer_care": "care@test.com 1800-123", "dimensions": "",
                    "edible": "yes",
                }

            def verify_currency_symbol(self, image_path, value):
                return True

            def prompt_fingerprint(self):
                return "test-fingerprint"

        monkeypatch.setattr(svc, "_get_default_ocr", lambda: BareOcr())
        r = _upload(client, sample_image, auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["declarations"]["mrp"] == "50.00"
        assert not any(v["field"] == "mrp" for v in data["violations"])
        assert not any(c["check"] == "mrp_format" for c in data["misleading_checks"])
        assert data["status"] != "POTENTIAL_VIOLATION"

    def test_bare_mrp_unconfirmed_still_flagged(self, client, sample_image, auth_headers, monkeypatch):
        import app.services.inspection_service as svc

        class BareOcr:
            def extract_structured(self, image_path):
                return {
                    "mrp": "50.00", "usp": "", "net_quantity": "50 g",
                    "product_name": "Test Commodity",
                    "manufacturer": "Test Manufacturer Pvt Ltd",
                    "manufacturing_date": "MFG: 01/2026", "expiry_date": "EXP: 01/2028",
                    "consumer_care": "care@test.com 1800-123", "dimensions": "",
                    "edible": "yes",
                }

            def verify_currency_symbol(self, image_path, value):
                return False

            def prompt_fingerprint(self):
                return "test-fingerprint"

        monkeypatch.setattr(svc, "_get_default_ocr", lambda: BareOcr())
        r = _upload(client, sample_image, auth_headers)
        assert r.status_code == 200
        data = r.json()
        mrp_violations = [v for v in data["violations"] if v["field"] == "mrp"]
        assert mrp_violations and mrp_violations[0]["status"] == "FORMAT_ISSUE"


class TestExportEndpoint:
    def test_export_json(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.get(f"/api/inspect/{inspection_id}/export?format=json", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["inspection"]["inspection_id"] == inspection_id

    def test_export_csv(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.get(f"/api/inspect/{inspection_id}/export?format=csv", headers=auth_headers)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert b"field,value" in r.content

    def test_export_bad_format(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.get(f"/api/inspect/{inspection_id}/export?format=xlsx", headers=auth_headers)
        assert r.status_code == 400


class TestManualOverride:
    def test_override_corrects_value_and_keeps_original(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.patch(
            f"/api/inspect/{inspection_id}",
            json={"overrides": {"product_name": "Corrected Commodity Name"}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["declarations"]["product_name"] == "Corrected Commodity Name"
        assert data["product_name"] == "Corrected Commodity Name"
        assert data["manual_overrides"]["product_name"]["original"] == "Test Commodity"
        assert data["manual_overrides"]["product_name"]["corrected"] == "Corrected Commodity Name"

    def test_override_reevaluates_rules(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        # Clearing a CRITICAL declaration must flip status to POTENTIAL_VIOLATION.
        r = client.patch(
            f"/api/inspect/{inspection_id}",
            json={"overrides": {"mrp": ""}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "POTENTIAL_VIOLATION"
        assert "mrp" in data["missing_declarations"]
        assert any(v["field"] == "mrp" and v["status"] == "MISSING" for v in data["violations"])

    def test_override_rejects_unknown_field(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.patch(
            f"/api/inspect/{inspection_id}",
            json={"overrides": {"bogus_field": "x"}},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_override_requires_role(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.patch(
            f"/api/inspect/{inspection_id}",
            json={"overrides": {"mrp": ""}},
        )
        assert r.status_code == 401


class TestEvidenceEndpoint:
    def test_evidence_image_served(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.get(f"/api/inspect/{inspection_id}/evidence/0", headers=auth_headers)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        assert len(r.content) > 0

    def test_evidence_requires_auth(self, client, sample_image):
        inspection_id = _upload(client, sample_image, None).json()["inspection_id"]
        assert client.get(f"/api/inspect/{inspection_id}/evidence/0").status_code == 401

    def test_evidence_bad_index(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        assert client.get(f"/api/inspect/{inspection_id}/evidence/99", headers=auth_headers).status_code == 404


class TestEvidenceAndConfidence:
    """The frugal cascade surfaces *why* each value was accepted: which OCR text
    backed it, from which engine — plus a 0-100 extraction-confidence score."""

    @staticmethod
    def _fake_result(index=0):
        return {
            "mrp": "MRP Rs. 50.00/", "usp": "USP Rs. 1.00/g", "net_quantity": "25 g",
            "product_name": "Test Commodity", "manufacturer": "Acme Pvt Ltd",
            "manufacturing_date": "MFG: 01/2026", "expiry_date": "EXP: 01/2028",
            "consumer_care": "care@acme.com", "dimensions": "", "edible": "yes",
            "tokens": [{"text": "MRP", "box": [0, 0, 5, 5], "conf": 0.8}],
            "field_map": {"mrp": [{"text": "MRP Rs. 50.00/", "box": [0, 0, 5, 5], "conf": 0.8}]},
            "ocr_meta": {"engine": "mock", "classifier": "regex", "confidence": 0.9},
        }

    def test_field_evidence_traces_ocr_text_and_source(self):
        merged = {k: "" for k in ("mrp", "usp", "net_quantity", "product_name",
                                  "manufacturer", "manufacturing_date", "expiry_date",
                                  "consumer_care", "dimensions", "edible")}
        merged["mrp"] = "MRP Rs. 50.00/"
        ev = _field_evidence([self._fake_result()], merged)
        assert ev["mrp"]["source"] == "regex"
        assert ev["mrp"]["text"] == "MRP Rs. 50.00/"
        assert ev["mrp"]["image_index"] == 0
        # absent fields yield empty evidence (callers render "Not detected")
        assert ev["dimensions"]["text"] == ""

    def test_confidence_punishes_low_coverage(self):
        merged = {k: "" for k in ("mrp", "usp", "net_quantity", "product_name",
                                  "manufacturer", "manufacturing_date", "expiry_date",
                                  "consumer_care", "dimensions", "edible")}
        merged["product_name"] = "Test Commodity"
        merged["edible"] = "yes"
        low = _extraction_confidence([self._fake_result()], merged, ["mrp", "net_quantity", "manufacturing_date"])
        assert low["overall"] < 50
        assert low["coverage_ratio"] < 1.0
        assert low["by_field"]["mrp"] == 0.0
        assert low["fields_present"] < low["fields_required"]

    def test_confidence_high_when_all_required_found(self):
        merged = {k: str(v) if str(v) else "" for k, v in self._fake_result().items()
                  if isinstance(v, str)}
        merged["dimensions"] = ""
        high = _extraction_confidence([self._fake_result()], {"dimensions": "", **merged},
                                      [])
        assert high["coverage_ratio"] == 1.0
        assert high["overall"] >= 60


class TestSearchAndDashboard:
    def test_search_finds_persisted_scan(self, client, sample_image, auth_headers):
        _upload(client, sample_image, auth_headers)
        r = client.get("/api/search?q=Test", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_dashboard_stats(self, client, sample_image, auth_headers):
        _upload(client, sample_image, auth_headers)
        r = client.get("/api/dashboard/stats", headers=auth_headers)
        assert r.status_code == 200
        stats = r.json()
        assert stats["total_inspections"] >= 1
        assert "by_status" in stats and "daily_trend" in stats and "recent" in stats

    def test_unauthorized_dashboard(self, client):
        assert client.get("/api/dashboard/stats").status_code == 401