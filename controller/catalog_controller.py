"""Client-facing catalog resolution using single-stage MongoDB aggregation pipelines.

STRICT LAYER RULE:
Reads instance reference rows and joins central documents via $lookup.
Implements the canonical resolution merge:
  effective = { **central_document, **row.overrides }
              + is_enabled, sequence, is_premium, views, downloads, sourceId
Filters out unresolvable items whose central source is deleted.
"""

from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import (
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    INSTANCE_SUPER_CATEGORIES,
    SUBCATEGORIES,
    SUPER_CATEGORIES,
)
from utils.ids import to_object_id


_NO_CAT = object()


def _one_parent(id_var: str, cat_var: str | None = None) -> list[dict[str, Any]]:
    """Parent-lookup tail keeping a single match: the exact _id first, else one in the same category.

    A central subcategory can live in several instance categories, so the source_id fallbacks
    match many parents and the following $unwind would show the row once per parent.
    """
    rank: dict[str, Any] = {"_exact": {"$eq": ["$_id", f"$${id_var}"]}}
    if cat_var:
        rank["_same_cat"] = {"$eq": ["$category_id", f"$${cat_var}"]}
    return [{"$addFields": rank}, {"$sort": {k: -1 for k in rank}}, {"$limit": 1}]


def _top_folder_pipeline(match_filter: dict[str, Any], central_coll: str, extra: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve instance folder rows (super categories / categories) against their central docs + overrides."""
    return [
        {"$match": match_filter},
        {
            "$lookup": {
                "from": central_coll,
                "localField": "source_id",
                "foreignField": "_id",
                "as": "central",
            }
        },
        # Preserve folders created directly in the app instance (where source_id is None)
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
                **extra,
                "is_enabled": "$is_enabled",
                # Instance value once set, else the central folder's flag
                "is_premium": {"$ifNull": ["$is_premium", {"$ifNull": ["$central.is_premium", False]}]},
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
                **{k: 1 for k in extra},
                "is_enabled": 1,
                "is_premium": 1,
                "sequence": 1,
                "overrides": 1,
                "name": "$merged.name",
                "thumbnail_url": "$merged.thumbnail_url",
                "image_url": "$merged.image_url",
            }
        },
        {"$sort": {"sequence": 1, "name": 1}},
    ]


async def get_resolved_super_categories(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    only_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve resolved super categories (the optional level above categories) for an app instance."""
    match_filter: dict[str, Any] = {"app_instance_id": to_object_id(app_instance_id), "deleted_at": None}
    if only_enabled:
        match_filter["is_enabled"] = True
    cursor = db[INSTANCE_SUPER_CATEGORIES].aggregate(_top_folder_pipeline(match_filter, SUPER_CATEGORIES, {}))
    return await cursor.to_list(length=None)


async def get_resolved_categories(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    only_enabled: bool = False,
    super_category_id: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve resolved categories for an app instance with overrides merged.

    `superCategoryId` is the instance super category _id (or None when ungrouped).
    """
    inst_oid = to_object_id(app_instance_id)

    match_filter: dict[str, Any] = {"app_instance_id": inst_oid, "deleted_at": None}
    if only_enabled:
        match_filter["is_enabled"] = True
    if super_category_id:
        sc_oid = to_object_id(super_category_id)
        sup = await db[INSTANCE_SUPER_CATEGORIES].find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": sc_oid}, {"source_id": sc_oid}]}, {"_id": 1}
        )
        match_filter["super_category_id"] = sup["_id"] if sup else sc_oid

    pipeline = _top_folder_pipeline(
        match_filter,
        CATEGORIES,
        {"superCategoryId": {"$cond": [{"$ifNull": ["$super_category_id", False]}, {"$toString": "$super_category_id"}, None]}},
    )
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
                "categoryId": {"$toString": "$category_id"},
                "_cat": "$category_id",
                "_central_cat": "$central.category_id",
                "is_enabled": "$is_enabled",
                # Instance value once set, else the central folder's flag
                "is_premium": {"$ifNull": ["$is_premium", {"$ifNull": ["$central.is_premium", False]}]},
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
                "categoryId": 1,
                "_cat": 1,
                "_central_cat": 1,
                "is_enabled": 1,
                "is_premium": 1,
                "sequence": 1,
                "overrides": 1,
                "name": "$merged.name",
                "thumbnail_url": "$merged.thumbnail_url",
                "image_url": "$merged.image_url",
            }
        },
        {"$sort": {"sequence": 1, "name": 1}},
    ]

    docs = await db[INSTANCE_SUBCATEGORIES].aggregate(pipeline).to_list(length=None)
    # Parent instance category in Python: a per-row $lookup here was unindexable (folders x categories)
    cats = _folder_index(
        await db[INSTANCE_CATEGORIES].find({"app_instance_id": inst_oid, "deleted_at": None}, {"source_id": 1}).to_list(length=None)
    )
    for d in docs:
        cat = _pick_parent(cats, d.pop("_cat", None), d.pop("_central_cat", None))
        if cat:
            d["categoryId"] = str(cat["_id"])
    return docs


def _pick_parent(
    index: dict[Any, list[tuple[int, dict[str, Any]]]], raw_id: Any, central_id: Any, same_cat: Any = _NO_CAT
) -> dict[str, Any] | None:
    """Instance folder for an asset: matched by _id or source_id (raw id, else the central asset's).

    Same ranking as _one_parent: the exact _id first, then one in the asset's category, then stored order.
    """
    found: dict[Any, tuple[int, dict[str, Any]]] = {}
    for key in (("id", raw_id), ("src", raw_id), ("src", central_id)):
        if key[1] is not None:
            for pos, row in index.get(key, []):
                found[row["_id"]] = (pos, row)
    if not found:
        return None
    return min(
        found.values(),
        key=lambda pr: (pr[1]["_id"] != raw_id, same_cat is not _NO_CAT and pr[1].get("category_id") != same_cat, pr[0]),
    )[1]


def _folder_index(rows: list[dict[str, Any]]) -> dict[Any, list[tuple[int, dict[str, Any]]]]:
    index: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    for pos, row in enumerate(rows):
        index.setdefault(("id", row["_id"]), []).append((pos, row))
        if row.get("source_id") is not None:
            index.setdefault(("src", row["source_id"]), []).append((pos, row))
    return index


async def _attach_instance_parents(db: AsyncIOMotorDatabase, inst_oid: Any, docs: list[dict[str, Any]]) -> None:
    """Point each resolved asset at its instance category/subcategory (id + name), in one query per collection.

    Replaces two per-asset $lookup sub-pipelines that MongoDB could not index (they were ~70% of the query time).
    """
    live = {"app_instance_id": inst_oid, "deleted_at": None}
    fields = {"source_id": 1, "category_id": 1, "name": 1}
    cats = _folder_index(await db[INSTANCE_CATEGORIES].find(live, fields).to_list(length=None))
    subs = _folder_index(await db[INSTANCE_SUBCATEGORIES].find(live, fields).to_list(length=None))
    for d in docs:
        raw_cat, raw_sub = d.pop("_cat", None), d.pop("_sub", None)
        central_cat, central_sub = d.pop("_central_cat", None), d.pop("_central_sub", None)
        cat = _pick_parent(cats, raw_cat, central_cat)
        if cat:
            d["categoryId"] = str(cat["_id"])
            if cat.get("name") is not None:
                d["category_name"] = cat["name"]
        sub = _pick_parent(subs, raw_sub, central_sub, same_cat=raw_cat)
        if sub:
            d["subCategoryId"] = str(sub["_id"])
            if sub.get("name") is not None:
                d["subcategory_name"] = sub["name"]


def _asset_sort_stage(sort: str | None, order: str | None) -> dict[str, Any]:
    """$sort for resolved assets; keys exist on both the full and the get_asset_index projections."""
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
    return sort_stage


async def _asset_match_filter(
    db: AsyncIOMotorDatabase,
    inst_oid: Any,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    only_enabled: bool = False,
    tag: str | None = None,
) -> dict[str, Any]:
    """$match for an instance's live asset rows, scoped by folder (instance or central id), enabled flag or tag."""
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
        enabled_condition = [
            {"overrides.is_enabled": True},
            {"overrides.is_enabled": {"$exists": False}, "is_enabled": True},
        ]
        match_filter["$or"] = enabled_condition

    if tag and tag.strip():
        tag_condition = {
            "$or": [
                {"tags": tag.strip()},
                {"overrides.tags": tag.strip()}
            ]
        }
        if "$or" in match_filter:
            prev_or = match_filter.pop("$or")
            match_filter["$and"] = [{"$or": prev_or}, tag_condition]
        else:
            match_filter["$or"] = tag_condition["$or"]
    return match_filter


async def dead_asset_row_ids(db: AsyncIOMotorDatabase, inst_oid: Any) -> list[Any]:
    """Live instance asset rows whose central asset is soft-deleted (unresolvable).

    Looked up from the deleted side, so the cost follows deletions instead of the app's size.
    """
    dead = await db[ASSETS].distinct("_id", {"deleted_at": {"$ne": None}})
    if not dead:
        return []
    return await db[INSTANCE_ASSETS].distinct(
        "_id", {"app_instance_id": inst_oid, "deleted_at": None, "source_id": {"$in": dead}}
    )


async def get_resolved_assets(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    only_enabled: bool = False,
    sort: str | None = None,
    order: str | None = None,
    tag: str | None = None,
    asset_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve resolved assets for an app instance (only `asset_ids` when given, e.g. one page)."""
    inst_oid = to_object_id(app_instance_id)

    match_filter = await _asset_match_filter(db, inst_oid, category_id, sub_category_id, only_enabled, tag)
    if asset_ids is not None:
        match_filter["_id"] = {"$in": [to_object_id(i) for i in asset_ids]}

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
        # Lookup category and subcategory via central asset as fallback
        {
            "$lookup": {
                "from": CATEGORIES,
                "localField": "central.category_id",
                "foreignField": "_id",
                "as": "cat_via_central",
            }
        },
        {
            "$lookup": {
                "from": SUBCATEGORIES,
                "localField": "central.sub_category_id",
                "foreignField": "_id",
                "as": "sub_via_central",
            }
        },
        # Preserve assets created directly in instance without a central link
        {"$unwind": {"path": "$central", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$cat_via_central", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$sub_via_central", "preserveNullAndEmptyArrays": True}},
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
                "categoryId": {"$toString": {"$ifNull": ["$category_id", "$central.category_id"]}},
                "subCategoryId": {"$toString": {"$ifNull": ["$sub_category_id", "$central.sub_category_id"]}},
                "category_name": {"$ifNull": ["$cat_via_central.name", "—"]},
                "subcategory_name": {"$ifNull": ["$sub_via_central.name", "—"]},
                "_cat": "$category_id",
                "_sub": "$sub_category_id",
                "_central_cat": "$central.category_id",
                "_central_sub": "$central.sub_category_id",
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
                "is_rewarded": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_rewarded"}, "missing"]},
                        "$overrides.is_rewarded",
                        {"$ifNull": ["$is_rewarded", False]},
                    ]
                },
                "is_priced": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_priced"}, "missing"]},
                        "$overrides.is_priced",
                        {"$ifNull": ["$is_priced", False]},
                    ]
                },
                "rewarded_credits": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.rewarded_credits"}, "missing"]},
                        "$overrides.rewarded_credits",
                        {"$ifNull": ["$rewarded_credits", 5]},
                    ]
                },
                "sequence": "$sequence",
                "views": {"$ifNull": ["$views", 0]},
                "downloads": {"$ifNull": ["$downloads", 0]},
                "created_at": {"$ifNull": ["$created_at", "$central.created_at"]},
                "updated_at": {"$ifNull": ["$updated_at", "$central.updated_at"]},
                "overrides": "$overrides",
                "source_id": {"$ifNull": [{"$toString": "$source_id"}, {"$toString": "$central._id"}]},
                "merged": {"$mergeObjects": ["$central", "$overrides"]},
            }
        },
        {
            "$project": {
                "_id": 0,
                "id": 1,
                "source_id": 1,
                "sourceId": "$source_id",
                "categoryId": 1,
                "subCategoryId": 1,
                "category_name": 1,
                "subcategory_name": 1,
                "_cat": 1,
                "_sub": 1,
                "_central_cat": 1,
                "_central_sub": 1,
                "is_enabled": 1,
                "is_premium": 1,
                "is_rewarded": 1,
                "isRewarded": "$is_rewarded",
                "is_priced": 1,
                "isPriced": "$is_priced",
                "rewarded_credits": 1,
                "rewardedCredits": "$rewarded_credits",
                "sequence": 1,
                "views": 1,
                "downloads": 1,
                "created_at": 1,
                "updated_at": 1,
                "overrides": 1,
                "name": "$merged.name",
                "description": "$merged.description",
                "thumbnail_url": "$merged.thumbnail_url",
                "more_fields": "$merged.more_fields",
                "tags": {"$ifNull": ["$overrides.tags", {"$ifNull": ["$tags", {"$ifNull": ["$central.tags", []]}]}]},
            }
        },
    ]

    sort_stage = _asset_sort_stage(sort, order)
    pipeline.append(sort_stage)

    docs = await db[INSTANCE_ASSETS].aggregate(pipeline).to_list(length=None)
    await _attach_instance_parents(db, inst_oid, docs)
    return docs


def _bson_order(value: Any) -> tuple[int, Any]:
    """Sort key following MongoDB's cross-type order (null < numbers < strings < ObjectId < bool < dates)."""
    if value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (4, value)
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, str):
        return (2, value)
    if isinstance(value, ObjectId):
        return (3, value.binary)
    return (5, value)


async def get_asset_index(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    sort: str | None = None,
    order: str | None = None,
) -> list[dict[str, Any]]:
    """Light pass over an instance's live assets: id + resolved categoryId/subCategoryId, in display order.

    Same membership and order as get_resolved_assets, but from two indexed finds joined in Python instead of a
    per-row $lookup (~4x faster at 5k assets), so callers can count folders / paginate here and fully resolve
    only the page they show.
    """
    inst_oid = to_object_id(app_instance_id)
    rows = await db[INSTANCE_ASSETS].find(
        await _asset_match_filter(db, inst_oid, category_id, sub_category_id),
        {"source_id": 1, "category_id": 1, "sub_category_id": 1, "sequence": 1, "views": 1, "downloads": 1,
         "created_at": 1, "overrides.name": 1},
    ).to_list(length=None)
    source_ids = list({r["source_id"] for r in rows if r.get("source_id") is not None})
    central = {
        c["_id"]: c
        for c in await db[ASSETS].find(
            {"_id": {"$in": source_ids}},
            {"category_id": 1, "sub_category_id": 1, "deleted_at": 1, "name": 1, "created_at": 1},
        ).to_list(length=None)
    }

    def first(*values: Any) -> Any:  # $ifNull
        return next((v for v in values if v is not None), None)

    out: list[dict[str, Any]] = []
    for r in rows:
        cen = central.get(r.get("source_id"))
        if cen is not None and cen.get("deleted_at") is not None:
            continue  # central source deleted: unresolvable, same as get_resolved_assets
        cen = cen or {}
        ov = r.get("overrides") if isinstance(r.get("overrides"), dict) else {}
        cat, sub = first(r.get("category_id"), cen.get("category_id")), first(r.get("sub_category_id"), cen.get("sub_category_id"))
        out.append({
            "id": str(r["_id"]),
            "categoryId": str(cat) if cat is not None else None,
            "subCategoryId": str(sub) if sub is not None else None,
            "_cat": r.get("category_id"),
            "_sub": r.get("sub_category_id"),
            "_central_cat": cen.get("category_id"),
            "_central_sub": cen.get("sub_category_id"),
            "sequence": r.get("sequence"),
            "views": first(r.get("views"), 0),
            "downloads": first(r.get("downloads"), 0),
            "created_at": first(r.get("created_at"), cen.get("created_at")),
            "name": ov["name"] if "name" in ov else cen.get("name"),  # $mergeObjects(central, overrides).name
        })

    # Apply the $sort keys right to left with stable sorts (one direction per key)
    for field, direction in reversed(list(_asset_sort_stage(sort, order)["$sort"].items())):
        out.sort(key=lambda d: _bson_order(d.get(field)), reverse=direction == -1)
    for d in out:
        for field in ("sequence", "views", "downloads", "created_at", "name"):
            del d[field]
    await _attach_instance_parents(db, inst_oid, out)
    return out


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
        # Lookup parent category from INSTANCE_CATEGORIES to ensure assigned instance category ID is returned
        {
            "$lookup": {
                "from": INSTANCE_CATEGORIES,
                "let": {
                    "asset_cat_id": "$category_id",
                    "central_cat_id": "$central.category_id",
                    "inst_id": "$app_instance_id",
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$app_instance_id", "$$inst_id"]},
                                    {"$eq": ["$deleted_at", None]},
                                    {
                                        "$or": [
                                            {"$eq": ["$_id", "$$asset_cat_id"]},
                                            {"$eq": ["$source_id", "$$asset_cat_id"]},
                                            {
                                                "$and": [
                                                    {"$ne": ["$$central_cat_id", None]},
                                                    {"$eq": ["$source_id", "$$central_cat_id"]},
                                                ]
                                            },
                                        ]
                                    },
                                ]
                            }
                        }
                    },
                    *_one_parent("asset_cat_id"),
                ],
                "as": "parent_inst_cat",
            }
        },
        # Lookup parent subcategory from INSTANCE_SUBCATEGORIES to ensure assigned instance subcategory ID is returned
        {
            "$lookup": {
                "from": INSTANCE_SUBCATEGORIES,
                "let": {
                    "asset_sub_id": "$sub_category_id",
                    "asset_cat_id": "$category_id",
                    "central_sub_id": "$central.sub_category_id",
                    "inst_id": "$app_instance_id",
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$app_instance_id", "$$inst_id"]},
                                    {"$eq": ["$deleted_at", None]},
                                    {
                                        "$or": [
                                            {"$eq": ["$_id", "$$asset_sub_id"]},
                                            {"$eq": ["$source_id", "$$asset_sub_id"]},
                                            {
                                                "$and": [
                                                    {"$ne": ["$$central_sub_id", None]},
                                                    {"$eq": ["$source_id", "$$central_sub_id"]},
                                                ]
                                            },
                                        ]
                                    },
                                ]
                            }
                        }
                    },
                    *_one_parent("asset_sub_id", "asset_cat_id"),
                ],
                "as": "parent_inst_sub",
            }
        },
        # Fallback lookups for category/subcategory names
        {
            "$lookup": {
                "from": CATEGORIES,
                "localField": "central.category_id",
                "foreignField": "_id",
                "as": "cat_via_central",
            }
        },
        {
            "$lookup": {
                "from": SUBCATEGORIES,
                "localField": "central.sub_category_id",
                "foreignField": "_id",
                "as": "sub_via_central",
            }
        },
        {"$unwind": {"path": "$parent_inst_cat", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$parent_inst_sub", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$cat_via_central", "preserveNullAndEmptyArrays": True}},
        {"$unwind": {"path": "$sub_via_central", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "categoryId": {
                    "$cond": [
                        {"$ifNull": ["$parent_inst_cat._id", False]},
                        {"$toString": "$parent_inst_cat._id"},
                        {"$toString": {"$ifNull": ["$category_id", "$central.category_id"]}},
                    ]
                },
                "subCategoryId": {
                    "$cond": [
                        {"$ifNull": ["$parent_inst_sub._id", False]},
                        {"$toString": "$parent_inst_sub._id"},
                        {"$toString": {"$ifNull": ["$sub_category_id", "$central.sub_category_id"]}},
                    ]
                },
                "category_name": {
                    "$ifNull": [
                        "$parent_inst_cat.name",
                        {"$ifNull": ["$cat_via_central.name", "—"]}
                    ]
                },
                "subcategory_name": {
                    "$ifNull": [
                        "$parent_inst_sub.name",
                        {"$ifNull": ["$sub_via_central.name", "—"]}
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
                "is_rewarded": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_rewarded"}, "missing"]},
                        "$overrides.is_rewarded",
                        {"$ifNull": ["$is_rewarded", False]},
                    ]
                },
                "is_priced": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.is_priced"}, "missing"]},
                        "$overrides.is_priced",
                        {"$ifNull": ["$is_priced", False]},
                    ]
                },
                "rewarded_credits": {
                    "$cond": [
                        {"$ne": [{"$type": "$overrides.rewarded_credits"}, "missing"]},
                        "$overrides.rewarded_credits",
                        {"$ifNull": ["$rewarded_credits", 5]},
                    ]
                },
                "sequence": "$sequence",
                "views": {"$ifNull": ["$views", 0]},
                "downloads": {"$ifNull": ["$downloads", 0]},
                "created_at": {"$ifNull": ["$created_at", "$central.created_at"]},
                "updated_at": {"$ifNull": ["$updated_at", "$central.updated_at"]},
                "overrides": "$overrides",
                "source_id": {"$ifNull": [{"$toString": "$source_id"}, {"$toString": "$central._id"}]},
                "merged": {"$mergeObjects": ["$central", "$overrides"]},
            }
        },
        {
            "$project": {
                "_id": 0,
                "id": 1,
                "source_id": 1,
                "sourceId": "$source_id",
                "categoryId": 1,
                "subCategoryId": 1,
                "category_name": 1,
                "subcategory_name": 1,
                "is_enabled": 1,
                "is_premium": 1,
                "is_rewarded": 1,
                "isRewarded": "$is_rewarded",
                "is_priced": 1,
                "isPriced": "$is_priced",
                "rewarded_credits": 1,
                "rewardedCredits": "$rewarded_credits",
                "sequence": 1,
                "views": 1,
                "downloads": 1,
                "created_at": 1,
                "updated_at": 1,
                "overrides": 1,
                "name": "$merged.name",
                "description": "$merged.description",
                "thumbnail_url": "$merged.thumbnail_url",
                "more_fields": "$merged.more_fields",
                "tags": {"$ifNull": ["$overrides.tags", {"$ifNull": ["$tags", {"$ifNull": ["$central.tags", []]}]}]},
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
    """Build the complete, resolved, enabled catalog hierarchy ready for client apps.

    `categories` keeps its original nested shape; `super_categories` (additive) lists the optional top level,
    each with the ordered `categoryIds` it groups. Categories carry `superCategoryId`.
    """
    super_categories = await get_resolved_super_categories(db, app_instance_id, only_enabled=True)
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

    cat_ids_by_super: dict[str, list[str]] = {}
    for c in categories:
        c["subcategories"] = subs_by_cat.get(c["id"], [])
        if c.get("superCategoryId"):
            cat_ids_by_super.setdefault(c["superCategoryId"], []).append(c["id"])
    for sc in super_categories:
        sc["categoryIds"] = cat_ids_by_super.get(sc["id"], [])

    return {
        "app_instance_id": app_instance_id,
        "super_categories": super_categories,
        "categories": categories,
    }
