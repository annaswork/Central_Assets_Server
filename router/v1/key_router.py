"""API key management endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.authorization_controller import (
    activate_key,
    create_key,
    delete_key,
    list_keys,
    revoke_key,
    rotate_key,
)
from database.models.api_key import ApiKeyCreate, ApiKeyOut
from router.deps import get_db

router = APIRouter(prefix="/keys", tags=["API Key Management"])


@router.get("", dependencies=[Depends(require_scope("keys:manage"))])
async def list_keys_endpoint(
    instanceId: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    return await list_keys(db, app_instance_id=instanceId)


@router.post("", status_code=201, dependencies=[Depends(require_scope("keys:manage"))])
async def create_key_endpoint(
    payload: ApiKeyCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> ApiKeyOut:
    return await create_key(db, payload)


@router.post("/{id}/rotate", dependencies=[Depends(require_scope("keys:manage"))])
async def rotate_key_endpoint(
    id: str,
    graceHours: int = Query(default=24, ge=1, le=168),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    new_key, old_key = await rotate_key(db, key_id=id, grace_hours=graceHours)
    return {"new_key": new_key, "previous_key": old_key}


@router.post("/{id}/revoke", dependencies=[Depends(require_scope("keys:manage"))])
async def revoke_key_post_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    success = await revoke_key(db, key_id=id)
    return {"success": success, "revoked_id": id}


@router.post("/{id}/activate", dependencies=[Depends(require_scope("keys:manage"))])
async def activate_key_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    success = await activate_key(db, key_id=id)
    return {"success": success, "activated_id": id}


@router.delete("/{id}", dependencies=[Depends(require_scope("keys:manage"))])
async def revoke_key_endpoint(
    id: str,
    permanent: bool = Query(default=False),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    if permanent:
        success = await delete_key(db, key_id=id)
        return {"success": success, "deleted_id": id}
    success = await revoke_key(db, key_id=id)
    return {"success": success, "revoked_id": id}
