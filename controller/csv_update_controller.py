"""Controller for updating database records from CSV data scoped to active filters."""

from collections import defaultdict
import csv
from datetime import datetime, timezone
import itertools
import json
import re
from typing import Any, BinaryIO

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from database.collections import ASSETS, CATEGORIES, SUBCATEGORIES
from utils.csv_utils import iter_csv_rows

# Writes per bulk_write round-trip.
BULK_BATCH_SIZE = 1000
# Detail rows returned to the UI; counts always cover the whole file.
MAX_REPORTED_ROWS = 500


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

    # Tag and string list columns (tags, keywords, labels, badges, etc.)
    is_list_col = (
        col in (
            "tags",
            "tag",
            "keywords",
            "keyword",
            "labels",
            "label",
            "badges",
            "badge",
            "string_list",
            "strings",
        )
        or col.endswith(("_tags", "_list", "_keywords", "_labels"))
    )
    if is_list_col:
        # JSON array structure
        if val_stripped.startswith("[") and val_stripped.endswith("]"):
            try:
                parsed = json.loads(val_stripped)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        # Comma, semicolon, pipe, or newline separated list
        if any(sep in val_stripped for sep in (",", ";", "|", "\n")):
            parts = [
                p.strip()
                for p in re.split(r"[,;|\n]+", val_stripped)
                if p.strip()
            ]
            return parts
        elif val_stripped:
            return [val_stripped]
        return []

    # JSON structures (if payload block or object is passed)
    if (val_stripped.startswith("{") and val_stripped.endswith("}")) or (
        val_stripped.startswith("[") and val_stripped.endswith("]")
    ):
        try:
            return json.loads(val_stripped)
        except Exception:
            try:
                import ast
                parsed = ast.literal_eval(val_stripped)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass

    return val_stripped


async def apply_csv_column_updates(
    db: AsyncIOMotorDatabase,
    collection_name: str,
    content: str | bytes | BinaryIO,
    filter_query: dict[str, Any] | None = None,
    is_asset: bool = False,
) -> dict[str, Any]:
    """Parse CSV rows and update matching records within the filtered dataset.

    Args:
        db: AsyncIOMotorDatabase instance
        collection_name: Name of target collection (categories, subcategories, assets)
        content: Raw CSV string/bytes, or a binary file object (streamed)
        filter_query: Filter dictionary to constrain candidate records (active UI filter)
        is_asset: True if updating the assets collection (handles more_fields)

    Returns:
        Summary dict containing success flag, updated count, skipped count, and details.
    """
    def _fail(message: str, skipped: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "success": False,
            "total_rows": 0,
            "updated_count": 0,
            "skipped_count": len(skipped or []),
            "updated": [],
            "skipped": skipped or [],
            "message": message,
        }

    rows = iter_csv_rows(content)
    try:
        first = next(rows, None)
    except ValueError as e:
        return _fail(f"CSV parse error: {e}", [{"line": 1, "error": str(e)}])
    except csv.Error as e:
        return _fail(f"CSV parse error: {e}", [{"line": 2, "error": str(e)}])

    if first is None:
        return _fail("CSV file contains no data rows.")

    # Verify 'name' column exists
    if "name" not in first[1]:
        return _fail(
            "CSV must include a 'name' column to match records.",
            [{"reason": "Missing 'name' column"}],
        )

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

    updated_count = 0
    skipped_count = 0
    total_rows = 0
    ops: list[UpdateOne] = []
    collection = db[collection_name]

    def _skip(entry: dict[str, Any]) -> None:
        nonlocal skipped_count
        skipped_count += 1
        if len(skipped) < MAX_REPORTED_ROWS:
            skipped.append(entry)

    async def _flush() -> None:
        if ops:
            await collection.bulk_write(ops, ordered=False)
            ops.clear()

    try:
        for line, row in itertools.chain([first], rows):
            total_rows += 1
            name_val = row.get("name", "").strip()
            if not name_val:
                _skip({"line": line, "name": "", "reason": "Missing name value in row"})
                continue

            matching_docs = candidates_by_name.get(name_val.lower())
            if not matching_docs:
                _skip({
                    "line": line,
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
                _skip({
                    "line": line,
                    "name": name_val,
                    "reason": "No valid updatable columns provided in row",
                })
                continue

            update_doc["updated_at"] = now

            for target_doc in matching_docs:
                ops.append(UpdateOne({"_id": target_doc["_id"]}, {"$set": update_doc}))
                updated_count += 1
                if len(updated) < MAX_REPORTED_ROWS:
                    updated.append({
                        "line": line,
                        "id": str(target_doc["_id"]),
                        "name": target_doc.get("name", name_val),
                        "fields": [k for k in update_doc.keys() if k != "updated_at"],
                    })
            if len(ops) >= BULK_BATCH_SIZE:
                await _flush()
    except csv.Error as e:
        await _flush()  # keep rows already processed; report where parsing stopped
        return {
            "success": False,
            "total_rows": total_rows,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "updated": updated,
            "skipped": skipped,
            "message": (
                f"CSV parse error after row {total_rows}: {e}. "
                f"{updated_count} item(s) before that point were updated."
            ),
        }
    await _flush()

    return {
        "success": True,
        "total_rows": total_rows,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "updated": updated,
        "skipped": skipped,
        "truncated": updated_count > len(updated) or skipped_count > len(skipped),
        "message": f"Successfully updated {updated_count} item(s). {skipped_count} item(s) skipped.",
    }
