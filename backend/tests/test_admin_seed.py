"""Seeded-admin credentials: env-driven seed + startup password rotation.

Covered here:
- seeding uses the configured username/password (not a hardcoded default)
- an explicit LEGALMATRIX_ADMIN_PASSWORD rotates an existing admin account
- rotation is skipped when the variable is not explicitly set (idempotent boot)
- the insecure default AUTH_SECRET is detected for startup warning
"""
import os

from app.main import _seed_default_admin
from app.repositories import users as user_repo


def _db_path(tmp_path):
    return str(tmp_path / "cg" / "legalmatrix.db")


def test_seed_uses_configured_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGALMATRIX_ADMIN_USERNAME", "ops")
    monkeypatch.setenv("LEGALMATRIX_ADMIN_PASSWORD", "s3cret-ops-pw")
    _seed_default_admin(data_dir=tmp_path / "cg")
    user = user_repo.get_user_by_username("ops", db_path=_db_path(tmp_path))
    assert user is not None
    assert user_repo.verify_password("s3cret-ops-pw", user["password_hash"], user["salt"])
    # legacy default was NOT created
    assert user_repo.get_user_by_username("admin", db_path=_db_path(tmp_path)) is None


def test_rotation_updates_existing_admin_password(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGALMATRIX_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("LEGALMATRIX_ADMIN_PASSWORD", raising=False)
    # seed with the demo default first (a pre-existing account from an old boot)
    _seed_default_admin(data_dir=tmp_path / "cg")
    old = user_repo.get_user_by_username("admin", db_path=_db_path(tmp_path))
    assert user_repo.verify_password("admin@123", old["password_hash"], old["salt"])

    # operator explicitly rotates
    monkeypatch.setenv("LEGALMATRIX_ADMIN_PASSWORD", "rotated-pw-42")
    _seed_default_admin(data_dir=tmp_path / "cg")
    new = user_repo.get_user_by_username("admin", db_path=_db_path(tmp_path))
    assert user_repo.verify_password("rotated-pw-42", new["password_hash"], new["salt"])
    assert not user_repo.verify_password("admin@123", new["password_hash"], new["salt"])


def test_no_rotation_when_password_not_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGALMATRIX_ADMIN_PASSWORD", raising=False)
    _seed_default_admin(data_dir=tmp_path / "cg")
    before = user_repo.get_user_by_username("admin", db_path=_db_path(tmp_path))["password_hash"]
    # boot again with same (unset) env — hash must be untouched
    _seed_default_admin(data_dir=tmp_path / "cg")
    after = user_repo.get_user_by_username("admin", db_path=_db_path(tmp_path))["password_hash"]
    assert before == after


def test_update_password_returns_rowcount(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGALMATRIX_ADMIN_PASSWORD", raising=False)
    _seed_default_admin(data_dir=tmp_path / "cg")
    n = user_repo.update_password("admin", "another-pw", db_path=_db_path(tmp_path))
    assert n == 1
    user = user_repo.get_user_by_username("admin", db_path=_db_path(tmp_path))
    assert user_repo.verify_password("another-pw", user["password_hash"], user["salt"])
    assert user_repo.update_password("ghost", "x", db_path=_db_path(tmp_path)) == 0


def test_insecure_default_secret_flag():
    import app.config as config
    assert config.AUTH_SECRET_IS_DEFAULT == (
        config.AUTH_TOKEN_SECRET == "change-me-in-production-legalmatrix"
    )