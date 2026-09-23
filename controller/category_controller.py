import shutil
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.paths import ROOT_DIR, get_category_dir
from controller.asset_controller import delete_asset_file_from_disk
from controller.base_controller import format_page_response, serialize_mongo_doc
from database.collections import (
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    SUBCATEGORIES,
)
from database.models.category import CategoryCreate, CategoryUpdate
from database.repository import CentralRepository
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError
from utils.ids import to_object_id
from utils.image_utils import generate_scaled_thumbnail
from utils.responses import bulk_item_result, bulk_response
from utils.sequencing import compute_next_sequence
from utils.slugify import slugify


async def list_categories(
    db: AsyncIOMotorDatabase,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    sort_by: str = "sequence",
    sort_order: str = "asc",
) -> dict[str, Any]:
    """List central categories with pagination, optional search, and sorting."""
    repo = CentralRepository(db, CATEGORIES)
    query: dict[str, Any] = {}
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


async def get_category(db: AsyncIOMotorDatabase, category_id: str) -> dict[str, Any]:
    """Retrieve a single central category by its ID."""
    repo = CentralRepository(db, CATEGORIES)
    doc = await repo.find_by_id(category_id)
    if not doc:
        raise NotFoundError("Category not found")
    return serialize_mongo_doc(doc)  # type: ignore


async def create_category(db: AsyncIOMotorDatabase, data: CategoryCreate) -> dict[str, Any]:
    """Create a new central category, enforcing case-insensitive name uniqueness and creating folder."""
    repo = CentralRepository(db, CATEGORIES)
    existing = await repo.find_one({"name": {"$regex": f"^{data.name.strip()}$", "$options": "i"}})
    if existing:
        raise ConflictError(f"Category with name '{data.name}' already exists")

    folder_name = slugify(data.name.strip()) or "category"
    category_dir = get_category_dir(folder_name)
    category_dir.mkdir(parents=True, exist_ok=True)

    thumb_url = data.thumbnail_url
    if not thumb_url and data.image_url and data.image_url.startswith("/static/"):
        local_path = ROOT_DIR / data.image_url.lstrip("/")
        if local_path.exists() and local_path.is_file():
            try:
                scaled_bytes, ext = generate_scaled_thumbnail(
                    local_path.read_bytes(), 1 / 3, "WEBP", 85
                )
                thumb_name = f"thumb_{local_path.stem}.{ext}"
                dest = category_dir / thumb_name
                dest.write_bytes(scaled_bytes)
                thumb_url = f"/static/central_data/{folder_name}/{thumb_name}"
            except Exception:
                pass

    # Assign sequence
    assigned_seq = data.sequence
    if assigned_seq is None:
        max_docs = await repo.find_many(
            query={"deleted_at": None}, sort=[("sequence", -1)], limit=1
        )
        assigned_seq = compute_next_sequence(
            max_docs[0].get("sequence") if max_docs else None
        )

    now = utc_now()
    doc = {
        "name": data.name.strip(),
        "folder_name": folder_name,
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


async def update_category(
    db: AsyncIOMotorDatabase, category_id: str, data: CategoryUpdate
) -> dict[str, Any]:
    """Update central category fields."""
    repo = CentralRepository(db, CATEGORIES)
    oid = to_object_id(category_id)
    existing = await repo.find_by_id(oid)
    if not existing:
        raise NotFoundError("Category not found")

    update_fields: dict[str, Any] = {}
    if data.name is not None:
        name_clean = data.name.strip()
        # Verify unique if name changed
        conflict = await repo.find_one(
            {
                "name": {"$regex": f"^{name_clean}$", "$options": "i"},
                "_id": {"$ne": oid},
            }
        )
        if conflict:
            raise ConflictError(f"Category with name '{name_clean}' already exists")
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


async def delete_category(
    db: AsyncIOMotorDatabase, category_id: str, cascade: bool = False
) -> dict[str, Any]:
    """Soft delete central category, previewing or executing cascade impact.

    Does NOT cascade delete to app instance reference rows; they become unresolvable.
    """
    repo = CentralRepository(db, CATEGORIES)
    oid = to_object_id(category_id)
    category = await repo.find_by_id(oid)
    if not category:
        raise NotFoundError("Category not found")

    sub_repo = CentralRepository(db, SUBCATEGORIES)
    asset_repo = CentralRepository(db, ASSETS)

    sub_count = await sub_repo.count({"category_id": oid})
    asset_count = await asset_repo.count({"category_id": oid})

    # Count external app references pointing at this category hierarchy
    inst_cat_refs = await db[INSTANCE_CATEGORIES].count_documents(
        {
            "source_id": oid,
            "deleted_at": None,
        }
    )
    inst_sub_refs = await db[INSTANCE_SUBCATEGORIES].count_documents(
        {
            "category_id": oid,
            "deleted_at": None,
        }
    )
    inst_asset_refs = await db[INSTANCE_ASSETS].count_documents(
        {
            "category_id": oid,
            "deleted_at": None,
        }
    )
    total_inst_refs = inst_cat_refs + inst_sub_refs + inst_asset_refs

    if (sub_count > 0 or asset_count > 0) and not cascade:
        raise ConflictError(
            f"Category has {sub_count} subcategories and {asset_count} assets. "
            f"Pass cascade=true to confirm removal. "
            f"Note: {total_inst_refs} instance references will become unresolvable.",
            details={
                "subcategories_count": sub_count,
                "assets_count": asset_count,
                "referenced_by_instances_count": total_inst_refs,
            },
        )

    # Perform hard deletes centrally and cleanup filesystem
    await repo.hard_delete({"_id": oid})
    await db[INSTANCE_CATEGORIES].delete_many({"source_id": oid})
    if cascade:
        # Delete physical files of all child assets under this category
        child_assets = await asset_repo.find_many({"category_id": oid})
        for child in child_assets:
            delete_asset_file_from_disk(child)

        # Delete category directory from disk
        folder_name = category.get("folder_name") or slugify(category.get("name", "")) or "category"
        cat_dir = get_category_dir(folder_name)
        if cat_dir.exists() and cat_dir.is_dir():
            shutil.rmtree(cat_dir, ignore_errors=True)

        child_subs = await sub_repo.find_many({"category_id": oid})
        child_sub_ids = [s["_id"] for s in child_subs]
        child_asset_ids = [c["_id"] for c in child_assets]

        await sub_repo.hard_delete({"category_id": oid})
        await asset_repo.hard_delete({"category_id": oid})

        inst_sub_query: dict[str, Any] = {"category_id": oid}
        if child_sub_ids:
            inst_sub_query = {"$or": [{"category_id": oid}, {"source_id": {"$in": child_sub_ids}}]}
        await db[INSTANCE_SUBCATEGORIES].delete_many(inst_sub_query)

        clauses: list[dict[str, Any]] = [{"category_id": oid}]
        if child_sub_ids:
            clauses.append({"sub_category_id": {"$in": child_sub_ids}})
        if child_asset_ids:
            clauses.append({"source_id": {"$in": child_asset_ids}})
        await db[INSTANCE_ASSETS].delete_many({"$or": clauses} if len(clauses) > 1 else clauses[0])
    else:
        await db[INSTANCE_SUBCATEGORIES].delete_many({"category_id": oid})
        await db[INSTANCE_ASSETS].delete_many({"category_id": oid})
        # Delete category directory from disk for empty category
        folder_name = category.get("folder_name") or slugify(category.get("name", "")) or "category"
        cat_dir = get_category_dir(folder_name)
        if cat_dir.exists() and cat_dir.is_dir():
            shutil.rmtree(cat_dir, ignore_errors=True)

    return {
        "success": True,
        "deleted_id": str(oid),
        "cascade": cascade,
        "removed_subcategories": sub_count if cascade else 0,
        "removed_assets": asset_count if cascade else 0,
        "unresolvable_instance_references": total_inst_refs,
    }


async def bulk_create_categories(
    db: AsyncIOMotorDatabase,
    items: list[CategoryCreate],
    atomic: bool = False,
) -> dict[str, Any]:
    """Bulk create central categories with partial success support (HTTP 207)."""
    results: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        try:
            created = await create_category(db, item)
            results.append(bulk_item_result(index=index, status="created", id=created["id"]))
        except ConflictError as err:
            results.append(bulk_item_result(index=index, status="skipped", error=str(err)))
        except Exception as exc:
            results.append(bulk_item_result(index=index, status="failed", error=str(exc)))

    return bulk_response(results, atomic=atomic)
