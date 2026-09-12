"""Tests for repositories (persistence layer)."""
import os
import tempfile

import pytest

from app.repositories import inspections, users
from app.services import inspection_service
from app.services.auth_service import create_token, verify_token


@pytest.fixture()
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


def _sample_inspection(**overrides):
    data = {
        "id": "LGM-TEST-0001",
        "product_name": "Sample Product",
        "manufacturer": "Sample Mfg",
        "status": "COMPLIANT",
        "compliance_score": 100.0,
        "passed_count": 7,
        "total_rules": 7,
        "declarations": {"mrp": "MRP Rs. 50/-", "net_quantity": "50 g"},
        "missing_declarations": [],
        "violations": [],
        "evidence_hash": "deadbeef",
        "images_count": 1,
        "model": "fake",
        "user_id": None,
    }
    data.update(overrides)
    return data


class TestUsersRepo:
    def test_create_and_get(self, tmp_db):
        users.create_user("alice", "Alice", "INSPECTOR", "pw123", db_path=tmp_db)
        u = users.get_user_by_username("alice", db_path=tmp_db)
        assert u["role"] == "INSPECTOR"
        assert users.verify_password("pw123", u["password_hash"], u["salt"])
        assert not users.verify_password("wrong", u["password_hash"], u["salt"])

    def test_duplicate_username(self, tmp_db):
        users.create_user("bob", "Bob", "VIEWER", "pw", db_path=tmp_db)
        with pytest.raises(Exception):
            users.create_user("bob", "Bob2", "ADMIN", "pw", db_path=tmp_db)

    def test_invalid_role_rejected(self, tmp_db):
        with pytest.raises(ValueError):
            users.create_user("x", "X", "SUPERUSER", "pw", db_path=tmp_db)


class TestInspectionsRepo:
    def test_save_get_roundtrip(self, tmp_db):
        inspections.save_inspection(
            _sample_inspection(), db_path=tmp_db
        )
        got = inspections.get_inspection("LGM-TEST-0001", db_path=tmp_db)
        assert got["product_name"] == "Sample Product"
        assert got["declarations"]["mrp"] == "MRP Rs. 50/-"
        assert got["missing_declarations"] == []
        assert got["violations"] == []

    def test_save_get_missing_json_roundtrip(self, tmp_db):
        inspections.save_inspection(
            _sample_inspection(
                status="POTENTIAL_VIOLATION",
                missing_declarations=["mrp"],
                violations=[{"rule_id": "mrp", "severity": "CRITICAL"}],
            ),
            db_path=tmp_db,
        )
        got = inspections.get_inspection("LGM-TEST-0001", db_path=tmp_db)
        assert got["status"] == "POTENTIAL_VIOLATION"
        assert got["missing_declarations"] == ["mrp"]
        assert got["violations"][0]["severity"] == "CRITICAL"

    def test_add_images(self, tmp_db):
        inspections.save_inspection(_sample_inspection(), db_path=tmp_db)
        inspections.add_inspection_image(
            "LGM-TEST-0001", "a.jpg", "front.jpg", "h1", 0, db_path=tmp_db
        )
        inspections.add_inspection_image(
            "LGM-TEST-0001", "b.jpg", "back.jpg", "h2", 1, db_path=tmp_db
        )
        got = inspections.get_inspection("LGM-TEST-0001", db_path=tmp_db)
        assert len(got["images"]) == 2
        assert got["images"][1]["original_name"] == "back.jpg"

    def test_search(self, tmp_db):
        inspections.save_inspection(_sample_inspection(id="LGM-TEST-0001"), db_path=tmp_db)
        inspections.save_inspection(
            _sample_inspection(id="LGM-TEST-0002", status="REVIEW_REQUIRED", missing_declarations=["usp"]),
            db_path=tmp_db,
        )
        r = inspections.search_inspections(q="Sample", db_path=tmp_db)
        assert r["total"] == 2
        r = inspections.search_inspections(status="COMPLIANT", db_path=tmp_db)
        assert r["total"] == 1
        r = inspections.search_inspections(q="does-not-exist", db_path=tmp_db)
        assert r["total"] == 0

    def test_dashboard_stats(self, tmp_db):
        inspections.save_inspection(
            _sample_inspection(id="LGM-TEST-0003", violations=[{"rule_id": "mrp", "severity": "CRITICAL"}]),
            db_path=tmp_db,
        )
        inspections.save_inspection(_sample_inspection(id="LGM-TEST-0004"), db_path=tmp_db)
        stats = inspections.dashboard_stats(db_path=tmp_db)
        assert stats["total_inspections"] == 2
        assert stats["by_status"]["COMPLIANT"] >= 1
        assert stats["field_violations"]["mrp"]["count"] == 1


class TestInspectionServiceHelpers:
    def test_merge_extractions_prefers_longer(self):
        merged = inspection_service.merge_extractions([
            {"mrp": "Rs. 10", "product_name": "A"},
            {"mrp": "MRP Rs. 100/-", "usp": "x"},
        ])
        assert merged["mrp"] == "MRP Rs. 100/-"

    def test_merge_skips_empty(self):
        merged = inspection_service.merge_extractions([
            {"mrp": "", "usp": None, "product_name": "P"},
        ])
        assert "mrp" not in merged
        assert merged["product_name"] == "P"

    def test_compute_missing_maps_required_fields(self):
        decl = {
            "manufacturer": "M", "product_name": "P", "net_quantity": "1 kg",
            "manufacturing_date": "01/2026", "mrp": "MRP Rs.1", "consumer_care": "c@x",
            "dimensions": "", "edible": "no",
        }
        assert inspection_service.compute_missing(decl) == ["dimensions_where_relevant"]

    def test_dimensions_not_required_for_edible(self):
        decl = {
            "manufacturer": "M", "product_name": "P", "net_quantity": "1 kg",
            "manufacturing_date": "01/2026", "mrp": "MRP Rs.1", "consumer_care": "c@x",
            "dimensions": "", "edible": "yes",
        }
        assert inspection_service.compute_missing(decl) == []

    def test_dimensions_not_required_when_edibility_unknown(self):
        decl = {
            "manufacturer": "M", "product_name": "P", "net_quantity": "1 kg",
            "manufacturing_date": "01/2026", "mrp": "MRP Rs.1", "consumer_care": "c@x",
            "dimensions": "",
        }
        assert inspection_service.compute_missing(decl) == []

    def test_overall_status(self):
        assert inspection_service.compute_overall_status([]) == "COMPLIANT"
        assert inspection_service.compute_overall_status(["dimensions_where_relevant"]) == "REVIEW_REQUIRED"
        assert inspection_service.compute_overall_status(["mrp"]) == "POTENTIAL_VIOLATION"

    def test_parse_net_quantity(self):
        assert inspection_service._parse_net_quantity_g({"net_quantity": "200 g"}) == 200
        assert inspection_service._parse_net_quantity_g({"net_quantity": "1 kg"}) == 1000
        assert inspection_service._parse_net_quantity_g({"net_quantity": "500 ml"}) == 500
        assert inspection_service._parse_net_quantity_g({"net_quantity": "N/A"}) is None


class TestAuthTokens:
    def test_token_roundtrip_and_expiry(self):
        token = create_token(1, "admin", "ADMIN")
        payload = verify_token(token)
        assert payload["username"] == "admin"
        assert payload["role"] == "ADMIN"
        assert verify_token(token + "tampered") is None
        assert verify_token("not-a-token") is None