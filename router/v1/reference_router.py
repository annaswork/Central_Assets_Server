"""Reference API endpoints for App Instances.

R1 HARD RULE:
Instances can NEVER author content. Rejects create attempts with 409 INSTANCE_CANNOT_CREATE_CONTENT.
"""

from typing import Any

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.reference_controller import (
    add_references,
    copy_references_from_instance,
)
from database.models.instance_content import ReferenceAddPayload, ReferenceCopyPayload
from router.deps import get_db
from utils.errors import InstanceCannotCreateContentError

router = APIRouter(prefix="/app-instances/{id}", tags=["Instance References"])


@router.post("/references", status_code=201, dependencies=[Depends(require_scope("assets:write"))])
async def add_references_endpoint(
    id: str,
    payload: ReferenceAddPayload,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Reference categories, subcategories, or individual assets from the central library."""
    return await add_references(
        db,
        app_instance_id=id,
        category_ids=payload.category_ids,
        sub_category_ids=payload.sub_category_ids,
        asset_ids=payload.asset_ids,
    )


@router.post(
    "/references/copy-from", status_code=201, dependencies=[Depends(require_scope("assets:write"))]
)
async def copy_references_endpoint(
    id: str,
    payload: ReferenceCopyPayload,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Copy all reference selections and settings from an existing app instance."""
    return await copy_references_from_instance(
        db,
        target_instance_id=id,
        source_instance_id=payload.source_instance_id,
        include_overrides=payload.include_overrides,
    )


# Explicit route catching disallowed instance content creation
@router.post("/categories", include_in_schema=False)
@router.post("/subcategories", include_in_schema=False)
@router.post("/assets", include_in_schema=False)
async def reject_instance_create_content(id: str) -> None:
    raise InstanceCannotCreateContentError(
        f"App instance '{id}' cannot author content. "
        "Create content centrally under /api/v1/categories, /subcategories, or /assets first, "
        f"then call POST /api/v1/app-instances/{id}/references to reference it."
    )
