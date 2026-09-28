"""Overrides and instance settings controller.

STRICT LAYER RULE:
This module operates exclusively on instance_* collections.
It NEVER imports central controllers or CentralRepository.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import (
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
)
from utils.datetimes import utc_now
from utils.errors import NotFoundError, ValidationError
from utils.ids import to_object_id
from utils.sequencing import generate_sequence_reordering

ALLOWED_CATEGORY_OVERRIDES = {"name", "thumbnail_url", "image_url"}
ALLOWED_SUBCATEGORY_OVERRIDES = {"name", "thumbnail_url", "image_url"}
ALLOWED_ASSET_OVERRIDES = {"name", "description", "thumbnail_url", "more_fields"}
BLOCKED_OVERRIDE_KEYS = {
    "category_id",
    "sub_category_id",
    "source_id",
    "created_at",
    "updated_at",
    "deleted_at",
}


async def update_item_settings_and_overrides(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    item_type: str,
    item_id: str,
    is_enabled: bool | None = None,
    sequence: int | None = None,
    is_premium: bool | None = None,
    is_rewarded: bool | None = None,
    rewarded_credits: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update reference settings (is_enabled, sequence, is_premium, is_rewarded, rewarded_credits) and sparse field overrides."""
    inst_oid = to_object_id(app_instance_id)
    ref_oid = to_object_id(item_id)

    col_name = (
        INSTANCE_CATEGORIES
        if item_type == "category"
        else INSTANCE_SUBCATEGORIES if item_type == "subcategory" else INSTANCE_ASSETS
    )
    allowed_overrides = (
        ALLOWED_CATEGORY_OVERRIDES
        if item_type == "category"
        else (
            ALLOWED_SUBCATEGORY_OVERRIDES if item_type == "subcategory" else ALLOWED_ASSET_OVERRIDES
        )
    )

    query = {
        "app_instance_id": inst_oid,
        "$or": [{"_id": ref_oid}, {"source_id": ref_oid}],
        "deleted_at": None,
    }

    doc = await db[col_name].find_one(query)
    if not doc:
        raise NotFoundError(f"Instance {item_type} reference not found")

    set_fields: dict[str, Any] = {"updated_at": utc_now()}
    if is_enabled is not None:
        set_fields["is_enabled"] = bool(is_enabled)
    if sequence is not None:
        set_fields["sequence"] = sequence
    if is_premium is not None and item_type == "asset":
        set_fields["is_premium"] = bool(is_premium)
    if is_rewarded is not None and item_type == "asset":
        set_fields["is_rewarded"] = bool(is_rewarded)
        if is_rewarded and rewarded_credits is None and not doc.get("rewarded_credits"):
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

    await db[col_name].update_one({"_id": doc["_id"]}, {"$set": set_fields})
    updated = await db[col_name].find_one({"_id": doc["_id"]})
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

    col_name = (
        INSTANCE_CATEGORIES
        if item_type == "category"
        else INSTANCE_SUBCATEGORIES if item_type == "subcategory" else INSTANCE_ASSETS
    )

    query = {
        "app_instance_id": inst_oid,
        "$or": [{"_id": ref_oid}, {"source_id": ref_oid}],
        "deleted_at": None,
    }

    doc = await db[col_name].find_one(query)
    if not doc:
        raise NotFoundError(f"Instance {item_type} reference not found")

    if not fields:
        # Reset all overrides
        await db[col_name].update_one(
            {"_id": doc["_id"]},
            {"$set": {"overrides": {}, "updated_at": utc_now()}},
        )
    else:
        # Unset specific keys from the overrides object
        unset_dict = {f"overrides.{f}": "" for f in fields}
        await db[col_name].update_one(
            {"_id": doc["_id"]},
            {"$unset": unset_dict, "$set": {"updated_at": utc_now()}},
        )

    updated = await db[col_name].find_one({"_id": doc["_id"]})
    return updated  # type: ignore


async def reorder_items(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    item_type: str,
    ordered_ids: list[str],
) -> dict[str, Any]:
    """Assign sequence numbers spaced by 10 according to the provided ordered list of IDs."""
    inst_oid = to_object_id(app_instance_id)
    col_name = (
        INSTANCE_CATEGORIES
        if item_type == "category"
        else INSTANCE_SUBCATEGORIES if item_type == "subcategory" else INSTANCE_ASSETS
    )

    reorder_pairs = generate_sequence_reordering(ordered_ids)
    now = utc_now()

    for item_id, seq in reorder_pairs:
        oid = to_object_id(item_id)
        await db[col_name].update_one(
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
    col_name = (
        INSTANCE_CATEGORIES
        if item_type == "category"
        else INSTANCE_SUBCATEGORIES if item_type == "subcategory" else INSTANCE_ASSETS
    )

    set_fields: dict[str, Any] = {"updated_at": utc_now()}
    if is_enabled is not None:
        set_fields["is_enabled"] = is_enabled
    if is_premium is not None and item_type == "asset":
        set_fields["is_premium"] = is_premium

    oids = [to_object_id(i) for i in ids]
    res = await db[col_name].update_many(
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
