"""Manager direct upload orchestration with automatic Central Library sync & app-level asset override diff proposals.

Kept separate from `instance_workspace_controller.py`, `reference_controller.py`, `override_controller.py`,
`catalog_controller.py`, and `router/manager/*.py` so static central-isolation checks in `tests/test_instance_isolation.py`
remain cleanly enforced while enabling manager-initiated central additions and app-level override proposals.
"""

import re
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from controller.asset_controller import (
    bulk_create_assets,
    create_asset,
    derive_asset_name,
    enrich_more_fields_metadata,
)
from controller.base_controller import serialize_mongo_doc
from controller.catalog_controller import get_resolved_single_asset
from controller.category_controller import create_category, list_categories
from controller.manager_controller import send_manager_message
from controller.override_controller import update_item_settings_and_overrides
from controller.reference_controller import (
    add_references,
    ensure_category_link,
    ensure_subcategory_link,
)
from controller.subcategory_controller import create_subcategory, list_subcategories
from database.collections import (
    APP_INSTANCES,
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    SUBCATEGORIES,
)
from database.models.asset import AssetCreate
from database.models.category import CategoryCreate
from database.models.subcategory import SubcategoryCreate
from utils.csv_utils import parse_lines_list
from utils.datetimes import utc_now
from utils.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from utils.ids import to_object_id
from utils.slugify import slugify


async def _stamp_manager_creator(
    db: AsyncIOMotorDatabase,
    collection: str,
    doc_id: str,
    app_instance_id: str,
    manager_user: dict[str, Any] | None,
) -> None:
    """Attach optional audit attribution for manager-created central records."""
    if not manager_user:
        return
    m_id = manager_user.get("user_id") or manager_user.get("_id") or manager_user.get("id")
    fields: dict[str, Any] = {
        "created_by_role": "manager",
        "created_from_app_instance_id": to_object_id(app_instance_id),
        "updated_at": utc_now(),
    }
    if m_id:
        fields["created_by_manager_id"] = to_object_id(str(m_id))
    if manager_user.get("username"):
        fields["created_by_username"] = manager_user["username"]
    await db[collection].update_one({"_id": to_object_id(doc_id)}, {"$set": fields})


async def resolve_or_create_central_category(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str | None = None,
    new_category_name: str | None = None,
    manager_user: dict[str, Any] | None = None,
    super_category_id: str | None = None,
    thumbnail_url: str | None = None,
    image_url: str | None = None,
) -> tuple[str, str, bool]:
    """Resolve an existing central category (or promote/create one) and ensure it is linked to `app_instance_id`.

    Returns `(central_category_id, instance_category_id, added_to_instance)`.
    """
    inst_oid = to_object_id(app_instance_id)
    clean_new_name = (new_category_name or "").strip()

    if clean_new_name:
        central_doc = await db[CATEGORIES].find_one(
            {"name": {"$regex": f"^{re.escape(clean_new_name)}$", "$options": "i"}, "deleted_at": None}
        )
        if central_doc:
            central_id = str(central_doc["_id"])
        else:
            created = await create_category(
                db,
                CategoryCreate(
                    name=clean_new_name,
                    thumbnail_url=thumbnail_url,
                    image_url=image_url,
                    super_category_id=super_category_id or None,
                ),
            )
            central_id = created["id"]
            await _stamp_manager_creator(db, CATEGORIES, central_id, app_instance_id, manager_user)
        inst_cat_id, added = await ensure_category_link(
            db, app_instance_id, central_id, super_category_id=super_category_id
        )
        return central_id, inst_cat_id, added

    clean_id = (category_id or "").strip()
    if not clean_id:
        raise ValidationError("Category ID or new category name is required.")

    c_oid = to_object_id(clean_id)
    central_doc = await db[CATEGORIES].find_one({"_id": c_oid, "deleted_at": None})
    if central_doc:
        central_id = str(central_doc["_id"])
        inst_cat_id, added = await ensure_category_link(
            db, app_instance_id, central_id, super_category_id=super_category_id
        )
        return central_id, inst_cat_id, added

    inst_doc = await db[INSTANCE_CATEGORIES].find_one(
        {"app_instance_id": inst_oid, "_id": c_oid, "deleted_at": None}
    )
    if not inst_doc:
        raise NotFoundError("Target category not found.")

    if inst_doc.get("source_id"):
        src_doc = await db[CATEGORIES].find_one({"_id": inst_doc["source_id"], "deleted_at": None})
        if src_doc:
            return str(src_doc["_id"]), str(inst_doc["_id"]), False

    # Promote native instance-only category into central library and backfill source_id
    native_name = (inst_doc.get("name") or "").strip()
    if not native_name:
        raise ValidationError("Instance category is missing a valid name.")
    existing_central = await db[CATEGORIES].find_one(
        {"name": {"$regex": f"^{re.escape(native_name)}$", "$options": "i"}, "deleted_at": None}
    )
    if existing_central:
        central_id = str(existing_central["_id"])
    else:
        created = await create_category(
            db,
            CategoryCreate(
                name=native_name,
                thumbnail_url=inst_doc.get("thumbnail_url"),
                image_url=inst_doc.get("image_url"),
                super_category_id=super_category_id or None,
            ),
        )
        central_id = created["id"]
        await _stamp_manager_creator(db, CATEGORIES, central_id, app_instance_id, manager_user)

    await db[INSTANCE_CATEGORIES].update_one(
        {"_id": inst_doc["_id"]},
        {"$set": {"source_id": to_object_id(central_id), "updated_at": utc_now()}},
    )
    return central_id, str(inst_doc["_id"]), False


async def resolve_or_create_central_subcategory(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    central_cat_id: str,
    inst_cat_id: str | None = None,
    sub_category_id: str | None = None,
    new_subcategory_name: str | None = None,
    manager_user: dict[str, Any] | None = None,
    thumbnail_url: str | None = None,
    image_url: str | None = None,
) -> tuple[str, str, bool]:
    """Resolve an existing central subcategory (or promote/create one) and link it to `app_instance_id`.

    Returns `(central_subcategory_id, instance_subcategory_id, added_to_instance)`.
    """
    inst_oid = to_object_id(app_instance_id)
    central_cat_oid = to_object_id(central_cat_id)
    if not inst_cat_id:
        inst_cat_id, _ = await ensure_category_link(db, app_instance_id, central_cat_id)

    clean_new_name = (new_subcategory_name or "").strip()
    if clean_new_name:
        central_sub = await db[SUBCATEGORIES].find_one(
            {
                "category_id": central_cat_oid,
                "name": {"$regex": f"^{re.escape(clean_new_name)}$", "$options": "i"},
                "deleted_at": None,
            }
        )
        if central_sub:
            central_sub_id = str(central_sub["_id"])
        else:
            created = await create_subcategory(
                db,
                SubcategoryCreate(
                    name=clean_new_name,
                    categoryId=central_cat_id,
                    thumbnailUrl=thumbnail_url,
                    imageUrl=image_url,
                ),
            )
            central_sub_id = created["id"]
            await _stamp_manager_creator(db, SUBCATEGORIES, central_sub_id, app_instance_id, manager_user)
        inst_sub_id, added = await ensure_subcategory_link(
            db, app_instance_id, central_sub_id, target_category_id=inst_cat_id
        )
        return central_sub_id, inst_sub_id, added

    clean_sub_id = (sub_category_id or "").strip()
    if not clean_sub_id:
        raise ValidationError("Subcategory ID or new subcategory name is required.")

    s_oid = to_object_id(clean_sub_id)
    central_sub = await db[SUBCATEGORIES].find_one({"_id": s_oid, "deleted_at": None})
    if central_sub:
        central_sub_id = str(central_sub["_id"])
        inst_sub_id, added = await ensure_subcategory_link(
            db, app_instance_id, central_sub_id, target_category_id=inst_cat_id
        )
        return central_sub_id, inst_sub_id, added

    inst_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
        {"app_instance_id": inst_oid, "_id": s_oid, "deleted_at": None}
    )
    if not inst_sub:
        raise NotFoundError("Target subcategory not found.")

    if inst_sub.get("source_id"):
        src_doc = await db[SUBCATEGORIES].find_one({"_id": inst_sub["source_id"], "deleted_at": None})
        if src_doc:
            return str(src_doc["_id"]), str(inst_sub["_id"]), False

    # Promote native instance-only subcategory into central library under central_cat_id
    native_name = (inst_sub.get("name") or "").strip()
    if not native_name:
        raise ValidationError("Instance subcategory is missing a valid name.")
    existing_central = await db[SUBCATEGORIES].find_one(
        {
            "category_id": central_cat_oid,
            "name": {"$regex": f"^{re.escape(native_name)}$", "$options": "i"},
            "deleted_at": None,
        }
    )
    if existing_central:
        central_sub_id = str(existing_central["_id"])
    else:
        created = await create_subcategory(
            db,
            SubcategoryCreate(
                name=native_name,
                categoryId=central_cat_id,
                thumbnailUrl=inst_sub.get("thumbnail_url"),
                imageUrl=inst_sub.get("image_url"),
            ),
        )
        central_sub_id = created["id"]
        await _stamp_manager_creator(db, SUBCATEGORIES, central_sub_id, app_instance_id, manager_user)

    await db[INSTANCE_SUBCATEGORIES].update_one(
        {"_id": inst_sub["_id"]},
        {"$set": {"source_id": to_object_id(central_sub_id), "updated_at": utc_now()}},
    )
    return central_sub_id, str(inst_sub["_id"]), False


async def list_upload_categories_for_instance(
    db: AsyncIOMotorDatabase, app_instance_id: str, *, include_central: bool = True
) -> list[dict[str, Any]]:
    """Return Central Categories + native Instance Categories (or only instance categories when restricted)."""
    inst_oid = to_object_id(app_instance_id)
    if not include_central:
        inst_cats = (
            await db[INSTANCE_CATEGORIES]
            .find({"app_instance_id": inst_oid, "deleted_at": None})
            .sort("sequence", 1)
            .to_list(length=500)
        )
        source_oids = [c["source_id"] for c in inst_cats if c.get("source_id") is not None]
        central_map: dict[str, dict[str, Any]] = {}
        if source_oids:
            c_docs = await db[CATEGORIES].find(
                {"_id": {"$in": source_oids}, "deleted_at": None}
            ).to_list(length=500)
            central_map = {str(cd["_id"]): cd for cd in c_docs}

        scoped_items: list[dict[str, Any]] = []
        for ic in inst_cats:
            ov = ic.get("overrides") or {}
            src_doc = central_map.get(str(ic.get("source_id") or ""))
            name = (
                ov.get("name")
                or ic.get("name")
                or (src_doc.get("name") if src_doc else None)
                or "Unnamed Category"
            )
            scoped_items.append(
                {
                    "id": str(ic["_id"]),
                    "name": name,
                    "raw_name": name,
                    "is_native_instance_folder": ic.get("source_id") is None,
                }
            )
        return scoped_items

    central_res = await list_categories(db, page=1, page_size=500)
    items = list(central_res.get("items", []))
    native_cats = (
        await db[INSTANCE_CATEGORIES]
        .find({"app_instance_id": inst_oid, "source_id": None, "deleted_at": None})
        .sort("sequence", 1)
        .to_list(length=200)
    )
    seen_names = {str(c.get("name", "")).strip().lower() for c in items}
    for nc in native_cats:
        n_name = str(nc.get("name", "")).strip()
        if n_name.lower() in seen_names:
            continue
        items.append(
            {
                "id": str(nc["_id"]),
                "name": f"{n_name} (App folder — syncs on upload)",
                "raw_name": n_name,
                "is_native_instance_folder": True,
            }
        )
    return items


async def list_upload_subcategories_for_instance(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str,
    *,
    include_central: bool = True,
) -> list[dict[str, Any]]:
    """Return matching Central Subcategories + native Instance Subcategories (or only instance subcategories when restricted)."""
    clean_cat = (category_id or "").strip()
    if not clean_cat:
        return []

    inst_oid = to_object_id(app_instance_id)
    c_oid = to_object_id(clean_cat)
    if not include_central:
        inst_cat = await db[INSTANCE_CATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "$or": [{"_id": c_oid}, {"source_id": c_oid}],
                "deleted_at": None,
            }
        )
        if not inst_cat:
            return []
        cat_candidates = [inst_cat["_id"]]
        if inst_cat.get("source_id") is not None:
            cat_candidates.append(inst_cat["source_id"])
        inst_subs = (
            await db[INSTANCE_SUBCATEGORIES]
            .find(
                {
                    "app_instance_id": inst_oid,
                    "category_id": {"$in": cat_candidates},
                    "deleted_at": None,
                }
            )
            .sort("sequence", 1)
            .to_list(length=500)
        )
        sub_source_oids = [s["source_id"] for s in inst_subs if s.get("source_id") is not None]
        central_sub_map: dict[str, dict[str, Any]] = {}
        if sub_source_oids:
            s_docs = await db[SUBCATEGORIES].find(
                {"_id": {"$in": sub_source_oids}, "deleted_at": None}
            ).to_list(length=500)
            central_sub_map = {str(sd["_id"]): sd for sd in s_docs}

        scoped_subs: list[dict[str, Any]] = []
        for isub in inst_subs:
            ov = isub.get("overrides") or {}
            src_doc = central_sub_map.get(str(isub.get("source_id") or ""))
            name = (
                ov.get("name")
                or isub.get("name")
                or (src_doc.get("name") if src_doc else None)
                or "Unnamed Subcategory"
            )
            scoped_subs.append(
                {
                    "id": str(isub["_id"]),
                    "name": name,
                    "category_id": str(inst_cat["_id"]),
                }
            )
        return scoped_subs

    central_cat_id: str | None = None
    inst_cat_oid: Any = None

    central_cat = await db[CATEGORIES].find_one({"_id": c_oid, "deleted_at": None})
    if central_cat:
        central_cat_id = str(central_cat["_id"])
        inst_match = await db[INSTANCE_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "source_id": c_oid, "deleted_at": None}
        )
        if inst_match:
            inst_cat_oid = inst_match["_id"]
    else:
        inst_cat = await db[INSTANCE_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "_id": c_oid, "deleted_at": None}
        )
        if inst_cat:
            inst_cat_oid = inst_cat["_id"]
            if inst_cat.get("source_id"):
                central_cat_id = str(inst_cat["source_id"])

    items: list[dict[str, Any]] = []
    if central_cat_id:
        central_subs = await list_subcategories(db, category_id=central_cat_id, page=1, page_size=500)
        items.extend(central_subs.get("items", []))

    seen_names = {str(s.get("name", "")).strip().lower() for s in items}
    if inst_cat_oid:
        native_subs = (
            await db[INSTANCE_SUBCATEGORIES]
            .find(
                {
                    "app_instance_id": inst_oid,
                    "category_id": inst_cat_oid,
                    "source_id": None,
                    "deleted_at": None,
                }
            )
            .sort("sequence", 1)
            .to_list(length=200)
        )
        for ns in native_subs:
            n_name = str(ns.get("name", "")).strip()
            if n_name.lower() in seen_names:
                continue
            items.append(
                {
                    "id": str(ns["_id"]),
                    "name": f"{n_name} (App folder — syncs on upload)",
                    "category_id": clean_cat,
                }
            )
    return items


async def resolve_central_folders_for_upload(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str | None,
    sub_category_id: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Resolve canonical `(central_cat_id, central_sub_id, category_folder, subcategory_folder)` from form/instance IDs."""
    if not category_id or not sub_category_id:
        return None, None, None, None

    inst_oid = to_object_id(app_instance_id)
    cat_oid = to_object_id(category_id)
    sub_oid = to_object_id(sub_category_id)

    cat_doc = await db[CATEGORIES].find_one({"_id": cat_oid, "deleted_at": None})
    if not cat_doc:
        inst_cat = await db[INSTANCE_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "_id": cat_oid, "deleted_at": None}
        )
        if inst_cat and inst_cat.get("source_id"):
            cat_doc = await db[CATEGORIES].find_one({"_id": inst_cat["source_id"], "deleted_at": None})

    sub_doc = await db[SUBCATEGORIES].find_one({"_id": sub_oid, "deleted_at": None})
    if not sub_doc:
        inst_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
            {"app_instance_id": inst_oid, "_id": sub_oid, "deleted_at": None}
        )
        if inst_sub and inst_sub.get("source_id"):
            sub_doc = await db[SUBCATEGORIES].find_one({"_id": inst_sub["source_id"], "deleted_at": None})

    if not cat_doc or not sub_doc:
        return (
            str(cat_doc["_id"]) if cat_doc else None,
            str(sub_doc["_id"]) if sub_doc else None,
            (cat_doc.get("folder_name") or slugify(cat_doc.get("name", ""))) if cat_doc else None,
            (sub_doc.get("folder_name") or slugify(sub_doc.get("name", ""))) if sub_doc else None,
        )

    return (
        str(cat_doc["_id"]),
        str(sub_doc["_id"]),
        cat_doc.get("folder_name") or slugify(cat_doc.get("name", "")),
        sub_doc.get("folder_name") or slugify(sub_doc.get("name", "")),
    )


async def create_manager_folder_with_central_sync(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    data: dict[str, Any],
    manager_user: dict[str, Any] | None = None,
    *,
    allow_existing_in_instance: bool = False,
) -> dict[str, Any]:
    """Create a Category or Subcategory from Manager Portal, pushing/reusing Central Data automatically."""
    folder_type = str(data.get("folder_type", "category")).strip().lower().replace("super_category", "supercategory")
    name = (data.get("name") or "").strip()
    parent_category_id = (data.get("parent_category_id") or "").strip()
    parent_super_category_id = (data.get("parent_super_category_id") or "").strip() or None
    thumbnail_url = (data.get("thumbnail_url") or "").strip() or None
    image_url = (data.get("image_url") or "").strip() or None

    if folder_type == "supercategory":
        from controller.instance_workspace_controller import create_instance_folder

        return await create_instance_folder(db, app_instance_id, data)

    if not name:
        raise ValidationError("Folder name is required")

    if folder_type == "category":
        central_id, inst_id, added = await resolve_or_create_central_category(
            db,
            app_instance_id,
            new_category_name=name,
            manager_user=manager_user,
            super_category_id=parent_super_category_id,
            thumbnail_url=thumbnail_url,
            image_url=image_url,
        )
        if not added and not allow_existing_in_instance:
            raise ValidationError(f"Category folder '{name}' already exists in this app instance")
        return {
            "success": True,
            "folder_type": "category",
            "id": central_id,
            "inst_id": inst_id,
            "name": name,
        }

    if folder_type == "subcategory":
        if not parent_category_id:
            raise ValidationError("Parent category is required for sub-folder")
        central_cat_id, inst_cat_id, _ = await resolve_or_create_central_category(
            db,
            app_instance_id,
            category_id=parent_category_id,
            manager_user=manager_user,
        )
        central_sub_id, inst_sub_id, added = await resolve_or_create_central_subcategory(
            db,
            app_instance_id,
            central_cat_id=central_cat_id,
            inst_cat_id=inst_cat_id,
            new_subcategory_name=name,
            manager_user=manager_user,
            thumbnail_url=thumbnail_url,
            image_url=image_url,
        )
        if not added and not allow_existing_in_instance:
            raise ValidationError(f"Subcategory folder '{name}' already exists in this category")
        return {
            "success": True,
            "folder_type": "subcategory",
            "id": central_sub_id,
            "inst_id": inst_sub_id,
            "category_id": central_cat_id,
            "name": name,
        }

    raise ValidationError(f"Unknown folder type: {folder_type}")


async def create_central_asset_for_instance(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    payload: dict[str, Any],
    manager_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Push newly created asset (or text-name batch) to Central Data and auto-attach into the Manager's App Instance."""
    cat_id = payload.get("category_id") or payload.get("categoryId")
    sub_id = payload.get("sub_category_id") or payload.get("subCategoryId")
    new_cat_name = payload.get("new_category_name") or payload.get("newCategoryName")
    new_sub_name = payload.get("new_subcategory_name") or payload.get("newSubcategoryName")

    central_cat_id, inst_cat_id, _ = await resolve_or_create_central_category(
        db,
        app_instance_id,
        category_id=cat_id,
        new_category_name=new_cat_name,
        manager_user=manager_user,
    )
    central_sub_id, inst_sub_id, _ = await resolve_or_create_central_subcategory(
        db,
        app_instance_id,
        central_cat_id=central_cat_id,
        inst_cat_id=inst_cat_id,
        sub_category_id=sub_id,
        new_subcategory_name=new_sub_name,
        manager_user=manager_user,
    )

    description = str(payload.get("description") or "").strip()
    names_list_raw = payload.get("names_list")
    names = parse_lines_list(names_list_raw or "") if names_list_raw else []
    if names:
        created_res = await bulk_create_assets(
            db,
            [
                AssetCreate(
                    name=n,
                    description=description,
                    category_id=central_cat_id,
                    sub_category_id=central_sub_id,
                )
                for n in names
            ],
        )
        created_ids = [item["id"] for item in created_res.get("created", []) if item.get("id")]
        # Also include already-existing asset IDs? Only link created items (plus skip existing duplicates centrally).
        for aid in created_ids:
            await _stamp_manager_creator(db, ASSETS, aid, app_instance_id, manager_user)
        if created_ids:
            await add_references(
                db,
                app_instance_id,
                asset_ids=created_ids,
                target_category_id=inst_cat_id,
                target_sub_category_id=inst_sub_id,
            )
        return {
            "success": True,
            "bulk_text": True,
            "created_count": len(created_ids),
            "created": created_res.get("created", []),
            "errors": created_res.get("errors", []),
            "central_category_id": central_cat_id,
            "central_sub_category_id": central_sub_id,
        }

    more_fields = payload.get("more_fields") if payload.get("more_fields") is not None else payload.get("moreFields")
    if not isinstance(more_fields, dict):
        more_fields = {}

    raw_thumb = payload.get("thumbnail_url") if payload.get("thumbnail_url") is not None else payload.get("thumbnailUrl")
    clean_thumb = str(raw_thumb).strip() if raw_thumb and str(raw_thumb).strip() else None

    raw_name = payload.get("name")
    clean_name = str(raw_name).strip() if raw_name and str(raw_name).strip() else ""
    if not clean_name:
        clean_name = derive_asset_name(clean_thumb, more_fields)

    created_asset = await create_asset(
        db,
        AssetCreate(
            name=clean_name,
            description=description,
            category_id=central_cat_id,
            sub_category_id=central_sub_id,
            thumbnail_url=clean_thumb,
            more_fields=more_fields,
        ),
    )
    await _stamp_manager_creator(db, ASSETS, created_asset["id"], app_instance_id, manager_user)
    await add_references(
        db,
        app_instance_id,
        asset_ids=[created_asset["id"]],
        target_category_id=inst_cat_id,
        target_sub_category_id=inst_sub_id,
    )

    inst_asset_doc = await db[INSTANCE_ASSETS].find_one(
        {
            "app_instance_id": to_object_id(app_instance_id),
            "source_id": to_object_id(created_asset["id"]),
            "deleted_at": None,
        },
        {"_id": 1},
    )

    return {
        "success": True,
        "data": created_asset,
        "id": created_asset["id"],
        "inst_asset_id": str(inst_asset_doc["_id"]) if inst_asset_doc else None,
        "central_category_id": central_cat_id,
        "central_sub_category_id": central_sub_id,
    }


def _clean_text(val: Any) -> str:
    return str(val or "").strip()


async def save_app_level_asset_edit_and_notify(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    asset_id: str,
    payload: dict[str, Any],
    manager_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save edits strictly in `instance_assets.overrides` without touching Central Data.

    When `manager_user` edits an asset (with actual changes to name, description, thumbnail_url,
    or more_fields), automatically dispatches a structured `asset_update` proposal message to Admin.
    """
    before = await get_resolved_single_asset(db, app_instance_id=app_instance_id, asset_id=asset_id)
    if not before:
        raise NotFoundError("App instance asset not found.")

    source_id = before.get("source_id") or before.get("sourceId")
    central_doc = (
        await db[ASSETS].find_one({"_id": to_object_id(str(source_id)), "deleted_at": None})
        if source_id
        else None
    )

    new_name = _clean_text(payload.get("name")) or before.get("name") or "Untitled Asset"
    new_desc = (
        _clean_text(payload.get("description"))
        if "description" in payload
        else _clean_text(before.get("description"))
    )
    if "thumbnail_url" in payload or "thumbnailUrl" in payload:
        raw_thumb = payload.get("thumbnail_url") if "thumbnail_url" in payload else payload.get("thumbnailUrl")
        new_thumb = str(raw_thumb).strip() if raw_thumb and str(raw_thumb).strip() else None
    else:
        new_thumb = str(before.get("thumbnail_url") or before.get("thumbnailUrl") or "").strip() or None

    raw_mf = payload.get("more_fields") if "more_fields" in payload else payload.get("moreFields")
    if isinstance(raw_mf, dict):
        new_more_fields = enrich_more_fields_metadata(raw_mf)
    else:
        new_more_fields = before.get("more_fields") or {}

    # Compute sparse overrides against underlying central doc so matching fields unset cleanly
    override_patch: dict[str, Any] = {}
    if central_doc:
        override_patch["name"] = None if new_name == _clean_text(central_doc.get("name")) else new_name
        override_patch["description"] = (
            None if new_desc == _clean_text(central_doc.get("description")) else new_desc
        )
        c_thumb = str(central_doc.get("thumbnail_url") or "").strip() or None
        override_patch["thumbnail_url"] = None if new_thumb == c_thumb else new_thumb
        c_mf = central_doc.get("more_fields") or {}
        override_patch["more_fields"] = None if new_more_fields == c_mf else new_more_fields
    else:
        override_patch = {
            "name": new_name,
            "description": new_desc,
            "thumbnail_url": new_thumb,
            "more_fields": new_more_fields,
        }

    await update_item_settings_and_overrides(
        db,
        app_instance_id=app_instance_id,
        item_type="asset",
        item_id=before["id"],
        overrides=override_patch,
    )

    before_snapshot = {
        "name": before.get("name") or "",
        "description": before.get("description") or "",
        "thumbnail_url": before.get("thumbnail_url") or None,
        "more_fields": before.get("more_fields") or {},
    }
    proposed_snapshot = {
        "name": new_name,
        "description": new_desc,
        "thumbnail_url": new_thumb,
        "more_fields": new_more_fields,
    }

    changed_fields: list[str] = []
    if proposed_snapshot["name"] != before_snapshot["name"]:
        changed_fields.append("name")
    if proposed_snapshot["description"] != before_snapshot["description"]:
        changed_fields.append("description")
    if proposed_snapshot["thumbnail_url"] != before_snapshot["thumbnail_url"]:
        changed_fields.append("thumbnail_url")
    if proposed_snapshot["more_fields"] != before_snapshot["more_fields"]:
        changed_fields.append("more_fields")

    message_sent = False
    if changed_fields and manager_user and source_id:
        inst_doc = await db[APP_INSTANCES].find_one({"_id": to_object_id(app_instance_id)})
        inst_name = inst_doc.get("name", app_instance_id) if inst_doc else app_instance_id
        pkg_name = (inst_doc.get("package_name") or "") if inst_doc else ""
        manager_id = str(manager_user.get("user_id") or manager_user.get("_id") or manager_user.get("id") or "")
        manager_name = manager_user.get("username") or manager_user.get("display_name") or "Manager"

        diff_lines = [
            f"Manager '{manager_name}' edited asset '{before_snapshot['name']}' in app '{inst_name}' ({pkg_name or app_instance_id}).",
            "Saved at app level only (Central Data unchanged).",
            "",
            "Proposed Changes:",
        ]
        if "name" in changed_fields:
            diff_lines.append(f"• Name: '{before_snapshot['name']}' -> '{proposed_snapshot['name']}'")
        if "description" in changed_fields:
            diff_lines.append(f"• Description updated ('{before_snapshot['description'][:60]}' -> '{proposed_snapshot['description'][:60]}')")
        if "thumbnail_url" in changed_fields:
            diff_lines.append(f"• Thumbnail updated: {proposed_snapshot['thumbnail_url'] or '(cleared)'}")
        if "more_fields" in changed_fields:
            diff_lines.append(
                f"• Content blocks updated ({len(before_snapshot['more_fields'])} -> {len(proposed_snapshot['more_fields'])} block(s): "
                f"{', '.join(proposed_snapshot['more_fields'].keys()) or 'none'})"
            )

        await send_manager_message(
            db,
            manager_id=manager_id,
            sender_name=manager_name,
            subject=f"App Asset Edit Proposal: {new_name} ({inst_name})",
            content="\n".join(diff_lines),
            payload_type="asset_update",
            data_payload={
                "action": "update_central_asset",
                "app_instance_id": str(app_instance_id),
                "app_instance_name": inst_name,
                "app_package_name": pkg_name,
                "instance_asset_id": before["id"],
                "source_asset_id": str(source_id),
                "category_id": before.get("categoryId"),
                "category_name": before.get("category_name"),
                "sub_category_id": before.get("subCategoryId"),
                "subcategory_name": before.get("subcategory_name"),
                "name": new_name,
                "thumbnail_url": proposed_snapshot["thumbnail_url"] or before_snapshot["thumbnail_url"],
                "changed_fields": changed_fields,
                "before": before_snapshot,
                "proposed": proposed_snapshot,
            },
        )
        message_sent = True

    return {
        "success": True,
        "instance_asset_id": before["id"],
        "source_asset_id": str(source_id) if source_id else None,
        "changed_fields": changed_fields,
        "message_sent": message_sent,
    }


async def notify_asset_rename_proposal(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    before_asset: dict[str, Any],
    new_name: str,
    manager_user: dict[str, Any],
) -> bool:
    """Send an `asset_update` proposal message to Admin when quick Rename updates an asset name."""
    source_id = before_asset.get("source_id") or before_asset.get("sourceId")
    old_name = _clean_text(before_asset.get("name"))
    clean_new = _clean_text(new_name)
    if not source_id or not clean_new or clean_new == old_name:
        return False

    inst_doc = await db[APP_INSTANCES].find_one({"_id": to_object_id(app_instance_id)})
    inst_name = inst_doc.get("name", app_instance_id) if inst_doc else app_instance_id
    pkg_name = (inst_doc.get("package_name") or "") if inst_doc else ""
    manager_id = str(manager_user.get("user_id") or manager_user.get("_id") or manager_user.get("id") or "")
    manager_name = manager_user.get("username") or manager_user.get("display_name") or "Manager"

    await send_manager_message(
        db,
        manager_id=manager_id,
        sender_name=manager_name,
        subject=f"App Asset Rename Proposal: {clean_new} ({inst_name})",
        content=(
            f"Manager '{manager_name}' renamed asset '{old_name}' -> '{clean_new}' in app '{inst_name}'.\n"
            "Saved at app level only (Central Data unchanged)."
        ),
        payload_type="asset_update",
        data_payload={
            "action": "update_central_asset",
            "app_instance_id": str(app_instance_id),
            "app_instance_name": inst_name,
            "app_package_name": pkg_name,
            "instance_asset_id": before_asset["id"],
            "source_asset_id": str(source_id),
            "category_id": before_asset.get("categoryId"),
            "category_name": before_asset.get("category_name"),
            "sub_category_id": before_asset.get("subCategoryId"),
            "subcategory_name": before_asset.get("subcategory_name"),
            "name": clean_new,
            "thumbnail_url": before_asset.get("thumbnail_url"),
            "changed_fields": ["name"],
            "before": {
                "name": old_name,
                "description": before_asset.get("description") or "",
                "thumbnail_url": before_asset.get("thumbnail_url"),
                "more_fields": before_asset.get("more_fields") or {},
            },
            "proposed": {
                "name": clean_new,
                "description": before_asset.get("description") or "",
                "thumbnail_url": before_asset.get("thumbnail_url"),
                "more_fields": before_asset.get("more_fields") or {},
            },
        },
    )
    return True


def normalize_asset_aliases(asset: dict[str, Any]) -> dict[str, Any]:
    """Ensure camelCase/snake_case aliases and JSON-safe scalar types on an asset dict."""
    serialized = serialize_mongo_doc(asset)
    if isinstance(serialized, dict):
        asset.clear()
        asset.update(serialized)
    if "more_fields" in asset and "moreFields" not in asset:
        asset["moreFields"] = asset["more_fields"]
    if "moreFields" in asset and "more_fields" not in asset:
        asset["more_fields"] = asset["moreFields"]
    if "thumbnail_url" in asset and "thumbnailUrl" not in asset:
        asset["thumbnailUrl"] = asset["thumbnail_url"]
    if "thumbnailUrl" in asset and "thumbnail_url" not in asset:
        asset["thumbnail_url"] = asset["thumbnailUrl"]
    return asset


def find_frame_block_key(more_fields: dict[str, Any] | None, preferred_key: str | None = None) -> str:
    """Resolve the target frame block key in `more_fields`, supporting custom frame keys."""
    mf = more_fields if isinstance(more_fields, dict) else {}
    pref = _clean_text(preferred_key)
    if pref:
        return pref
    if "frames" in mf:
        return "frames"
    for k, val in mf.items():
        if isinstance(val, dict) and (
            val.get("type") == "frames"
            or "coordinates" in val
            or "placeholders" in val
            or "frame" in str(k).lower()
        ):
            return str(k)
    return "frames"


def sanitize_frame_coordinates(coords: Any) -> list[dict[str, Any]]:
    """Normalize frame placeholder coordinates cleanly to [-45, 45] degree bounds."""
    if not isinstance(coords, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for idx, c in enumerate(coords):
        if not isinstance(c, dict):
            continue
        try:
            rot = float(c.get("rotation") or 0)
        except Exception:
            rot = 0.0
        try:
            w = float(c.get("width") or 0)
        except Exception:
            w = 0.0
        try:
            h = float(c.get("height") or 0)
        except Exception:
            h = 0.0
        while rot > 45:
            rot -= 90
            w, h = h, w
        while rot < -45:
            rot += 90
            w, h = h, w
        rot = max(-45.0, min(45.0, round(rot, 2)))
        try:
            elev = int(c["elevation"]) if c.get("elevation") is not None else idx
        except Exception:
            elev = idx
        cleaned.append({
            "x": round(float(c.get("x") or 0)),
            "y": round(float(c.get("y") or 0)),
            "height": round(h),
            "width": round(w),
            "rotation": rot,
            "elevation": elev,
        })
    return cleaned


async def apply_frame_editor_save(
    db: AsyncIOMotorDatabase,
    *,
    app_instance_id: str,
    asset_id: str,
    payload: dict[str, Any],
    manager_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist Interactive Frame Editor updates at app level without altering Central Data."""
    before = await get_resolved_single_asset(db, app_instance_id=app_instance_id, asset_id=asset_id)
    if not before:
        raise NotFoundError("App instance asset not found.")

    preferred = payload.get("frameBlockKey") or payload.get("frame_block_key") or payload.get("block_key")
    block_key = find_frame_block_key(before.get("more_fields"), preferred)

    raw_mf = payload.get("moreFields") if "moreFields" in payload else payload.get("more_fields")
    if isinstance(raw_mf, dict):
        next_mf = {str(k): v for k, v in raw_mf.items()}
    else:
        next_mf = dict(before.get("more_fields") or {})

    target_block = next_mf.get(block_key)
    if isinstance(target_block, dict):
        img_url = str(target_block.get("image_url") or target_block.get("imageUrl") or payload.get("image_url") or "").strip()
        raw_coords = target_block.get("coordinates") if "coordinates" in target_block else target_block.get("placeholders")
        next_mf[block_key] = {
            "image_url": img_url,
            "coordinates": sanitize_frame_coordinates(raw_coords),
        }
    elif "coordinates" in payload or "image_url" in payload:
        existing_blk = next_mf.get(block_key) if isinstance(next_mf.get(block_key), dict) else {}
        img_url = str(payload.get("image_url") or existing_blk.get("image_url") or existing_blk.get("imageUrl") or "").strip()
        next_mf[block_key] = {
            "image_url": img_url,
            "coordinates": sanitize_frame_coordinates(payload.get("coordinates") or existing_blk.get("coordinates")),
        }

    res = await save_app_level_asset_edit_and_notify(
        db,
        app_instance_id=app_instance_id,
        asset_id=asset_id,
        payload={"more_fields": next_mf},
        manager_user=manager_user,
    )
    msg_sent = bool(res.get("message_sent"))
    return {
        "success": True,
        "asset_id": before["id"],
        "block_key": block_key,
        "message_sent": msg_sent,
        "message": (
            "Frame placeholders saved at app level & proposal sent to Admin."
            if msg_sent
            else "Frame placeholders saved at app level."
        ),
    }


async def check_instance_asset_name_availability(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    name: str,
    *,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    asset_id: str | None = None,
) -> dict[str, Any]:
    """Check asset name conflicts strictly within `app_instance_id` without querying Central Data."""
    clean_name = (name or "").strip()
    if not clean_name:
        return {"available": True, "exists": False}

    inst_oid = to_object_id(app_instance_id)
    match: dict[str, Any] = {"app_instance_id": inst_oid, "deleted_at": None}
    if sub_category_id:
        try:
            s_oid = to_object_id(sub_category_id)
            sub_doc = await db[INSTANCE_SUBCATEGORIES].find_one(
                {"app_instance_id": inst_oid, "$or": [{"_id": s_oid}, {"source_id": s_oid}], "deleted_at": None}
            )
            sub_candidates = [s_oid]
            if sub_doc:
                sub_candidates = [sub_doc["_id"]]
                if sub_doc.get("source_id") is not None:
                    sub_candidates.append(sub_doc["source_id"])
            match["sub_category_id"] = {"$in": sub_candidates}
        except Exception:
            pass
    elif category_id:
        try:
            c_oid = to_object_id(category_id)
            cat_doc = await db[INSTANCE_CATEGORIES].find_one(
                {"app_instance_id": inst_oid, "$or": [{"_id": c_oid}, {"source_id": c_oid}], "deleted_at": None}
            )
            cat_candidates = [c_oid]
            if cat_doc:
                cat_candidates = [cat_doc["_id"]]
                if cat_doc.get("source_id") is not None:
                    cat_candidates.append(cat_doc["source_id"])
            match["category_id"] = {"$in": cat_candidates}
        except Exception:
            pass

    rows = await db[INSTANCE_ASSETS].find(match, {"_id": 1, "name": 1, "overrides": 1, "source_id": 1}).to_list(length=1000)
    target_lower = clean_name.lower()
    exclude_id = str(asset_id or "").strip()

    linked_src_ids = [r["source_id"] for r in rows if r.get("source_id") is not None]
    src_names: dict[str, str] = {}
    if linked_src_ids:
        for ad in await db[ASSETS].find({"_id": {"$in": linked_src_ids}, "deleted_at": None}, {"name": 1}).to_list(length=1000):
            src_names[str(ad["_id"])] = str(ad.get("name") or "")

    for row in rows:
        if exclude_id and str(row["_id"]) == exclude_id:
            continue
        ov = row.get("overrides") or {}
        eff_name = str(ov.get("name") or row.get("name") or src_names.get(str(row.get("source_id") or ""), "")).strip()
        if eff_name.lower() == target_lower:
            return {
                "available": False,
                "exists": True,
                "message": f"An asset named '{clean_name}' already exists in this app folder.",
            }
    return {"available": True, "exists": False}


async def check_instance_media_similarity(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    filenames: list[str],
    *,
    existing_staged: list[str] | None = None,
    asset_id: str | None = None,
) -> list[dict[str, Any]]:
    """Compare candidate upload filenames strictly against staged items and this instance's own media."""
    import os
    from difflib import SequenceMatcher
    from config.paths import CENTRAL_DATA_DIR

    inst_oid = to_object_id(app_instance_id)
    exclude_id = str(asset_id or "").strip()

    known_files: list[str] = []
    for staged in (existing_staged or []):
        if staged:
            known_files.append(os.path.basename(str(staged)).strip().lower())

    rows = await db[INSTANCE_ASSETS].find(
        {"app_instance_id": inst_oid, "deleted_at": None},
        {"_id": 1, "thumbnail_url": 1, "overrides": 1, "source_id": 1},
    ).to_list(length=1000)
    for row in rows:
        if exclude_id and str(row["_id"]) == exclude_id:
            continue
        ov = row.get("overrides") or {}
        for url in (ov.get("thumbnail_url"), row.get("thumbnail_url")):
            if url:
                known_files.append(os.path.basename(str(url).split("?")[0]).lower())

    override_dir = CENTRAL_DATA_DIR / "instance_overrides" / str(app_instance_id)
    if override_dir.exists():
        for p in override_dir.rglob("*"):
            if p.is_file():
                known_files.append(p.name.lower())

    known_unique = sorted({k for k in known_files if k})
    results: list[dict[str, Any]] = []
    for fn in filenames:
        base = os.path.basename(str(fn or "")).strip()
        stem = os.path.splitext(base)[0].lower()
        base_low = base.lower()
        similar: list[dict[str, Any]] = []
        exact = False
        for kf in known_unique:
            kstem = os.path.splitext(kf)[0].lower()
            if kf == base_low:
                exact = True
                similar.append({"filename": kf, "score": 1.0, "exact": True})
            elif stem and kstem:
                ratio = SequenceMatcher(None, stem, kstem).ratio()
                if ratio >= 0.85:
                    similar.append({"filename": kf, "score": round(ratio, 2), "exact": False})
        results.append(
            {
                "filename": base,
                "has_conflict": exact or bool(similar),
                "exact_match": exact,
                "similar_files": similar[:5],
            }
        )
    return results


async def resolve_instance_upload_preselection(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str | None,
    sub_category_id: str | None,
) -> tuple[str, str]:
    """Map query `categoryId`/`subCategoryId` (instance `_id` or linked `source_id`) to scoped instance IDs."""
    if not category_id:
        return "", ""

    inst_oid = to_object_id(app_instance_id)
    try:
        c_oid = to_object_id(category_id)
    except Exception:
        return "", ""

    inst_cat = await db[INSTANCE_CATEGORIES].find_one(
        {"app_instance_id": inst_oid, "$or": [{"_id": c_oid}, {"source_id": c_oid}], "deleted_at": None},
        {"_id": 1, "source_id": 1},
    )
    if not inst_cat:
        return "", ""

    selected_cat = str(inst_cat["_id"])
    selected_sub = ""
    if sub_category_id:
        try:
            s_oid = to_object_id(sub_category_id)
            cat_candidates = [inst_cat["_id"]]
            if inst_cat.get("source_id") is not None:
                cat_candidates.append(inst_cat["source_id"])
            inst_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "category_id": {"$in": cat_candidates},
                    "$or": [{"_id": s_oid}, {"source_id": s_oid}],
                    "deleted_at": None,
                },
                {"_id": 1},
            )
            if inst_sub:
                selected_sub = str(inst_sub["_id"])
        except Exception:
            pass
    return selected_cat, selected_sub


async def _resolve_or_create_instance_only_folders(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    *,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    new_category_name: str | None = None,
    new_subcategory_name: str | None = None,
) -> tuple[Any, Any]:
    """Resolve existing app-instance folders or create native app-local folders without touching Central Data."""
    from controller.instance_workspace_controller import create_instance_folder

    inst_oid = to_object_id(app_instance_id)
    clean_new_cat = (new_category_name or "").strip()
    inst_cat_doc = None

    if clean_new_cat:
        inst_cat_doc = await db[INSTANCE_CATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "$or": [
                    {"name": {"$regex": f"^{re.escape(clean_new_cat)}$", "$options": "i"}},
                    {"overrides.name": {"$regex": f"^{re.escape(clean_new_cat)}$", "$options": "i"}},
                ],
                "deleted_at": None,
            }
        )
        if not inst_cat_doc:
            created = await create_instance_folder(
                db, app_instance_id, {"folder_type": "category", "name": clean_new_cat}
            )
            inst_cat_oid = to_object_id(created["id"])
        else:
            inst_cat_oid = inst_cat_doc["_id"]
    elif category_id:
        c_oid = to_object_id(category_id)
        inst_cat_doc = await db[INSTANCE_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": c_oid}, {"source_id": c_oid}], "deleted_at": None}
        )
        if not inst_cat_doc:
            raise ForbiddenError("Selected category is not part of this App Instance.")
        inst_cat_oid = inst_cat_doc["_id"]
    else:
        raise ValidationError("Category is required.")

    clean_new_sub = (new_subcategory_name or "").strip()
    cat_candidates = [inst_cat_oid]
    if inst_cat_doc and inst_cat_doc.get("source_id") is not None:
        cat_candidates.append(inst_cat_doc["source_id"])

    if clean_new_sub:
        inst_sub_doc = await db[INSTANCE_SUBCATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "category_id": {"$in": cat_candidates},
                "$or": [
                    {"name": {"$regex": f"^{re.escape(clean_new_sub)}$", "$options": "i"}},
                    {"overrides.name": {"$regex": f"^{re.escape(clean_new_sub)}$", "$options": "i"}},
                ],
                "deleted_at": None,
            }
        )
        if not inst_sub_doc:
            created_sub = await create_instance_folder(
                db,
                app_instance_id,
                {"folder_type": "subcategory", "name": clean_new_sub, "parent_category_id": str(inst_cat_oid)},
            )
            inst_sub_oid = to_object_id(created_sub["id"])
        else:
            inst_sub_oid = inst_sub_doc["_id"]
    elif sub_category_id:
        s_oid = to_object_id(sub_category_id)
        inst_sub_doc = await db[INSTANCE_SUBCATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "category_id": {"$in": cat_candidates},
                "$or": [{"_id": s_oid}, {"source_id": s_oid}],
                "deleted_at": None,
            }
        )
        if not inst_sub_doc:
            raise ForbiddenError("Selected subcategory is not part of this App Instance category.")
        inst_sub_oid = inst_sub_doc["_id"]
    else:
        raise ValidationError("Subcategory is required.")

    return inst_cat_oid, inst_sub_oid


async def create_instance_local_asset_for_instance(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    payload: dict[str, Any],
    manager_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create app-only asset(s) inside `instance_assets` without reading or writing Central Library."""
    inst_oid = to_object_id(app_instance_id)
    cat_id = payload.get("category_id") or payload.get("categoryId")
    sub_id = payload.get("sub_category_id") or payload.get("subCategoryId")
    inst_cat_oid, inst_sub_oid = await _resolve_or_create_instance_only_folders(
        db,
        app_instance_id,
        category_id=cat_id,
        sub_category_id=sub_id,
        new_category_name=payload.get("new_category_name") or payload.get("newCategoryName"),
        new_subcategory_name=payload.get("new_subcategory_name") or payload.get("newSubcategoryName"),
    )

    last_row = await db[INSTANCE_ASSETS].find_one(
        {"app_instance_id": inst_oid, "deleted_at": None},
        sort=[("sequence", -1)],
    )
    next_seq = (int(last_row.get("sequence", 0)) if last_row else 0) + 1
    now = utc_now()
    description = str(payload.get("description") or "").strip()

    async def _insert_one(
        asset_name: str,
        thumb_url: str | None = None,
        mf: dict[str, Any] | None = None,
    ) -> str:
        nonlocal next_seq
        avail = await check_instance_asset_name_availability(
            db, app_instance_id, asset_name, sub_category_id=str(inst_sub_oid)
        )
        if not avail.get("available", True):
            raise ConflictError(avail.get("message") or f"Asset '{asset_name}' already exists.")
        enriched_mf = enrich_more_fields_metadata(mf or {}) if mf else {}
        doc = {
            "app_instance_id": inst_oid,
            "source_id": None,
            "category_id": inst_cat_oid,
            "sub_category_id": inst_sub_oid,
            "name": asset_name,
            "description": description,
            "thumbnail_url": thumb_url,
            "more_fields": enriched_mf,
            "is_enabled": True,
            "is_premium": False,
            "is_rewarded": False,
            "is_priced": False,
            "rewarded_credits": 5,
            "sequence": next_seq,
            "views": 0,
            "downloads": 0,
            "overrides": {
                "name": asset_name,
                "description": description,
                "thumbnail_url": thumb_url,
                "more_fields": enriched_mf,
            },
            "created_by_role": "manager",
            "created_by_username": (manager_user or {}).get("username"),
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        next_seq += 1
        try:
            res = await db[INSTANCE_ASSETS].insert_one(doc)
        except DuplicateKeyError:
            raise ConflictError(
                f"Asset '{asset_name}' conflicts with an existing item in this app folder."
            )
        return str(res.inserted_id)

    names_list_raw = payload.get("names_list")
    names = parse_lines_list(names_list_raw or "") if names_list_raw else []
    if names:
        created_items: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for n in names:
            try:
                new_id = await _insert_one(n)
                created_items.append({"id": new_id, "name": n})
            except ConflictError as exc:
                errors.append({"name": n, "error": exc.message})
        return {
            "success": True,
            "bulk_text": True,
            "created_count": len(created_items),
            "created": created_items,
            "errors": errors,
        }

    more_fields = payload.get("more_fields") if payload.get("more_fields") is not None else payload.get("moreFields")
    if not isinstance(more_fields, dict):
        more_fields = {}
    raw_thumb = payload.get("thumbnail_url") if payload.get("thumbnail_url") is not None else payload.get("thumbnailUrl")
    clean_thumb = str(raw_thumb).strip() if raw_thumb and str(raw_thumb).strip() else None
    raw_name = payload.get("name")
    clean_name = str(raw_name).strip() if raw_name and str(raw_name).strip() else ""
    if not clean_name:
        clean_name = derive_asset_name(clean_thumb, more_fields)

    new_inst_id = await _insert_one(clean_name, clean_thumb, more_fields)
    return {
        "success": True,
        "id": new_inst_id,
        "instance_asset_id": new_inst_id,
        "name": clean_name,
        "app_local_only": True,
    }
