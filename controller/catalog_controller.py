"""Client-facing catalog resolution using single-stage MongoDB aggregation pipelines.

STRICT LAYER RULE:
Reads instance reference rows and joins central documents via $lookup.
Implements the canonical resolution merge:
  effective = { **central_document, **row.overrides }
              + is_enabled, sequence, is_premium, views, downloads, sourceId
Filters out unresolvable items whose central source is deleted.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import (
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    SUBCATEGORIES,
)
from utils.ids import to_object_id


async def get_resolved_categories(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    only_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve resolved categories for an app instance with overrides merged."""
    inst_oid = to_object_id(app_instance_id)

    match_filter: dict[str, Any] = {"app_instance_id": inst_oid, "deleted_at": None}
    if only_enabled:
        match_filter["is_enabled"] = True

    pipeline = [
        {"$match": match_filter},
        {
            "$lookup": {
                "from": CATEGORIES,
                "localField": "source_id",
                "foreignField": "_id",
                "as": "central",
            }
        },
        # Preserve categories created directly in the app instance (where source_id is None)
        {"$unwind": {"path": "$central", "preserveNullAndEmptyArrays": True}},
        {
            "$match": {
                "$or": [
                    {"central": None},
                    {"central.deleted_at": None},
                ]
            }
        },
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "sourceId": {
                    "$cond": [
                        {"$ifNull": ["$source_id", False]},
                        {"$toString": "$source_id"},
                        {"$toString": "$_id"},
                    ]
                },
                "is_enabled": "$is_enabled",
                "sequence": "$sequence",
                "overrides": {"$ifNull": ["$overrides", {}]},
                "merged": {
                    "$mergeObjects": [
                        {
                            "name": "$name",
                            "thumbnail_url": "$thumbnail_url",
                        },
                        {"$ifNull": ["$central", {}]},
                        {"$ifNull": ["$overrides", {}]},
                    ]
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "id": 1,
                "sourceId": 1,
                "is_enabled": 1,
                "sequence": 1,
                "overrides": 1,
                "name": "$merged.name",
                "thumbnail_url": "$merged.thumbnail_url",
                "image_url": "$merged.image_url",
            }
        },
        {"$sort": {"sequence": 1, "name": 1}},
    ]

    cursor = db[INSTANCE_CATEGORIES].aggregate(pipeline)
    return await cursor.to_list(length=None)


async def get_resolved_subcategories(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str | None = None,
    only_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve resolved subcategories for an app instance."""
    inst_oid = to_object_id(app_instance_id)

    match_filter: dict[str, Any] = {"app_instance_id": inst_oid, "deleted_at": None}
    if category_id:
        c_oid = to_object_id(category_id)
        cat_doc = await db[INSTANCE_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": c_oid}, {"source_id": c_oid}]}
        )
        if cat_doc:
            possible_cat_ids = [cat_doc["_id"]]
            if cat_doc.get("source_id"):
                possible_cat_ids.append(cat_doc["source_id"])
            match_filter["category_id"] = {"$in": possible_cat_ids}
        else:
            match_filter["category_id"] = c_oid
    if only_enabled:
        match_filter["is_enabled"] = True

    pipeline = [
        {"$match": match_filter},
        {
            "$lookup": {
                "from": SUBCATEGORIES,
                "localField": "source_id",
                "foreignField": "_id",
                "as": "central",
            }
        },
        # Preserve subcategories created directly in the app instance (where source_id is None)
        {"$unwind": {"path": "$central", "preserveNullAndEmptyArrays": True}},
        {
            "$match": {
                "$or": [
                    {"central": None},
                    {"central.deleted_at": None},
                ]
            }
        },
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "sourceId": {
                    "$cond": [
                        {"$ifNull": ["$source_id", False]},
                        {"$toString": "$source_id"},
                        {"$toString": "$_id"},
                    ]
                },
                "categoryId": {"$toString": "$category_id"},
                "is_enabled": "$is_enabled",
                "sequence": "$sequence",
                "overrides": {"$ifNull": ["$overrides", {}]},
                "merged": {
                    "$mergeObjects": [
                        {
                            "name": "$name",
                            "thumbnail_url": "$thumbnail_url",
                        },
                        {"$ifNull": ["$central", {}]},
                        {"$ifNull": ["$overrides", {}]},
                    ]
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "id": 1,
                "sourceId": 1,
                "categoryId": 1,
                "is_enabled": 1,
                "sequence": 1,
                "overrides": 1,
                "name": "$merged.name",
                "thumbnail_url": "$merged.thumbnail_url",
                "image_url": "$merged.image_url",
            }
        },
        {"$sort": {"sequence": 1, "name": 1}},
    ]

    cursor = db[INSTANCE_SUBCATEGORIES].aggregate(pipeline)
    return await cursor.to_list(length=None)


async def get_resolved_assets(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    only_enabled: bool = False,
    sort: str | None = None,
    order: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve resolved assets for an app instance."""
    inst_oid = to_object_id(app_instance_id)

    match_filter: dict[str, Any] = {"app_instance_id": inst_oid, "deleted_at": None}
    if category_id:
        c_oid = to_object_id(category_id)
        cat_doc = await db[INSTANCE_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": c_oid}, {"source_id": c_oid}]}
        )
        if cat_doc:
            possible_cat_ids = [cat_doc["_id"]]
            if cat_doc.get("source_id"):
                possible_cat_ids.append(cat_doc["source_id"])
            match_filter["category_id"] = {"$in": possible_cat_ids}
        else:
            match_filter["category_id"] = c_oid
    if sub_category_id:
        s_oid = to_object_id(sub_category_id)
        sub_doc = await db[INSTANCE_SUBCATEGORIES].find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": s_oid}, {"source_id": s_oid}]}
        )
        if sub_doc:
            possible_sub_ids = [sub_doc["_id"]]
            if sub_doc.get("source_id"):
                possible_sub_ids.append(sub_doc["source_id"])
            match_filter["sub_category_id"] = {"$in": possible_sub_ids}
        else:
            match_filter["sub_category_id"] = s_oid
    if only_enabled:
        match_filter["$or"] = [
            {"overrides.is_enabled": True},
            {"overrides.is_enabled": {"$exists": False}, "is_enabled": True},
        ]

    pipeline = [
        {"$match": match_filter},
        {
            "$lookup": {
                "from": ASSETS,
                "localField": "source_id",
                "foreignField": "_id",
                "as": "central",
            }
        },
        # Lookup Category name from central CATEGORIES or INSTANCE_CATEGORIES
        {
            "$lookup": {
                "from": CATEGORIES,
                "localField": "category_id",
                "foreignField": "_id",
                "as": "cat_central",
            }
        },
        {
            "$lookup": {
                "from": INSTANCE_CATEGORIES,
                "localField": "category_id",
                "foreignField": "_id",
                "as": "cat_inst",
            }
        },
        # Lookup Subcategory name from central SUBCATEGORIES or INSTANCE_SUBCATEGORIES
        {
            "$lookup": {
                "from": SUBCATEGORIES,
                "localField": "sub_category_id",
                "foreignField": "_id",
                "as": "sub_central",
            }
        },
        {
            "$lookup": {
                "from": INSTANCE_SUBCATEGORIES,
                "localField": "sub_category_id",
                "foreignField": "_id",
                "as": "sub_inst",
            }
        },
        # Preserve assets created directly in instance without a central link
        {"$unwind": {"path": "$central", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$cat_central", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$cat_inst", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$sub_central", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$sub_inst", "preserveNullAndEmptyArrays": True}},
        {
            "$match": {
                "$or": [
                    {"central": None},
                    {"central.deleted_at": None},
                ]
            }
        },
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "sourceId": {
                    "$cond": [
                        {"$ifNull": ["$source_id", False]},
                        {"$toString": "$source_id"},
                        {"$toString": "$_id"},
                    ]
                },
                "categoryId": {"$toString": "$category_id"},
                "subCategoryId": {"$toString": "$sub_category_id"},
                "category_name": {
                    "$ifNull": [
                        "$cat_inst.name",
                        {"$ifNull": ["$cat_central.name", "—"]}
                    ]
                },
                "subcategory_name": {
                    "$ifNull": [
                        "$sub_inst.name",
                        {"$ifNull": ["$sub_central.name", "—"]}
                    ]
                },
                "is_enabled": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_enabled"}, "missing"]},
                        "$overrides.is_enabled",
                        "$is_enabled",
                    ]
                },
                "is_premium": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_premium"}, "missing"]},
                        "$overrides.is_premium",
                        "$is_premium",
                    ]
                },
                "sequence": "$sequence",
                "views": {"$ifNull": ["$views", 0]},
                "downloads": {"$ifNull": ["$downloads", 0]},
                "created_at": {"$ifNull": ["$created_at", "$central.created_at"]},
                "updated_at": {"$ifNull": ["$updated_at", "$central.updated_at"]},
                "overrides": "$overrides",
                "merged": {"$mergeObjects": ["$central", "$overrides"]},
            }
        },
        {
            "$project": {
                "_id": 0,
                "id": 1,
                "sourceId": 1,
                "categoryId": 1,
                "subCategoryId": 1,
                "category_name": 1,
                "categoryName": "$category_name",
                "subcategory_name": 1,
                "subCategoryName": "$subcategory_name",
                "is_enabled": 1,
                "is_premium": 1,
                "sequence": 1,
                "views": 1,
                "downloads": 1,
                "created_at": 1,
                "updated_at": 1,
                "overrides": 1,
                "name": "$merged.name",
                "description": "$merged.description",
                "thumbnail_url": "$merged.thumbnail_url",
                "thumbnailUrl": "$merged.thumbnail_url",
                "moreFields": "$merged.more_fields",
                "more_fields": "$merged.more_fields",
            }
        },
    ]

    s_clean = (sort or "").strip().lower()
    o_clean = (order or "").strip().lower()

    if s_clean in ("name", "by_name", "title"):
        dir_val = -1 if o_clean == "desc" else 1
        sort_stage = {"$sort": {"name": dir_val, "sequence": 1}}
    elif s_clean in ("newest",) or (s_clean in ("created_at", "created") and o_clean == "desc"):
        sort_stage = {"$sort": {"created_at": -1, "name": 1}}
    elif s_clean in ("oldest",) or (s_clean in ("created_at", "created") and o_clean == "asc"):
        sort_stage = {"$sort": {"created_at": 1, "name": 1}}
    elif s_clean in ("most_viewed", "views"):
        dir_val = 1 if o_clean == "asc" else -1
        sort_stage = {"$sort": {"views": dir_val, "sequence": 1, "name": 1}}
    elif s_clean in ("most_downloaded", "downloads"):
        dir_val = 1 if o_clean == "asc" else -1
        sort_stage = {"$sort": {"downloads": dir_val, "sequence": 1, "name": 1}}
    else:
        dir_val = -1 if o_clean == "desc" else 1
        sort_stage = {"$sort": {"sequence": dir_val, "name": 1}}

    pipeline.append(sort_stage)

    cursor = db[INSTANCE_ASSETS].aggregate(pipeline)
    return await cursor.to_list(length=None)


async def get_resolved_single_asset(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    asset_id: str,
) -> dict[str, Any] | None:
    """Retrieve single resolved asset by ID or source ID."""
    inst_oid = to_object_id(app_instance_id)
    asset_oid = to_object_id(asset_id)

    pipeline = [
        {
            "$match": {
                "app_instance_id": inst_oid,
                "$or": [{"_id": asset_oid}, {"source_id": asset_oid}],
                "deleted_at": None,
            }
        },
        {
            "$lookup": {
                "from": ASSETS,
                "localField": "source_id",
                "foreignField": "_id",
                "as": "central",
            }
        },
        {"$unwind": "$central"},
        {"$match": {"central.deleted_at": None}},
        {
            "$lookup": {
                "from": CATEGORIES,
                "localField": "category_id",
                "foreignField": "_id",
                "as": "central_cat",
            }
        },
        {
            "$lookup": {
                "from": INSTANCE_CATEGORIES,
                "localField": "category_id",
                "foreignField": "_id",
                "as": "inst_cat",
            }
        },
        {
            "$lookup": {
                "from": SUBCATEGORIES,
                "localField": "sub_category_id",
                "foreignField": "_id",
                "as": "central_sub",
            }
        },
        {
            "$lookup": {
                "from": INSTANCE_SUBCATEGORIES,
                "localField": "sub_category_id",
                "foreignField": "_id",
                "as": "inst_sub",
            }
        },
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "sourceId": {"$toString": "$source_id"},
                "categoryId": {
                    "$cond": [
                        {"$ifNull": ["$category_id", False]},
                        {"$toString": "$category_id"},
                        {"$toString": "$central.category_id"},
                    ]
                },
                "subCategoryId": {
                    "$cond": [
                        {"$ifNull": ["$sub_category_id", False]},
                        {"$toString": "$sub_category_id"},
                        {"$toString": "$central.sub_category_id"},
                    ]
                },
                "category_name": {
                    "$ifNull": [
                        {"$first": "$inst_cat.name"},
                        {"$ifNull": [{"$first": "$central_cat.name"}, "—"]},
                    ]
                },
                "subcategory_name": {
                    "$ifNull": [
                        {"$first": "$inst_sub.name"},
                        {"$ifNull": [{"$first": "$central_sub.name"}, "—"]},
                    ]
                },
                "is_enabled": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_enabled"}, "missing"]},
                        "$overrides.is_enabled",
                        "$is_enabled",
                    ]
                },
                "is_premium": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_premium"}, "missing"]},
                        "$overrides.is_premium",
                        "$is_premium",
                    ]
                },
                "sequence": "$sequence",
                "views": {"$ifNull": ["$views", 0]},
                "downloads": {"$ifNull": ["$downloads", 0]},
                "created_at": {"$ifNull": ["$created_at", "$central.created_at"]},
                "updated_at": {"$ifNull": ["$updated_at", "$central.updated_at"]},
                "overrides": "$overrides",
                "merged": {"$mergeObjects": ["$central", "$overrides"]},
            }
        },
        {
            "$project": {
                "_id": 0,
                "id": 1,
                "sourceId": 1,
                "categoryId": 1,
                "subCategoryId": 1,
                "category_name": 1,
                "categoryName": "$category_name",
                "subcategory_name": 1,
                "subCategoryName": "$subcategory_name",
                "is_enabled": 1,
                "is_premium": 1,
                "sequence": 1,
                "views": 1,
                "downloads": 1,
                "created_at": 1,
                "updated_at": 1,
                "overrides": 1,
                "name": "$merged.name",
                "description": "$merged.description",
                "thumbnail_url": "$merged.thumbnail_url",
                "thumbnailUrl": "$merged.thumbnail_url",
                "moreFields": "$merged.more_fields",
                "more_fields": "$merged.more_fields",
            }
        },
    ]

    cursor = db[INSTANCE_ASSETS].aggregate(pipeline)
    docs = await cursor.to_list(1)
    return docs[0] if docs else None


async def get_instance_catalog(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
) -> dict[str, Any]:
    """Build the complete, resolved, enabled catalog hierarchy ready for client apps."""
    categories = await get_resolved_categories(db, app_instance_id, only_enabled=True)
    subcategories = await get_resolved_subcategories(db, app_instance_id, only_enabled=True)
    assets = await get_resolved_assets(db, app_instance_id, only_enabled=True)

    # Group assets by subcategory
    assets_by_sub: dict[str, list[dict[str, Any]]] = {}
    for a in assets:
        sub_id = a.get("subCategoryId", "")
        assets_by_sub.setdefault(sub_id, []).append(a)

    # Group subcategories by category
    subs_by_cat: dict[str, list[dict[str, Any]]] = {}
    for s in subcategories:
        s["assets"] = assets_by_sub.get(s["id"], [])
        cat_id = s.get("categoryId", "")
        subs_by_cat.setdefault(cat_id, []).append(s)

    for c in categories:
        c["subcategories"] = subs_by_cat.get(c["id"], [])

    return {
        "app_instance_id": app_instance_id,
        "categories": categories,
    }
