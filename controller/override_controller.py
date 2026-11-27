"""Overrides and instance settings controller.

STRICT LAYER RULE:
This module operates exclusively on instance_* collections.
It NEVER imports central controllers or CentralRepository.
"""

from collections import defaultdict
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from controller.catalog_controller import dead_asset_row_ids
from database.collections import (
    APP_INSTANCES,
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
    if doc.get("source_id") is None:
        raise ValidationError(
            f"App-local {item_type} items have no Central Data defaults to reset to."
        )

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
    alternate_paid: bool = False,
) -> list[str]:
    """Calculate the sequence of tiers ('normal', 'premium', 'rewarded') for total_count items.

    Enforces that combined premium + rewarded cannot exceed total_count - 1 (when total_count > 0),
    ensuring at least 1 item remains normal/free.
    When alternate_paid is False, each cycle appends Normal -> Premium -> Rewarded.
    When alternate_paid is True, each cycle appends Normal -> one paid tier, alternating
    between Premium and Rewarded across cycles (e.g. N, N, P, N, N, R, N, N, P, N).
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
    paid_turn = "premium" if rem_premium > 0 else "rewarded"

    while len(result) < total_count:
        # Step 1: Normal batch
        normal_batch = min(n_freq, rem_normal, total_count - len(result))
        for _ in range(normal_batch):
            result.append("normal")
            rem_normal -= 1

        # Step 2: Paid batch(es)
        if len(result) < total_count:
            if alternate_paid:
                choose_prem = (
                    (paid_turn == "premium" and rem_premium > 0)
                    or (paid_turn == "rewarded" and rem_rewarded == 0 and rem_premium > 0)
                )
                choose_rew = (not choose_prem) and rem_rewarded > 0
                if choose_prem:
                    prem_batch = min(p_freq, rem_premium, total_count - len(result))
                    for _ in range(prem_batch):
                        result.append("premium")
                        rem_premium -= 1
                    paid_turn = "rewarded"
                elif choose_rew:
                    rew_batch = min(r_freq, rem_rewarded, total_count - len(result))
                    for _ in range(rew_batch):
                        result.append("rewarded")
                        rem_rewarded -= 1
                    paid_turn = "premium"
            else:
                if rem_premium > 0:
                    prem_batch = min(p_freq, rem_premium, total_count - len(result))
                    for _ in range(prem_batch):
                        result.append("premium")
                        rem_premium -= 1
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


def clamp_counts_for_total(
    total_count: int,
    premium_count: int,
    rewarded_count: int,
) -> tuple[int, int]:
    """Clamp requested counts to [0, total_count - 1], scaling proportionally when both tiers compete."""
    if total_count <= 1:
        return (0, 0)
    max_allowed = total_count - 1
    prem = max(0, int(premium_count))
    rew = max(0, int(rewarded_count))
    if prem + rew <= max_allowed:
        return (prem, rew)

    if prem > 0 and rew > 0 and max_allowed >= 2:
        eff_prem = round(max_allowed * (prem / (prem + rew)))
        eff_prem = max(1, min(max_allowed - 1, eff_prem))
        return (eff_prem, max_allowed - eff_prem)
    if prem > 0 and (rew == 0 or prem >= rew):
        return (max_allowed, 0)
    if rew > 0:
        return (0, max_allowed)
    return (0, 0)


def resolve_effective_counts(
    total_count: int,
    count_mode: str = "fixed",
    premium_count: int = 0,
    rewarded_count: int = 0,
    premium_percent: float = 0.0,
    rewarded_percent: float = 0.0,
) -> tuple[int, int]:
    """Compute effective (premium, rewarded) counts for a single container under fixed or percentage rules."""
    if count_mode == "percentage":
        raw_p = round(total_count * max(0.0, float(premium_percent)) / 100.0)
        raw_r = round(total_count * max(0.0, float(rewarded_percent)) / 100.0)
        return clamp_counts_for_total(total_count, raw_p, raw_r)
    return clamp_counts_for_total(total_count, premium_count, rewarded_count)


def _build_item_tier_ops(
    items: list[dict[str, Any]],
    pattern: list[str],
    target_type_clean: str,
    now: Any,
) -> tuple[list[UpdateOne], list[dict[str, Any]]]:
    """Build MongoDB UpdateOne operations and assignment summaries for zipped items and computed tiers."""
    operations: list[UpdateOne] = []
    assignments: list[dict[str, Any]] = []
    for item, tier in zip(items, pattern):
        is_prem = tier == "premium"
        is_rew = tier == "rewarded"
        set_fields: dict[str, Any] = {
            "is_premium": is_prem,
            "is_rewarded": is_rew,
            "updated_at": now,
        }
        if target_type_clean == "asset" and is_rew and not item.get("rewarded_credits"):
            set_fields["rewarded_credits"] = 5

        operations.append(UpdateOne({"_id": item["_id"]}, {"$set": set_fields}))
        assignments.append({
            "id": str(item["_id"]),
            "name": item.get("name") or "",
            "sequence": item.get("sequence", 1),
            "tier": tier,
            "is_premium": is_prem,
            "is_rewarded": is_rew,
        })
    return operations, assignments


def _id_variants(val: Any) -> set[Any]:
    """Return both raw ObjectId/value and str forms for defensive folder reference matching."""
    return {val, str(val)} if val is not None else set()


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
    alternate_paid: bool = False,
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

    scope_keys = _id_variants(scope_doc["_id"]) | _id_variants(scope_doc.get("source_id"))

    # Query matching live items in sequence order
    if target_type_clean == "subcategory":
        coll_name = INSTANCE_SUBCATEGORIES
        item_query: dict[str, Any] = {
            "app_instance_id": inst_oid,
            "category_id": {"$in": list(scope_keys)},
            "deleted_at": None,
        }
    else:  # asset
        coll_name = INSTANCE_ASSETS
        dead_ids = await dead_asset_row_ids(db, inst_oid)
        if scope_type_clean == "subcategory":
            # Isolate shared central source_id folders by scoping source_id matches to the parent category
            own_keys = _id_variants(scope_doc["_id"])
            src_keys = _id_variants(scope_doc.get("source_id"))
            sub_match: dict[str, Any]
            if src_keys and scope_doc.get("category_id"):
                cat_oid = scope_doc["category_id"]
                parent_cat = await instance_collection(db, INSTANCE_CATEGORIES).find_one(
                    {"app_instance_id": inst_oid, "$or": [{"_id": cat_oid}, {"source_id": cat_oid}], "deleted_at": None},
                    {"_id": 1, "source_id": 1},
                )
                cat_keys = _id_variants(cat_oid)
                if parent_cat:
                    cat_keys |= _id_variants(parent_cat["_id"]) | _id_variants(parent_cat.get("source_id"))
                sub_match = {
                    "$or": [
                        {"sub_category_id": {"$in": list(own_keys)}},
                        {"sub_category_id": {"$in": list(src_keys)}, "category_id": {"$in": list(cat_keys)}},
                    ]
                }
            else:
                sub_match = {"sub_category_id": {"$in": list(scope_keys)}}
            item_query = {"app_instance_id": inst_oid, "deleted_at": None, **sub_match}
        else:
            item_query = {
                "app_instance_id": inst_oid,
                "category_id": {"$in": list(scope_keys)},
                "deleted_at": None,
            }
        if dead_ids:
            item_query["_id"] = {"$nin": dead_ids}

    items = await instance_collection(db, coll_name).find(
        item_query,
        {"_id": 1, "sequence": 1, "name": 1, "is_premium": 1, "is_rewarded": 1, "rewarded_credits": 1},
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
        alternate_paid=alternate_paid,
    )

    now = utc_now()
    operations, assignments = _build_item_tier_ops(items, pattern, target_type_clean, now)

    if operations:
        await instance_collection(db, coll_name).bulk_write(operations, ordered=False)

    # Persist the configuration on the parent scope document
    settings_doc = {
        "target_type": target_type_clean,
        "count_mode": "fixed",
        "premium_count": premium_count,
        "rewarded_count": rewarded_count,
        "normal_frequency": normal_frequency,
        "premium_frequency": premium_frequency,
        "rewarded_frequency": rewarded_frequency,
        "alternate_paid": bool(alternate_paid),
        "updated_at": now.isoformat(),
    }
    await instance_collection(db, scope_coll).update_one(
        {"_id": scope_doc["_id"]},
        {"$set": {"tier_distribution_settings": settings_doc, "updated_at": now}},
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


async def bulk_distribute_subcategory_assets(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    *,
    subcategory_ids: list[str] | None = None,
    parent_category_id: str | None = None,
    apply_to_all: bool = False,
    count_mode: str = "fixed",
    premium_count: int = 0,
    rewarded_count: int = 0,
    premium_percent: float = 0.0,
    rewarded_percent: float = 0.0,
    normal_frequency: int = 1,
    premium_frequency: int = 1,
    rewarded_frequency: int = 1,
    alternate_paid: bool = False,
) -> dict[str, Any]:
    """Apply tier distribution rules across assets of multiple or all subcategories in a batched DB pass."""
    inst_oid = to_object_id(app_instance_id)

    if count_mode not in ("fixed", "percentage"):
        raise ValidationError(f"Invalid count_mode '{count_mode}'. Must be 'fixed' or 'percentage'.")
    if count_mode == "percentage" and (premium_percent + rewarded_percent >= 100 or premium_percent < 0 or rewarded_percent < 0):
        raise ValidationError("Combined premium and rewarded percentage must be >= 0 and strictly < 100%.")

    # Resolve parent category if specified (also supports setting persistence on that category)
    parent_cat_doc = None
    sub_query: dict[str, Any] = {"app_instance_id": inst_oid, "deleted_at": None}

    if parent_category_id:
        cat_oid = to_object_id(parent_category_id)
        parent_cat_doc = await instance_collection(db, INSTANCE_CATEGORIES).find_one(
            {"app_instance_id": inst_oid, "$or": [{"_id": cat_oid}, {"source_id": cat_oid}], "deleted_at": None}
        )
        if not parent_cat_doc:
            raise NotFoundError("Parent category not found in this app instance")
        cat_keys = _id_variants(parent_cat_doc["_id"]) | _id_variants(parent_cat_doc.get("source_id"))
        sub_query["category_id"] = {"$in": list(cat_keys)}
    elif not apply_to_all:
        sub_oids: list[Any] = []
        for raw_id in subcategory_ids or []:
            if raw_id and str(raw_id).strip():
                sub_oids.append(to_object_id(str(raw_id).strip()))
        if not sub_oids:
            raise ValidationError("Provide subcategory_ids, parent_category_id, or set apply_to_all=True.")
        sub_query["$or"] = [{"_id": {"$in": sub_oids}}, {"source_id": {"$in": sub_oids}}]

    sub_docs = await instance_collection(db, INSTANCE_SUBCATEGORIES).find(
        sub_query,
        {"_id": 1, "source_id": 1, "category_id": 1, "name": 1, "sequence": 1},
    ).sort([("sequence", 1), ("_id", 1)]).to_list(length=None)

    if not sub_docs:
        raise ValidationError("No matching subcategories found in this app instance.")

    # Build category alias index so shared source_id subcategories isolate assets per parent category
    cat_docs = await instance_collection(db, INSTANCE_CATEGORIES).find(
        {"app_instance_id": inst_oid, "deleted_at": None},
        {"_id": 1, "source_id": 1},
    ).to_list(length=None)
    cat_alias_groups: dict[str, set[str]] = {}
    for c in cat_docs:
        group = {str(c["_id"])}
        if c.get("source_id"):
            group.add(str(c["source_id"]))
        for k in group:
            cat_alias_groups.setdefault(k, set()).update(group)

    all_sub_keys: set[Any] = set()
    sub_by_own_key: dict[str, dict[str, Any]] = {}
    subs_by_src_key: dict[str, list[tuple[dict[str, Any], set[str]]]] = defaultdict(list)

    for sub in sub_docs:
        own_id_str = str(sub["_id"])
        sub_by_own_key[own_id_str] = sub
        all_sub_keys.update(_id_variants(sub["_id"]))

        if sub.get("source_id"):
            src_str = str(sub["source_id"])
            all_sub_keys.update(_id_variants(sub["source_id"]))
            raw_cat = str(sub["category_id"]) if sub.get("category_id") is not None else ""
            cat_keys_str = cat_alias_groups.get(raw_cat, {raw_cat} if raw_cat else set())
            subs_by_src_key[src_str].append((sub, cat_keys_str))

    # Single query for all live assets across all targeted subcategories
    dead_ids = await dead_asset_row_ids(db, inst_oid)
    asset_query: dict[str, Any] = {
        "app_instance_id": inst_oid,
        "deleted_at": None,
        "sub_category_id": {"$in": list(all_sub_keys)},
    }
    if dead_ids:
        asset_query["_id"] = {"$nin": dead_ids}

    all_assets = await instance_collection(db, INSTANCE_ASSETS).find(
        asset_query,
        {"_id": 1, "sub_category_id": 1, "category_id": 1, "sequence": 1, "name": 1, "rewarded_credits": 1},
    ).sort([("sequence", 1), ("_id", 1)]).to_list(length=None)

    assets_by_sub_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in all_assets:
        sub_val_str = str(asset.get("sub_category_id") or "")
        if sub_val_str in sub_by_own_key:
            assets_by_sub_id[sub_val_str].append(asset)
        elif sub_val_str in subs_by_src_key:
            asset_cat_str = str(asset.get("category_id") or "")
            for candidate_sub, allowed_cats in subs_by_src_key[sub_val_str]:
                if not allowed_cats or asset_cat_str in allowed_cats:
                    assets_by_sub_id[str(candidate_sub["_id"])].append(asset)

    now = utc_now()
    asset_ops: list[UpdateOne] = []
    sub_ops: list[UpdateOne] = []
    subcategories_summary: list[dict[str, Any]] = []

    updated_subs = 0
    skipped_empty = 0
    clamped_subs = 0
    total_assets_updated = 0
    total_prem = 0
    total_rew = 0
    total_norm = 0

    for sub in sub_docs:
        sub_id_str = str(sub["_id"])
        sub_assets = assets_by_sub_id.get(sub_id_str, [])
        sub_total = len(sub_assets)
        if sub_total == 0:
            skipped_empty += 1
            continue

        eff_prem, eff_rew = resolve_effective_counts(
            total_count=sub_total,
            count_mode=count_mode,
            premium_count=premium_count,
            rewarded_count=rewarded_count,
            premium_percent=premium_percent,
            rewarded_percent=rewarded_percent,
        )
        if count_mode == "fixed" and (eff_prem != premium_count or eff_rew != rewarded_count):
            clamped_subs += 1

        pattern = compute_tier_distribution(
            total_count=sub_total,
            premium_count=eff_prem,
            rewarded_count=eff_rew,
            normal_frequency=normal_frequency,
            premium_frequency=premium_frequency,
            rewarded_frequency=rewarded_frequency,
            alternate_paid=alternate_paid,
        )

        ops, _ = _build_item_tier_ops(sub_assets, pattern, "asset", now)
        asset_ops.extend(ops)

        sub_settings = {
            "target_type": "asset",
            "count_mode": count_mode,
            "premium_count": eff_prem,
            "rewarded_count": eff_rew,
            "premium_percent": premium_percent if count_mode == "percentage" else 0,
            "rewarded_percent": rewarded_percent if count_mode == "percentage" else 0,
            "normal_frequency": normal_frequency,
            "premium_frequency": premium_frequency,
            "rewarded_frequency": rewarded_frequency,
            "alternate_paid": bool(alternate_paid),
            "updated_at": now.isoformat(),
        }
        sub_ops.append(
            UpdateOne(
                {"_id": sub["_id"]},
                {"$set": {"tier_distribution_settings": sub_settings, "updated_at": now}},
            )
        )

        sub_norm = sub_total - eff_prem - eff_rew
        updated_subs += 1
        total_assets_updated += sub_total
        total_prem += eff_prem
        total_rew += eff_rew
        total_norm += sub_norm

        subcategories_summary.append({
            "subcategory_id": sub_id_str,
            "name": sub.get("name") or "",
            "total_assets": sub_total,
            "premium_count": eff_prem,
            "rewarded_count": eff_rew,
            "normal_count": sub_norm,
            "settings": sub_settings,
        })

    if updated_subs == 0:
        raise ValidationError("All targeted subcategories have 0 live assets; nothing to update.")

    if asset_ops:
        await instance_collection(db, INSTANCE_ASSETS).bulk_write(asset_ops, ordered=False)
    if sub_ops:
        await instance_collection(db, INSTANCE_SUBCATEGORIES).bulk_write(sub_ops, ordered=False)

    bulk_settings_doc = {
        "target_type": "bulk_subcategories",
        "count_mode": count_mode,
        "premium_count": premium_count,
        "rewarded_count": rewarded_count,
        "premium_percent": premium_percent if count_mode == "percentage" else 0,
        "rewarded_percent": rewarded_percent if count_mode == "percentage" else 0,
        "normal_frequency": normal_frequency,
        "premium_frequency": premium_frequency,
        "rewarded_frequency": rewarded_frequency,
        "alternate_paid": bool(alternate_paid),
        "updated_at": now.isoformat(),
    }

    if parent_cat_doc is not None:
        await instance_collection(db, INSTANCE_CATEGORIES).update_one(
            {"_id": parent_cat_doc["_id"]},
            {"$set": {"bulk_asset_tier_distribution_settings": bulk_settings_doc, "updated_at": now}},
        )
    elif apply_to_all:
        await db[APP_INSTANCES].update_one(
            {"_id": inst_oid},
            {"$set": {"bulk_asset_tier_distribution_settings": bulk_settings_doc, "updated_at": now}},
        )

    return {
        "success": True,
        "targeted_subcategories_count": len(sub_docs),
        "updated_subcategories_count": updated_subs,
        "skipped_empty_subcategories_count": skipped_empty,
        "clamped_subcategories_count": clamped_subs,
        "total_assets_updated": total_assets_updated,
        "premium_assigned": total_prem,
        "rewarded_assigned": total_rew,
        "normal_assigned": total_norm,
        "settings": bulk_settings_doc,
        "subcategories_summary": subcategories_summary,
    }
