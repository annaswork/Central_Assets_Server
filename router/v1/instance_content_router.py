from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from analytics.counters import increment_asset_counter
from authorization.scopes import require_scope
from controller.catalog_controller import (
    get_resolved_assets,
    get_resolved_categories,
    get_resolved_single_asset,
    get_resolved_subcategories,
)
from controller.override_controller import (
    bulk_update_flags,
    reorder_items,
    reset_overrides,
    update_item_settings_and_overrides,
)
from controller.reference_controller import get_unresolved_references, remove_reference
from database.models.instance_content import (
    BulkFlagsPayload,
    InstanceContentUpdate,
    ReorderPayload,
    ResetOverridesPayload,
)
from router.deps import get_db
from utils.errors import NotFoundError


class TrackEventPayload(BaseModel):
    event: Literal["view", "download"] = Field(..., description="'view' or 'download'")

router = APIRouter(prefix="/app-instances/{id}", tags=["Instance Content"])


@router.get("/categories", dependencies=[Depends(require_scope("categories:read"))])
async def get_instance_categories_endpoint(
    id: str,
    only_enabled: bool = Query(default=False),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    return await get_resolved_categories(db, app_instance_id=id, only_enabled=only_enabled)


@router.get("/subcategories", dependencies=[Depends(require_scope("categories:read"))])
async def get_instance_subcategories_endpoint(
    id: str,
    categoryId: str | None = Query(default=None),
    only_enabled: bool = Query(default=False),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    return await get_resolved_subcategories(
        db, app_instance_id=id, category_id=categoryId, only_enabled=only_enabled
    )


@router.get("/assets", dependencies=[Depends(require_scope("assets:read"))])
async def get_instance_assets_endpoint(
    id: str,
    categoryId: str | None = Query(default=None),
    subCategoryId: str | None = Query(default=None),
    only_enabled: bool = Query(default=False),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    return await get_resolved_assets(
        db,
        app_instance_id=id,
        category_id=categoryId,
        sub_category_id=subCategoryId,
        only_enabled=only_enabled,
    )


@router.get("/assets/{assetId}", dependencies=[Depends(require_scope("assets:read"))])
async def get_instance_single_asset_endpoint(
    id: str,
    assetId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    doc = await get_resolved_single_asset(db, app_instance_id=id, asset_id=assetId)
    if not doc:
        raise NotFoundError("Referenced asset not found in this app instance")
    return doc


@router.post("/assets/{assetId}/track", dependencies=[Depends(require_scope("assets:read"))])
async def track_instance_asset_event_endpoint(
    id: str,
    assetId: str,
    payload: TrackEventPayload,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Increment asset view or download counter and record analytics."""
    request.state.tracking_event_type = payload.event
    return await increment_asset_counter(
        db, app_instance_id=id, asset_id=assetId, event_type=payload.event
    )


@router.patch("/assets/{assetId}", dependencies=[Depends(require_scope("assets:write"))])
async def update_instance_asset_endpoint(
    id: str,
    assetId: str,
    payload: InstanceContentUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await update_item_settings_and_overrides(
        db,
        app_instance_id=id,
        item_type="asset",
        item_id=assetId,
        is_enabled=payload.is_enabled,
        sequence=payload.sequence,
        is_premium=payload.is_premium,
        overrides=payload.overrides,
    )


@router.post(
    "/assets/{assetId}/reset-overrides", dependencies=[Depends(require_scope("assets:write"))]
)
async def reset_instance_asset_overrides_endpoint(
    id: str,
    assetId: str,
    payload: ResetOverridesPayload,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await reset_overrides(
        db,
        app_instance_id=id,
        item_type="asset",
        item_id=assetId,
        fields=payload.fields,
    )


@router.delete("/assets/{assetId}", dependencies=[Depends(require_scope("assets:write"))])
async def delete_instance_asset_endpoint(
    id: str,
    assetId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await remove_reference(db, app_instance_id=id, item_type="asset", item_id=assetId)


@router.delete("/subcategories/{subId}", dependencies=[Depends(require_scope("categories:write"))])
async def delete_instance_subcategory_endpoint(
    id: str,
    subId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await remove_reference(db, app_instance_id=id, item_type="subcategory", item_id=subId)


@router.delete("/categories/{catId}", dependencies=[Depends(require_scope("categories:write"))])
async def delete_instance_category_endpoint(
    id: str,
    catId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await remove_reference(db, app_instance_id=id, item_type="category", item_id=catId)


@router.post("/reorder", dependencies=[Depends(require_scope("assets:write"))])
async def reorder_instance_items_endpoint(
    id: str,
    payload: ReorderPayload,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await reorder_items(
        db,
        app_instance_id=id,
        item_type=payload.type,
        ordered_ids=payload.ordered_ids,
    )


@router.post("/bulk-flags", dependencies=[Depends(require_scope("assets:write"))])
async def bulk_flags_endpoint(
    id: str,
    payload: BulkFlagsPayload,
    type: str = Query(default="asset", description="'category', 'subcategory', or 'asset'"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await bulk_update_flags(
        db,
        app_instance_id=id,
        item_type=type,
        ids=payload.ids,
        is_enabled=payload.is_enabled,
        is_premium=payload.is_premium,
    )


@router.get("/unresolved", dependencies=[Depends(require_scope("assets:read"))])
async def get_unresolved_references_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await get_unresolved_references(db, app_instance_id=id)
