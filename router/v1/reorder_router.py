"""Central library reordering API endpoint."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.reorder_controller import get_reorder_items, reorder_central_items
from database.models.instance_content import ReorderPayload
from router.deps import get_db

router = APIRouter(prefix="/reorder", tags=["Central Reordering"])


@router.get("/items", dependencies=[Depends(require_scope("assets:read"))])
async def get_central_reorder_items_endpoint(
    type: str = Query(..., description="'category', 'subcategory', or 'asset'"),
    categoryId: str | None = Query(default=None),
    subCategoryId: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve items of the specified type in sequence order."""
    items = await get_reorder_items(
        db=db,
        item_type=type,
        category_id=categoryId,
        sub_category_id=subCategoryId,
    )
    return {"items": items, "total_count": len(items)}


@router.post("", dependencies=[Depends(require_scope("assets:write"))])
async def reorder_central_items_endpoint(
    payload: ReorderPayload,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Reorder central categories, subcategories, or assets by ordered IDs."""
    return await reorder_central_items(
        db=db,
        item_type=payload.type,
        ordered_ids=payload.ordered_ids,
    )
