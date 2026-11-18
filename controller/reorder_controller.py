"""Controller for central library reordering of categories, subcategories, and assets."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from controller.base_controller import serialize_mongo_doc
from database.collections import ASSETS, CATEGORIES, SUBCATEGORIES
from utils.datetimes import utc_now
from utils.errors import ValidationError
from utils.ids import to_object_id
from utils.sequencing import generate_sequence_reordering


def _resolve_collection(item_type: str) -> str:
    norm = (item_type or "").strip().lower()
    if norm in ("category", "categories"):
        return CATEGORIES
    elif norm in ("subcategory", "subcategories"):
        return SUBCATEGORIES
    elif norm in ("asset", "assets"):
        return ASSETS
    raise ValidationError(
        f"Invalid item_type '{item_type}'. Must be 'category', 'subcategory', or 'asset'."
    )


async def get_reorder_items(
    db: AsyncIOMotorDatabase,
    item_type: str,
    category_id: str | None = None,
    sub_category_id: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve items of the specified type within optional filter scope, ordered by sequence."""
    col_name = _resolve_collection(item_type)
    query: dict[str, Any] = {"deleted_at": None}

    if col_name == SUBCATEGORIES:
        if category_id and category_id.strip():
            cat_oid = to_object_id(category_id.strip())
            query["$or"] = [{"category_id": cat_oid}, {"category_id": str(cat_oid)}]
    elif col_name == ASSETS:
        if sub_category_id and sub_category_id.strip():
            sub_oid = to_object_id(sub_category_id.strip())
            query["$or"] = [{"sub_category_id": sub_oid}, {"sub_category_id": str(sub_oid)}]
        elif category_id and category_id.strip():
            cat_oid = to_object_id(category_id.strip())
            query["$or"] = [{"category_id": cat_oid}, {"category_id": str(cat_oid)}]

    cursor = db[col_name].find(query).sort([("sequence", 1), ("created_at", 1), ("_id", 1)])
    raw_docs = await cursor.to_list(length=1000)

    results: list[dict[str, Any]] = []
    for idx, doc in enumerate(raw_docs):
        serialized = serialize_mongo_doc(doc)
        # Ensure sequence is populated
        seq = serialized.get("sequence")
        if seq is None:
            seq = idx + 1
            serialized["sequence"] = seq
        results.append(
            {
                "id": serialized["id"],
                "name": serialized.get("name", ""),
                "sequence": seq,
                "thumbnail_url": serialized.get("thumbnail_url")
                or serialized.get("image_url")
                or "",
                "is_enabled": serialized.get("is_enabled", True),
                "is_premium": serialized.get("is_premium", False),
                "folder_name": serialized.get("folder_name", ""),
                "category_id": str(serialized.get("category_id", "")),
                "sub_category_id": str(serialized.get("sub_category_id", "")),
            }
        )

    return results


async def reorder_central_items(
    db: AsyncIOMotorDatabase,
    item_type: str,
    ordered_ids: list[str],
) -> dict[str, Any]:
    """Assign sequence numbers spaced by 10 according to the provided ordered list of IDs."""
    col_name = _resolve_collection(item_type)
    if not ordered_ids:
        return {"success": True, "reordered_count": 0, "item_type": item_type}

    reorder_pairs = generate_sequence_reordering(ordered_ids)
    now = utc_now()

    for item_id, seq in reorder_pairs:
        try:
            oid = to_object_id(item_id)
            await db[col_name].update_one(
                {"_id": oid, "deleted_at": None},
                {"$set": {"sequence": seq, "updated_at": now}},
            )
        except Exception:
            pass

    return {
        "success": True,
        "reordered_count": len(reorder_pairs),
        "item_type": item_type,
    }
