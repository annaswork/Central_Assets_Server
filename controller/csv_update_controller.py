"""Controller for updating database records from CSV data scoped to active filters."""

from collections import defaultdict
from datetime import datetime, timezone
import json
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import ASSETS, CATEGORIES, SUBCATEGORIES
from utils.csv_utils import parse_csv_rows


def _convert_value(col: str, val: str) -> Any:
    """Convert string CSV cell values to appropriate Python types."""
    val_stripped = val.strip()

    # Boolean columns
    if col in (
        "is_enabled",
        "is_active",
        "is_premium",
        "premium",
        "enabled",
        "active",
    ):
        lower = val_stripped.lower()
        if lower in ("true", "1", "yes", "y", "enabled", "active"):
            return True
        if lower in ("false", "0", "no", "n", "disabled", "inactive"):
            return False
        return bool(val_stripped)

    # Integer columns
    if col in ("views", "downloads", "sequence", "order", "sort_order"):
        try:
            return int(val_stripped)
        except ValueError:
            pass

    # JSON structures (if payload block or object is passed)
    if (val_stripped.startswith("{") and val_stripped.endswith("}")) or (
        val_stripped.startswith("[") and val_stripped.endswith("]")
    ):
        try:
            return json.loads(val_stripped)
        except Exception:
            pass

    return val_stripped


async def apply_csv_column_updates(
    db: AsyncIOMotorDatabase,
    collection_name: str,
    content: str | bytes,
    filter_query: dict[str, Any] | None = None,
    is_asset: bool = False,
) -> dict[str, Any]:
    """Parse CSV rows and update matching records within the filtered dataset.

    Args:
        db: AsyncIOMotorDatabase instance
        collection_name: Name of target collection (categories, subcategories, assets)
        content: Raw CSV string or bytes
        filter_query: Filter dictionary to constrain candidate records (active UI filter)
        is_asset: True if updating the assets collection (handles more_fields)

    Returns:
        Summary dict containing success flag, updated count, skipped count, and details.
    """
    rows, errors = parse_csv_rows(content)
    if errors:
        return {
            "success": False,
            "total_rows": 0,
            "updated_count": 0,
            "skipped_count": len(errors),
            "updated": [],
            "skipped": errors,
            "message": f"CSV parse error: {errors[0].get('error', 'Invalid CSV format')}",
        }

    if not rows:
        return {
            "success": False,
            "total_rows": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "updated": [],
            "skipped": [],
            "message": "CSV file contains no data rows.",
        }

    # Verify 'name' column exists
    first_row = rows[0]
    if "name" not in first_row:
        return {
            "success": False,
            "total_rows": len(rows),
            "updated_count": 0,
            "skipped_count": len(rows),
            "updated": [],
            "skipped": [{"reason": "Missing 'name' column"}],
            "message": "CSV must include a 'name' column to match records.",
        }

    # Query only records in the active filtered dataset
    base_query: dict[str, Any] = {"deleted_at": None}
    if filter_query:
        base_query.update(filter_query)

    cursor = db[collection_name].find(base_query)
    candidates_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    async for doc in cursor:
        doc_name = str(doc.get("name") or "").strip().lower()
        if doc_name:
            candidates_by_name[doc_name].append(doc)

    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    # Map aliases to standard schema attributes
    alias_map = {
        "is_active": "is_enabled",
        "active": "is_enabled",
        "enabled": "is_enabled",
        "premium": "is_premium",
        "thumbnail": "thumbnail_url",
        "image": "image_url",
    }

    # Standard root fields per collection
    root_fields = {
        CATEGORIES: {"name", "thumbnail_url", "image_url", "is_enabled", "is_premium"},
        SUBCATEGORIES: {
            "name",
            "category_id",
            "thumbnail_url",
            "image_url",
            "is_enabled",
            "is_premium",
        },
        ASSETS: {
            "name",
            "description",
            "category_id",
            "sub_category_id",
            "folder_name",
            "thumbnail_url",
            "is_enabled",
            "is_premium",
            "views",
            "downloads",
        },
    }.get(collection_name, set())

    now = datetime.now(timezone.utc)

    for idx, row in enumerate(rows, start=1):
        name_val = row.get("name", "").strip()
        if not name_val:
            skipped.append({
                "line": idx + 1,
                "name": "",
                "reason": "Missing name value in row",
            })
            continue

        name_key = name_val.lower()
        matching_docs = candidates_by_name.get(name_key)
        if not matching_docs:
            skipped.append({
                "line": idx + 1,
                "name": name_val,
                "reason": "No match found in currently filtered data",
            })
            continue

        # Prepare update dict
        update_doc: dict[str, Any] = {}
        for col_name, raw_val in row.items():
            if col_name in ("name", "id", "_id"):
                continue  # 'name' was used for matching; do not overwrite unless explicit

            canon_name = alias_map.get(col_name, col_name)
            typed_val = _convert_value(canon_name, raw_val)

            if is_asset and canon_name not in root_fields:
                # Custom attribute -> place under more_fields.<column>
                update_doc[f"more_fields.{canon_name}"] = typed_val
            else:
                update_doc[canon_name] = typed_val

        if not update_doc:
            skipped.append({
                "line": idx + 1,
                "name": name_val,
                "reason": "No valid updatable columns provided in row",
            })
            continue

        update_doc["updated_at"] = now

        for target_doc in matching_docs:
            await db[collection_name].update_one(
                {"_id": target_doc["_id"]},
                {"$set": update_doc},
            )
            updated.append({
                "line": idx + 1,
                "id": str(target_doc["_id"]),
                "name": target_doc.get("name", name_val),
                "fields": [k for k in update_doc.keys() if k != "updated_at"],
            })

    return {
        "success": True,
        "total_rows": len(rows),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "updated": updated,
        "skipped": skipped,
        "message": f"Successfully updated {len(updated)} item(s). {len(skipped)} item(s) skipped.",
    }
