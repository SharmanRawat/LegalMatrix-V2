"""Authentication service — HMAC-signed tokens + FastAPI dependencies.

Uses only the stdlib (hmac/hashlib/base64), no external JWT dependency.
Token payload is base64url(JSON). Signature is HMAC-SHA256(secret, payload).
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import AUTH_TOKEN_SECRET, AUTH_TOKEN_TTL_HOURS
from app.repositories import users as user_repo

_bearer = HTTPBearer(auto_error=False)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(payload_b64: str) -> str:
    return hmac.new(
        AUTH_TOKEN_SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()


def create_token(user_id: int, username: str, role: str) -> str:
    payload = {
        "uid": user_id,
        "username": username,
        "role": role,
        "exp": time.time() + AUTH_TOKEN_TTL_HOURS * 3600,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str) -> Optional[dict]:
    try:
        payload_b64, signature = token.split(".", 1)
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(_sign(payload_b64), signature):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None
    if float(payload.get("exp", 0)) < time.time():
        return None
    return payload


def authenticate(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if not credentials or credentials.scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def optional_auth(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """Authenticate if a token is provided, otherwise return None.
    Lets inspect/report endpoints work in demo mode without a login."""
    if not credentials or credentials.scheme != "Bearer":
        return None
    return verify_token(credentials.credentials) or None


def require_roles(*roles: str):
    def dependency(payload: dict = Depends(authenticate)) -> dict:
        if payload.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return payload

    return dependency