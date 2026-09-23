"""Admin controller for managing Managers, reviewing messages and proposals, and approving access requests."""

from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from controller.base_controller import serialize_mongo_doc, serialize_mongo_docs
from controller.category_controller import create_category
from controller.subcategory_controller import create_subcategory
from database.collections import (
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
from database.models.category import CategoryCreate
from database.models.subcategory import SubcategoryCreate
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError, ValidationError
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


# =========================================================================
# 2. Admin Messaging & Proposal Review
# =========================================================================

async def list_message_threads(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """List all message threads grouped by manager."""
    pipeline = [
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
    db: AsyncIOMotorDatabase, message_id: str
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
        cat_id = data_payload.get("category_id") or data_payload.get("categoryId")
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
        cat_id = data_payload.get("category_id") or data_payload.get("categoryId")
        sub_id = data_payload.get("sub_category_id") or data_payload.get("subCategoryId")
        if not name or not str(name).strip():
            raise ValidationError("Proposed asset requires a valid name.")
        if not cat_id or not sub_id:
            raise ValidationError("Proposed asset requires categoryId and subCategoryId.")

        # Insert asset into central collection
        now = utc_now()
        asset_doc = {
            "name": str(name).strip(),
            "description": data_payload.get("description", ""),
            "category_id": to_object_id(str(cat_id)),
            "sub_category_id": to_object_id(str(sub_id)),
            "thumbnail_url": data_payload.get("thumbnail_url"),
            "more_fields": data_payload.get("more_fields") or data_payload.get("moreFields") or {},
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        res = await db[ASSETS].insert_one(asset_doc)
        asset_doc["_id"] = res.inserted_id
        created_record = serialize_mongo_doc(asset_doc)

    else:
        raise ValidationError(f"Unsupported payload type: '{payload_type}'")

    # Mark proposal as applied
    await db[MESSAGES].update_one(
        {"_id": msg_oid},
        {"$set": {"status": "applied", "applied_at": utc_now(), "updated_at": utc_now()}},
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
