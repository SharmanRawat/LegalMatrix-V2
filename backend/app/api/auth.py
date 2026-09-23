"""Auth API — login, current user, user management (ADMIN only)."""
from fastapi import APIRouter, HTTPException, Depends, status, Query

from pydantic import BaseModel

from app.repositories import users as user_repo
from app.repositories import inspections as inspection_repo
from app.repositories.users import verify_password
from app.services.auth_service import (
    create_token,
    authenticate,
    require_roles,
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    name: str
    role: str
    password: str


class PasswordReset(BaseModel):
    password: str


@router.post("/auth/login")
def login(body: LoginRequest):
    user = user_repo.get_user_by_username(body.username)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(body.password, user["password_hash"], user["salt"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_token(user["id"], user["username"], user["role"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
        },
    }


@router.get("/auth/me")
def me(user=Depends(authenticate)):
    return {"id": user["uid"], "username": user["username"], "role": user["role"]}


@router.post("/auth/users")
def create_user(body: UserCreate, admin=Depends(require_roles("ADMIN"))):
    if user_repo.get_user_by_username(body.username):
        raise HTTPException(status_code=400, detail="Username already exists")
    try:
        user_repo.create_user(body.username, body.name, body.role, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": f"User {body.username} created", "role": body.role.upper()}


@router.get("/auth/users")
def list_users(
    q: str = Query("", description="Free-text search by username or name"),
    role: str = Query(None, description="Filter by role: ADMIN, INSPECTOR, VIEWER"),
    admin=Depends(require_roles("ADMIN")),
):
    return user_repo.search_users(q=q or None, role=role)


@router.post("/auth/users/{username}/reset-password")
def reset_user_password(
    username: str,
    body: PasswordReset,
    admin=Depends(require_roles("ADMIN")),
):
    """Admin resets a user's password (the old one is unrecoverable by design)."""
    if not body.password:
        raise HTTPException(status_code=400, detail="New password must not be empty")
    target = user_repo.get_user_by_username(username)
    if target is None:
        raise HTTPException(status_code=404, detail=f"User {username} not found")
    user_repo.update_password(username, body.password)
    return {"message": f"Password reset for {username}"}


@router.get("/auth/users/{username}/inspections")
def user_inspections(
    username: str,
    limit: int = Query(100, ge=1, le=500),
    admin=Depends(require_roles("ADMIN")),
):
    """All inspections run by a user (admin audit view)."""
    target = user_repo.get_user_by_username(username)
    if target is None:
        raise HTTPException(status_code=404, detail=f"User {username} not found")
    scans = inspection_repo.list_inspections_by_user(target["id"], limit=limit)
    return {
        "username": username,
        "name": target["name"],
        "role": target["role"],
        "total": len(scans),
        "scans": scans,
    }