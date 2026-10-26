"""Reference controller managing app instance references to central data.

STRICT LAYER RULE:
This module operates exclusively on instance_* collections.
It NEVER imports central controllers or CentralRepository.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from controller.catalog_controller import dead_asset_row_ids
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
from database.repository import InstanceRepository, instance_collection
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError
from utils.ids import to_object_id
from utils.sequencing import compute_next_sequence


_ASSET_DEFAULTS = {
    "is_premium": False,
    "is_rewarded": False,
    "rewarded_credits": 5,
    "views": 0,
    "downloads": 0,
}

def _restore_op(now: Any, **extra: Any) -> dict[str, Any]:
    return {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now, **extra}}


async def _ensure_link(
    db: AsyncIOMotorDatabase, coll: str, key: dict[str, Any], now: Any
) -> tuple[Any, str]:
    """Find-or-create the instance reference identified by `key` (scope fields + source_id).

    Returns (instance _id, status) with status "inserted", "restored" (was soft-deleted) or "present".
    New docs get the next sequence within their scope (key minus source_id).
    """
    existing = await instance_collection(db, coll).find_one(key)
    if existing:
        if existing.get("deleted_at") is None:
            return existing["_id"], "present"
        await instance_collection(db, coll).update_one({"_id": existing["_id"]}, _restore_op(now))
        return existing["_id"], "restored"

    scope = {k: v for k, v in key.items() if k != "source_id"}
    max_seq_doc = await instance_collection(db, coll).find_one({**scope, "deleted_at": None}, sort=[("sequence", -1)])
    doc = {
        **key,
        "is_enabled": True,
        "sequence": compute_next_sequence(max_seq_doc.get("sequence") if max_seq_doc else None),
        **(_ASSET_DEFAULTS if coll == INSTANCE_ASSETS else {}),
        "overrides": {},
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    try:
        return await InstanceRepository(db, coll).insert_one(doc), "inserted"
    except DuplicateKeyError:
        # Lost a race with a concurrent import: revive the winner's doc
        dup = await instance_collection(db, coll).find_one(key)
        await instance_collection(db, coll).update_one({"_id": dup["_id"]}, _restore_op(now))
        return dup["_id"], "present"


def _tally(counts: dict[str, int], kind: str, status: str, count_present: bool = True) -> None:
    if status != "present":
        counts[kind] += 1
    elif count_present:
        counts["already_present"] += 1


async def _restore_target(
    db: AsyncIOMotorDatabase,
    coll: str,
    inst_oid: Any,
    raw_id: str | None,
    counts: dict[str, int],
    kind: str,
    now: Any,
    **extra_set: Any,
) -> Any:
    """Resolve a target folder (by instance _id or source_id), reviving it if soft-deleted. None if not found."""
    if not raw_id:
        return None
    oid = to_object_id(raw_id)
    target = await instance_collection(db, coll).find_one({"app_instance_id": inst_oid, "$or": [{"_id": oid}, {"source_id": oid}]})
    if not target:
        return None
    if target.get("deleted_at") is not None:
        await instance_collection(db, coll).update_one({"_id": target["_id"]}, _restore_op(now, **extra_set))
        counts[kind] += 1
    return target["_id"]


async def _link_asset(
    db: AsyncIOMotorDatabase, inst_oid: Any, a_oid: Any, cat_id: Any, sub_id: Any, counts: dict[str, int], now: Any
) -> None:
    key = {"app_instance_id": inst_oid, "category_id": cat_id, "sub_category_id": sub_id, "source_id": a_oid}
    _, status = await _ensure_link(db, INSTANCE_ASSETS, key, now)
    _tally(counts, "added_assets", status)


async def _auto_super_category(db: AsyncIOMotorDatabase, inst_oid: Any, c_oid: Any, counts: dict[str, int], now: Any) -> Any:
    """Instance super category for a central category's super category (auto-added), or None if it has none."""
    central = await db[CATEGORIES].find_one({"_id": c_oid}, {"super_category_id": 1})
    sc_oid = central.get("super_category_id") if central else None
    if not sc_oid or not await db[SUPER_CATEGORIES].find_one({"_id": sc_oid, "deleted_at": None}, {"_id": 1}):
        return None
    sup_id, status = await _ensure_link(
        db, INSTANCE_SUPER_CATEGORIES, {"app_instance_id": inst_oid, "source_id": sc_oid}, now
    )
    _tally(counts, "added_super_categories", status, count_present=False)
    return sup_id


async def _ensure_category(
    db: AsyncIOMotorDatabase,
    inst_oid: Any,
    c_oid: Any,
    counts: dict[str, int],
    now: Any,
    super_link: Any = None,
    count_present: bool = True,
) -> Any:
    """Find-or-create the instance category for a central category (one per instance).

    A newly inserted category joins its central super category (auto-added); `super_link`
    (an instance super category _id) explicitly places it there instead, moving it if needed.
    """
    cat_id, status = await _ensure_link(
        db, INSTANCE_CATEGORIES, {"app_instance_id": inst_oid, "source_id": c_oid}, now
    )
    _tally(counts, "added_categories", status, count_present)
    if not super_link and status == "inserted":
        super_link = await _auto_super_category(db, inst_oid, c_oid, counts, now)
    if super_link:
        await instance_collection(db, INSTANCE_CATEGORIES).update_one(
            {"_id": cat_id}, {"$set": {"super_category_id": super_link}}
        )
    return cat_id


async def _import_category(
    db: AsyncIOMotorDatabase,
    inst_oid: Any,
    c_oid: Any,
    target_category_id: str | None,
    counts: dict[str, int],
    now: Any,
    super_link: Any = None,
) -> Any:
    """Reference a central category with all its subcategories and assets (into the target folder if given)."""
    if target_category_id:
        cat_inst_id = await _restore_target(
            db, INSTANCE_CATEGORIES, inst_oid, target_category_id, counts, "added_categories", now
        )
        if not cat_inst_id:
            fallback = await db[INSTANCE_CATEGORIES].find_one({"app_instance_id": inst_oid, "deleted_at": None})
            cat_inst_id = fallback["_id"] if fallback else None
    else:
        cat_inst_id = await _ensure_category(db, inst_oid, c_oid, counts, now, super_link=super_link)

    if not cat_inst_id:
        return None

    sub_id_map: dict[Any, Any] = {}
    central_subs = await db[SUBCATEGORIES].find({"category_id": c_oid, "deleted_at": None}).to_list(length=2000)
    for sub in central_subs:
        key = {"app_instance_id": inst_oid, "category_id": cat_inst_id, "source_id": sub["_id"]}
        sub_id_map[sub["_id"]], status = await _ensure_link(db, INSTANCE_SUBCATEGORIES, key, now)
        _tally(counts, "added_subcategories", status)

    central_assets = await db[ASSETS].find({"category_id": c_oid, "deleted_at": None}).to_list(length=10000)
    for a in central_assets:
        sub_link_id = sub_id_map.get(a["sub_category_id"], a["sub_category_id"])
        await _link_asset(db, inst_oid, a["_id"], cat_inst_id, sub_link_id, counts, now)
    return cat_inst_id


async def link_super_category(db: AsyncIOMotorDatabase, app_instance_id: str, super_category_id: str) -> Any:
    """Reference a central super category in an app instance (without importing its categories).

    Returns the instance super category _id, or None if the central super category doesn't exist.
    """
    sc_oid = to_object_id(super_category_id)
    if not await db[SUPER_CATEGORIES].find_one({"_id": sc_oid, "deleted_at": None}, {"_id": 1}):
        return None
    sup_id, _ = await _ensure_link(
        db, INSTANCE_SUPER_CATEGORIES, {"app_instance_id": to_object_id(app_instance_id), "source_id": sc_oid}, utc_now()
    )
    return sup_id


async def _import_super_category(
    db: AsyncIOMotorDatabase, inst_oid: Any, sc_oid: Any, counts: dict[str, int], now: Any
) -> None:
    """Reference a central super category and, under it, every category it groups (with their contents)."""
    if not await db[SUPER_CATEGORIES].find_one({"_id": sc_oid, "deleted_at": None}, {"_id": 1}):
        return
    sup_id, status = await _ensure_link(
        db, INSTANCE_SUPER_CATEGORIES, {"app_instance_id": inst_oid, "source_id": sc_oid}, now
    )
    _tally(counts, "added_super_categories", status)
    cats = await db[CATEGORIES].find({"super_category_id": sc_oid, "deleted_at": None}, {"_id": 1}).sort(
        "sequence", 1
    ).to_list(length=None)
    for cat in cats:
        await _import_category(db, inst_oid, cat["_id"], None, counts, now, super_link=sup_id)


async def _import_subcategory(
    db: AsyncIOMotorDatabase, inst_oid: Any, s_oid: Any, target_category_id: str | None, counts: dict[str, int], now: Any
) -> None:
    """Reference a central subcategory and its assets, under the target folder or its (auto-added) parent."""
    central_sub = await db[SUBCATEGORIES].find_one({"_id": s_oid, "deleted_at": None})
    if not central_sub:
        return

    cat_link_id = await _restore_target(
        db, INSTANCE_CATEGORIES, inst_oid, target_category_id, counts, "added_categories", now
    )
    if not cat_link_id:
        cat_link_id = await _ensure_category(db, inst_oid, central_sub["category_id"], counts, now, count_present=False)

    # Keyed by parent category, so the same subcategory may live in several folders
    sub_inst_id, status = await _ensure_link(
        db, INSTANCE_SUBCATEGORIES, {"app_instance_id": inst_oid, "category_id": cat_link_id, "source_id": s_oid}, now
    )
    _tally(counts, "added_subcategories", status)

    central_assets = await db[ASSETS].find({"sub_category_id": s_oid, "deleted_at": None}).to_list(length=5000)
    for a in central_assets:
        await _link_asset(db, inst_oid, a["_id"], cat_link_id, sub_inst_id, counts, now)


async def _import_asset(
    db: AsyncIOMotorDatabase,
    inst_oid: Any,
    a_oid: Any,
    target_category_id: str | None,
    target_sub_category_id: str | None,
    counts: dict[str, int],
    now: Any,
) -> None:
    """Reference one central asset, under the target folders or its (auto-added) parent category/subcategory."""
    central_asset = await db[ASSETS].find_one({"_id": a_oid, "deleted_at": None})
    if not central_asset:
        return

    cat_link_id = await _restore_target(
        db, INSTANCE_CATEGORIES, inst_oid, target_category_id, counts, "added_categories", now
    )
    if not cat_link_id:
        cat_link_id = await _ensure_category(db, inst_oid, central_asset["category_id"], counts, now, count_present=False)

    sub_link_id = await _restore_target(
        db, INSTANCE_SUBCATEGORIES, inst_oid, target_sub_category_id, counts, "added_subcategories", now,
        category_id=cat_link_id,
    )
    if not sub_link_id:
        key = {"app_instance_id": inst_oid, "category_id": cat_link_id, "source_id": central_asset["sub_category_id"]}
        sub_link_id, status = await _ensure_link(db, INSTANCE_SUBCATEGORIES, key, now)
        _tally(counts, "added_subcategories", status, count_present=False)

    await _link_asset(db, inst_oid, a_oid, cat_link_id, sub_link_id, counts, now)


async def add_references(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_ids: list[str] | None = None,
    sub_category_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
    target_category_id: str | None = None,
    target_sub_category_id: str | None = None,
    super_category_ids: list[str] | None = None,
    target_super_category_id: str | None = None,
) -> dict[str, Any]:
    """Add references from the central library to this app instance.

    Auto-adds missing parents (super category, category, subcategory) to maintain referential integrity.
    A super category brings all its categories; a category brings all its subcategories and assets;
    a subcategory brings its assets. `target_super_category_id` places imported categories in that
    instance super category.
    """
    inst_oid = to_object_id(app_instance_id)
    now = utc_now()
    counts = {
        "added_super_categories": 0,
        "added_categories": 0,
        "added_subcategories": 0,
        "added_assets": 0,
        "already_present": 0,
    }

    for scid in super_category_ids or []:
        await _import_super_category(db, inst_oid, to_object_id(scid), counts, now)
    target_super = (
        await _restore_target(
            db, INSTANCE_SUPER_CATEGORIES, inst_oid, target_super_category_id, counts, "added_super_categories", now
        )
        if category_ids and not target_category_id
        else None
    )
    for cid in category_ids or []:
        await _import_category(db, inst_oid, to_object_id(cid), target_category_id, counts, now, super_link=target_super)
    for sid in sub_category_ids or []:
        await _import_subcategory(db, inst_oid, to_object_id(sid), target_category_id, counts, now)
    for aid in asset_ids or []:
        await _import_asset(db, inst_oid, to_object_id(aid), target_category_id, target_sub_category_id, counts, now)

    return {"success": True, **counts}


async def copy_references_from_instance(
    db: AsyncIOMotorDatabase,
    target_instance_id: str,
    source_instance_id: str,
    include_overrides: bool = True,
) -> dict[str, Any]:
    """Copy referenced selections from one app instance to another.

    Counters (views, downloads) reset to 0 for the target app.
    """
    target_oid = to_object_id(target_instance_id)
    source_oid = to_object_id(source_instance_id)

    if target_oid == source_oid:
        raise ConflictError("Cannot copy references to the same app instance")

    now = utc_now()

    # 1. Copy Categories
    source_cats = (
        await db[INSTANCE_CATEGORIES]
        .find({"app_instance_id": source_oid, "deleted_at": None})
        .to_list(length=1000)
    )

    cats_copied = 0
    for sc in source_cats:
        exists = await db[INSTANCE_CATEGORIES].find_one(
            {
                "app_instance_id": target_oid,
                "source_id": sc["source_id"],
            }
        )
        if exists:
            if exists.get("deleted_at") is not None:
                await db[INSTANCE_CATEGORIES].update_one(
                    {"_id": exists["_id"]},
                    {"$set": {"deleted_at": None, "is_enabled": sc.get("is_enabled", True), "updated_at": now}},
                )
                cats_copied += 1
        else:
            try:
                await db[INSTANCE_CATEGORIES].insert_one(
                    {
                        "app_instance_id": target_oid,
                        "source_id": sc["source_id"],
                        "is_enabled": sc.get("is_enabled", True),
                        "sequence": sc.get("sequence", 1),
                        "overrides": sc.get("overrides", {}) if include_overrides else {},
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                    }
                )
                cats_copied += 1
            except DuplicateKeyError:
                pass

    # 2. Copy Subcategories
    source_subs = (
        await db[INSTANCE_SUBCATEGORIES]
        .find({"app_instance_id": source_oid, "deleted_at": None})
        .to_list(length=5000)
    )

    subs_copied = 0
    for ss in source_subs:
        exists = await db[INSTANCE_SUBCATEGORIES].find_one(
            {
                "app_instance_id": target_oid,
                "category_id": ss["category_id"],
                "source_id": ss["source_id"],
            }
        )
        if exists:
            if exists.get("deleted_at") is not None:
                await db[INSTANCE_SUBCATEGORIES].update_one(
                    {"_id": exists["_id"]},
                    {
                        "$set": {
                            "deleted_at": None,
                            "is_enabled": ss.get("is_enabled", True),
                            "category_id": ss["category_id"],
                            "updated_at": now,
                        }
                    },
                )
                subs_copied += 1
        else:
            try:
                await db[INSTANCE_SUBCATEGORIES].insert_one(
                    {
                        "app_instance_id": target_oid,
                        "source_id": ss["source_id"],
                        "category_id": ss["category_id"],
                        "is_enabled": ss.get("is_enabled", True),
                        "sequence": ss.get("sequence", 1),
                        "overrides": ss.get("overrides", {}) if include_overrides else {},
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                    }
                )
                subs_copied += 1
            except DuplicateKeyError:
                pass

    # 3. Copy Assets
    source_assets = (
        await db[INSTANCE_ASSETS]
        .find({"app_instance_id": source_oid, "deleted_at": None})
        .to_list(length=20000)
    )

    assets_copied = 0
    for sa in source_assets:
        exists = await db[INSTANCE_ASSETS].find_one(
            {
                "app_instance_id": target_oid,
                "category_id": sa["category_id"],
                "sub_category_id": sa["sub_category_id"],
                "source_id": sa["source_id"],
            }
        )
        if exists:
            if exists.get("deleted_at") is not None:
                await db[INSTANCE_ASSETS].update_one(
                    {"_id": exists["_id"]},
                    {
                        "$set": {
                            "deleted_at": None,
                            "is_enabled": sa.get("is_enabled", True),
                            "category_id": sa["category_id"],
                            "sub_category_id": sa["sub_category_id"],
                            "updated_at": now,
                        }
                    },
                )
                assets_copied += 1
        else:
            try:
                await db[INSTANCE_ASSETS].insert_one(
                    {
                        "app_instance_id": target_oid,
                        "source_id": sa["source_id"],
                        "category_id": sa["category_id"],
                        "sub_category_id": sa["sub_category_id"],
                        "is_enabled": sa.get("is_enabled", True),
                        "is_premium": sa.get("is_premium", False),
                        "is_rewarded": sa.get("is_rewarded", False),
                        "rewarded_credits": sa.get("rewarded_credits", 5),
                        "sequence": sa.get("sequence", 1),
                        "views": 0,
                        "downloads": 0,
                        "overrides": sa.get("overrides", {}) if include_overrides else {},
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                    }
                )
                assets_copied += 1
            except DuplicateKeyError:
                pass

    return {
        "success": True,
        "copied_categories": cats_copied,
        "copied_subcategories": subs_copied,
        "copied_assets": assets_copied,
    }


async def remove_reference(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    item_type: str,
    item_id: str,
) -> dict[str, Any]:
    """Remove a reference row from this app instance.

    Cascades removal ONLY within this app instance to children, never touching central data.
    """
    inst_oid = to_object_id(app_instance_id)
    ref_oid = to_object_id(item_id)
    now = utc_now()

    if item_type in ("super_category", "supercategory"):
        sup = await instance_collection(db, INSTANCE_SUPER_CATEGORIES).find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": ref_oid}, {"source_id": ref_oid}]}
        )
        if not sup:
            raise NotFoundError("Instance super category reference not found")
        totals = {"removed_super_categories": 1, "removed_categories": 0, "removed_subcategories": 0, "removed_assets": 0}
        child_cats = await db[INSTANCE_CATEGORIES].find(
            {"app_instance_id": inst_oid, "super_category_id": sup["_id"]}, {"_id": 1}
        ).to_list(length=None)
        for cat in child_cats:
            res = await remove_reference(db, app_instance_id, "category", str(cat["_id"]))
            for key in ("removed_categories", "removed_subcategories", "removed_assets"):
                totals[key] += res.get(key, 0)
        await instance_collection(db, INSTANCE_SUPER_CATEGORIES).delete_one({"_id": sup["_id"]})
        return {"success": True, **totals}

    if item_type == "asset":
        res = await db[INSTANCE_ASSETS].delete_one(
            {
                "app_instance_id": inst_oid,
                "$or": [{"_id": ref_oid}, {"source_id": ref_oid}],
            }
        )
        if res.deleted_count == 0:
            raise NotFoundError("Instance asset reference not found")
        return {"success": True, "removed_assets": 1}

    elif item_type == "subcategory":
        sub_ref = await db[INSTANCE_SUBCATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "$or": [{"_id": ref_oid}, {"source_id": ref_oid}],
            }
        )
        if not sub_ref:
            raise NotFoundError("Instance subcategory reference not found")

        # Assets keyed by the central id only belong here when in this folder's category:
        # the same central subcategory may also live under other categories
        owned = [{"sub_category_id": sub_ref["_id"]}]
        if sub_ref.get("source_id"):
            owned.append({"sub_category_id": sub_ref["source_id"], "category_id": sub_ref["category_id"]})

        # Remove subcategory reference and all child asset references in this app permanently
        await db[INSTANCE_SUBCATEGORIES].delete_one({"_id": sub_ref["_id"]})
        asset_res = await db[INSTANCE_ASSETS].delete_many({"app_instance_id": inst_oid, "$or": owned})
        return {
            "success": True,
            "removed_subcategories": 1,
            "removed_assets": asset_res.deleted_count,
        }

    elif item_type == "category":
        cat_ref = await db[INSTANCE_CATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "$or": [{"_id": ref_oid}, {"source_id": ref_oid}],
            }
        )
        if not cat_ref:
            raise NotFoundError("Instance category reference not found")

        source_cat_oid = cat_ref.get("source_id")
        cat_ids = [cat_ref["_id"]]
        if source_cat_oid:
            cat_ids.append(source_cat_oid)

        # Remove category, child subcategories, and child assets in this app permanently
        await db[INSTANCE_CATEGORIES].delete_one({"_id": cat_ref["_id"]})
        sub_res = await db[INSTANCE_SUBCATEGORIES].delete_many(
            {"app_instance_id": inst_oid, "category_id": {"$in": cat_ids}}
        )
        asset_res = await db[INSTANCE_ASSETS].delete_many(
            {"app_instance_id": inst_oid, "category_id": {"$in": cat_ids}}
        )
        return {
            "success": True,
            "removed_categories": 1,
            "removed_subcategories": sub_res.deleted_count,
            "removed_assets": asset_res.deleted_count,
        }

    raise NotFoundError(f"Unsupported reference item type '{item_type}'")


async def get_unresolved_references(
    db: AsyncIOMotorDatabase, app_instance_id: str
) -> dict[str, Any]:
    """Find references in this app whose central source document has been soft-deleted or removed.
    Native folders created directly in the app instance (source_id is None) are excluded."""
    inst_oid = to_object_id(app_instance_id)

    # Categories: only inspect references with a central source_id
    unresolved_cats = (
        await db[INSTANCE_CATEGORIES]
        .aggregate(
            [
                {
                    "$match": {
                        "app_instance_id": inst_oid,
                        "source_id": {"$ne": None},
                        "deleted_at": None,
                    }
                },
                {
                    "$lookup": {
                        "from": CATEGORIES,
                        "localField": "source_id",
                        "foreignField": "_id",
                        "as": "central",
                    }
                },
                {
                    "$match": {
                        "$or": [{"central": {"$size": 0}}, {"central.deleted_at": {"$ne": None}}]
                    }
                },
                {
                    "$project": {
                        "id": {"$toString": "$_id"},
                        "reference_id": {"$toString": "$_id"},
                        "source_id": {"$toString": "$source_id"},
                        "target_id": {"$toString": "$source_id"},
                        "targetId": {"$toString": "$source_id"},
                        "name": {"$ifNull": ["$overrides.name", "$name"]},
                    }
                },
            ]
        )
        .to_list(1000)
    )

    # Subcategories: only inspect references with a central source_id
    unresolved_subs = (
        await db[INSTANCE_SUBCATEGORIES]
        .aggregate(
            [
                {
                    "$match": {
                        "app_instance_id": inst_oid,
                        "source_id": {"$ne": None},
                        "deleted_at": None,
                    }
                },
                {
                    "$lookup": {
                        "from": SUBCATEGORIES,
                        "localField": "source_id",
                        "foreignField": "_id",
                        "as": "central",
                    }
                },
                {
                    "$match": {
                        "$or": [{"central": {"$size": 0}}, {"central.deleted_at": {"$ne": None}}]
                    }
                },
                {
                    "$project": {
                        "id": {"$toString": "$_id"},
                        "reference_id": {"$toString": "$_id"},
                        "source_id": {"$toString": "$source_id"},
                        "target_id": {"$toString": "$source_id"},
                        "targetId": {"$toString": "$source_id"},
                        "name": {"$ifNull": ["$overrides.name", "$name"]},
                    }
                },
            ]
        )
        .to_list(1000)
    )

    # Assets: rows whose central asset is soft-deleted. Hard deletes remove instance rows too
    # (base_controller), so this skips the per-row $lookup that grew with the app's size.
    unresolved_assets = (
        await db[INSTANCE_ASSETS]
        .aggregate(
            [
                {"$match": {"_id": {"$in": await dead_asset_row_ids(db, inst_oid)}}},
                {
                    "$project": {
                        "id": {"$toString": "$_id"},
                        "reference_id": {"$toString": "$_id"},
                        "source_id": {"$toString": "$source_id"},
                        "target_id": {"$toString": "$source_id"},
                        "targetId": {"$toString": "$source_id"},
                        "name": {"$ifNull": ["$overrides.name", "$name"]},
                    }
                },
            ]
        )
        .to_list(1000)
    )

    return {
        "unresolved_categories": unresolved_cats,
        "unresolved_subcategories": unresolved_subs,
        "unresolved_assets": unresolved_assets,
        "categories": unresolved_cats,
        "subcategories": unresolved_subs,
        "assets": unresolved_assets,
        "total_unresolved": len(unresolved_cats) + len(unresolved_subs) + len(unresolved_assets),
    }


async def add_instance_references(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Helper to add bulk polymorphic references to an instance."""
    cat_ids = [i["target_id"] for i in items if i.get("target_type") == "category"]
    sub_ids = [i["target_id"] for i in items if i.get("target_type") == "subcategory"]
    asset_ids = [i["target_id"] for i in items if i.get("target_type") == "asset"]
    return await add_references(
        db,
        app_instance_id=app_instance_id,
        category_ids=cat_ids,
        sub_category_ids=sub_ids,
        asset_ids=asset_ids,
    )
