"""Client-facing catalog tree read and asset view/download event tracking endpoints."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from analytics.counters import increment_asset_counter
from authorization.instance_guard import get_instance_filter
from authorization.scopes import require_scope
from controller.catalog_controller import (
    get_instance_catalog,
    get_resolved_assets,
    get_resolved_categories,
    get_resolved_single_asset,
    get_resolved_subcategories,
)
from router.deps import get_db
from utils.errors import NotFoundError

router = APIRouter(prefix="/instance/{id}", tags=["Client Catalog & Tracking"])


class TrackEventPayload(BaseModel):
    event: Literal["view", "download"] = Field(..., description="'view' or 'download'")


@router.get("/catalog", dependencies=[Depends(require_scope("assets:read"))])
async def get_instance_catalog_endpoint(
    id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve full resolved catalog for a specific app instance.

    Enforces data layer instance isolation via get_instance_filter.
    """
    get_instance_filter(request, target_instance_id=id)
    return await get_instance_catalog(db, app_instance_id=id)


@router.get("/categories", dependencies=[Depends(require_scope("categories:read"))])
async def get_instance_categories_endpoint(
    id: str,
    request: Request,
    only_enabled: bool = Query(default=False),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve resolved categories for a specific app instance."""
    get_instance_filter(request, target_instance_id=id)
    return await get_resolved_categories(db, app_instance_id=id, only_enabled=only_enabled)


@router.get("/subcategories", dependencies=[Depends(require_scope("categories:read"))])
async def get_instance_subcategories_endpoint(
    id: str,
    request: Request,
    categoryId: str | None = Query(default=None),
    only_enabled: bool = Query(default=False),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve resolved subcategories for a specific app instance."""
    get_instance_filter(request, target_instance_id=id)
    return await get_resolved_subcategories(
        db, app_instance_id=id, category_id=categoryId, only_enabled=only_enabled
    )


@router.get("/assets", dependencies=[Depends(require_scope("assets:read"))])
async def get_instance_assets_endpoint(
    id: str,
    request: Request,
    categoryId: str | None = Query(default=None),
    subCategoryId: str | None = Query(default=None),
    only_enabled: bool = Query(default=False),
    sort: str | None = Query(default=None),
    order: str | None = Query(default=None),
    tag: str | None = Query(default=None, description="Filter assets by tag"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve resolved assets for a specific app instance."""
    get_instance_filter(request, target_instance_id=id)
    return await get_resolved_assets(
        db,
        app_instance_id=id,
        category_id=categoryId,
        sub_category_id=subCategoryId,
        only_enabled=only_enabled,
        sort=sort,
        order=order,
        tag=tag,
    )


@router.get("/assets/{assetId}", dependencies=[Depends(require_scope("assets:read"))])
async def get_instance_single_asset_endpoint(
    id: str,
    assetId: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve single resolved asset for a specific app instance."""
    get_instance_filter(request, target_instance_id=id)
    doc = await get_resolved_single_asset(db, app_instance_id=id, asset_id=assetId)
    if not doc:
        raise NotFoundError("Referenced asset not found in this app instance")
    return doc


@router.post("/assets/{assetId}/track", dependencies=[Depends(require_scope("assets:read"))])
async def track_asset_event_endpoint(
    id: str,
    assetId: str,
    payload: TrackEventPayload,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Increment asset view or download counter in the app instance."""
    get_instance_filter(request, target_instance_id=id)
    request.state.tracking_event_type = payload.event
    return await increment_asset_counter(
        db, app_instance_id=id, asset_id=assetId, event_type=payload.event
    )
