"""API tests for the inspection pipeline (OCR mocked)."""
import io


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