import shutil
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.paths import ROOT_DIR, get_subcategory_dir
from controller.asset_controller import delete_asset_file_from_disk
from controller.base_controller import format_page_response, serialize_mongo_doc
from database.collections import (
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_SUBCATEGORIES,
    SUBCATEGORIES,
)
from database.models.subcategory import SubcategoryCreate, SubcategoryUpdate
from database.repository import CentralRepository
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError
from utils.ids import to_object_id
from utils.image_utils import generate_scaled_thumbnail
from utils.responses import bulk_item_result, bulk_response
from utils.sequencing import compute_next_sequence
from utils.slugify import slugify


async def list_subcategories(
    db: AsyncIOMotorDatabase,
    category_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    sort_by: str = "sequence",
    sort_order: str = "asc",
) -> dict[str, Any]:
    """List central subcategories with pagination, optional category/search filter, and sorting."""
    repo = CentralRepository(db, SUBCATEGORIES)
    query: dict[str, Any] = {}
    if category_id:
        try:
            cat_oid = to_object_id(category_id)
            query["$or"] = [{"category_id": cat_oid}, {"category_id": str(category_id)}]
        except Exception:
            query["category_id"] = str(category_id)
    if search and search.strip():
        query["name"] = {"$regex": search.strip(), "$options": "i"}

    # Determine sort field and direction
    s_lower = (sort_by or "sequence").lower()
    if s_lower in ("sequence", "order", "custom"):
        sort_field = "sequence"
        direction = 1 if (sort_order or "asc").lower() in ("asc", "1") else -1
    elif s_lower == "oldest":
        sort_field = "created_at"
        direction = 1
    elif s_lower in ("newest", "created_at", "created"):
        sort_field = "created_at"
        direction = 1 if (sort_order or "desc").lower() in ("asc", "1") else -1
    elif s_lower == "name":
        sort_field = "name"
        direction = 1 if (sort_order or "asc").lower() in ("asc", "1") else -1
    else:
        sort_field = "sequence"
        direction = 1 if (sort_order or "asc").lower() in ("asc", "1") else -1

    sort = [(sort_field, direction)]
    if sort_field != "created_at":
        sort.append(("created_at", direction))
    sort.append(("_id", direction))

    skip = (page - 1) * page_size
    total = await repo.count(query)
    items = await repo.find_many(query=query, skip=skip, limit=page_size, sort=sort)
    return format_page_response(items, total, page, page_size)


async def get_subcategory(db: AsyncIOMotorDatabase, subcategory_id: str) -> dict[str, Any]:
    """Retrieve a single central subcategory by ID."""
    repo = CentralRepository(db, SUBCATEGORIES)
    doc = await repo.find_by_id(subcategory_id)
    if not doc:
        raise NotFoundError("Subcategory not found")
    return serialize_mongo_doc(doc)  # type: ignore


async def create_subcategory(db: AsyncIOMotorDatabase, data: SubcategoryCreate) -> dict[str, Any]:
    """Create a new central subcategory under a valid parent category."""
    cat_repo = CentralRepository(db, CATEGORIES)
    cat_oid = to_object_id(data.category_id)
    parent_cat = await cat_repo.find_by_id(cat_oid)
    if not parent_cat:
        raise NotFoundError(f"Parent category '{data.category_id}' does not exist")

    repo = CentralRepository(db, SUBCATEGORIES)
    name_clean = data.name.strip()
    existing = await repo.find_one(
        {
            "category_id": cat_oid,
            "name": {"$regex": f"^{name_clean}$", "$options": "i"},
        }
    )
    if existing:
        raise ConflictError(
            f"Subcategory '{name_clean}' already exists under parent category '{parent_cat['name']}'"
        )

    parent_folder = parent_cat.get("folder_name") or slugify(parent_cat["name"]) or "category"
    sub_folder = slugify(name_clean) or "subcategory"
    sub_dir = get_subcategory_dir(parent_folder, sub_folder)
    sub_dir.mkdir(parents=True, exist_ok=True)

    thumb_url = data.thumbnail_url
    if not thumb_url and data.image_url and data.image_url.startswith("/static/"):
        local_path = ROOT_DIR / data.image_url.lstrip("/")
        if local_path.exists() and local_path.is_file():
            try:
                scaled_bytes, ext = generate_scaled_thumbnail(
                    local_path.read_bytes(), 1 / 3, "WEBP", 85
                )
                thumb_name = f"thumb_{local_path.stem}.{ext}"
                dest = sub_dir / thumb_name
                dest.write_bytes(scaled_bytes)
                thumb_url = f"/static/central_data/{parent_folder}/{sub_folder}/{thumb_name}"
            except Exception:
                pass

    # Assign sequence within category
    assigned_seq = data.sequence
    if assigned_seq is None:
        max_docs = await repo.find_many(
            query={"category_id": cat_oid, "deleted_at": None},
            sort=[("sequence", -1)],
            limit=1,
        )
        assigned_seq = compute_next_sequence(
            max_docs[0].get("sequence") if max_docs else None
        )

    now = utc_now()
    doc = {
        "name": name_clean,
        "folder_name": sub_folder,
        "category_id": cat_oid,
        "thumbnail_url": thumb_url,
        "image_url": data.image_url,
        "sequence": assigned_seq,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    inserted_id = await repo.insert_one(doc)
    doc["_id"] = inserted_id
    return serialize_mongo_doc(doc)  # type: ignore


async def update_subcategory(
    db: AsyncIOMotorDatabase, subcategory_id: str, data: SubcategoryUpdate
) -> dict[str, Any]:
    """Update central subcategory fields."""
    repo = CentralRepository(db, SUBCATEGORIES)
    oid = to_object_id(subcategory_id)
    existing = await repo.find_by_id(oid)
    if not existing:
        raise NotFoundError("Subcategory not found")

    update_fields: dict[str, Any] = {}
    if data.name is not None:
        name_clean = data.name.strip()
        conflict = await repo.find_one(
            {
                "category_id": existing["category_id"],
                "name": {"$regex": f"^{name_clean}$", "$options": "i"},
                "_id": {"$ne": oid},
            }
        )
        if conflict:
            raise ConflictError(
                f"Subcategory with name '{name_clean}' already exists under parent category"
            )
        update_fields["name"] = name_clean

    if "thumbnail_url" in data.model_fields_set:
        update_fields["thumbnail_url"] = data.thumbnail_url
    elif data.thumbnail_url is not None:
        update_fields["thumbnail_url"] = data.thumbnail_url
    if "image_url" in data.model_fields_set:
        update_fields["image_url"] = data.image_url
    elif data.image_url is not None:
        update_fields["image_url"] = data.image_url
    if data.sequence is not None:
        update_fields["sequence"] = data.sequence

    if update_fields:
        await repo.update_one({"_id": oid}, {"$set": update_fields})

    updated = await repo.find_by_id(oid)
    return serialize_mongo_doc(updated)  # type: ignore


async def delete_subcategory(
    db: AsyncIOMotorDatabase, subcategory_id: str, cascade: bool = False
) -> dict[str, Any]:
    """Soft delete central subcategory, checking child assets and instance references."""
    repo = CentralRepository(db, SUBCATEGORIES)
    oid = to_object_id(subcategory_id)
    sub = await repo.find_by_id(oid)
    if not sub:
        raise NotFoundError("Subcategory not found")

    asset_repo = CentralRepository(db, ASSETS)
    asset_count = await asset_repo.count({"sub_category_id": oid})

    inst_sub_refs = await db[INSTANCE_SUBCATEGORIES].count_documents(
        {
            "source_id": oid,
            "deleted_at": None,
        }
    )
    inst_asset_refs = await db[INSTANCE_ASSETS].count_documents(
        {
            "sub_category_id": oid,
            "deleted_at": None,
        }
    )
    total_inst_refs = inst_sub_refs + inst_asset_refs

    if asset_count > 0 and not cascade:
        raise ConflictError(
            f"Subcategory has {asset_count} assets. Pass cascade=true to confirm removal. "
            f"Note: {total_inst_refs} instance references will become unresolvable.",
            details={
                "assets_count": asset_count,
                "referenced_by_instances_count": total_inst_refs,
            },
        )

    await repo.hard_delete({"_id": oid})
    await db[INSTANCE_SUBCATEGORIES].delete_many({"source_id": oid})
    if cascade:
        # Delete physical files of all child assets
        child_assets = await asset_repo.find_many({"sub_category_id": oid})
        for child in child_assets:
            delete_asset_file_from_disk(child)

        # Delete subcategory directory from disk
        cat_repo = CentralRepository(db, CATEGORIES)
        parent_cat = await cat_repo.find_by_id(sub["category_id"])
        parent_folder = (
            parent_cat.get("folder_name") or slugify(parent_cat["name"])
            if parent_cat
            else "category"
        )
        sub_folder = sub.get("folder_name") or slugify(sub["name"]) or "subcategory"
        sub_dir = get_subcategory_dir(parent_folder, sub_folder)
        if sub_dir.exists() and sub_dir.is_dir():
            shutil.rmtree(sub_dir, ignore_errors=True)

        child_asset_ids = [c["_id"] for c in child_assets]
        await asset_repo.hard_delete({"sub_category_id": oid})
        inst_asset_query: dict[str, Any] = {"sub_category_id": oid}
        if child_asset_ids:
            inst_asset_query = {
                "$or": [{"sub_category_id": oid}, {"source_id": {"$in": child_asset_ids}}]
            }
        await db[INSTANCE_ASSETS].delete_many(inst_asset_query)
    else:
        await db[INSTANCE_ASSETS].delete_many({"sub_category_id": oid})
        # Delete empty subcategory directory from disk
        cat_repo = CentralRepository(db, CATEGORIES)
        parent_cat = await cat_repo.find_by_id(sub["category_id"])
        parent_folder = (
            parent_cat.get("folder_name") or slugify(parent_cat["name"])
            if parent_cat
            else "category"
        )
        sub_folder = sub.get("folder_name") or slugify(sub["name"]) or "subcategory"
        sub_dir = get_subcategory_dir(parent_folder, sub_folder)
        if sub_dir.exists() and sub_dir.is_dir():
            shutil.rmtree(sub_dir, ignore_errors=True)

    return {
        "success": True,
        "deleted_id": str(oid),
        "cascade": cascade,
        "removed_assets": asset_count if cascade else 0,
        "unresolvable_instance_references": total_inst_refs,
    }


async def bulk_create_subcategories(
    db: AsyncIOMotorDatabase,
    items: list[SubcategoryCreate],
    atomic: bool = False,
) -> dict[str, Any]:
    """Bulk create central subcategories with partial success support (HTTP 207)."""
    results: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        try:
            created = await create_subcategory(db, item)
            results.append(bulk_item_result(index=index, status="created", id=created["id"]))
        except (ConflictError, NotFoundError) as err:
            results.append(bulk_item_result(index=index, status="skipped", error=str(err)))
        except Exception as exc:
            results.append(bulk_item_result(index=index, status="failed", error=str(exc)))

    return bulk_response(results, atomic=atomic)
