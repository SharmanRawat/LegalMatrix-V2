"""Dashboard API — monitoring stats for enforcement officials."""
from fastapi import APIRouter, Depends

from app.repositories import inspections as inspection_repo
from app.services.auth_service import require_roles

router = APIRouter()


@router.get("/dashboard/stats")
def get_stats(user=Depends(require_roles("ADMIN", "INSPECTOR", "VIEWER"))):
    # Non-admins only see aggregates + recent rows for scans they created.
    user_id = None if user.get("role") == "ADMIN" else int(user.get("uid") or -1)
    return inspection_repo.dashboard_stats(user_id=user_id)