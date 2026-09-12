"""User repository — authentication store with PBKDF2 password hashing."""
import hashlib
import secrets
from datetime import datetime, timezone

from app.database.connection import get_connection

ROLES = ("ADMIN", "INSPECTOR", "VIEWER")


def _iterations() -> int:
    return 260000


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _iterations()
    ).hex()
    return digest, salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _iterations()
    ).hex()
    return secrets.compare_digest(digest, password_hash)


def create_user(username: str, name: str, role: str, password: str, db_path=None):
    if role.upper() not in ROLES:
        raise ValueError(f"Invalid role: {role}")
    pwd_hash, salt = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO users (username, name, role, password_hash, salt, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (username, name, role.upper(), pwd_hash, salt, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_username(username: str, db_path=None):
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int, db_path=None):
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users(db_path=None):
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, username, name, role, is_active, created_at FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()