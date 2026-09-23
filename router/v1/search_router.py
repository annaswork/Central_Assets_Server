"""Global Search API router for categories, subcategories, and central assets."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.search_controller import global_search
from router.deps import get_db

router = APIRouter(prefix="/search", tags=["Global Search"])


@router.get("", dependencies=[Depends(require_scope("assets:read"))])
async def search_endpoint(
    q: str = Query(
        default="", description="Search query term across categories, subcategories, assets"
    ),
    limit: int = Query(default=6, ge=1, le=50, description="Max matches per entity type"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Perform a global search returning matched categories, subcategories, and assets."""
    return await global_search(db=db, query=q, limit=limit)
