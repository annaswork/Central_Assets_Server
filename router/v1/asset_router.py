"""Asset API endpoints for the central creative library."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.asset_controller import (
    bulk_create_assets,
    check_asset_name_availability,
    create_asset,
    delete_asset,
    delete_asset_item,
    get_asset,
    get_asset_references,
    list_assets,
    update_asset,
)
from database.models.asset import AssetCreate, AssetUpdate
from router.deps import get_db, get_pagination
from utils.pagination import PageParams

router = APIRouter(prefix="/assets", tags=["Central Assets"])


@router.get("/check-name", dependencies=[Depends(require_scope("assets:read"))])
async def check_asset_name_endpoint(
    name: str = Query(..., description="Asset name to verify availability for"),
    categoryId: str | None = Query(default=None, description="Category ID"),
    subCategoryId: str | None = Query(default=None, description="Subcategory ID"),
    assetId: str | None = Query(default=None, description="Current asset ID if editing"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Verify if candidate asset name is usable and not already used in db."""
    return await check_asset_name_availability(
        db=db,
        name=name,
        category_id=categoryId,
        sub_category_id=subCategoryId,
        asset_id=assetId,
    )


@router.get("", dependencies=[Depends(require_scope("assets:read"))])
async def list_assets_endpoint(
    categoryId: str | None = Query(default=None, description="Filter by parent category ID"),
    subCategoryId: str | None = Query(default=None, description="Filter by parent subcategory ID"),
    q: str | None = Query(default=None, description="Text search term"),
    type: str | None = Query(default=None, description="Filter by data type: images, videos, audios, json, frames"),
    sort: str = Query(
        default="sequence",
        description="Sort by field: sequence, created_at, views, downloads, name",
    ),
    order: str = Query(default="asc", description="Sort order: asc or desc"),
    pagination: PageParams = Depends(get_pagination),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await list_assets(
        db,
        category_id=categoryId,
        sub_category_id=subCategoryId,
        search=q,
        page=pagination.page,
        page_size=pagination.page_size,
        sort_by=sort,
        sort_order=order,
        asset_type=type,
    )


@router.post("", status_code=201, dependencies=[Depends(require_scope("assets:write"))])
async def create_asset_endpoint(
    payload: AssetCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await create_asset(db, payload)


@router.post("/bulk", status_code=207, dependencies=[Depends(require_scope("assets:write"))])
async def bulk_create_assets_endpoint(
    payload: list[AssetCreate],
    atomic: bool = Query(default=False, description="Fail entire batch on any error if true"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await bulk_create_assets(db, items=payload, atomic=atomic)


@router.get("/{id}", dependencies=[Depends(require_scope("assets:read"))])
async def get_asset_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await get_asset(db, asset_id=id)


@router.patch("/{id}", dependencies=[Depends(require_scope("assets:write"))])
async def update_asset_endpoint(
    id: str,
    payload: AssetUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await update_asset(db, asset_id=id, data=payload)


@router.delete("/{id}", dependencies=[Depends(require_scope("assets:write"))])
async def delete_asset_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await delete_asset(db, asset_id=id)


@router.delete("/{id}/items", dependencies=[Depends(require_scope("assets:write"))])
async def delete_asset_item_endpoint(
    id: str,
    block_key: str | None = Query(default=None),
    blockKey: str | None = Query(default=None),
    item_index: int | None = Query(default=None),
    itemIndex: int | None = Query(default=None),
    url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    resolved_block_key = block_key or blockKey
    resolved_item_index = item_index if item_index is not None else itemIndex
    return await delete_asset_item(
        db,
        asset_id=id,
        block_key=resolved_block_key,
        item_index=resolved_item_index,
        url=url,
    )


@router.get("/{id}/references", dependencies=[Depends(require_scope("assets:read"))])
async def get_asset_references_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    """Reverse lookup: returns all app instances that reference this central asset."""
    return await get_asset_references(db, asset_id=id)
