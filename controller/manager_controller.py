"""Manager controller managing manager accounts, scoping, keys, messaging, and dashboard counts."""

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.encryption import hash_password, verify_password
from authorization.manager_session import authenticate_manager_user
from authorization.totp import (
    generate_backup_codes,
    generate_provisioning_uri,
    generate_qr_code_base64,
    generate_totp_secret,
    hash_backup_codes,
    verify_and_consume_backup_code,
    verify_totp_code,
)
from controller.base_controller import serialize_mongo_doc, serialize_mongo_docs
from database.collections import (
    API_KEYS,
    APP_INSTANCE_ACCESS,
    APP_INSTANCE_ACCESS_REQUESTS,
    APP_INSTANCES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    MANAGERS,
    MESSAGES,
)
from database.models.api_key import ApiKeyCreate, ApiKeyOut
from database.models.manager_user import ManagerUserCreate
from utils.datetimes import utc_now
from utils.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationError
from utils.ids import to_object_id


# =========================================================================
# 1. Registration & Authentication
# =========================================================================

async def check_username_available(db: AsyncIOMotorDatabase, username: str) -> dict[str, Any]:
    """Check if a username is available for manager registration."""
    clean_username = username.strip()
    if not clean_username or len(clean_username) < 3:
        return {"available": False, "message": "Username must be at least 3 characters."}

    existing = await db[MANAGERS].find_one(
        {"username": {"$regex": f"^{clean_username}$", "$options": "i"}}
    )
    if existing:
        return {"available": False, "message": f"Username '{clean_username}' is already taken."}

    return {"available": True, "message": "Username is available."}


async def register_manager(db: AsyncIOMotorDatabase, data: ManagerUserCreate) -> dict[str, Any]:
    """Register a new manager account with active status by default."""
    clean_username = data.username.strip()
    if len(clean_username) < 3 or len(clean_username) > 50:
        raise ValidationError("Username must be between 3 and 50 characters.")

    # Check username uniqueness case-insensitively
    existing = await db[MANAGERS].find_one(
        {"username": {"$regex": f"^{clean_username}$", "$options": "i"}}
    )
    if existing:
        raise ConflictError(f"Username '{clean_username}' is already taken.")

    if data.confirm_password and data.password != data.confirm_password:
        raise ValidationError("Password and confirmation password do not match.")

    if len(data.password) < 8:
        raise ValidationError("Password must be at least 8 characters long.")

    pw_hash = hash_password(data.password)
    now = utc_now()

    doc: dict[str, Any] = {
        "username": clean_username,
        "email": data.email.strip().lower() if data.email else None,
        "password_hash": pw_hash,
        "role": "manager",
        "status": "active",  # Default active per specification
        "is_active": True,
        "display_name": clean_username,
        "profile_picture": None,
        "is_2fa_enabled": False,
        "totp_secret": None,
        "totp_temp_secret": None,
        "backup_codes": [],
        "created_at": now,
        "updated_at": now,
    }

    res = await db[MANAGERS].insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_mongo_doc(doc)  # type: ignore


async def login_manager(db: AsyncIOMotorDatabase, username: str, password: str) -> dict[str, Any]:
    """Authenticate manager credentials."""
    return await authenticate_manager_user(db, username=username, password=password)


async def get_manager_by_id(db: AsyncIOMotorDatabase, manager_id: str) -> dict[str, Any]:
    """Fetch manager document by ID."""
    oid = to_object_id(manager_id)
    doc = await db[MANAGERS].find_one({"_id": oid})
    if not doc:
        raise NotFoundError("Manager account not found")
    return serialize_mongo_doc(doc)  # type: ignore


# =========================================================================
# 2. Manager Profile & Password
# =========================================================================

async def update_manager_profile(
    db: AsyncIOMotorDatabase,
    manager_id: str,
    display_name: str | None = None,
    profile_picture: str | None = None,
) -> dict[str, Any]:
    """Update editable profile fields. Username modification is strictly forbidden."""
    oid = to_object_id(manager_id)
    update_data: dict[str, Any] = {"updated_at": utc_now()}

    if display_name is not None and display_name.strip():
        update_data["display_name"] = display_name.strip()

    if profile_picture is not None:
        update_data["profile_picture"] = profile_picture.strip() if profile_picture.strip() else None

    res = await db[MANAGERS].update_one({"_id": oid}, {"$set": update_data})
    if res.matched_count == 0:
        raise NotFoundError("Manager account not found")

    return await get_manager_by_id(db, manager_id)


async def change_manager_password(
    db: AsyncIOMotorDatabase,
    manager_id: str,
    current_password: str,
    new_password: str,
    confirm_new_password: str | None = None,
) -> bool:
    """Change manager password with verification of current password."""
    oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    if not verify_password(current_password, manager["password_hash"]):
        raise UnauthorizedError("Incorrect current password.")

    if confirm_new_password and new_password != confirm_new_password:
        raise ValidationError("New password and confirmation do not match.")

    if len(new_password) < 8:
        raise ValidationError("New password must be at least 8 characters long.")

    pw_hash = hash_password(new_password)
    await db[MANAGERS].update_one(
        {"_id": oid},
        {"$set": {"password_hash": pw_hash, "updated_at": utc_now()}},
    )
    return True


# =========================================================================
# 3. Manager 2FA Operations
# =========================================================================

async def initiate_manager_2fa(db: AsyncIOMotorDatabase, manager_id: str) -> dict[str, Any]:
    """Generate temporary TOTP secret and QR code for manager 2FA onboarding."""
    manager = await get_manager_by_id(db, manager_id)
    secret = generate_totp_secret()
    uri = generate_provisioning_uri(manager["username"], secret, issuer_name="Asset Platform")
    qr_data_url = generate_qr_code_base64(uri)

    await db[MANAGERS].update_one(
        {"_id": to_object_id(manager_id)},
        {"$set": {"totp_temp_secret": secret, "updated_at": utc_now()}},
    )

    return {
        "secret": secret,
        "qr_code_url": qr_data_url,
        "uri": uri,
        "username": manager["username"],
    }


async def confirm_and_enable_manager_2fa(
    db: AsyncIOMotorDatabase, manager_id: str, code: str
) -> list[str]:
    """Verify code against temporary secret, enable 2FA, and return backup codes."""
    oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    temp_secret = manager.get("totp_temp_secret")
    if not temp_secret:
        raise ValidationError("2FA setup was not initiated. Please start setup again.")

    if not verify_totp_code(temp_secret, code):
        raise ValidationError("Invalid 6-digit verification code. Please check your Authenticator app.")

    backup_codes = generate_backup_codes(8)
    hashed_backups = hash_backup_codes(backup_codes)

    await db[MANAGERS].update_one(
        {"_id": oid},
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


async def disable_manager_2fa(
    db: AsyncIOMotorDatabase, manager_id: str, password: str
) -> bool:
    """Disable 2FA for manager after verifying password."""
    oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    if not verify_password(password, manager["password_hash"]):
        raise UnauthorizedError("Incorrect password. 2FA was not disabled.")

    await db[MANAGERS].update_one(
        {"_id": oid},
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


async def verify_manager_login_2fa(
    db: AsyncIOMotorDatabase, manager_id: str, code: str
) -> dict[str, Any]:
    """Verify 2FA code or backup code during manager login."""
    oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": oid})
    if not manager:
        raise UnauthorizedError("Manager account not found")

    if not manager.get("is_active", True) or manager.get("status") in ["disabled", "inactive"]:
        raise UnauthorizedError("Manager account is inactive")

    totp_secret = manager.get("totp_secret")
    backup_codes = manager.get("backup_codes", [])

    if totp_secret and verify_totp_code(totp_secret, code):
        return manager

    matched, remaining = verify_and_consume_backup_code(backup_codes, code)
    if matched:
        await db[MANAGERS].update_one(
            {"_id": oid},
            {"$set": {"backup_codes": remaining, "updated_at": utc_now()}},
        )
        return manager

    raise UnauthorizedError("Invalid authentication code or backup code.")


# =========================================================================
# 4. App Instance Scoping & Access Control
# =========================================================================

async def get_manager_accessible_instance_ids(
    db: AsyncIOMotorDatabase, manager_id: str
) -> list[str]:
    """Return all app instance IDs the manager has access to (owned + granted)."""
    oid = to_object_id(manager_id)

    # 1. Owned instances
    owned_cursor = db[APP_INSTANCES].find({"owner_id": oid}, {"_id": 1})
    owned_docs = await owned_cursor.to_list(length=1000)
    instance_ids = {str(d["_id"]) for d in owned_docs}

    # Also string-formatted owner_id compatibility
    owned_str_cursor = db[APP_INSTANCES].find({"owner_id": str(oid)}, {"_id": 1})
    owned_str_docs = await owned_str_cursor.to_list(length=1000)
    for d in owned_str_docs:
        instance_ids.add(str(d["_id"]))

    # 2. Granted access instances
    granted_cursor = db[APP_INSTANCE_ACCESS].find({"manager_id": oid}, {"app_instance_id": 1})
    granted_docs = await granted_cursor.to_list(length=1000)
    for g in granted_docs:
        instance_ids.add(str(g["app_instance_id"]))

    granted_str_cursor = db[APP_INSTANCE_ACCESS].find({"manager_id": str(oid)}, {"app_instance_id": 1})
    granted_str_docs = await granted_str_cursor.to_list(length=1000)
    for g in granted_str_docs:
        instance_ids.add(str(g["app_instance_id"]))

    return sorted(list(instance_ids))


async def verify_manager_instance_access(
    db: AsyncIOMotorDatabase,
    manager_id: str,
    instance_id: str,
    require_owner: bool = False,
) -> dict[str, Any]:
    """Verify manager access to an app instance. Raises ForbiddenError if not accessible."""
    inst_oid = to_object_id(instance_id)
    instance = await db[APP_INSTANCES].find_one({"_id": inst_oid})
    if not instance:
        raise NotFoundError("App instance not found")

    manager_oid = to_object_id(manager_id)
    is_owner = instance.get("owner_id") in [manager_oid, str(manager_oid)]

    if require_owner:
        if not is_owner:
            raise ForbiddenError("You do not own this app instance.")
        return instance

    if is_owner:
        return instance

    # Check grant table
    grant = await db[APP_INSTANCE_ACCESS].find_one(
        {
            "$or": [
                {"manager_id": manager_oid, "app_instance_id": inst_oid},
                {"manager_id": str(manager_oid), "app_instance_id": str(inst_oid)},
                {"manager_id": manager_oid, "app_instance_id": str(inst_oid)},
                {"manager_id": str(manager_oid), "app_instance_id": inst_oid},
            ]
        }
    )
    if not grant:
        raise ForbiddenError("You do not have access to this app instance.")

    return instance


# =========================================================================
# 5. Main Dashboard Scoped Counts
# =========================================================================

async def get_manager_dashboard_counts(
    db: AsyncIOMotorDatabase, manager_id: str
) -> dict[str, int]:
    """Return counts of categories, subcategories, assets, and instances scoped to manager's access.
    
    Central data counts reflect distinct items referenced/imported by the manager's accessible instances.
    """
    accessible_ids = await get_manager_accessible_instance_ids(db, manager_id)
    if not accessible_ids:
        return {
            "instances": 0,
            "categories": 0,
            "subcategories": 0,
            "assets": 0,
        }

    accessible_oids = [to_object_id(i) for i in accessible_ids]

    # Distinct categories referenced across accessible apps
    cat_pipeline = [
        {"$match": {"app_instance_id": {"$in": accessible_oids}, "deleted_at": None, "is_enabled": True}},
        {"$group": {"_id": "$source_id"}},
        {"$count": "total"},
    ]
    cat_res = await db[INSTANCE_CATEGORIES].aggregate(cat_pipeline).to_list(length=1)
    cat_count = cat_res[0]["total"] if cat_res else 0

    # Distinct subcategories referenced
    sub_pipeline = [
        {"$match": {"app_instance_id": {"$in": accessible_oids}, "deleted_at": None, "is_enabled": True}},
        {"$group": {"_id": "$source_id"}},
        {"$count": "total"},
    ]
    sub_res = await db[INSTANCE_SUBCATEGORIES].aggregate(sub_pipeline).to_list(length=1)
    sub_count = sub_res[0]["total"] if sub_res else 0

    # Distinct assets referenced
    asset_pipeline = [
        {"$match": {"app_instance_id": {"$in": accessible_oids}, "deleted_at": None, "is_enabled": True}},
        {"$group": {"_id": "$source_id"}},
        {"$count": "total"},
    ]
    asset_res = await db[INSTANCE_ASSETS].aggregate(asset_pipeline).to_list(length=1)
    asset_count = asset_res[0]["total"] if asset_res else 0

    return {
        "instances": len(accessible_ids),
        "categories": cat_count,
        "subcategories": sub_count,
        "assets": asset_count,
    }


# =========================================================================
# 6. Scoped API Key Management
# =========================================================================

async def list_manager_keys(
    db: AsyncIOMotorDatabase, manager_id: str
) -> list[dict[str, Any]]:
    """List API keys owned by this manager without exposing secrets."""
    m_oid = to_object_id(manager_id)
    cursor = db[API_KEYS].find(
        {"$or": [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]},
        {"secret_hash": 0},
    ).sort("created_at", -1)

    docs = await cursor.to_list(length=1000)
    serialized = serialize_mongo_docs(docs)
    for d in serialized:
        d["is_revoked"] = bool(d.get("is_revoked") or d.get("revoked_at") or not d.get("is_active", True))
    return serialized


async def create_manager_key(
    db: AsyncIOMotorDatabase, manager_id: str, data: ApiKeyCreate
) -> ApiKeyOut:
    """Issue a new API key scoped to manager's accessible app instance."""
    from authorization.api_key import issue_api_key

    if not data.app_instance_id:
        raise ValidationError("App instance must be selected for the API key.")

    # Verify that the manager owns or has access to this app instance
    await verify_manager_instance_access(db, manager_id, data.app_instance_id)

    key_out = await issue_api_key(
        db,
        name=data.name,
        app_instance_id=data.app_instance_id,
        scopes=data.scopes,
        rate_limit_per_min=data.rate_limit_per_min,
        expires_at=data.expires_at,
    )

    # Attach owner_id to key document
    await db[API_KEYS].update_one(
        {"_id": to_object_id(key_out.id)},
        {"$set": {"owner_id": to_object_id(manager_id), "owner_role": "manager"}},
    )

    key_out.owner_id = manager_id
    key_out.owner_role = "manager"
    return key_out


async def revoke_manager_key(
    db: AsyncIOMotorDatabase, manager_id: str, key_id: str
) -> bool:
    """Revoke an API key owned by this manager."""
    from authorization.api_key import revoke_api_key

    k_oid = to_object_id(key_id)
    m_oid = to_object_id(manager_id)
    key_doc = await db[API_KEYS].find_one(
        {"_id": k_oid, "$or": [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]}
    )
    if not key_doc:
        raise ForbiddenError("API key not found or you do not have permission to modify it.")

    return await revoke_api_key(db, key_id)


async def delete_manager_key(
    db: AsyncIOMotorDatabase, manager_id: str, key_id: str
) -> bool:
    """Permanently delete an API key owned by this manager."""
    from authorization.api_key import delete_api_key

    k_oid = to_object_id(key_id)
    m_oid = to_object_id(manager_id)
    key_doc = await db[API_KEYS].find_one(
        {"_id": k_oid, "$or": [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]}
    )
    if not key_doc:
        raise ForbiddenError("API key not found or you do not have permission to delete it.")

    return await delete_api_key(db, key_id)


async def update_manager_key_rate_limit(
    db: AsyncIOMotorDatabase, manager_id: str, key_id: str, rate_limit: int
) -> bool:
    """Update rate limit on an API key owned by this manager."""
    k_oid = to_object_id(key_id)
    m_oid = to_object_id(manager_id)
    key_doc = await db[API_KEYS].find_one(
        {"_id": k_oid, "$or": [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]}
    )
    if not key_doc:
        raise ForbiddenError("API key not found or you do not have permission to modify it.")

    await db[API_KEYS].update_one(
        {"_id": k_oid},
        {"$set": {"rate_limit_per_min": max(1, rate_limit), "updated_at": utc_now()}},
    )
    return True


# =========================================================================
# 7. Messaging System (Manager Side)
# =========================================================================

async def send_manager_message(
    db: AsyncIOMotorDatabase,
    manager_id: str,
    sender_name: str,
    content: str,
    subject: str | None = None,
    payload_type: str | None = None,
    data_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a message or central data proposal to Admin."""
    if not content or not content.strip():
        raise ValidationError("Message content cannot be empty.")

    m_oid = to_object_id(manager_id)
    now = utc_now()

    doc: dict[str, Any] = {
        "manager_id": m_oid,
        "sender_role": "manager",
        "sender_id": m_oid,
        "sender_name": sender_name,
        "subject": subject.strip() if subject else None,
        "content": content.strip(),
        "payload_type": payload_type.strip().lower() if payload_type else None,
        "data_payload": data_payload,
        "status": "unread",
        "created_at": now,
        "updated_at": now,
    }

    res = await db[MESSAGES].insert_one(doc)
    await db[MANAGERS].update_one(
        {"_id": m_oid},
        {"$set": {"has_active_thread": True, "updated_at": now}},
    )
    doc["_id"] = res.inserted_id
    return serialize_mongo_doc(doc)  # type: ignore


async def get_manager_messages(
    db: AsyncIOMotorDatabase, manager_id: str
) -> list[dict[str, Any]]:
    """Get message thread history for this manager and mark admin messages as read."""
    m_oid = to_object_id(manager_id)

    # Mark incoming admin messages as read
    await db[MESSAGES].update_many(
        {
            "$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}],
            "sender_role": "admin",
            "status": "unread",
        },
        {"$set": {"status": "read", "updated_at": utc_now()}},
    )

    cursor = db[MESSAGES].find(
        {"$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}]}
    ).sort("created_at", 1)

    docs = await cursor.to_list(length=1000)
    return serialize_mongo_docs(docs)


# =========================================================================
# 8. Access Requests (Manager Side)
# =========================================================================

async def create_access_request(
    db: AsyncIOMotorDatabase,
    manager_id: str,
    app_instance_id: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Submit a structured request to access an app instance."""
    inst_oid = to_object_id(app_instance_id)
    manager_oid = to_object_id(manager_id)

    # Verify instance exists
    inst = await db[APP_INSTANCES].find_one({"_id": inst_oid})
    if not inst:
        raise NotFoundError("App instance not found")

    # Check if already owned
    if inst.get("owner_id") in [manager_oid, str(manager_oid)]:
        raise ConflictError("You already own this app instance.")

    # Check if already granted
    grant = await db[APP_INSTANCE_ACCESS].find_one(
        {"manager_id": manager_oid, "app_instance_id": inst_oid}
    )
    if grant:
        raise ConflictError("You already have access to this app instance.")

    # Check if pending request exists
    existing_req = await db[APP_INSTANCE_ACCESS_REQUESTS].find_one(
        {
            "requesting_manager_id": manager_oid,
            "app_instance_id": inst_oid,
            "status": "pending",
        }
    )
    if existing_req:
        raise ConflictError("You already have a pending access request for this app instance.")

    now = utc_now()
    doc: dict[str, Any] = {
        "requesting_manager_id": manager_oid,
        "app_instance_id": inst_oid,
        "status": "pending",
        "notes": notes.strip() if notes else None,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": now,
        "updated_at": now,
    }

    res = await db[APP_INSTANCE_ACCESS_REQUESTS].insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_mongo_doc(doc)  # type: ignore


async def list_manager_access_requests(
    db: AsyncIOMotorDatabase, manager_id: str
) -> list[dict[str, Any]]:
    """List access requests created by this manager."""
    m_oid = to_object_id(manager_id)
    cursor = db[APP_INSTANCE_ACCESS_REQUESTS].find(
        {"requesting_manager_id": m_oid}
    ).sort("created_at", -1)

    docs = await cursor.to_list(length=200)
    serialized = serialize_mongo_docs(docs)

    # Attach instance name
    for r in serialized:
        inst_oid = to_object_id(r["app_instance_id"])
        inst = await db[APP_INSTANCES].find_one({"_id": inst_oid}, {"name": 1})
        r["app_instance_name"] = inst["name"] if inst else "Unknown"

    return serialized
