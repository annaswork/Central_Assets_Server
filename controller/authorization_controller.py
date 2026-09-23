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


async def get_admin_user_by_id(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, Any]:
    """Fetch admin user document by id."""
    from database.collections import ADMIN_USERS
    from utils.errors import NotFoundError
    from utils.ids import to_object_id

    oid = to_object_id(user_id)
    user = await db[ADMIN_USERS].find_one({"_id": oid})
    if not user:
        raise NotFoundError("Admin user not found")
    return user


async def initiate_2fa_setup(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, Any]:
    """Generate temporary TOTP secret and QR code for 2FA onboarding."""
    from authorization.totp import generate_provisioning_uri, generate_qr_code_base64, generate_totp_secret
    from database.collections import ADMIN_USERS
    from utils.datetimes import utc_now
    from utils.ids import to_object_id

    user = await get_admin_user_by_id(db, user_id)
    secret = generate_totp_secret()
    uri = generate_provisioning_uri(user["username"], secret)
    qr_data_url = generate_qr_code_base64(uri)

    await db[ADMIN_USERS].update_one(
        {"_id": to_object_id(user_id)},
        {"$set": {"totp_temp_secret": secret, "updated_at": utc_now()}},
    )

    return {
        "secret": secret,
        "qr_code_url": qr_data_url,
        "uri": uri,
        "username": user["username"],
    }


async def confirm_and_enable_2fa(
    db: AsyncIOMotorDatabase, user_id: str, code: str
) -> list[str]:
    """Verify code against temporary secret, enable 2FA, and return generated backup codes."""
    from authorization.totp import (
        generate_backup_codes,
        hash_backup_codes,
        verify_totp_code,
    )
    from database.collections import ADMIN_USERS
    from utils.datetimes import utc_now
    from utils.errors import ValidationError
    from utils.ids import to_object_id

    user = await get_admin_user_by_id(db, user_id)
    temp_secret = user.get("totp_temp_secret")
    if not temp_secret:
        raise ValidationError("2FA setup was not initiated. Please start setup again.")

    if not verify_totp_code(temp_secret, code):
        raise ValidationError("Invalid 6-digit verification code. Please check Google Authenticator.")

    backup_codes = generate_backup_codes(8)
    hashed_backups = hash_backup_codes(backup_codes)

    await db[ADMIN_USERS].update_one(
        {"_id": to_object_id(user_id)},
        {
            "$set": {
                "is_2fa_enabled": True,
                "totp_secret": temp_secret,
                "totp_temp_secret": None,
                "backup_codes": hashed_backups,
                "updated_at": utc_now(),
            }
        },
    )

    return backup_codes


async def disable_2fa(db: AsyncIOMotorDatabase, user_id: str, password: str) -> bool:
    """Disable 2FA for an admin user after verifying password."""
    from authorization.encryption import verify_password
    from database.collections import ADMIN_USERS
    from utils.datetimes import utc_now
    from utils.errors import UnauthorizedError
    from utils.ids import to_object_id

    user = await get_admin_user_by_id(db, user_id)
    if not verify_password(password, user["password_hash"]):
        raise UnauthorizedError("Incorrect password. 2FA was not disabled.")

    await db[ADMIN_USERS].update_one(
        {"_id": to_object_id(user_id)},
        {
            "$set": {
                "is_2fa_enabled": False,
                "totp_secret": None,
                "totp_temp_secret": None,
                "backup_codes": [],
                "updated_at": utc_now(),
            }
        },
    )
    return True


async def verify_login_2fa(
    db: AsyncIOMotorDatabase, user_id: str, code: str
) -> dict[str, Any]:
    """Verify 2FA code (or emergency backup code) during login."""
    from authorization.totp import verify_and_consume_backup_code, verify_totp_code
    from database.collections import ADMIN_USERS
    from utils.datetimes import utc_now
    from utils.errors import UnauthorizedError
    from utils.ids import to_object_id

    user = await get_admin_user_by_id(db, user_id)
    if not user.get("is_active", True):
        raise UnauthorizedError("Operator account is deactivated")

    totp_secret = user.get("totp_secret")
    backup_codes = user.get("backup_codes", [])

    # 1. Check TOTP 6-digit code
    if totp_secret and verify_totp_code(totp_secret, code):
        return user

    # 2. Check emergency backup code
    matched, remaining = verify_and_consume_backup_code(backup_codes, code)
    if matched:
        await db[ADMIN_USERS].update_one(
            {"_id": to_object_id(user_id)},
            {"$set": {"backup_codes": remaining, "updated_at": utc_now()}},
        )
        return user

    raise UnauthorizedError("Invalid authentication code or backup code.")
