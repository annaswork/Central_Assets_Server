"""Overrides and instance settings controller.

STRICT LAYER RULE:
This module operates exclusively on instance_* collections.
It NEVER imports central controllers or CentralRepository.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from database.collections import (
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    INSTANCE_SUPER_CATEGORIES,
)
from database.repository import instance_collection
from utils.datetimes import utc_now
from utils.errors import NotFoundError, ValidationError
from utils.ids import to_object_id
from utils.sequencing import generate_sequence_reordering

ALLOWED_FOLDER_OVERRIDES = {"name", "thumbnail_url", "image_url", "tags"}
ALLOWED_ASSET_OVERRIDES = {"name", "description", "thumbnail_url", "more_fields", "tags"}
BLOCKED_OVERRIDE_KEYS = {
    "super_category_id",
    "category_id",
    "sub_category_id",
    "source_id",
    "created_at",
    "updated_at",
    "deleted_at",
}


_COLLECTION_BY_TYPE = {
    "super_category": INSTANCE_SUPER_CATEGORIES,
    "supercategory": INSTANCE_SUPER_CATEGORIES,
    "category": INSTANCE_CATEGORIES,
    "subcategory": INSTANCE_SUBCATEGORIES,
}


def _collection_for(item_type: str) -> str:
    """Instance collection for an item type; anything unrecognized is treated as an asset."""
    return _COLLECTION_BY_TYPE.get(item_type, INSTANCE_ASSETS)


async def update_item_settings_and_overrides(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    item_type: str,
    item_id: str,
    is_enabled: bool | None = None,
    sequence: int | None = None,
    is_premium: bool | None = None,
    is_rewarded: bool | None = None,
    is_priced: bool | None = None,
    rewarded_credits: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update reference settings (is_enabled, sequence, is_premium, is_rewarded, is_priced, rewarded_credits) and sparse field overrides."""
    inst_oid = to_object_id(app_instance_id)
    ref_oid = to_object_id(item_id)

    col_name = _collection_for(item_type)
    allowed_overrides = (
        ALLOWED_ASSET_OVERRIDES if col_name == INSTANCE_ASSETS else ALLOWED_FOLDER_OVERRIDES
    )

    query = {
        "app_instance_id": inst_oid,
        "$or": [{"_id": ref_oid}, {"source_id": ref_oid}],
        "deleted_at": None,
    }

    doc = await instance_collection(db, col_name).find_one(query)
    if not doc:
        raise NotFoundError(f"Instance {item_type} reference not found")

    set_fields: dict[str, Any] = {"updated_at": utc_now()}
    if is_enabled is not None:
        set_fields["is_enabled"] = bool(is_enabled)
    if sequence is not None:
        set_fields["sequence"] = sequence
    if is_premium is not None:
        set_fields["is_premium"] = bool(is_premium)
    if is_rewarded is not None and item_type in ("asset", "subcategory"):
        set_fields["is_rewarded"] = bool(is_rewarded)
    if is_priced is not None and item_type == "asset":
        set_fields["is_priced"] = bool(is_priced)
        if is_priced and rewarded_credits is None and not doc.get("rewarded_credits"):
            set_fields["rewarded_credits"] = 5
    if rewarded_credits is not None and item_type == "asset":
        try:
            val = int(rewarded_credits)
            set_fields["rewarded_credits"] = max(0, val)
        except (ValueError, TypeError):
            set_fields["rewarded_credits"] = 5

    if overrides is not None:
        # Validate keys
        for k in overrides.keys():
            if k in BLOCKED_OVERRIDE_KEYS:
                raise ValidationError(f"Field '{k}' cannot be overridden in app instances")
            if k not in allowed_overrides:
                raise ValidationError(f"Field '{k}' is not an allowed override for {item_type}")

        # Merge existing overrides with new overrides
        existing_overrides = doc.get("overrides", {})
        merged = dict(existing_overrides)
        for k, v in overrides.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        set_fields["overrides"] = merged
        if "tags" in merged:
            set_fields["tags"] = merged["tags"]
        elif "tags" in overrides and overrides["tags"] is None:
            set_fields["tags"] = []

    await instance_collection(db, col_name).update_one({"_id": doc["_id"]}, {"$set": set_fields})
    updated = await instance_collection(db, col_name).find_one({"_id": doc["_id"]})
    return updated  # type: ignore


async def reset_overrides(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    item_type: str,
    item_id: str,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Reset field overrides, falling back to read-through to live central data."""
    inst_oid = to_object_id(app_instance_id)
    ref_oid = to_object_id(item_id)

    col_name = _collection_for(item_type)

    query = {
        "app_instance_id": inst_oid,
        "$or": [{"_id": ref_oid}, {"source_id": ref_oid}],
        "deleted_at": None,
    }

    doc = await instance_collection(db, col_name).find_one(query)
    if not doc:
        raise NotFoundError(f"Instance {item_type} reference not found")

    if not fields:
        # Reset all overrides
        await instance_collection(db, col_name).update_one(
            {"_id": doc["_id"]},
            {"$set": {"overrides": {}, "updated_at": utc_now()}},
        )
    else:
        # Unset specific keys from the overrides object
        unset_dict = {f"overrides.{f}": "" for f in fields}
        await instance_collection(db, col_name).update_one(
            {"_id": doc["_id"]},
            {"$unset": unset_dict, "$set": {"updated_at": utc_now()}},
        )

    updated = await instance_collection(db, col_name).find_one({"_id": doc["_id"]})
    return updated  # type: ignore


async def reorder_items(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    item_type: str,
    ordered_ids: list[str],
    start: int = 0,
) -> dict[str, Any]:
    """Assign sequence numbers start+1, start+2... according to the provided ordered list of IDs."""
    inst_oid = to_object_id(app_instance_id)
    col_name = _collection_for(item_type)

    reorder_pairs = generate_sequence_reordering(ordered_ids, start)
    now = utc_now()

    for item_id, seq in reorder_pairs:
        oid = to_object_id(item_id)
        await instance_collection(db, col_name).update_one(
            {
                "app_instance_id": inst_oid,
                "$or": [{"_id": oid}, {"source_id": oid}],
                "deleted_at": None,
            },
            {"$set": {"sequence": seq, "updated_at": now}},
        )

    return {"success": True, "reordered_count": len(reorder_pairs)}


async def bulk_update_flags(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    item_type: str,
    ids: list[str],
    is_enabled: bool | None = None,
    is_premium: bool | None = None,
) -> dict[str, Any]:
    """Bulk update is_enabled and/or is_premium flags across referenced items in an app."""
    inst_oid = to_object_id(app_instance_id)
    col_name = _collection_for(item_type)

    set_fields: dict[str, Any] = {"updated_at": utc_now()}
    if is_enabled is not None:
        set_fields["is_enabled"] = is_enabled
    if is_premium is not None:
        set_fields["is_premium"] = is_premium

    oids = [to_object_id(i) for i in ids]
    res = await instance_collection(db, col_name).update_many(
        {
            "app_instance_id": inst_oid,
            "$or": [{"_id": {"$in": oids}}, {"source_id": {"$in": oids}}],
            "deleted_at": None,
        },
        {"$set": set_fields},
    )

    return {"success": True, "modified_count": res.modified_count}


async def set_asset_override(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    asset_id: str,
    override_data: Any,
) -> dict[str, Any]:
    """Helper to set asset settings and overrides from model or dict."""
    name = getattr(override_data, "name", None)
    description = getattr(override_data, "description", None)
    sequence = getattr(override_data, "sequence", None)
    is_premium = getattr(override_data, "is_premium", None)
    is_enabled = getattr(override_data, "is_enabled", None)
    overrides = {}
    if name is not None:
        overrides["name"] = name
    if description is not None:
        overrides["description"] = description

    return await update_item_settings_and_overrides(
        db=db,
        app_instance_id=app_instance_id,
        item_type="asset",
        item_id=asset_id,
        is_enabled=is_enabled,
        sequence=sequence,
        is_premium=is_premium,
        overrides=overrides or None,
    )


async def bulk_update_folder_tags(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    categories: list[str],
    subcategories: list[str],
    tags: list[str] | str,
    mode: str = "add",
) -> dict[str, Any]:
    """Bulk update tags across categories and subcategories in an app instance.

    Supported modes:
    - 'add': appends tags without duplicates
    - 'replace': overwrites tags with the provided tags (empty clears tags)
    - 'remove': pulls matching tags
    """
    inst_oid = to_object_id(app_instance_id)

    # Clean tags
    if isinstance(tags, str):
        clean_tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        clean_tags = []
        for item in tags:
            if isinstance(item, str):
                for part in item.split(","):
                    p = part.strip()
                    if p and p not in clean_tags:
                        clean_tags.append(p)
    else:
        clean_tags = []

    clean_tags = list(dict.fromkeys(clean_tags))

    if mode not in ("add", "replace", "remove"):
        mode = "add"

    cat_oids: list[Any] = []
    for c in categories:
        try:
            cat_oids.append(to_object_id(c))
        except Exception:
            pass

    sub_oids: list[Any] = []
    for s in subcategories:
        try:
            sub_oids.append(to_object_id(s))
        except Exception:
            pass

    if not cat_oids and not sub_oids:
        raise ValidationError("No valid category or subcategory IDs provided")

    now = utc_now()
    if mode == "replace":
        update_op = {
            "$set": {
                "tags": clean_tags,
                "overrides.tags": clean_tags,
                "updated_at": now,
            }
        }
    elif mode == "remove":
        update_op = {
            "$pull": {
                "tags": {"$in": clean_tags},
                "overrides.tags": {"$in": clean_tags},
            },
            "$set": {"updated_at": now},
        }
    else:  # "add"
        update_op = {
            "$addToSet": {
                "tags": {"$each": clean_tags},
                "overrides.tags": {"$each": clean_tags},
            },
            "$set": {"updated_at": now},
        }

    cats_modified = 0
    subs_modified = 0
    tags_by_id: dict[str, list[str]] = {}

    if cat_oids:
        cat_query = {
            "app_instance_id": inst_oid,
            "$or": [{"_id": {"$in": cat_oids}}, {"source_id": {"$in": cat_oids}}],
            "deleted_at": None,
        }
        await instance_collection(db, INSTANCE_CATEGORIES).update_many(
            {**cat_query, "overrides": None},
            {"$set": {"overrides": {}}},
        )
        await instance_collection(db, INSTANCE_CATEGORIES).update_many(
            {**cat_query, "tags": None},
            {"$set": {"tags": []}},
        )
        await instance_collection(db, INSTANCE_CATEGORIES).update_many(
            {**cat_query, "overrides.tags": None},
            {"$set": {"overrides.tags": []}},
        )

        cat_res = await instance_collection(db, INSTANCE_CATEGORIES).update_many(cat_query, update_op)
        cats_modified = cat_res.modified_count

        updated_cats = await instance_collection(db, INSTANCE_CATEGORIES).find(
            cat_query,
            {"_id": 1, "source_id": 1, "tags": 1, "overrides": 1},
        ).to_list(length=None)

        for doc in updated_cats:
            doc_id = str(doc["_id"])
            t_list = doc.get("tags") or doc.get("overrides", {}).get("tags") or []
            tags_by_id[f"category_{doc_id}"] = t_list
            tags_by_id[doc_id] = t_list
            if doc.get("source_id"):
                src_id = str(doc["source_id"])
                tags_by_id[f"category_{src_id}"] = t_list
                tags_by_id[src_id] = t_list

    if sub_oids:
        sub_query = {
            "app_instance_id": inst_oid,
            "$or": [{"_id": {"$in": sub_oids}}, {"source_id": {"$in": sub_oids}}],
            "deleted_at": None,
        }
        await instance_collection(db, INSTANCE_SUBCATEGORIES).update_many(
            {**sub_query, "overrides": None},
            {"$set": {"overrides": {}}},
        )
        await instance_collection(db, INSTANCE_SUBCATEGORIES).update_many(
            {**sub_query, "tags": None},
            {"$set": {"tags": []}},
        )
        await instance_collection(db, INSTANCE_SUBCATEGORIES).update_many(
            {**sub_query, "overrides.tags": None},
            {"$set": {"overrides.tags": []}},
        )

        sub_res = await instance_collection(db, INSTANCE_SUBCATEGORIES).update_many(sub_query, update_op)
        subs_modified = sub_res.modified_count

        updated_subs = await instance_collection(db, INSTANCE_SUBCATEGORIES).find(
            sub_query,
            {"_id": 1, "source_id": 1, "tags": 1, "overrides": 1},
        ).to_list(length=None)

        for doc in updated_subs:
            doc_id = str(doc["_id"])
            t_list = doc.get("tags") or doc.get("overrides", {}).get("tags") or []
            tags_by_id[f"subcategory_{doc_id}"] = t_list
            tags_by_id[doc_id] = t_list
            if doc.get("source_id"):
                src_id = str(doc["source_id"])
                tags_by_id[f"subcategory_{src_id}"] = t_list
                tags_by_id[src_id] = t_list

    total_modified = cats_modified + subs_modified
    return {
        "success": True,
        "categories_modified": cats_modified,
        "subcategories_modified": subs_modified,
        "total_modified": total_modified,
        "tags_by_id": tags_by_id,
        "message": f"Successfully updated tags for {total_modified} folder(s)",
    }


def compute_tier_distribution(
    total_count: int,
    premium_count: int,
    rewarded_count: int = 0,
    normal_frequency: int = 1,
    premium_frequency: int = 1,
    rewarded_frequency: int = 1,
) -> list[str]:
    """Calculate the sequence of tiers ('normal', 'premium', 'rewarded') for total_count items.

    Enforces that combined premium + rewarded cannot exceed total_count - 1 (when total_count > 0),
    ensuring at least 1 item remains normal/free.
    Cycles through normal_frequency normal items, premium_frequency premium items, and
    rewarded_frequency rewarded items until all items are assigned, capping at the specified counts.
    """
    if total_count <= 0:
        return []

    max_allowed = max(0, total_count - 1)
    if premium_count + rewarded_count > max_allowed:
        raise ValidationError(
            f"Combined premium ({premium_count}) and rewarded ({rewarded_count}) count "
            f"cannot exceed {max_allowed} (out of {total_count} items). At least 1 item must remain normal/free."
        )

    rem_normal = total_count - premium_count - rewarded_count
    rem_premium = premium_count
    rem_rewarded = rewarded_count

    n_freq = max(1, normal_frequency)
    p_freq = max(1, premium_frequency)
    r_freq = max(1, rewarded_frequency)

    result: list[str] = []

    while len(result) < total_count:
        # Step 1: Normal batch
        normal_batch = min(n_freq, rem_normal, total_count - len(result))
        for _ in range(normal_batch):
            result.append("normal")
            rem_normal -= 1

        # Step 2: Premium batch (if budget remains)
        if rem_premium > 0 and len(result) < total_count:
            prem_batch = min(p_freq, rem_premium, total_count - len(result))
            for _ in range(prem_batch):
                result.append("premium")
                rem_premium -= 1

        # Step 3: Rewarded batch (if budget remains)
        if rem_rewarded > 0 and len(result) < total_count:
            rew_batch = min(r_freq, rem_rewarded, total_count - len(result))
            for _ in range(rew_batch):
                result.append("rewarded")
                rem_rewarded -= 1

        # Fallback: if premium & rewarded budgets exhausted, remaining slots become normal
        if rem_premium == 0 and rem_rewarded == 0:
            while len(result) < total_count:
                result.append("normal")
                rem_normal -= 1

    return result


async def distribute_item_tiers(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    scope_type: str,
    scope_id: str,
    target_type: str,
    premium_count: int = 0,
    rewarded_count: int = 0,
    normal_frequency: int = 1,
    premium_frequency: int = 1,
    rewarded_frequency: int = 1,
) -> dict[str, Any]:
    """Assign premium and rewarded tiers across child items (subcategories in category, or assets in subcategory/category)."""
    inst_oid = to_object_id(app_instance_id)
    scope_oid = to_object_id(scope_id)

    scope_type_clean = scope_type.strip().lower()
    target_type_clean = target_type.strip().lower()

    if scope_type_clean not in ("category", "subcategory"):
        raise ValidationError(f"Invalid scope_type '{scope_type}'. Must be 'category' or 'subcategory'.")
    if target_type_clean not in ("subcategory", "asset"):
        raise ValidationError(f"Invalid target_type '{target_type}'. Must be 'subcategory' or 'asset'.")

    # Resolve parent scope keys (_id and source_id, ObjectId and str)
    scope_coll = INSTANCE_CATEGORIES if scope_type_clean == "category" else INSTANCE_SUBCATEGORIES
    scope_doc = await instance_collection(db, scope_coll).find_one(
        {"app_instance_id": inst_oid, "$or": [{"_id": scope_oid}, {"source_id": scope_oid}], "deleted_at": None}
    )
    if not scope_doc:
        raise NotFoundError(f"Parent {scope_type_clean} not found in this app instance")

    scope_keys: set[Any] = {scope_doc["_id"], str(scope_doc["_id"])}
    if scope_doc.get("source_id"):
        scope_keys.add(scope_doc["source_id"])
        scope_keys.add(str(scope_doc["source_id"]))

    # Query matching items in sequence order
    if target_type_clean == "subcategory":
        coll_name = INSTANCE_SUBCATEGORIES
        item_query = {
            "app_instance_id": inst_oid,
            "category_id": {"$in": list(scope_keys)},
            "deleted_at": None,
        }
    else:  # asset
        coll_name = INSTANCE_ASSETS
        field_name = "sub_category_id" if scope_type_clean == "subcategory" else "category_id"
        item_query = {
            "app_instance_id": inst_oid,
            field_name: {"$in": list(scope_keys)},
            "deleted_at": None,
        }

    items = await instance_collection(db, coll_name).find(
        item_query,
        {"_id": 1, "sequence": 1, "name": 1, "is_premium": 1, "is_rewarded": 1, "rewarded_credits": 1}
    ).sort([("sequence", 1), ("_id", 1)]).to_list(length=None)

    total_count = len(items)
    if total_count == 0:
        raise ValidationError(f"No {target_type_clean}s found in the specified {scope_type_clean}")

    pattern = compute_tier_distribution(
        total_count=total_count,
        premium_count=premium_count,
        rewarded_count=rewarded_count,
        normal_frequency=normal_frequency,
        premium_frequency=premium_frequency,
        rewarded_frequency=rewarded_frequency,
    )

    operations = []
    assignments = []
    now = utc_now()

    for item, tier in zip(items, pattern):
        is_prem = (tier == "premium")
        is_rew = (tier == "rewarded")
        item_id_str = str(item["_id"])

        set_fields: dict[str, Any] = {
            "is_premium": is_prem,
            "is_rewarded": is_rew,
            "updated_at": now,
        }
        if target_type_clean == "asset" and is_rew and not item.get("rewarded_credits"):
            set_fields["rewarded_credits"] = 5

        operations.append(UpdateOne({"_id": item["_id"]}, {"$set": set_fields}))
        assignments.append({
            "id": item_id_str,
            "name": item.get("name") or "",
            "sequence": item.get("sequence", 1),
            "tier": tier,
            "is_premium": is_prem,
            "is_rewarded": is_rew,
        })

    if operations:
        await instance_collection(db, coll_name).bulk_write(operations, ordered=False)

    # Persist the configuration on the parent scope document
    settings_doc = {
        "target_type": target_type_clean,
        "premium_count": premium_count,
        "rewarded_count": rewarded_count,
        "normal_frequency": normal_frequency,
        "premium_frequency": premium_frequency,
        "rewarded_frequency": rewarded_frequency,
        "updated_at": now.isoformat(),
    }
    await instance_collection(db, scope_coll).update_one(
        {"_id": scope_doc["_id"]},
        {"$set": {"tier_distribution_settings": settings_doc, "updated_at": now}}
    )

    return {
        "success": True,
        "total_items": total_count,
        "premium_count": premium_count,
        "rewarded_count": rewarded_count,
        "normal_count": total_count - premium_count - rewarded_count,
        "target_type": target_type_clean,
        "scope_type": scope_type_clean,
        "scope_id": str(scope_doc["_id"]),
        "settings": settings_doc,
        "assignments": assignments,
    }
