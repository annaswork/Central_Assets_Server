"""Admin controller for managing Managers, reviewing messages and proposals, and approving access requests."""

from datetime import datetime
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from authorization.encryption import decrypt_password, encrypt_password, hash_password
from authorization.totp import verify_and_consume_backup_code, verify_totp_code
from controller.asset_controller import create_asset
from controller.base_controller import serialize_mongo_doc, serialize_mongo_docs
from controller.category_controller import create_category
from controller.subcategory_controller import create_subcategory
from database.collections import (
    ADMIN_USERS,
    API_KEYS,
    APP_INSTANCE_ACCESS,
    APP_INSTANCE_ACCESS_REQUESTS,
    APP_INSTANCES,
    ASSETS,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    MANAGERS,
    MESSAGES,
)
from database.models.asset import AssetCreate
from database.models.category import CategoryCreate
from database.models.subcategory import SubcategoryCreate
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from utils.ids import to_object_id


# =========================================================================
# 1. Manager Account Management
# =========================================================================

async def list_managers(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """List all manager accounts with instance counts and granted instances."""
    cursor = db[MANAGERS].find({}).sort("created_at", -1)
    managers = await cursor.to_list(length=1000)
    serialized = serialize_mongo_docs(managers)

    for m in serialized:
        m_oid = to_object_id(m["id"])

        # Count owned instances
        owned_count = await db[APP_INSTANCES].count_documents(
            {"$or": [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]}
        )
        m["owned_instances_count"] = owned_count

        # Fetch granted instances
        grants_cursor = db[APP_INSTANCE_ACCESS].find(
            {"$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}]}
        )
        grants = await grants_cursor.to_list(length=1000)
        granted_inst_ids = [to_object_id(g["app_instance_id"]) for g in grants]

        granted_instances = []
        if granted_inst_ids:
            inst_cursor = db[APP_INSTANCES].find({"_id": {"$in": granted_inst_ids}})
            inst_docs = await inst_cursor.to_list(length=1000)
            granted_instances = serialize_mongo_docs(inst_docs)

        m["granted_instances"] = granted_instances
        m["granted_instances_count"] = len(granted_instances)

    return serialized


async def grant_instance_access(
    db: AsyncIOMotorDatabase, manager_id: str, app_instance_id: str, admin_id: str | None = None
) -> dict[str, Any]:
    """Grant a manager access to a specific app instance."""
    m_oid = to_object_id(manager_id)
    inst_oid = to_object_id(app_instance_id)

    manager = await db[MANAGERS].find_one({"_id": m_oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    instance = await db[APP_INSTANCES].find_one({"_id": inst_oid})
    if not instance:
        raise NotFoundError("App instance not found")

    # If manager already owns this instance, no need to grant
    if instance.get("owner_id") in [m_oid, str(m_oid)]:
        raise ConflictError(f"Manager already owns '{instance['name']}'.")

    now = utc_now()
    doc = {
        "manager_id": m_oid,
        "app_instance_id": inst_oid,
        "granted_by": to_object_id(admin_id) if admin_id else None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        res = await db[APP_INSTANCE_ACCESS].update_one(
            {"manager_id": m_oid, "app_instance_id": inst_oid},
            {"$setOnInsert": doc},
            upsert=True,
        )
    except DuplicateKeyError:
        pass

    return {"success": True, "message": f"Access granted to '{instance['name']}'."}


async def revoke_instance_access(
    db: AsyncIOMotorDatabase, manager_id: str, app_instance_id: str
) -> dict[str, Any]:
    """Revoke a manager's access to an app instance."""
    m_oid = to_object_id(manager_id)
    inst_oid = to_object_id(app_instance_id)

    res = await db[APP_INSTANCE_ACCESS].delete_many(
        {
            "$or": [
                {"manager_id": m_oid, "app_instance_id": inst_oid},
                {"manager_id": str(m_oid), "app_instance_id": str(inst_oid)},
                {"manager_id": m_oid, "app_instance_id": str(inst_oid)},
                {"manager_id": str(m_oid), "app_instance_id": inst_oid},
            ]
        }
    )
    return {"success": True, "revoked_count": res.deleted_count}


async def delete_manager_account(
    db: AsyncIOMotorDatabase, manager_id: str
) -> dict[str, Any]:
    """Delete a manager account and cascade clean their owned app instances and access grants."""
    from controller.app_instance_controller import delete_app_instance

    m_oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": m_oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    # Cascade delete owned app instances
    owned_cursor = db[APP_INSTANCES].find({"$or": [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]})
    owned_instances = await owned_cursor.to_list(length=1000)
    for inst in owned_instances:
        try:
            await delete_app_instance(db, str(inst["_id"]))
        except Exception:
            pass

    # Clean up access grants
    await db[APP_INSTANCE_ACCESS].delete_many({"$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}]})

    # Clean up access requests
    await db[APP_INSTANCE_ACCESS_REQUESTS].delete_many(
        {"$or": [{"requesting_manager_id": m_oid}, {"requesting_manager_id": str(m_oid)}]}
    )

    # Clean up API keys owned by manager
    await db[API_KEYS].delete_many({"$or": [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]})

    # Clean up chat messages
    await db[MESSAGES].delete_many({"$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}]})

    # Delete manager document
    await db[MANAGERS].delete_one({"_id": m_oid})

    return {"success": True, "deleted_manager_id": str(m_oid)}


async def _verify_admin_2fa(
    db: AsyncIOMotorDatabase, admin_id: str, two_factor_code: str
) -> dict[str, Any]:
    """Helper to verify Admin's 2FA (TOTP code or backup code)."""
    admin_oid = to_object_id(admin_id)
    admin = await db[ADMIN_USERS].find_one({"_id": admin_oid})
    if not admin:
        raise UnauthorizedError("Admin account not found.")

    if not admin.get("is_active", True):
        raise UnauthorizedError("Admin account is deactivated.")

    if not admin.get("is_2fa_enabled") or not admin.get("totp_secret"):
        raise ValidationError(
            "Two-Factor Authentication (2FA) is not enabled on your Admin account. "
            "Please enable 2FA in Security settings to inspect or manage credentials."
        )

    code = (two_factor_code or "").strip()
    if not code:
        raise ValidationError("Please enter your 6-digit Two-Factor Authentication (2FA) code.")

    totp_secret = admin.get("totp_secret")
    if totp_secret and verify_totp_code(totp_secret, code):
        return admin

    # Check emergency backup code
    backup_codes = admin.get("backup_codes", [])
    matched, remaining = verify_and_consume_backup_code(backup_codes, code)
    if matched:
        await db[ADMIN_USERS].update_one(
            {"_id": admin_oid},
            {"$set": {"backup_codes": remaining, "updated_at": utc_now()}},
        )
        return admin

    raise UnauthorizedError("Invalid 2FA code or backup code. Verification failed.")


async def admin_verify_and_reveal_manager_password(
    db: AsyncIOMotorDatabase,
    admin_id: str,
    manager_id: str,
    two_factor_code: str,
) -> dict[str, Any]:
    """Verify admin's 2FA and reveal manager's password (if lost)."""
    await _verify_admin_2fa(db, admin_id, two_factor_code)

    m_oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": m_oid})
    if not manager:
        raise NotFoundError("Manager account not found.")

    encrypted_pw = manager.get("encrypted_password")
    if not encrypted_pw:
        return {
            "success": False,
            "has_encrypted_password": False,
            "manager_id": str(manager["_id"]),
            "username": manager["username"],
            "message": "This manager account was registered prior to encrypted credential storage. You can set a new password below.",
        }

    try:
        decrypted = decrypt_password(encrypted_pw)
        return {
            "success": True,
            "has_encrypted_password": True,
            "manager_id": str(manager["_id"]),
            "username": manager["username"],
            "password": decrypted,
        }
    except Exception as exc:
        return {
            "success": False,
            "has_encrypted_password": True,
            "manager_id": str(manager["_id"]),
            "username": manager["username"],
            "error": "Failed to decrypt password: key mismatch or corrupted cipher.",
        }


async def admin_reset_manager_password(
    db: AsyncIOMotorDatabase,
    admin_id: str,
    manager_id: str,
    two_factor_code: str,
    new_password: str,
) -> dict[str, Any]:
    """Verify admin's 2FA and set/reset manager's password."""
    await _verify_admin_2fa(db, admin_id, two_factor_code)

    clean_new_pw = (new_password or "").strip()
    if len(clean_new_pw) < 8:
        raise ValidationError("New password must be at least 8 characters long.")

    m_oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": m_oid})
    if not manager:
        raise NotFoundError("Manager account not found.")

    pw_hash = hash_password(clean_new_pw)
    encrypted_pw = encrypt_password(clean_new_pw)

    await db[MANAGERS].update_one(
        {"_id": m_oid},
        {
            "$set": {
                "password_hash": pw_hash,
                "encrypted_password": encrypted_pw,
                "updated_at": utc_now(),
            }
        },
    )

    return {
        "success": True,
        "manager_id": str(manager["_id"]),
        "username": manager["username"],
        "password": clean_new_pw,
        "message": f"Password for manager '{manager['username']}' updated successfully.",
    }


# =========================================================================
# 2. Admin Messaging & Proposal Review
# =========================================================================

async def list_message_threads(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """List all message threads grouped by manager."""
    pipeline = [
        {"$match": {"manager_id": {"$ne": None}, "channel_type": {"$ne": "admin_direct"}}},
        {"$sort": {"created_at": -1}},
        {
            "$group": {
                "_id": "$manager_id",
                "last_message": {"$first": "$$ROOT"},
                "total_messages": {"$sum": 1},
                "unread_count": {
                    "$sum": {
                        "$cond": [
                            {"$and": [{"$eq": ["$status", "unread"]}, {"$eq": ["$sender_role", "manager"]}]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"last_message.created_at": -1}},
    ]

    grouped = await db[MESSAGES].aggregate(pipeline).to_list(length=1000)
    threads = []
    seen_manager_ids = set()

    for g in grouped:
        manager_oid = to_object_id(g["_id"])
        manager = await db[MANAGERS].find_one({"_id": manager_oid})
        if not manager:
            continue
        if manager.get("has_active_thread") is False and g.get("total_messages", 0) == 0:
            continue

        seen_manager_ids.add(str(manager["_id"]))
        manager_name = manager["username"] if manager else "Unknown Manager"
        last_msg = serialize_mongo_doc(g["last_message"]) if g.get("last_message") else None
        threads.append(
            {
                "manager_id": str(manager["_id"]),
                "manager_name": manager_name,
                "manager_email": manager.get("email") if manager else None,
                "total_messages": g["total_messages"],
                "unread_count": g["unread_count"],
                "last_message": last_msg,
            }
        )

    # Also include managers with has_active_thread: True whose messages were cleared (0 messages)
    cleared_managers = await db[MANAGERS].find(
        {"has_active_thread": True, "_id": {"$nin": [to_object_id(mid) for mid in seen_manager_ids]}}
    ).to_list(length=100)

    for m in cleared_managers:
        threads.append(
            {
                "manager_id": str(m["_id"]),
                "manager_name": m.get("display_name") or m["username"],
                "manager_email": m.get("email"),
                "total_messages": 0,
                "unread_count": 0,
                "last_message": None,
            }
        )

    return threads


async def get_thread_messages(
    db: AsyncIOMotorDatabase, manager_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retrieve full message history for a manager and mark manager messages as read."""
    m_oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": m_oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    # Mark incoming messages as read
    await db[MESSAGES].update_many(
        {"manager_id": m_oid, "sender_role": "manager", "status": "unread"},
        {"$set": {"status": "read", "updated_at": utc_now()}},
    )

    cursor = db[MESSAGES].find(
        {"$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}]}
    ).sort("created_at", 1)
    docs = await cursor.to_list(length=1000)

    return serialize_mongo_doc(manager), serialize_mongo_docs(docs)  # type: ignore


async def clear_conversation(
    db: AsyncIOMotorDatabase, manager_id: str
) -> dict[str, Any]:
    """Permanently delete all messages in this conversation while keeping the thread in the conversation list."""
    m_oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": m_oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    res = await db[MESSAGES].delete_many(
        {"$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}]}
    )
    await db[MANAGERS].update_one(
        {"_id": m_oid},
        {"$set": {"has_active_thread": True, "updated_at": utc_now()}},
    )
    return {"success": True, "deleted_count": res.deleted_count}


async def delete_chat_thread(
    db: AsyncIOMotorDatabase, manager_id: str
) -> dict[str, Any]:
    """Permanently delete all messages and remove the chat thread from the admin inbox."""
    m_oid = to_object_id(manager_id)
    manager = await db[MANAGERS].find_one({"_id": m_oid})
    if not manager:
        raise NotFoundError("Manager account not found")

    res = await db[MESSAGES].delete_many(
        {"$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}]}
    )
    await db[MANAGERS].update_one(
        {"_id": m_oid},
        {"$set": {"has_active_thread": False, "updated_at": utc_now()}},
    )
    return {"success": True, "deleted_count": res.deleted_count}


async def admin_reply_message(
    db: AsyncIOMotorDatabase,
    manager_id: str,
    admin_id: str,
    admin_name: str,
    content: str,
    subject: str | None = None,
) -> dict[str, Any]:
    """Send an Admin reply message into the manager's thread."""
    if not content or not content.strip():
        raise ValidationError("Reply content cannot be empty.")

    m_oid = to_object_id(manager_id)
    now = utc_now()

    doc: dict[str, Any] = {
        "manager_id": m_oid,
        "sender_role": "admin",
        "sender_id": to_object_id(admin_id),
        "sender_name": admin_name or "Administrator",
        "subject": subject.strip() if subject else None,
        "content": content.strip(),
        "payload_type": None,
        "data_payload": None,
        "status": "read",
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


async def apply_message_proposal_to_central(
    db: AsyncIOMotorDatabase,
    message_id: str,
    category_id: str | None = None,
    sub_category_id: str | None = None,
) -> dict[str, Any]:
    """Review and apply a manager's structured proposal payload into central library data."""
    msg_oid = to_object_id(message_id)
    msg = await db[MESSAGES].find_one({"_id": msg_oid})
    if not msg:
        raise NotFoundError("Message not found")

    payload_type = (msg.get("payload_type") or "").lower()
    data_payload = msg.get("data_payload") or {}

    if not payload_type or not data_payload:
        raise ValidationError("This message does not contain a structured data proposal.")

    created_record = None

    if payload_type == "category":
        name = data_payload.get("name")
        if not name or not str(name).strip():
            raise ValidationError("Proposed category requires a valid name.")
        cat_create = CategoryCreate(
            name=str(name).strip(),
            thumbnail_url=data_payload.get("thumbnail_url"),
            image_url=data_payload.get("image_url"),
        )
        created_record = await create_category(db, cat_create)

    elif payload_type == "subcategory":
        name = data_payload.get("name")
        cat_id = category_id or data_payload.get("category_id") or data_payload.get("categoryId")
        if not name or not str(name).strip():
            raise ValidationError("Proposed subcategory requires a valid name.")
        if not cat_id:
            raise ValidationError("Proposed subcategory requires a parent categoryId.")
        sub_create = SubcategoryCreate(
            name=str(name).strip(),
            categoryId=str(cat_id),
            thumbnail_url=data_payload.get("thumbnail_url"),
            image_url=data_payload.get("image_url"),
        )
        created_record = await create_subcategory(db, sub_create)

    elif payload_type == "asset":
        name = data_payload.get("name")
        clean_cat = category_id.strip() if category_id and category_id.strip() else None
        clean_sub = sub_category_id.strip() if sub_category_id and sub_category_id.strip() else None

        cat_id = clean_cat or data_payload.get("category_id") or data_payload.get("categoryId")
        sub_id = clean_sub or (
            data_payload.get("sub_category_id") or data_payload.get("subCategoryId")
            if category_id is None
            else None
        )
        if not name or not str(name).strip():
            raise ValidationError("Proposed asset requires a valid name.")
        if not cat_id or not sub_id:
            raise ValidationError("Proposed asset requires categoryId and subCategoryId.")

        media_url = data_payload.get("media_url") or data_payload.get("thumbnail_url")
        raw_more_fields = data_payload.get("more_fields") or data_payload.get("moreFields")
        more_fields = dict(raw_more_fields) if isinstance(raw_more_fields, dict) else {}

        if not more_fields and media_url:
            ext = Path(str(media_url).split("?")[0]).suffix.lower().lstrip(".")
            meta = data_payload.get("file_metadata") or {}
            filename = data_payload.get("media_filename") or Path(str(media_url)).name
            if ext in ("mp4", "webm", "mov", "avi", "mkv"):
                more_fields["video"] = {
                    "type": "video",
                    "url": media_url,
                    "urls": [media_url],
                    "items": [{
                        "url": media_url,
                        "filename": filename,
                        "size_bytes": meta.get("size_bytes"),
                        "mime": meta.get("mime_type") or "video/mp4",
                        "duration": meta.get("duration"),
                        "duration_ms": meta.get("duration_ms"),
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                    }],
                }
            elif ext in ("mp3", "wav", "ogg", "m4a", "aac", "flac"):
                more_fields["audio"] = {
                    "type": "audio",
                    "url": media_url,
                    "urls": [media_url],
                    "items": [{
                        "url": media_url,
                        "filename": filename,
                        "size_bytes": meta.get("size_bytes"),
                        "mime": meta.get("mime_type") or "audio/mpeg",
                        "duration": meta.get("duration"),
                        "duration_ms": meta.get("duration_ms"),
                    }],
                }
            elif ext == "json":
                more_fields["json_data"] = {
                    "type": "json",
                    "url": media_url,
                }
            else:
                more_fields["image"] = {
                    "type": "image",
                    "url": media_url,
                    "urls": [media_url],
                    "items": [{
                        "url": media_url,
                        "filename": filename,
                        "size_bytes": meta.get("size_bytes"),
                        "mime": meta.get("mime_type") or "image/png",
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                    }],
                }

        asset_create = AssetCreate(
            name=str(name).strip(),
            description=data_payload.get("description", ""),
            category_id=str(cat_id),
            sub_category_id=str(sub_id),
            thumbnail_url=data_payload.get("thumbnail_url") or media_url,
            more_fields=more_fields,
        )
        created_record = await create_asset(db, asset_create)

    else:
        raise ValidationError(f"Unsupported payload type: '{payload_type}'")

    # Mark proposal as applied and update payload with chosen category/subcategory
    update_doc: dict[str, Any] = {
        "status": "applied",
        "applied_at": utc_now(),
        "updated_at": utc_now(),
    }
    if payload_type == "asset":
        update_doc["data_payload.category_id"] = str(cat_id)
        update_doc["data_payload.sub_category_id"] = str(sub_id)
    elif payload_type == "subcategory":
        update_doc["data_payload.category_id"] = str(cat_id)

    await db[MESSAGES].update_one(
        {"_id": msg_oid},
        {"$set": update_doc},
    )

    return {
        "success": True,
        "message": f"Proposal successfully applied to central {payload_type} library.",
        "created_record": created_record,
    }


# =========================================================================
# 3. Access Request Queue
# =========================================================================

async def list_access_requests(
    db: AsyncIOMotorDatabase, status: str | None = None
) -> list[dict[str, Any]]:
    """List all structured access requests with manager and instance metadata."""
    query: dict[str, Any] = {}
    if status and status != "all":
        query["status"] = status

    cursor = db[APP_INSTANCE_ACCESS_REQUESTS].find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=1000)
    serialized = serialize_mongo_docs(docs)

    for r in serialized:
        # Requesting manager
        req_m_id = r.get("requesting_manager_id") or r.get("manager_id")
        m_oid = to_object_id(req_m_id) if req_m_id else None
        mgr = await db[MANAGERS].find_one({"_id": m_oid}, {"username": 1, "email": 1}) if m_oid else None
        r["manager_username"] = mgr["username"] if mgr else "Unknown Manager"
        r["manager_email"] = mgr.get("email") if mgr else None

        # App instance
        inst_oid = to_object_id(r["app_instance_id"])
        inst = await db[APP_INSTANCES].find_one({"_id": inst_oid}, {"name": 1, "package_name": 1})
        r["app_instance_name"] = inst["name"] if inst else "Unknown App"
        r["app_package_name"] = inst.get("package_name") if inst else None

    return serialized


async def approve_access_request(
    db: AsyncIOMotorDatabase, request_id: str, admin_id: str | None = None
) -> dict[str, Any]:
    """Approve access request: grant access in APP_INSTANCE_ACCESS and update request status."""
    r_oid = to_object_id(request_id)
    req = await db[APP_INSTANCE_ACCESS_REQUESTS].find_one({"_id": r_oid})
    if not req:
        raise NotFoundError("Access request not found")

    manager_id = str(req["requesting_manager_id"])
    instance_id = str(req["app_instance_id"])

    # Grant access
    await grant_instance_access(db, manager_id=manager_id, app_instance_id=instance_id, admin_id=admin_id)

    # Update request status
    now = utc_now()
    await db[APP_INSTANCE_ACCESS_REQUESTS].update_one(
        {"_id": r_oid},
        {
            "$set": {
                "status": "approved",
                "reviewed_by": to_object_id(admin_id) if admin_id else None,
                "reviewed_at": now,
                "updated_at": now,
            }
        },
    )

    return {"success": True, "message": "Access request approved and granted."}


async def deny_access_request(
    db: AsyncIOMotorDatabase, request_id: str, admin_id: str | None = None
) -> dict[str, Any]:
    """Deny an access request."""
    r_oid = to_object_id(request_id)
    req = await db[APP_INSTANCE_ACCESS_REQUESTS].find_one({"_id": r_oid})
    if not req:
        raise NotFoundError("Access request not found")

    now = utc_now()
    await db[APP_INSTANCE_ACCESS_REQUESTS].update_one(
        {"_id": r_oid},
        {
            "$set": {
                "status": "denied",
                "reviewed_by": to_object_id(admin_id) if admin_id else None,
                "reviewed_at": now,
                "updated_at": now,
            }
        },
    )

    return {"success": True, "message": "Access request denied."}


# =========================================================================
# 4. Admin Team Cross-Communication (Admin ↔ Admin Direct Chat)
# =========================================================================

async def list_admin_conversations(
    db: AsyncIOMotorDatabase, current_admin_id: str
) -> list[dict[str, Any]]:
    """List all other administrators and their direct message threads with current admin."""
    curr_oid = to_object_id(current_admin_id)

    # Fetch all other active admins
    cursor = db[ADMIN_USERS].find({
        "_id": {"$nin": [curr_oid, str(curr_oid)]},
        "is_active": {"$ne": False},
    })
    other_admins = await cursor.to_list(length=200)

    conversations: list[dict[str, Any]] = []

    for admin in other_admins:
        other_oid = admin["_id"]

        # Fetch last message between curr_admin and other_admin
        last_msg = await db[MESSAGES].find_one(
            {
                "channel_type": "admin_direct",
                "$or": [
                    {
                        "sender_id": {"$in": [curr_oid, str(curr_oid)]},
                        "recipient_id": {"$in": [other_oid, str(other_oid)]},
                    },
                    {
                        "sender_id": {"$in": [other_oid, str(other_oid)]},
                        "recipient_id": {"$in": [curr_oid, str(curr_oid)]},
                    },
                ],
            },
            sort=[("created_at", -1)],
        )

        # Count unread messages sent by other_admin to curr_admin
        unread_count = await db[MESSAGES].count_documents(
            {
                "channel_type": "admin_direct",
                "sender_id": {"$in": [other_oid, str(other_oid)]},
                "recipient_id": {"$in": [curr_oid, str(curr_oid)]},
                "status": "unread",
            }
        )

        name = admin.get("full_name") or admin.get("display_name") or admin.get("username") or "Admin"
        initial = (name or "A")[:1].upper()

        conversations.append(
            {
                "admin_id": str(admin["_id"]),
                "username": admin.get("username"),
                "display_name": name,
                "email": admin.get("email"),
                "profile_picture": admin.get("profile_picture"),
                "initial": initial,
                "unread_count": unread_count,
                "last_message": serialize_mongo_doc(last_msg) if last_msg else None,
            }
        )

    # Sort: conversations with messages first (most recent first), then alphabetically
    def sort_key(conv: dict[str, Any]):
        lm = conv.get("last_message")
        if lm and lm.get("created_at"):
            ts = lm["created_at"]
            if isinstance(ts, datetime):
                return (1, ts.timestamp())
            elif isinstance(ts, str):
                try:
                    return (1, datetime.fromisoformat(ts).timestamp())
                except Exception:
                    return (1, 0)
            return (1, 0)
        return (0, 0)

    conversations.sort(key=sort_key, reverse=True)
    return conversations


async def get_admin_direct_messages(
    db: AsyncIOMotorDatabase, current_admin_id: str, other_admin_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retrieve direct message history between current admin and another admin, marking incoming as read."""
    curr_oid = to_object_id(current_admin_id)
    other_oid = to_object_id(other_admin_id)

    other_admin = await db[ADMIN_USERS].find_one({"_id": other_oid})
    if not other_admin:
        raise NotFoundError("Administrator account not found.")

    # Mark incoming unread messages as read
    await db[MESSAGES].update_many(
        {
            "channel_type": "admin_direct",
            "sender_id": {"$in": [other_oid, str(other_oid)]},
            "recipient_id": {"$in": [curr_oid, str(curr_oid)]},
            "status": "unread",
        },
        {"$set": {"status": "read", "updated_at": utc_now()}},
    )

    cursor = db[MESSAGES].find(
        {
            "channel_type": "admin_direct",
            "$or": [
                {
                    "sender_id": {"$in": [curr_oid, str(curr_oid)]},
                    "recipient_id": {"$in": [other_oid, str(other_oid)]},
                },
                {
                    "sender_id": {"$in": [other_oid, str(other_oid)]},
                    "recipient_id": {"$in": [curr_oid, str(curr_oid)]},
                },
            ],
        }
    ).sort("created_at", 1)

    docs = await cursor.to_list(length=1000)

    name = other_admin.get("full_name") or other_admin.get("display_name") or other_admin.get("username") or "Admin"
    other_admin_data = serialize_mongo_doc(other_admin)
    other_admin_data["display_name"] = name
    other_admin_data["initial"] = (name or "A")[:1].upper()

    return other_admin_data, serialize_mongo_docs(docs)  # type: ignore


async def send_admin_direct_message(
    db: AsyncIOMotorDatabase,
    sender_id: str,
    sender_name: str,
    recipient_id: str,
    content: str,
) -> dict[str, Any]:
    """Send a direct message from one admin to another admin."""
    clean_content = (content or "").strip()
    if not clean_content:
        raise ValidationError("Message content cannot be empty.")

    s_oid = to_object_id(sender_id)
    r_oid = to_object_id(recipient_id)

    recipient = await db[ADMIN_USERS].find_one({"_id": r_oid})
    if not recipient:
        raise NotFoundError("Recipient administrator account not found.")

    recipient_name = recipient.get("full_name") or recipient.get("display_name") or recipient.get("username") or "Admin"
    now = utc_now()

    doc: dict[str, Any] = {
        "channel_type": "admin_direct",
        "sender_id": s_oid,
        "recipient_id": r_oid,
        "sender_name": sender_name or "Administrator",
        "recipient_name": recipient_name,
        "sender_role": "admin",
        "recipient_role": "admin",
        "content": clean_content,
        "payload_type": None,
        "data_payload": None,
        "status": "unread",
        "created_at": now,
        "updated_at": now,
    }

    res = await db[MESSAGES].insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_mongo_doc(doc)  # type: ignore


async def clear_admin_direct_conversation(
    db: AsyncIOMotorDatabase, current_admin_id: str, other_admin_id: str
) -> dict[str, Any]:
    """Permanently delete all direct messages between two administrators."""
    curr_oid = to_object_id(current_admin_id)
    other_oid = to_object_id(other_admin_id)

    res = await db[MESSAGES].delete_many(
        {
            "channel_type": "admin_direct",
            "$or": [
                {
                    "sender_id": {"$in": [curr_oid, str(curr_oid)]},
                    "recipient_id": {"$in": [other_oid, str(other_oid)]},
                },
                {
                    "sender_id": {"$in": [other_oid, str(other_oid)]},
                    "recipient_id": {"$in": [curr_oid, str(curr_oid)]},
                },
            ],
        }
    )
    return {"success": True, "deleted_count": res.deleted_count}
