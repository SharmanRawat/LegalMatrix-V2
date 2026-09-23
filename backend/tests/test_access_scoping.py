"""Tests for per-user access scoping of stored inspections (multi-user isolation).

An INSPECTOR must only see / open / export / override scans they created;
an ADMIN sees everything; anonymous (no-login demo) reads keep working.
"""
import pytest


def _upload(client, path, headers):
    with open(path, "rb") as f:
        return client.post(
            "/api/inspect",
            files={"images": ("label.jpg", f, "image/jpeg")},
            headers=headers,
        )


def _make_inspector(client, auth_headers, username="insp-scope", password="1234"):
    """Create an INSPECTOR user via the admin API and return its auth headers."""
    r = client.post(
        "/api/auth/users",
        json={"username": username, "name": "Scope Inspector", "role": "INSPECTOR", "password": password},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestHistoryIsolation:
    def test_inspector_history_excludes_admin_scans(self, client, sample_image, auth_headers):
        admin_scan = _upload(client, sample_image, auth_headers)
        assert admin_scan.status_code == 200
        admin_id = admin_scan.json()["inspection_id"]

        insp_headers = _make_inspector(client, auth_headers)

        # Inspector's history must NOT contain the admin's scan.
        mine = client.get("/api/inspect", headers=insp_headers)
        assert mine.status_code == 200
        assert mine.json() == []

        # Admin still sees it.
        all_rows = client.get("/api/inspect", headers=auth_headers)
        assert all_rows.status_code == 200
        assert any(r["inspection_id"] == admin_id for r in all_rows.json())

    def test_inspector_sees_only_own_scans_in_history(self, client, sample_image, auth_headers):
        _upload(client, sample_image, auth_headers)  # admin scan
        insp_headers = _make_inspector(client, auth_headers)
        own = _upload(client, sample_image, insp_headers)
        assert own.status_code == 200
        own_id = own.json()["inspection_id"]

        mine = client.get("/api/inspect", headers=insp_headers).json()
        assert [r["inspection_id"] for r in mine] == [own_id]

        # Admin sees both.
        all_rows = client.get("/api/inspect", headers=auth_headers).json()
        assert len(all_rows) == 2


class TestDetailIsolation:
    def test_inspector_cannot_open_admin_scan(self, client, sample_image, auth_headers):
        admin_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        insp_headers = _make_inspector(client, auth_headers)

        r = client.get(f"/api/inspect/{admin_id}", headers=insp_headers)
        assert r.status_code == 403

    def test_inspector_can_open_own_scan(self, client, sample_image, auth_headers):
        insp_headers = _make_inspector(client, auth_headers)
        own_id = _upload(client, sample_image, insp_headers).json()["inspection_id"]

        r = client.get(f"/api/inspect/{own_id}", headers=insp_headers)
        assert r.status_code == 200

    def test_anonymous_demo_detail_keeps_working(self, client, sample_image, auth_headers):
        """No-login demo flow must still render the report after a run."""
        admin_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        r = client.get(f"/api/inspect/{admin_id}")  # no auth headers
        assert r.status_code == 200
        assert r.json()["inspection_id"] == admin_id

    def test_inspector_cannot_export_admin_scan(self, client, sample_image, auth_headers):
        admin_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        insp_headers = _make_inspector(client, auth_headers)

        r = client.get(f"/api/inspect/{admin_id}/export?format=json", headers=insp_headers)
        assert r.status_code == 403

    def test_inspector_cannot_override_admin_scan(self, client, sample_image, auth_headers):
        admin_id = _upload(client, sample_image, auth_headers).json()["inspection_id"]
        insp_headers = _make_inspector(client, auth_headers)

        r = client.patch(
            f"/api/inspect/{admin_id}",
            json={"overrides": {"product_name": "Hacked"}},
            headers=insp_headers,
        )
        assert r.status_code == 403

        # ...but overriding their own scan is fine.
        own_id = _upload(client, sample_image, insp_headers).json()["inspection_id"]
        r = client.patch(
            f"/api/inspect/{own_id}",
            json={"overrides": {"product_name": "Corrected"}},
            headers=insp_headers,
        )
        assert r.status_code == 200
        assert r.json()["declarations"]["product_name"] == "Corrected"


class TestSearchIsolation:
    def test_inspector_search_is_own_user_scoped(self, client, sample_image, auth_headers):
        _upload(client, sample_image, auth_headers)  # admin scan
        insp_headers = _make_inspector(client, auth_headers)
        own_id = _upload(client, sample_image, insp_headers).json()["inspection_id"]

        mine = client.get("/api/search", headers=insp_headers).json()
        assert mine["total"] == 1
        assert [r["inspection_id"] for r in mine["results"]] == [own_id]

        # Admin search sees everything.
        all_rows = client.get("/api/search", headers=auth_headers).json()
        assert all_rows["total"] == 2


class TestDashboardIsolation:
    def test_inspector_dashboard_excludes_admin_scans(self, client, sample_image, auth_headers):
        _upload(client, sample_image, auth_headers)  # admin scan
        insp_headers = _make_inspector(client, auth_headers)
        own_id = _upload(client, sample_image, insp_headers).json()["inspection_id"]

        mine = client.get("/api/dashboard/stats", headers=insp_headers).json()
        assert mine["total_inspections"] == 1
        assert [r["id"] for r in mine["recent"]] == [own_id]

        all_stats = client.get("/api/dashboard/stats", headers=auth_headers).json()
        assert all_stats["total_inspections"] == 2