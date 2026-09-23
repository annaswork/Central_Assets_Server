"""Authorization controller managing API keys and operator authentication."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import authenticate_admin_user
from authorization.api_key import (
    activate_api_key,
    delete_api_key,
    issue_api_key,
    revoke_api_key,
    rotate_api_key,
)
from controller.base_controller import serialize_mongo_docs
from database.collections import API_KEYS
from database.models.api_key import ApiKeyCreate, ApiKeyOut


async def list_keys(
    db: AsyncIOMotorDatabase, app_instance_id: str | None = None
) -> list[dict[str, Any]]:
    """List API keys without exposing secrets."""
    query: dict[str, Any] = {}
    if app_instance_id:
        query["app_instance_id"] = app_instance_id

    cursor = db[API_KEYS].find(query, {"secret_hash": 0}).sort("created_at", -1)
    docs = await cursor.to_list(length=1000)
    serialized = serialize_mongo_docs(docs)
    for d in serialized:
        d["is_revoked"] = bool(d.get("is_revoked") or d.get("revoked_at") or not d.get("is_active", True))
    return serialized


async def create_key(db: AsyncIOMotorDatabase, data: ApiKeyCreate) -> ApiKeyOut:
    """Issue a new API key."""
    return await issue_api_key(
        db,
        name=data.name,
        app_instance_id=data.app_instance_id,
        scopes=data.scopes,
        rate_limit_per_min=data.rate_limit_per_min,
        expires_at=data.expires_at,
    )


async def rotate_key(
    db: AsyncIOMotorDatabase, key_id: str, grace_hours: int = 24
) -> tuple[ApiKeyOut, ApiKeyOut]:
    """Rotate an existing key."""
    return await rotate_api_key(db, key_id, grace_period_hours=grace_hours)


async def revoke_key(db: AsyncIOMotorDatabase, key_id: str) -> bool:
    """Revoke an API key immediately."""
    return await revoke_api_key(db, key_id)


async def delete_key(db: AsyncIOMotorDatabase, key_id: str) -> bool:
    """Permanently delete an API key."""
    return await delete_api_key(db, key_id)


async def activate_key(db: AsyncIOMotorDatabase, key_id: str) -> bool:
    """Re-activate an API key."""
    return await activate_api_key(db, key_id)


async def update_key_rate_limit(db: AsyncIOMotorDatabase, key_id: str, rate_limit: int) -> bool:
    """Update an API key's rate limit."""
    from database.collections import API_KEYS
    from utils.datetimes import utc_now
    from utils.ids import to_object_id

    oid = to_object_id(key_id)
    res = await db[API_KEYS].update_one(
        {"_id": oid},
        {"$set": {"rate_limit_per_min": rate_limit, "updated_at": utc_now()}},
    )
    if res.matched_count == 0:
        from utils.errors import NotFoundError

        raise NotFoundError("API key not found")
    return True


async def login_operator(db: AsyncIOMotorDatabase, username: str, password: str) -> dict[str, Any]:
    """Authenticate admin user credentials."""
    return await authenticate_admin_user(db, username, password)
