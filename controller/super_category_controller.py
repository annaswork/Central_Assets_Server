"""Central Super Categories: optional top level grouping categories (Super Category → Category → Subcategory → Asset).

Only categories point up to a super category (`categories.super_category_id`); subcategories, assets and
storage paths are unaware of this level.
"""

import re
import shutil
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from config.paths import get_category_dir
from controller.base_controller import serialize_mongo_doc
from database.collections import (
    CATEGORIES,
    INSTANCE_CATEGORIES,
    INSTANCE_SUPER_CATEGORIES,
    SUPER_CATEGORIES,
)
from database.models.super_category import SuperCategoryCreate, SuperCategoryUpdate
from database.repository import CentralRepository
from utils.errors import ConflictError, NotFoundError, ValidationError
from utils.ids import to_object_id
from utils.sequencing import compute_next_sequence
from utils.slugify import slugify


def super_category_folder(name: str) -> str:
    """Media folder (under central_data) for a super category's banner/thumbnail."""
    return f"_super/{slugify(name.strip()) or 'super'}"


async def resolve_super_category_id(db: AsyncIOMotorDatabase, raw_id: str | None) -> ObjectId | None:
    """Validate an optional super category id from user input. '' / None means "no super category"."""
    if not raw_id or not str(raw_id).strip():
        return None
    try:
        oid = to_object_id(str(raw_id).strip())
    except ValueError as err:
        raise ValidationError("Invalid super category id") from err
    if not await CentralRepository(db, SUPER_CATEGORIES).find_by_id(oid):
        raise NotFoundError("Super category not found")
    return oid


async def list_super_categories(db: AsyncIOMotorDatabase, search: str | None = None) -> list[dict[str, Any]]:
    """All central super categories (sequence order) with their category counts."""
    query: dict[str, Any] = {}
    if search and search.strip():
        query["name"] = {"$regex": re.escape(search.strip()), "$options": "i"}
    # ponytail: unpaginated, super categories are a handful per library; paginate if that stops being true
    docs = await CentralRepository(db, SUPER_CATEGORIES).find_many(
        query, limit=1000, sort=[("sequence", 1), ("name", 1)]
    )
    items = []
    for doc in docs:
        item = serialize_mongo_doc(doc)
        item["category_count"] = await db[CATEGORIES].count_documents(
            {"super_category_id": doc["_id"], "deleted_at": None}
        )
        items.append(item)
    return items


async def get_super_category(db: AsyncIOMotorDatabase, super_category_id: str) -> dict[str, Any]:
    doc = await CentralRepository(db, SUPER_CATEGORIES).find_by_id(super_category_id)
    if not doc:
        raise NotFoundError("Super category not found")
    return serialize_mongo_doc(doc)  # type: ignore


async def _ensure_unique_name(repo: CentralRepository, name: str, exclude: ObjectId | None = None) -> None:
    query: dict[str, Any] = {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
    if exclude:
        query["_id"] = {"$ne": exclude}
    if await repo.find_one(query):
        raise ConflictError(f"Super category with name '{name}' already exists")


async def create_super_category(db: AsyncIOMotorDatabase, data: SuperCategoryCreate) -> dict[str, Any]:
    repo = CentralRepository(db, SUPER_CATEGORIES)
    name = data.name.strip()
    await _ensure_unique_name(repo, name)

    sequence = data.sequence
    if sequence is None:
        last = await repo.find_many({}, sort=[("sequence", -1)], limit=1)
        sequence = compute_next_sequence(last[0].get("sequence") if last else None)

    doc = {
        "name": name,
        "folder_name": super_category_folder(name),
        "thumbnail_url": data.thumbnail_url,
        "image_url": data.image_url,
        "sequence": sequence,
        "deleted_at": None,
    }
    doc["_id"] = await repo.insert_one(doc)
    return serialize_mongo_doc(doc)  # type: ignore


async def update_super_category(
    db: AsyncIOMotorDatabase, super_category_id: str, data: SuperCategoryUpdate
) -> dict[str, Any]:
    repo = CentralRepository(db, SUPER_CATEGORIES)
    oid = to_object_id(super_category_id)
    if not await repo.find_by_id(oid):
        raise NotFoundError("Super category not found")

    fields: dict[str, Any] = {}
    if data.name is not None:
        fields["name"] = data.name.strip()
        await _ensure_unique_name(repo, fields["name"], exclude=oid)
    for key in ("thumbnail_url", "image_url", "sequence"):
        if key in data.model_fields_set:
            fields[key] = getattr(data, key)
    if fields:
        await repo.update_one({"_id": oid}, {"$set": fields})
    return await get_super_category(db, str(oid))


async def delete_super_category(db: AsyncIOMotorDatabase, super_category_id: str) -> dict[str, Any]:
    """Delete an empty super category. App instances that referenced it keep their categories, ungrouped."""
    repo = CentralRepository(db, SUPER_CATEGORIES)
    oid = to_object_id(super_category_id)
    doc = await repo.find_by_id(oid)
    if not doc:
        raise NotFoundError("Super category not found")

    assigned = await db[CATEGORIES].count_documents({"super_category_id": oid, "deleted_at": None})
    if assigned:
        raise ConflictError(
            f"Super category '{doc['name']}' still has {assigned} categor{'y' if assigned == 1 else 'ies'}. "
            "Move or ungroup them first.",
            details={"categories_count": assigned},
        )

    await repo.hard_delete({"_id": oid})

    inst_super_ids = await db[INSTANCE_SUPER_CATEGORIES].distinct("_id", {"source_id": oid})
    if inst_super_ids:
        await db[INSTANCE_CATEGORIES].update_many(
            {"super_category_id": {"$in": inst_super_ids}}, {"$set": {"super_category_id": None}}
        )
        await db[INSTANCE_SUPER_CATEGORIES].delete_many({"_id": {"$in": inst_super_ids}})

    media_dir = get_category_dir(doc.get("folder_name") or super_category_folder(doc["name"]))
    if media_dir.is_dir():
        shutil.rmtree(media_dir, ignore_errors=True)

    return {"success": True, "deleted_id": str(oid), "ungrouped_instance_super_categories": len(inst_super_ids)}
