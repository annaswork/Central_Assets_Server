"""App Instance controller managing application entities and branding icons."""

from typing import Any

import anyio
from motor.motor_asyncio import AsyncIOMotorDatabase

from config.paths import APP_DATA_DIR, app_icon_url
from controller.base_controller import format_page_response, serialize_mongo_doc
from database.collections import (
    APP_INSTANCES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
)
from database.models.app_instance import AppInstanceCreate, AppInstanceUpdate
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError
from utils.ids import to_object_id
from utils.image_utils import generate_thumbnail


async def list_app_instances(
    db: AsyncIOMotorDatabase,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    instance_ids: list[str] | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """List app instances with pagination, optionally scoped by IDs or owner."""
    query: dict[str, Any] = {}
    if search and search.strip():
        query["name"] = {"$regex": search.strip(), "$options": "i"}

    if instance_ids is not None:
        query["_id"] = {"$in": [to_object_id(i) for i in instance_ids]}

    if owner_id:
        m_oid = to_object_id(owner_id)
        query["$or"] = [{"owner_id": m_oid}, {"owner_id": str(m_oid)}]

    skip = (page - 1) * page_size
    total = await db[APP_INSTANCES].count_documents(query)
    cursor = db[APP_INSTANCES].find(query).skip(skip).limit(page_size).sort("name", 1)
    items = await cursor.to_list(length=page_size)
    return format_page_response(items, total, page, page_size)


async def get_app_instance(db: AsyncIOMotorDatabase, instance_id: str) -> dict[str, Any]:
    """Retrieve single app instance by ID."""
    oid = to_object_id(instance_id)
    doc = await db[APP_INSTANCES].find_one({"_id": oid})
    if not doc:
        raise NotFoundError("App instance not found")
    return serialize_mongo_doc(doc)  # type: ignore


async def create_app_instance(db: AsyncIOMotorDatabase, data: AppInstanceCreate) -> dict[str, Any]:
    """Create a new app instance enforcing unique name and package_name."""
    name_clean = data.name.strip()
    existing = await db[APP_INSTANCES].find_one({"name": name_clean})
    if existing:
        raise ConflictError(f"App instance with name '{name_clean}' already exists")

    pkg_clean = (
        data.package_name.strip()
        if (data.package_name and data.package_name.strip() and data.package_name.strip().lower() != "none")
        else None
    )
    if pkg_clean:
        pkg_existing = await db[APP_INSTANCES].find_one({"package_name": pkg_clean})
        if pkg_existing:
            raise ConflictError(f"App with package name '{pkg_clean}' already exists")

    now = utc_now()
    doc: dict[str, Any] = {
        "name": name_clean,
        "app_icon": data.app_icon,
        "owner_id": to_object_id(data.owner_id) if data.owner_id else None,
        "created_at": now,
        "updated_at": now,
    }
    if pkg_clean:
        doc["package_name"] = pkg_clean

    res = await db[APP_INSTANCES].insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_mongo_doc(doc)  # type: ignore


async def update_app_instance(
    db: AsyncIOMotorDatabase, instance_id: str, data: AppInstanceUpdate
) -> dict[str, Any]:
    """Update an app instance's details."""
    oid = to_object_id(instance_id)
    existing = await db[APP_INSTANCES].find_one({"_id": oid})
    if not existing:
        raise NotFoundError("App instance not found")

    update_fields: dict[str, Any] = {}
    unset_fields: dict[str, Any] = {}

    if data.name is not None:
        name_clean = data.name.strip()
        conflict = await db[APP_INSTANCES].find_one({"name": name_clean, "_id": {"$ne": oid}})
        if conflict:
            raise ConflictError(f"App instance with name '{name_clean}' already exists")
        update_fields["name"] = name_clean

    if data.package_name is not None:
        pkg_clean = (
            data.package_name.strip()
            if (data.package_name and data.package_name.strip() and data.package_name.strip().lower() != "none")
            else None
        )
        if pkg_clean:
            pkg_conflict = await db[APP_INSTANCES].find_one(
                {"package_name": pkg_clean, "_id": {"$ne": oid}}
            )
            if pkg_conflict:
                raise ConflictError(f"Package name '{pkg_clean}' already in use by another app")
            update_fields["package_name"] = pkg_clean
        else:
            unset_fields["package_name"] = ""

    if data.app_icon is not None:
        update_fields["app_icon"] = data.app_icon

    update_op: dict[str, Any] = {}
    if update_fields or unset_fields:
        update_fields["updated_at"] = utc_now()
        if update_fields:
            update_op["$set"] = update_fields
        if unset_fields:
            update_op["$unset"] = unset_fields
        await db[APP_INSTANCES].update_one({"_id": oid}, update_op)

    updated = await db[APP_INSTANCES].find_one({"_id": oid})
    return serialize_mongo_doc(updated)  # type: ignore


async def delete_app_instance(db: AsyncIOMotorDatabase, instance_id: str) -> dict[str, Any]:
    """Delete an app instance and its reference rows.

    Leaves all central creative library data completely intact.
    """
    oid = to_object_id(instance_id)
    res = await db[APP_INSTANCES].delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise NotFoundError("App instance not found")

    now = utc_now()
    # Soft delete all instance reference rows for this app
    await db[INSTANCE_CATEGORIES].update_many(
        {"app_instance_id": oid}, {"$set": {"deleted_at": now}}
    )
    await db[INSTANCE_SUBCATEGORIES].update_many(
        {"app_instance_id": oid}, {"$set": {"deleted_at": now}}
    )
    await db[INSTANCE_ASSETS].update_many({"app_instance_id": oid}, {"$set": {"deleted_at": now}})

    return {"success": True, "deleted_instance_id": str(oid)}


async def upload_instance_icon(
    db: AsyncIOMotorDatabase, instance_id: str, file_bytes: bytes, filename: str
) -> dict[str, Any]:
    """Save an app icon to static/app_data/{instance_id}/ and update instance record."""
    oid = to_object_id(instance_id)
    existing = await db[APP_INSTANCES].find_one({"_id": oid})
    if not existing:
        raise NotFoundError("App instance not found")

    dest_dir = APP_DATA_DIR / str(oid)
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / "icon.png"
    async with await anyio.open_file(dest_file, "wb") as f:
        await f.write(file_bytes)

    # Generate thumbnail
    try:
        thumb_bytes = await anyio.to_thread.run_sync(generate_thumbnail, file_bytes, (128, 128))
        thumb_file = dest_dir / "icon_thumbnail.webp"
        async with await anyio.open_file(thumb_file, "wb") as f:
            await f.write(thumb_bytes)
    except Exception:
        pass

    icon_url = app_icon_url(str(oid), "icon.png")
    await db[APP_INSTANCES].update_one(
        {"_id": oid},
        {"$set": {"app_icon": icon_url, "updated_at": utc_now()}},
    )

    return {"app_icon": icon_url}
