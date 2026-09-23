"""App Instance API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.app_instance_controller import (
    create_app_instance,
    delete_app_instance,
    get_app_instance,
    list_app_instances,
    update_app_instance,
    upload_instance_icon,
)
from database.models.app_instance import AppInstanceCreate, AppInstanceUpdate
from router.deps import get_db, get_pagination
from utils.pagination import PageParams

router = APIRouter(prefix="/app-instances", tags=["App Instances"])


@router.get("", dependencies=[Depends(require_scope("keys:manage"))])
async def list_app_instances_endpoint(
    search: str | None = Query(default=None, description="Filter by app name"),
    pagination: PageParams = Depends(get_pagination),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await list_app_instances(
        db, page=pagination.page, page_size=pagination.page_size, search=search
    )


@router.post("", status_code=201, dependencies=[Depends(require_scope("keys:manage"))])
async def create_app_instance_endpoint(
    payload: AppInstanceCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await create_app_instance(db, payload)


@router.get("/{id}", dependencies=[Depends(require_scope("keys:manage"))])
async def get_app_instance_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await get_app_instance(db, instance_id=id)


@router.patch("/{id}", dependencies=[Depends(require_scope("keys:manage"))])
async def update_app_instance_endpoint(
    id: str,
    payload: AppInstanceUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await update_app_instance(db, instance_id=id, data=payload)


@router.delete("/{id}", dependencies=[Depends(require_scope("keys:manage"))])
async def delete_app_instance_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await delete_app_instance(db, instance_id=id)


@router.post("/{id}/icon", dependencies=[Depends(require_scope("keys:manage"))])
async def upload_app_icon_endpoint(
    id: str,
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read()
    filename = file.filename or "icon.png"
    return await upload_instance_icon(db, instance_id=id, file_bytes=content, filename=filename)
