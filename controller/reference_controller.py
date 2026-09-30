"""Reference controller managing app instance references to central data.

STRICT LAYER RULE:
This module operates exclusively on instance_* collections.
It NEVER imports central controllers or CentralRepository.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from database.collections import (
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    SUBCATEGORIES,
)
from database.repository import InstanceRepository
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError
from utils.ids import to_object_id
from utils.sequencing import compute_next_sequence


async def add_references(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    category_ids: list[str] | None = None,
    sub_category_ids: list[str] | None = None,
    asset_ids: list[str] | None = None,
    target_category_id: str | None = None,
    target_sub_category_id: str | None = None,
) -> dict[str, Any]:
    """Add references from the central library to this app instance.

    Auto-adds missing parent categories and subcategories when individual assets or
    subcategories are selected to maintain referential integrity.
    When a category is selected, references the category, all its subcategories, and all their assets.
    When a subcategory is selected, references the subcategory, its parent category, and all its assets.
    """
    inst_oid = to_object_id(app_instance_id)
    now = utc_now()

    cat_repo = InstanceRepository(db, INSTANCE_CATEGORIES)
    sub_repo = InstanceRepository(db, INSTANCE_SUBCATEGORIES)
    asset_repo = InstanceRepository(db, INSTANCE_ASSETS)

    added_cats = 0
    added_subs = 0
    added_assets = 0
    already_present = 0

    # 1. Process explicit categories (copying whole category folder: category + subcategories + assets)
    for cid in category_ids or []:
        c_oid = to_object_id(cid)
        # Check if already present in instance (active or soft-deleted)
        existing = await db[INSTANCE_CATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "source_id": c_oid,
            }
        )
        if existing:
            if existing.get("deleted_at") is not None:
                await db[INSTANCE_CATEGORIES].update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                )
                added_cats += 1
            else:
                already_present += 1
        else:
            max_seq_doc = await db[INSTANCE_CATEGORIES].find_one(
                {"app_instance_id": inst_oid, "deleted_at": None},
                sort=[("sequence", -1)],
            )
            seq = compute_next_sequence(max_seq_doc.get("sequence") if max_seq_doc else None)
            try:
                await cat_repo.insert_one(
                    {
                        "app_instance_id": inst_oid,
                        "source_id": c_oid,
                        "is_enabled": True,
                        "sequence": seq,
                        "overrides": {},
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                    }
                )
                added_cats += 1
            except DuplicateKeyError:
                await db[INSTANCE_CATEGORIES].update_one(
                    {"app_instance_id": inst_oid, "source_id": c_oid},
                    {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                )
                already_present += 1

        # Query all central subcategories under this category and reference them
        central_subs = await db[SUBCATEGORIES].find({"category_id": c_oid, "deleted_at": None}).to_list(length=2000)
        for sub in central_subs:
            s_oid = sub["_id"]
            sub_exists = await db[INSTANCE_SUBCATEGORIES].find_one(
                {"app_instance_id": inst_oid, "source_id": s_oid}
            )
            if sub_exists:
                if sub_exists.get("deleted_at") is not None:
                    await db[INSTANCE_SUBCATEGORIES].update_one(
                        {"_id": sub_exists["_id"]},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": c_oid,
                                "updated_at": now,
                            }
                        },
                    )
                    added_subs += 1
            else:
                max_seq_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
                    {"app_instance_id": inst_oid, "category_id": c_oid, "deleted_at": None},
                    sort=[("sequence", -1)],
                )
                sub_seq = compute_next_sequence(max_seq_sub.get("sequence") if max_seq_sub else None)
                try:
                    await sub_repo.insert_one(
                        {
                            "app_instance_id": inst_oid,
                            "source_id": s_oid,
                            "category_id": c_oid,
                            "is_enabled": True,
                            "sequence": sub_seq,
                            "overrides": {},
                            "created_at": now,
                            "updated_at": now,
                            "deleted_at": None,
                        }
                    )
                    added_subs += 1
                except DuplicateKeyError:
                    await db[INSTANCE_SUBCATEGORIES].update_one(
                        {"app_instance_id": inst_oid, "source_id": s_oid},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": c_oid,
                                "updated_at": now,
                            }
                        },
                    )

        # Query all central assets under this category and reference them
        central_assets = await db[ASSETS].find({"category_id": c_oid, "deleted_at": None}).to_list(length=10000)
        for a in central_assets:
            a_oid = a["_id"]
            asset_exists = await db[INSTANCE_ASSETS].find_one(
                {"app_instance_id": inst_oid, "source_id": a_oid}
            )
            if asset_exists:
                if asset_exists.get("deleted_at") is not None:
                    await db[INSTANCE_ASSETS].update_one(
                        {"_id": asset_exists["_id"]},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": c_oid,
                                "sub_category_id": a["sub_category_id"],
                                "updated_at": now,
                            }
                        },
                    )
                    added_assets += 1
            else:
                max_seq_asset = await db[INSTANCE_ASSETS].find_one(
                    {
                        "app_instance_id": inst_oid,
                        "category_id": c_oid,
                        "sub_category_id": a["sub_category_id"],
                        "deleted_at": None,
                    },
                    sort=[("sequence", -1)],
                )
                asset_seq = compute_next_sequence(max_seq_asset.get("sequence") if max_seq_asset else None)
                try:
                    await asset_repo.insert_one(
                        {
                            "app_instance_id": inst_oid,
                            "source_id": a_oid,
                            "category_id": c_oid,
                            "sub_category_id": a["sub_category_id"],
                            "is_enabled": True,
                            "sequence": asset_seq,
                            "is_premium": False,
                            "is_rewarded": False,
                            "rewarded_credits": 5,
                            "views": 0,
                            "downloads": 0,
                            "overrides": {},
                            "created_at": now,
                            "updated_at": now,
                            "deleted_at": None,
                        }
                    )
                    added_assets += 1
                except DuplicateKeyError:
                    await db[INSTANCE_ASSETS].update_one(
                        {"app_instance_id": inst_oid, "source_id": a_oid},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": c_oid,
                                "sub_category_id": a["sub_category_id"],
                                "updated_at": now,
                            }
                        },
                    )

    # 2. Process subcategories (auto-adding parent category and copying all assets in subcategory)
    for sid in sub_category_ids or []:
        s_oid = to_object_id(sid)
        central_sub = await db[SUBCATEGORIES].find_one({"_id": s_oid, "deleted_at": None})
        if not central_sub:
            continue

        target_inst_cat = None
        if target_category_id:
            t_cat_oid = to_object_id(target_category_id)
            target_inst_cat = await db[INSTANCE_CATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "$or": [{"_id": t_cat_oid}, {"source_id": t_cat_oid}],
                }
            )

        if target_inst_cat:
            if target_inst_cat.get("deleted_at") is not None:
                await db[INSTANCE_CATEGORIES].update_one(
                    {"_id": target_inst_cat["_id"]},
                    {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                )
                added_cats += 1
            cat_link_id = target_inst_cat.get("source_id") or target_inst_cat["_id"]
        else:
            parent_cat_oid = central_sub["category_id"]
            cat_link_id = parent_cat_oid

            # Ensure parent category reference exists in this instance
            parent_inst_cat = await db[INSTANCE_CATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "source_id": parent_cat_oid,
                }
            )
            if parent_inst_cat:
                if parent_inst_cat.get("deleted_at") is not None:
                    await db[INSTANCE_CATEGORIES].update_one(
                        {"_id": parent_inst_cat["_id"]},
                        {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                    )
                    added_cats += 1
            else:
                max_seq = await db[INSTANCE_CATEGORIES].find_one(
                    {"app_instance_id": inst_oid, "deleted_at": None}, sort=[("sequence", -1)]
                )
                cat_seq = compute_next_sequence(max_seq.get("sequence") if max_seq else None)
                try:
                    await cat_repo.insert_one(
                        {
                            "app_instance_id": inst_oid,
                            "source_id": parent_cat_oid,
                            "is_enabled": True,
                            "sequence": cat_seq,
                            "overrides": {},
                            "created_at": now,
                            "updated_at": now,
                            "deleted_at": None,
                        }
                    )
                    added_cats += 1
                except DuplicateKeyError:
                    await db[INSTANCE_CATEGORIES].update_one(
                        {"app_instance_id": inst_oid, "source_id": parent_cat_oid},
                        {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                    )

        existing = await db[INSTANCE_SUBCATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "source_id": s_oid,
            }
        )
        if existing:
            if existing.get("deleted_at") is not None:
                await db[INSTANCE_SUBCATEGORIES].update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "deleted_at": None,
                            "is_enabled": True,
                            "category_id": cat_link_id,
                            "updated_at": now,
                        }
                    },
                )
                added_subs += 1
            else:
                if target_category_id:
                    await db[INSTANCE_SUBCATEGORIES].update_one(
                        {"_id": existing["_id"]},
                        {
                            "$set": {
                                "category_id": cat_link_id,
                                "updated_at": now,
                            }
                        },
                    )
                already_present += 1
        else:
            max_seq_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
                {"app_instance_id": inst_oid, "category_id": cat_link_id, "deleted_at": None},
                sort=[("sequence", -1)],
            )
            sub_seq = compute_next_sequence(max_seq_sub.get("sequence") if max_seq_sub else None)
            try:
                await sub_repo.insert_one(
                    {
                        "app_instance_id": inst_oid,
                        "source_id": s_oid,
                        "category_id": cat_link_id,
                        "is_enabled": True,
                        "sequence": sub_seq,
                        "overrides": {},
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                    }
                )
                added_subs += 1
            except DuplicateKeyError:
                await db[INSTANCE_SUBCATEGORIES].update_one(
                    {"app_instance_id": inst_oid, "source_id": s_oid},
                    {
                        "$set": {
                            "deleted_at": None,
                            "is_enabled": True,
                            "category_id": cat_link_id,
                            "updated_at": now,
                        }
                    },
                )
                already_present += 1

        # Query and reference all central assets under this subcategory
        central_assets = await db[ASSETS].find({"sub_category_id": s_oid, "deleted_at": None}).to_list(length=5000)
        for a in central_assets:
            a_oid = a["_id"]
            asset_exists = await db[INSTANCE_ASSETS].find_one(
                {"app_instance_id": inst_oid, "source_id": a_oid}
            )
            if asset_exists:
                if asset_exists.get("deleted_at") is not None:
                    await db[INSTANCE_ASSETS].update_one(
                        {"_id": asset_exists["_id"]},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": cat_link_id,
                                "sub_category_id": s_oid,
                                "updated_at": now,
                            }
                        },
                    )
                    added_assets += 1
                else:
                    if target_category_id:
                        await db[INSTANCE_ASSETS].update_one(
                            {"_id": asset_exists["_id"]},
                            {
                                "$set": {
                                    "category_id": cat_link_id,
                                    "sub_category_id": s_oid,
                                    "updated_at": now,
                                }
                            },
                        )
            else:
                max_seq_asset = await db[INSTANCE_ASSETS].find_one(
                    {
                        "app_instance_id": inst_oid,
                        "category_id": cat_link_id,
                        "sub_category_id": s_oid,
                        "deleted_at": None,
                    },
                    sort=[("sequence", -1)],
                )
                asset_seq = compute_next_sequence(max_seq_asset.get("sequence") if max_seq_asset else None)
                try:
                    await asset_repo.insert_one(
                        {
                            "app_instance_id": inst_oid,
                            "source_id": a_oid,
                            "category_id": cat_link_id,
                            "sub_category_id": s_oid,
                            "is_enabled": True,
                            "sequence": asset_seq,
                            "is_premium": False,
                            "is_rewarded": False,
                            "rewarded_credits": 5,
                            "views": 0,
                            "downloads": 0,
                            "overrides": {},
                            "created_at": now,
                            "updated_at": now,
                            "deleted_at": None,
                        }
                    )
                    added_assets += 1
                except DuplicateKeyError:
                    await db[INSTANCE_ASSETS].update_one(
                        {"app_instance_id": inst_oid, "source_id": a_oid},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": cat_link_id,
                                "sub_category_id": s_oid,
                                "updated_at": now,
                            }
                        },
                    )

    # 3. Process individual assets (auto-adding parent subcategory and category)
    for aid in asset_ids or []:
        a_oid = to_object_id(aid)
        existing = await db[INSTANCE_ASSETS].find_one(
            {
                "app_instance_id": inst_oid,
                "source_id": a_oid,
            }
        )
        if existing and existing.get("deleted_at") is None:
            already_present += 1
            continue

        central_asset = await db[ASSETS].find_one({"_id": a_oid, "deleted_at": None})
        if not central_asset:
            continue

        target_inst_cat = None
        if target_category_id:
            t_cat_oid = to_object_id(target_category_id)
            target_inst_cat = await db[INSTANCE_CATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "$or": [{"_id": t_cat_oid}, {"source_id": t_cat_oid}],
                }
            )

        if target_inst_cat:
            if target_inst_cat.get("deleted_at") is not None:
                await db[INSTANCE_CATEGORIES].update_one(
                    {"_id": target_inst_cat["_id"]},
                    {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                )
                added_cats += 1
            cat_link_id = target_inst_cat.get("source_id") or target_inst_cat["_id"]
        else:
            cat_oid = central_asset["category_id"]
            cat_link_id = cat_oid
            # Ensure parent category reference exists
            parent_inst_cat = await db[INSTANCE_CATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "source_id": cat_oid,
                }
            )
            if parent_inst_cat:
                if parent_inst_cat.get("deleted_at") is not None:
                    await db[INSTANCE_CATEGORIES].update_one(
                        {"_id": parent_inst_cat["_id"]},
                        {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                    )
                    added_cats += 1
            else:
                max_seq = await db[INSTANCE_CATEGORIES].find_one(
                    {"app_instance_id": inst_oid, "deleted_at": None}, sort=[("sequence", -1)]
                )
                cat_seq = compute_next_sequence(max_seq.get("sequence") if max_seq else None)
                try:
                    await cat_repo.insert_one(
                        {
                            "app_instance_id": inst_oid,
                            "source_id": cat_oid,
                            "is_enabled": True,
                            "sequence": cat_seq,
                            "overrides": {},
                            "created_at": now,
                            "updated_at": now,
                            "deleted_at": None,
                        }
                    )
                    added_cats += 1
                except DuplicateKeyError:
                    await db[INSTANCE_CATEGORIES].update_one(
                        {"app_instance_id": inst_oid, "source_id": cat_oid},
                        {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                    )

        target_inst_sub = None
        if target_sub_category_id:
            t_sub_oid = to_object_id(target_sub_category_id)
            target_inst_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "$or": [{"_id": t_sub_oid}, {"source_id": t_sub_oid}],
                }
            )

        if target_inst_sub:
            if target_inst_sub.get("deleted_at") is not None:
                await db[INSTANCE_SUBCATEGORIES].update_one(
                    {"_id": target_inst_sub["_id"]},
                    {
                        "$set": {
                            "deleted_at": None,
                            "is_enabled": True,
                            "category_id": cat_link_id,
                            "updated_at": now,
                        }
                    },
                )
                added_subs += 1
            sub_link_id = target_inst_sub.get("source_id") or target_inst_sub["_id"]
        else:
            sub_oid = central_asset["sub_category_id"]
            sub_link_id = sub_oid
            # Ensure parent subcategory reference exists
            parent_inst_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "source_id": sub_oid,
                }
            )
            if parent_inst_sub:
                if parent_inst_sub.get("deleted_at") is not None:
                    await db[INSTANCE_SUBCATEGORIES].update_one(
                        {"_id": parent_inst_sub["_id"]},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": cat_link_id,
                                "updated_at": now,
                            }
                        },
                    )
                    added_subs += 1
            else:
                max_seq_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
                    {"app_instance_id": inst_oid, "category_id": cat_link_id, "deleted_at": None},
                    sort=[("sequence", -1)],
                )
                sub_seq = compute_next_sequence(max_seq_sub.get("sequence") if max_seq_sub else None)
                try:
                    await sub_repo.insert_one(
                        {
                            "app_instance_id": inst_oid,
                            "source_id": sub_oid,
                            "category_id": cat_link_id,
                            "is_enabled": True,
                            "sequence": sub_seq,
                            "overrides": {},
                            "created_at": now,
                            "updated_at": now,
                            "deleted_at": None,
                        }
                    )
                    added_subs += 1
                except DuplicateKeyError:
                    await db[INSTANCE_SUBCATEGORIES].update_one(
                        {"app_instance_id": inst_oid, "source_id": sub_oid},
                        {
                            "$set": {
                                "deleted_at": None,
                                "is_enabled": True,
                                "category_id": cat_link_id,
                                "updated_at": now,
                            }
                        },
                    )

        if existing:
            if existing.get("deleted_at") is not None:
                await db[INSTANCE_ASSETS].update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "deleted_at": None,
                            "is_enabled": True,
                            "category_id": cat_link_id,
                            "sub_category_id": sub_link_id,
                            "updated_at": now,
                        }
                    },
                )
                added_assets += 1
            else:
                if target_category_id or target_sub_category_id:
                    await db[INSTANCE_ASSETS].update_one(
                        {"_id": existing["_id"]},
                        {
                            "$set": {
                                "category_id": cat_link_id,
                                "sub_category_id": sub_link_id,
                                "updated_at": now,
                            }
                        },
                    )
                already_present += 1
        else:
            max_seq_asset = await db[INSTANCE_ASSETS].find_one(
                {
                    "app_instance_id": inst_oid,
                    "category_id": cat_link_id,
                    "sub_category_id": sub_link_id,
                    "deleted_at": None,
                },
                sort=[("sequence", -1)],
            )
            asset_seq = compute_next_sequence(max_seq_asset.get("sequence") if max_seq_asset else None)
            try:
                await asset_repo.insert_one(
                    {
                        "app_instance_id": inst_oid,
                        "source_id": a_oid,
                        "category_id": cat_link_id,
                        "sub_category_id": sub_link_id,
                        "is_enabled": True,
                        "sequence": asset_seq,
                        "is_premium": False,
                        "is_rewarded": False,
                        "rewarded_credits": 5,
                        "views": 0,
                        "downloads": 0,
                        "overrides": {},
                        "created_at": now,
                        "updated_at": now,
                        "deleted_at": None,
                    }
                )
                added_assets += 1
            except DuplicateKeyError:
                await db[INSTANCE_ASSETS].update_one(
                    {"app_instance_id": inst_oid, "source_id": a_oid},
                    {
                        "$set": {
                            "deleted_at": None,
                            "is_enabled": True,
                            "category_id": cat_link_id,
                            "sub_category_id": sub_link_id,
                            "updated_at": now,
                        }
                    },
                )
                already_present += 1

    return {
        "success": True,
        "added_categories": added_cats,
        "added_subcategories": added_subs,
        "added_assets": added_assets,
        "already_present": already_present,
    }


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

        source_sub_oid = sub_ref.get("source_id")
        sub_ids = [sub_ref["_id"]]
        if source_sub_oid:
            sub_ids.append(source_sub_oid)

        # Remove subcategory reference and all child asset references in this app permanently
        await db[INSTANCE_SUBCATEGORIES].delete_one({"_id": sub_ref["_id"]})
        asset_res = await db[INSTANCE_ASSETS].delete_many(
            {"app_instance_id": inst_oid, "sub_category_id": {"$in": sub_ids}}
        )
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

    # Assets: only inspect references with a central source_id
    unresolved_assets = (
        await db[INSTANCE_ASSETS]
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
                        "from": ASSETS,
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
