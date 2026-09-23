"""Search API — retrieval of previously scanned products and reports."""
from fastapi import APIRouter, Depends, Query

from app.repositories import inspections as inspection_repo
from app.services.auth_service import require_roles

router = APIRouter()


@router.get("/search")
def search(
    q: str = Query("", description="Free-text search across id, product, manufacturer"),
    status: str = Query(None, description="Filter by status"),
    product_name: str = Query(None),
    manufacturer: str = Query(None),
    date_from: str = Query(None, description="ISO date or datetime"),
    date_to: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(require_roles("ADMIN", "INSPECTOR", "VIEWER")),
):
    # Non-admins only see scans they created (own-user isolation).
    user_id = None if user.get("role") == "ADMIN" else int(user.get("uid") or -1)
    return inspection_repo.search_inspections(
        q=q or None,
        status=status or None,
        product_name=product_name or None,
        manufacturer=manufacturer or None,
        date_from=date_from or None,
        date_to=date_to or None,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )