"""Tests for the three submission fixes:
1. rule_version is persisted with each scan and exported (JSON/CSV/PDF).
2. Admin-only DELETE /api/inspect/{id} removes a stored inspection.
3. (EXIF chain is covered in test_font_measurement.py.)
"""
import pytest


def _upload(client, path, headers):
    with open(path, "rb") as f:
        return client.post(
            "/api/inspect",
            files={"images": ("label.jpg", f, "image/jpeg")},
            headers=headers,
        )


def _make_inspector(client, auth_headers, username="insp-fix", password="1234"):
    r = client.post(
        "/api/auth/users",
        json={"username": username, "name": "Fix Inspector", "role": "INSPECTOR", "password": password},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestRuleVersionPersisted:
    def test_scan_meta_and_exports_carry_rule_version(self, client, sample_image, auth_headers):
        r = _upload(client, sample_image, auth_headers)
        assert r.status_code == 200
        inspection_id = r.json()["inspection_id"]
        # Stored row flattens meta_json to top level, so detail includes it.
        detail = client.get(f"/api/inspect/{inspection_id}", headers=auth_headers)
        assert detail.status_code == 200
        assert detail.json().get("rule_version"), "rule_version missing from stored scan"

        # JSON export carries it.
        exp = client.get(f"/api/inspect/{inspection_id}/export?format=json", headers=auth_headers)
        assert exp.status_code == 200
        assert exp.json()["inspection"]["rule_version"] == detail.json()["rule_version"]

        # CSV export carries it as its first data row.
        csv_resp = client.get(f"/api/inspect/{inspection_id}/export?format=csv", headers=auth_headers)
        assert csv_resp.status_code == 200
        text = csv_resp.text
        assert "rule_version" in text and detail.json()["rule_version"] in text

    def test_rule_version_survives_manual_override(self, client, sample_image, auth_headers):
        r = _upload(client, sample_image, auth_headers)
        inspection_id = r.json()["inspection_id"]
        patch = client.patch(
            f"/api/inspect/{inspection_id}",
            json={"overrides": {"product_name": "Corrected Name"}},
            headers=auth_headers,
        )
        assert patch.status_code == 200
        detail = client.get(f"/api/inspect/{inspection_id}", headers=auth_headers).json()
        assert detail["declarations"]["product_name"] == "Corrected Name"
        assert detail.get("rule_version"), "rule_version lost after manual override"


class TestAdminDeleteEndpoint:
    def test_admin_can_delete_own_scan(self, client, sample_image, auth_headers):
        r = _upload(client, sample_image, auth_headers)
        inspection_id = r.json()["inspection_id"]

        d = client.delete(f"/api/inspect/{inspection_id}", headers=auth_headers)
        assert d.status_code == 200
        assert d.json()["deleted"] is True

        # Gone from history and detail.
        assert client.get(f"/api/inspect/{inspection_id}", headers=auth_headers).status_code == 404
        rows = client.get("/api/inspect", headers=auth_headers).json()
        assert all(row["inspection_id"] != inspection_id for row in rows)

    def test_inspector_cannot_delete(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        insp_headers = _make_inspector(client, auth_headers)

        d = client.delete(f"/api/inspect/{inspection_id}", headers=insp_headers)
        assert d.status_code == 403
        # Scan still present.
        assert client.get(f"/api/inspect/{inspection_id}", headers=auth_headers).status_code == 200

    def test_anonymous_cannot_delete(self, client, sample_image, auth_headers):
        inspection_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        d = client.delete(f"/api/inspect/{inspection_id}")
        assert d.status_code == 401

    def test_delete_missing_returns_404(self, client, auth_headers):
        d = client.delete("/api/inspect/LGM-does-not-exist", headers=auth_headers)
        assert d.status_code == 404