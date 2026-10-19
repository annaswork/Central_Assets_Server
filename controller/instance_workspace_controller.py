"""App instance working-set logic shared by the Admin and Manager portals.

Routers only handle auth/access checks and template/JSON rendering; everything else lives here.
"""

import re
from collections import defaultdict
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from controller.asset_controller import asset_has_type, list_assets
from controller.catalog_controller import (
    get_resolved_assets,
    get_resolved_categories,
    get_resolved_subcategories,
    get_resolved_super_categories,
)
from controller.category_controller import list_categories
from controller.reference_controller import link_super_category
from controller.subcategory_controller import list_subcategories
from controller.super_category_controller import list_super_categories
from database.collections import (
    ASSETS,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    INSTANCE_SUPER_CATEGORIES,
    SUBCATEGORIES,
)
from database.repository import instance_collection
from utils.datetimes import utc_now
from utils.errors import ValidationError
from utils.ids import to_object_id
from utils.sequencing import compute_next_sequence


def _clean(val: str | None) -> str | None:
    return val.strip() if val and val.strip() else None


async def _fallback_count(
    db: AsyncIOMotorDatabase,
    inst_oid: ObjectId,
    folder_coll: str,
    item_coll: str,
    field: str,
    ids: list[str],
) -> int:
    """Count items under a folder by every id form they may be stored as (_id/source_id, ObjectId/str)."""
    oids = [to_object_id(i) for i in ids if i]
    folder = await db[folder_coll].find_one(
        {"app_instance_id": inst_oid, "$or": [{"_id": {"$in": oids}}, {"source_id": {"$in": oids}}]}
    )
    if not folder:
        return 0
    keys = [folder["_id"]] + ([folder["source_id"]] if folder.get("source_id") else [])
    return await db[item_coll].count_documents(
        {"app_instance_id": inst_oid, field: {"$in": keys + [str(k) for k in keys]}, "deleted_at": None}
    )


async def _live_count(
    db: AsyncIOMotorDatabase,
    inst_oid: ObjectId,
    counts: dict[str, int],
    folder_coll: str,
    item_coll: str,
    field: str,
    fid: str,
    src: str,
) -> int:
    n = counts.get(fid, 0) or (counts.get(src, 0) if src else 0)
    return n or await _fallback_count(db, inst_oid, folder_coll, item_coll, field, [fid, src])


def _name_map(docs: list[dict[str, Any]]) -> dict[str, Any]:
    names: dict[str, Any] = {}
    for d in docs:
        if d.get("id"):
            names[str(d["id"])] = d.get("name")
        if d.get("sourceId"):
            names[str(d["sourceId"])] = d.get("name")
    return names


async def build_instance_content(
    db: AsyncIOMotorDatabase,
    instance_id: str,
    *,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    sort: str | None = None,
    asset_type: str | None = None,
    search_query: str = "",
    folder_cat: str | None = None,
    folder_sort: str | None = None,
    folder_search: str | None = None,
    folder_super: str | None = None,
    extra_name_categories: list[dict[str, Any]] | None = None,
    extra_name_subcategories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve folders, live counts, and filtered assets for the instance content page."""
    inst_oid = to_object_id(instance_id)
    categories = await get_resolved_categories(db, app_instance_id=instance_id)
    all_subcategories = await get_resolved_subcategories(db, app_instance_id=instance_id)
    s_order = sort or "sequence"

    # Fetch all instance assets so folder asset badges reflect true counts across all folders
    all_instance_assets = await get_resolved_assets(db, app_instance_id=instance_id, sort=s_order)
    if category_id or sub_category_id:
        assets = await get_resolved_assets(
            db,
            app_instance_id=instance_id,
            category_id=category_id,
            sub_category_id=sub_category_id,
            sort=s_order,
        )
    else:
        assets = all_instance_assets

    sub_asset_counts: dict[str, int] = defaultdict(int)
    cat_asset_counts: dict[str, int] = defaultdict(int)
    for a in all_instance_assets:
        if a.get("subCategoryId"):
            sub_asset_counts[str(a["subCategoryId"])] += 1
        if a.get("categoryId"):
            cat_asset_counts[str(a["categoryId"])] += 1

    cat_sub_counts: dict[str, int] = defaultdict(int)
    for s in all_subcategories:
        if s.get("categoryId"):
            cat_sub_counts[str(s["categoryId"])] += 1

    for cat in categories:
        cid = str(cat.get("id") or "")
        c_src = str(cat.get("sourceId") or cat.get("source_id") or "")
        cat["subcategories_count"] = await _live_count(
            db, inst_oid, cat_sub_counts, INSTANCE_CATEGORIES, INSTANCE_SUBCATEGORIES, "category_id", cid, c_src
        )
        cat["assets_count"] = await _live_count(
            db, inst_oid, cat_asset_counts, INSTANCE_CATEGORIES, INSTANCE_ASSETS, "category_id", cid, c_src
        )

    for sub in all_subcategories:
        sid = str(sub.get("id") or "")
        s_src = str(sub.get("sourceId") or sub.get("source_id") or "")
        sub["assets_count"] = await _live_count(
            db, inst_oid, sub_asset_counts, INSTANCE_SUBCATEGORIES, INSTANCE_ASSETS, "sub_category_id", sid, s_src
        )

    # Category alias map: both cat["id"] and cat["sourceId"] resolve to cat["id"]
    cat_alias_map: dict[str, str] = {}
    for c in categories:
        cid = str(c.get("id") or "")
        csrc = str(c.get("sourceId") or c.get("source_id") or "")
        if cid:
            cat_alias_map[cid] = cid
        if csrc:
            cat_alias_map[csrc] = cid

    for s in all_subcategories:
        raw_cat_id = str(s.get("categoryId") or "")
        s["canonicalCategoryId"] = cat_alias_map.get(raw_cat_id, raw_cat_id)
        s["categoryId"] = s["canonicalCategoryId"]
        s["category_id"] = s["canonicalCategoryId"]

    # All valid identifier forms for the selected category (id and sourceId)
    valid_cat_ids: set[str] = set()
    selected_cat_val = ""
    if category_id:
        for c in categories:
            if str(c.get("id")) == category_id or str(c.get("sourceId")) == category_id:
                selected_cat_val = str(c.get("id") or category_id)
                if c.get("id"):
                    valid_cat_ids.add(str(c["id"]))
                if c.get("sourceId"):
                    valid_cat_ids.add(str(c["sourceId"]))
                break
        if not valid_cat_ids:
            valid_cat_ids.add(str(category_id))
            selected_cat_val = str(category_id)

    filtered_subcategories = (
        [s for s in all_subcategories if str(s.get("canonicalCategoryId")) in valid_cat_ids or str(s.get("categoryId")) in valid_cat_ids]
        if category_id
        else all_subcategories
    )

    selected_subcat_val = ""
    if sub_category_id:
        for s in all_subcategories:
            if str(s.get("id")) == sub_category_id or str(s.get("sourceId")) == sub_category_id:
                selected_subcat_val = str(s.get("id") or sub_category_id)
                break
        if not selected_subcat_val:
            selected_subcat_val = str(sub_category_id)

    clean_type = (asset_type or "").strip().lower()
    if clean_type:
        assets = [
            a for a in assets
            if asset_has_type(a.get("more_fields") or a.get("moreFields"), clean_type, a.get("thumbnail_url"))
        ]

    # In-memory name fallback for instant display
    cat_map = _name_map(categories + (extra_name_categories or []))
    sub_map = _name_map(all_subcategories + (extra_name_subcategories or []))
    for a in assets:
        c_id = str(a.get("categoryId") or "")
        s_id = str(a.get("subCategoryId") or "")
        if not a.get("category_name") or a["category_name"] == "—":
            a["category_name"] = cat_map.get(c_id) or a.get("category_name") or "—"
        a["categoryName"] = a["category_name"]
        if not a.get("subcategory_name") or a["subcategory_name"] == "—":
            a["subcategory_name"] = sub_map.get(s_id) or a.get("subcategory_name") or "—"
        a["subCategoryName"] = a["subcategory_name"]

    if search_query:
        sq = search_query.lower()
        assets = [
            a for a in assets
            if sq in (a.get("name") or "").lower()
            or sq in (a.get("category_name") or "").lower()
            or sq in (a.get("subcategory_name") or "").lower()
            or any(sq in str(t).lower() for t in a.get("tags", []))
        ]

    # Super categories (optional top level) with live category counts and names on each category
    super_categories = await get_resolved_super_categories(db, app_instance_id=instance_id)
    super_names = {sc["id"]: sc["name"] for sc in super_categories}
    linked_central_ids = {
        str(i)
        for i in await db[INSTANCE_SUPER_CATEGORIES].distinct(
            "source_id", {"app_instance_id": inst_oid, "deleted_at": None}
        )
        if i
    }
    # Central super categories not in this app yet: picking one on a category links it in
    available_super_categories = [
        sc for sc in await list_super_categories(db) if sc["id"] not in linked_central_ids
    ]
    for c in categories:
        c["super_category_name"] = super_names.get(c.get("superCategoryId") or "")
    for sc in super_categories:
        sc["categories_count"] = sum(1 for c in categories if c.get("superCategoryId") == sc["id"])

    # Folder section filtering
    displayed_categories = list(categories)
    if folder_super == "none":
        displayed_categories = [c for c in displayed_categories if not c.get("super_category_name")]
    elif folder_super:
        displayed_categories = [c for c in displayed_categories if c.get("superCategoryId") == folder_super]
    if folder_cat:
        displayed_categories = [
            c for c in displayed_categories
            if str(c.get("id")) == folder_cat or str(c.get("sourceId")) == folder_cat
        ]

    if folder_search and folder_search.strip():
        fs = folder_search.strip().lower()
        displayed_categories = [
            c for c in displayed_categories
            if fs in (c.get("name") or "").lower()
            or any(
                fs in (s.get("name") or "").lower()
                for s in all_subcategories
                if str(s.get("categoryId")) in (str(c.get("id")), str(c.get("sourceId")))
            )
        ]

    folder_sort_keys = {
        "name": (lambda c: (c.get("name") or "").lower(), False),
        "newest": (lambda c: str(c.get("created_at") or ""), True),
        "oldest": (lambda c: str(c.get("created_at") or ""), False),
        "sequence": (lambda c: c.get("sequence", 0), False),
    }
    if folder_sort and folder_sort.strip().lower() in folder_sort_keys:
        key, reverse = folder_sort_keys[folder_sort.strip().lower()]
        displayed_categories.sort(key=key, reverse=reverse)

    return {
        "categories": displayed_categories,
        "all_categories": categories,
        "subcategories": filtered_subcategories,
        "all_subcategories": all_subcategories,
        "assets": assets,
        "selected_cat": selected_cat_val,
        "selected_subcat": selected_subcat_val,
        "selected_type": clean_type,
        "type": clean_type,
        "current_sort": s_order,
        "sort": s_order,
        "search": search_query,
        "q": search_query,
        "folder_cat": folder_cat or "",
        "folder_sort": folder_sort or "sequence",
        "folder_search": folder_search or "",
        "super_categories": super_categories,
        "available_super_categories": available_super_categories,
        "folder_super": folder_super or "",
    }


# --- Central content picker -------------------------------------------------


async def _folder_keys(db: AsyncIOMotorDatabase, coll: str, inst_oid: ObjectId, raw_id: str) -> set[Any]:
    """Every stored form (_id/source_id, ObjectId/str) of an instance folder referenced by raw_id."""
    oid = to_object_id(raw_id)
    keys: set[Any] = {oid, str(oid), raw_id}
    doc = await instance_collection(db, coll).find_one({"app_instance_id": inst_oid, "$or": [{"_id": oid}, {"source_id": oid}]})
    if doc:
        keys |= {doc["_id"], str(doc["_id"])}
        if doc.get("source_id"):
            keys |= {doc["source_id"], str(doc["source_id"])}
    return keys


async def picker_categories(db: AsyncIOMotorDatabase, instance_id: str, q: str | None = None) -> list[dict[str, Any]]:
    inst_oid = to_object_id(instance_id)
    active_ids = set(
        await db[INSTANCE_CATEGORIES].distinct("source_id", {"app_instance_id": inst_oid, "deleted_at": None})
    )
    items = (await list_categories(db, search=_clean(q), page=1, page_size=200)).get("items", [])
    for cat in items:
        c_oid = to_object_id(cat["id"])
        cat["subcategory_count"] = await db[SUBCATEGORIES].count_documents({"category_id": c_oid, "deleted_at": None})
        cat["asset_count"] = await db[ASSETS].count_documents({"category_id": c_oid, "deleted_at": None})
        cat["already_added"] = c_oid in active_ids
    return items


async def picker_subcategories(
    db: AsyncIOMotorDatabase,
    instance_id: str,
    category_id: str | None = None,
    q: str | None = None,
    target_category_id: str | None = None,
) -> list[dict[str, Any]]:
    inst_oid = to_object_id(instance_id)
    active_docs = await db[INSTANCE_SUBCATEGORIES].find(
        {"app_instance_id": inst_oid, "deleted_at": None}, {"source_id": 1, "category_id": 1}
    ).to_list(length=None)
    active_ids = {s["source_id"] for s in active_docs if s.get("source_id")}
    target_keys = (
        await _folder_keys(db, INSTANCE_CATEGORIES, inst_oid, target_category_id) if target_category_id else set()
    )
    target_ids = {s["source_id"] for s in active_docs if s.get("source_id") and s.get("category_id") in target_keys}

    items = (
        await list_subcategories(db, category_id=_clean(category_id), search=_clean(q), page=1, page_size=500)
    ).get("items", [])
    for sub in items:
        s_oid = to_object_id(sub["id"])
        sub["asset_count"] = await db[ASSETS].count_documents({"sub_category_id": s_oid, "deleted_at": None})
        sub["already_added"] = s_oid in active_ids
        sub["already_in_target"] = s_oid in target_ids
    return items


async def picker_assets(
    db: AsyncIOMotorDatabase,
    instance_id: str,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    q: str | None = None,
    target_sub_category_id: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    inst_oid = to_object_id(instance_id)
    active_ids = set(
        await db[INSTANCE_ASSETS].distinct("source_id", {"app_instance_id": inst_oid, "deleted_at": None})
    )
    target_ids: set[Any] = set()
    if target_sub_category_id:
        sub_keys = await _folder_keys(db, INSTANCE_SUBCATEGORIES, inst_oid, target_sub_category_id)
        target_ids = set(
            await db[INSTANCE_ASSETS].distinct(
                "source_id",
                {"app_instance_id": inst_oid, "sub_category_id": {"$in": list(sub_keys)}, "deleted_at": None},
            )
        )

    result = await list_assets(
        db,
        category_id=_clean(category_id),
        sub_category_id=_clean(sub_category_id),
        search=_clean(q),
        page=page,
        page_size=page_size,
    )
    items = result.get("items", [])
    for a in items:
        a_oid = to_object_id(a["id"])
        a["already_added"] = a_oid in active_ids
        a["already_in_target"] = a_oid in target_ids
    return {"items": items, "total": result.get("total", 0)}


async def picker_super_categories(db: AsyncIOMotorDatabase, instance_id: str) -> list[dict[str, Any]]:
    """Central super categories with category counts, marked if already referenced in this instance."""
    active_ids = set(
        await db[INSTANCE_SUPER_CATEGORIES].distinct(
            "source_id", {"app_instance_id": to_object_id(instance_id), "deleted_at": None}
        )
    )
    items = await list_super_categories(db)
    for sc in items:
        sc["already_added"] = to_object_id(sc["id"]) in active_ids
    return items


async def build_picker_page(
    db: AsyncIOMotorDatabase,
    instance_id: str,
    target_category_id: str | None = None,
    target_sub_category_id: str | None = None,
    target_super_category_id: str | None = None,
) -> dict[str, Any]:
    """Template context for the full central picker page."""
    return {
        "super_categories": await picker_super_categories(db, instance_id),
        "target_super_category_id": target_super_category_id or "",
        "categories": await picker_categories(db, instance_id),
        "subcategories": await picker_subcategories(db, instance_id, target_category_id=target_category_id),
        "initial_assets": (
            await picker_assets(db, instance_id, target_sub_category_id=target_sub_category_id)
        )["items"],
        "target_category_id": target_category_id or "",
        "target_sub_category_id": target_sub_category_id or "",
    }


# --- Request payload parsing & folder creation ------------------------------


def parse_reference_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize an import request body (id lists and/or polymorphic `items`) into add_references kwargs."""
    ids: dict[str, list[str]] = {
        "super_category_ids": list(data.get("super_category_ids") or []),
        "category_ids": list(data.get("category_ids") or []),
        "sub_category_ids": list(data.get("sub_category_ids") or []),
        "asset_ids": list(data.get("asset_ids") or []),
    }
    type_to_key = {
        "super_category": "super_category_ids",
        "supercategory": "super_category_ids",
        "asset": "asset_ids",
        "category": "category_ids",
        "subcategory": "sub_category_ids",
        "sub_category": "sub_category_ids",
    }
    for item in data.get("items", []):
        key = type_to_key.get(item.get("target_type") or item.get("type"))
        t_id = item.get("target_id") or item.get("id")
        if key and t_id:
            ids[key].append(t_id)
    return {
        **{k: list(dict.fromkeys(v)) for k, v in ids.items()},
        "target_category_id": data.get("target_category_id") or None,
        "target_sub_category_id": data.get("target_sub_category_id") or None,
        "target_super_category_id": data.get("target_super_category_id") or None,
    }


def parse_asset_override_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize an asset override body (snake/camel aliases) into update_item_settings_and_overrides kwargs."""
    is_rewarded = payload.get("is_rewarded")
    if is_rewarded is None:
        is_rewarded = payload.get("isRewarded")
    is_priced = payload.get("is_priced")
    if is_priced is None:
        is_priced = payload.get("isPriced")
    rewarded_credits = payload.get("rewarded_credits")
    if rewarded_credits is None:
        for alias in ("rewardedCredits", "credit", "credits"):
            if alias in payload:
                rewarded_credits = payload[alias]
                break

    overrides: dict[str, Any] = {}
    if payload.get("name") is not None:
        overrides["name"] = str(payload["name"]).strip()
    if "tags" in payload:
        raw_tags = payload.get("tags")
        if isinstance(raw_tags, str):
            overrides["tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            overrides["tags"] = [str(t).strip() for t in raw_tags if str(t).strip()]
        else:
            overrides["tags"] = []

    return {
        "is_enabled": payload.get("is_enabled"),
        "sequence": payload.get("sequence"),
        "is_premium": payload.get("is_premium"),
        "is_rewarded": is_rewarded,
        "is_priced": is_priced,
        "rewarded_credits": rewarded_credits,
        "overrides": overrides or None,
    }


async def _create_or_restore_folder(
    db: AsyncIOMotorDatabase,
    coll: str,
    scope: dict[str, Any],
    name: str,
    thumbnail_url: str | None,
    duplicate_msg: str,
    extra: dict[str, Any] | None = None,
) -> ObjectId:
    """Insert a custom (source_id=None) folder within `scope`, or revive a soft-deleted one with the same name.

    `extra` fields (e.g. a category's super_category_id) are written on insert and on revive.
    """
    extra = extra or {}
    now = utc_now()
    existing = await instance_collection(db, coll).find_one({**scope, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
    if existing:
        if existing.get("deleted_at") is None:
            raise ValidationError(duplicate_msg)
        await instance_collection(db, coll).update_one(
            {"_id": existing["_id"]},
            {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now, **extra}},
        )
        return existing["_id"]

    max_seq_doc = await instance_collection(db, coll).find_one({**scope, "deleted_at": None}, sort=[("sequence", -1)])
    oid = ObjectId()
    await instance_collection(db, coll).insert_one(
        {
            "_id": oid,
            **scope,
            **extra,
            "source_id": None,
            "name": name,
            "thumbnail_url": thumbnail_url,
            "is_enabled": True,
            "sequence": compute_next_sequence(max_seq_doc.get("sequence") if max_seq_doc else None),
            "overrides": {"name": name, "thumbnail_url": thumbnail_url},
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
    )
    return oid


async def create_instance_folder(db: AsyncIOMotorDatabase, instance_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Create a custom super category, category or subcategory folder in an app instance.

    Raises ValidationError on bad input.
    """
    folder_type = str(data.get("folder_type", "category")).strip().lower().replace("super_category", "supercategory")
    name = (data.get("name") or "").strip()
    parent_category_id = (data.get("parent_category_id") or "").strip()
    parent_super_category_id = (data.get("parent_super_category_id") or "").strip()
    thumbnail_url = (data.get("thumbnail_url") or "").strip() or None

    if not name:
        raise ValidationError("Folder name is required")

    inst_oid = to_object_id(instance_id)

    if folder_type == "supercategory":
        oid = await _create_or_restore_folder(
            db,
            INSTANCE_SUPER_CATEGORIES,
            {"app_instance_id": inst_oid},
            name,
            thumbnail_url,
            f"Super category '{name}' already exists in this app instance",
        )
    elif folder_type == "category":
        extra = {}
        if parent_super_category_id:
            extra["super_category_id"] = await _instance_super_id(db, inst_oid, parent_super_category_id)
        oid = await _create_or_restore_folder(
            db,
            INSTANCE_CATEGORIES,
            {"app_instance_id": inst_oid},
            name,
            thumbnail_url,
            f"Category folder '{name}' already exists in this app instance",
            extra,
        )
    elif folder_type == "subcategory":
        if not parent_category_id:
            raise ValidationError("Parent category is required for sub-folder")
        p_oid = to_object_id(parent_category_id)
        parent_cat = await db[INSTANCE_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": p_oid}, {"source_id": p_oid}], "deleted_at": None}
        )
        if not parent_cat:
            raise ValidationError("Parent category not found in this app instance")
        oid = await _create_or_restore_folder(
            db,
            INSTANCE_SUBCATEGORIES,
            {"app_instance_id": inst_oid, "category_id": parent_cat["_id"]},
            name,
            thumbnail_url,
            f"Subcategory folder '{name}' already exists in this category",
        )
    else:
        raise ValidationError(f"Unknown folder type: {folder_type}")

    return {"success": True, "folder_type": folder_type, "id": str(oid), "name": name}


async def _instance_super_id(db: AsyncIOMotorDatabase, inst_oid: ObjectId, raw_id: str) -> ObjectId:
    """Resolve an instance super category by instance _id or source_id.

    A central super category id that isn't in this app yet is linked in (or revived) first.
    """
    try:
        oid = to_object_id(raw_id)
    except ValueError as err:
        raise ValidationError("Invalid super category id") from err
    sup = await instance_collection(db, INSTANCE_SUPER_CATEGORIES).find_one(
        {"app_instance_id": inst_oid, "$or": [{"_id": oid}, {"source_id": oid}], "deleted_at": None}, {"_id": 1}
    )
    if sup:
        return sup["_id"]
    linked = await link_super_category(db, str(inst_oid), str(oid))
    if not linked:
        raise ValidationError("Super category not found")
    return linked


async def set_category_super_category(
    db: AsyncIOMotorDatabase, instance_id: str, category_id: str, super_category_id: str | None
) -> dict[str, Any]:
    """Move an instance category into a super category, or ungroup it when super_category_id is empty."""
    inst_oid = to_object_id(instance_id)
    try:
        c_oid = to_object_id(category_id)
    except ValueError as err:
        raise ValidationError("Invalid category id") from err
    sup_id = await _instance_super_id(db, inst_oid, super_category_id) if super_category_id else None
    res = await instance_collection(db, INSTANCE_CATEGORIES).update_one(
        {"app_instance_id": inst_oid, "$or": [{"_id": c_oid}, {"source_id": c_oid}], "deleted_at": None},
        {"$set": {"super_category_id": sup_id, "updated_at": utc_now()}},
    )
    if not res.matched_count:
        raise ValidationError("Category not found in this app instance")
    return {"success": True, "category_id": category_id, "super_category_id": str(sup_id) if sup_id else None}
