"""Auth API — login, current user, user management (ADMIN only)."""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from app.repositories import users as user_repo
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
def list_users(admin=Depends(require_roles("ADMIN"))):
    return user_repo.list_users()