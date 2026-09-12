"""Dashboard API — monitoring stats for enforcement officials."""
from fastapi import APIRouter, Depends

from app.repositories import inspections as inspection_repo
from app.services.auth_service import require_roles

router = APIRouter()


@router.get("/dashboard/stats")
def get_stats(user=Depends(require_roles("ADMIN", "INSPECTOR", "VIEWER"))):
    return inspection_repo.dashboard_stats()