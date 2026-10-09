"""API key issuance, lookup, validation, rotation, and revocation."""

import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.encryption import generate_key_pair, verify_secret
from database.collections import API_KEYS
from database.models.api_key import ApiKeyInDB, ApiKeyOut
from utils.datetimes import utc_now
from utils.errors import NotFoundError, UnauthorizedError
from utils.ids import to_object_id

logger = logging.getLogger(__name__)


async def issue_api_key(
    db: AsyncIOMotorDatabase,
    name: str,
    app_instance_id: str | None = None,
    scopes: list[str] | None = None,
    rate_limit_per_min: int = 60,
    app_surge_ceiling_per_min: int = 10000,
    expires_at: datetime | None = None,
) -> ApiKeyOut:
    """Issue a new API key, revealing the full key secret exactly once."""
    full_key, key_prefix, secret_hash = generate_key_pair()
    now = utc_now()

    doc = {
        "name": name,
        "key_prefix": key_prefix,
        "secret_hash": secret_hash,
        "app_instance_id": to_object_id(app_instance_id) if app_instance_id else None,
        "scopes": scopes or [],
        "rate_limit_per_min": rate_limit_per_min,
        "app_surge_ceiling_per_min": app_surge_ceiling_per_min,
        "is_active": True,
        "last_used_at": None,
        "expires_at": expires_at,
        "revoked_at": None,
        "created_at": now,
        "updated_at": now,
    }

    res = await db[API_KEYS].insert_one(doc)
    doc["_id"] = res.inserted_id
    doc["id"] = str(res.inserted_id)
    doc["app_instance_id"] = str(doc["app_instance_id"]) if doc.get("app_instance_id") else None
    doc["full_key"] = full_key

    return ApiKeyOut(**doc)


async def verify_api_key(db: AsyncIOMotorDatabase, raw_key: str) -> ApiKeyInDB:
    """Verify an incoming X-API-Key string against stored hashed keys.

    Key structure: ak_<env>_<22char_id>_<32char_secret>
    """
    if not raw_key or not raw_key.startswith("ak_"):
        raise UnauthorizedError("Missing or invalid API key format")

    parts = raw_key.split("_")
    # Expected parts: ["ak", <env>, <id>, <secret>]
    if len(parts) != 4:
        raise UnauthorizedError("Malformed API key structure")

    key_prefix = f"{parts[0]}_{parts[1]}_{parts[2]}"
    secret = parts[3]

    doc = await db[API_KEYS].find_one({"key_prefix": key_prefix})
    if not doc:
        raise UnauthorizedError("Invalid API key")

    if not doc.get("is_active", False):
        raise UnauthorizedError("API key has been deactivated or revoked")

    if doc.get("revoked_at") is not None:
        raise UnauthorizedError("API key has been revoked")

    expires_at = doc.get("expires_at")
    if expires_at is not None:
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            raise UnauthorizedError("API key has expired")

    if not verify_secret(secret, doc["secret_hash"]):
        raise UnauthorizedError("Invalid API key")

    # Update last_used_at non-blockingly
    await db[API_KEYS].update_one({"_id": doc["_id"]}, {"$set": {"last_used_at": utc_now()}})

    return ApiKeyInDB(**doc)


async def rotate_api_key(
    db: AsyncIOMotorDatabase, key_id: str, grace_period_hours: int = 24
) -> tuple[ApiKeyOut, ApiKeyOut]:
    """Rotate an API key: issues a replacement and schedules previous key expiration."""
    oid = to_object_id(key_id)
    existing = await db[API_KEYS].find_one({"_id": oid})
    if not existing:
        raise NotFoundError("API key not found")

    new_key = await issue_api_key(
        db,
        name=f"{existing['name']} (Rotated)",
        app_instance_id=(
            str(existing["app_instance_id"]) if existing.get("app_instance_id") else None
        ),
        scopes=existing.get("scopes", []),
        rate_limit_per_min=existing.get("rate_limit_per_min", 60),
        app_surge_ceiling_per_min=existing.get("app_surge_ceiling_per_min", 10000),
    )

    # Set grace period expiry on old key
    grace_expiry = utc_now() + timedelta(hours=grace_period_hours)
    await db[API_KEYS].update_one(
        {"_id": oid},
        {"$set": {"expires_at": grace_expiry, "updated_at": utc_now()}},
    )
    existing["expires_at"] = grace_expiry
    existing["id"] = str(existing["_id"])

    return new_key, ApiKeyOut(**existing)


async def revoke_api_key(db: AsyncIOMotorDatabase, key_id: str) -> bool:
    """Immediately revoke an API key."""
    oid = to_object_id(key_id)
    now = utc_now()
    res = await db[API_KEYS].update_one(
        {"_id": oid},
        {"$set": {"is_active": False, "is_revoked": True, "revoked_at": now, "updated_at": now}},
    )
    if res.matched_count == 0:
        raise NotFoundError("API key not found")
    return True


async def delete_api_key(db: AsyncIOMotorDatabase, key_id: str) -> bool:
    """Permanently delete an API key."""
    oid = to_object_id(key_id)
    res = await db[API_KEYS].delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise NotFoundError("API key not found")
    return True


async def activate_api_key(db: AsyncIOMotorDatabase, key_id: str) -> bool:
    """Re-activate a revoked or deactivated API key."""
    oid = to_object_id(key_id)
    now = utc_now()
    res = await db[API_KEYS].update_one(
        {"_id": oid},
        {"$set": {"is_active": True, "is_revoked": False, "revoked_at": None, "updated_at": now}},
    )
    if res.matched_count == 0:
        raise NotFoundError("API key not found")
    return True
