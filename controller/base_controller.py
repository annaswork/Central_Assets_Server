from datetime import datetime
from typing import Any

from bson import ObjectId

from utils.datetimes import to_iso_z
from utils.responses import page_response


def _serialize_value(val: Any) -> Any:
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, datetime):
        return to_iso_z(val)
    if isinstance(val, list):
        return [_serialize_value(x) for x in val]
    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    return val


def serialize_mongo_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Format MongoDB document by converting _id to id string and removing internal fields."""
    if not doc:
        return None
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d["_id"])
        del d["_id"]

    for k, v in list(d.items()):
        d[k] = _serialize_value(v)

    return d


def serialize_mongo_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format list of MongoDB documents."""
    return [serialize_mongo_doc(doc) for doc in docs if doc is not None]  # type: ignore


def format_page_response(
    items: list[dict[str, Any]], total: int, page: int, page_size: int
) -> dict[str, Any]:
    """Return standard paginated response envelope."""
    serialized = serialize_mongo_docs(items)
    return page_response(items=serialized, total=total, page=page, page_size=page_size)


async def execute_central_bulk_action(
    db: Any,
    collection_name: str,
    ids: list[str],
    action: str,
) -> dict[str, Any]:
    """Execute bulk update actions (enable, disable, set_premium, set_normal) on central collections."""
    from utils.datetimes import utc_now
    from utils.errors import ValidationError
    from utils.ids import to_object_id

    if not ids:
        return {"success": True, "modified_count": 0, "message": "No items selected"}

    update_fields: dict[str, Any] = {"updated_at": utc_now()}
    if action == "enable":
        update_fields["is_enabled"] = True
    elif action == "disable":
        update_fields["is_enabled"] = False
    elif action == "set_premium":
        update_fields["is_premium"] = True
    elif action in ("set_normal", "remove_premium"):
        update_fields["is_premium"] = False
    elif action == "delete":
        update_fields["deleted_at"] = utc_now()
    else:
        raise ValidationError(f"Unsupported bulk action: '{action}'")

    oids = [to_object_id(i) for i in ids if i]
    if not oids:
        return {"success": True, "modified_count": 0, "message": "No valid IDs provided"}

    if action == "delete":
        from database.collections import (
            ASSETS,
            CATEGORIES,
            INSTANCE_ASSETS,
            INSTANCE_CATEGORIES,
            INSTANCE_SUBCATEGORIES,
            SUBCATEGORIES,
        )

        if collection_name == ASSETS:
            from controller.asset_controller import delete_asset_file_from_disk

            cursor = db[collection_name].find({"_id": {"$in": oids}})
            docs = await cursor.to_list(length=len(oids))
            for doc in docs:
                delete_asset_file_from_disk(doc)
            await db[INSTANCE_ASSETS].delete_many({"source_id": {"$in": oids}})

        elif collection_name == SUBCATEGORIES:
            from controller.asset_controller import delete_asset_file_from_disk

            child_assets = (
                await db[ASSETS].find({"sub_category_id": {"$in": oids}}).to_list(length=None)
            )
            child_asset_ids = [c["_id"] for c in child_assets]
            for child in child_assets:
                delete_asset_file_from_disk(child)
            await db[ASSETS].delete_many({"sub_category_id": {"$in": oids}})
            await db[INSTANCE_SUBCATEGORIES].delete_many({"source_id": {"$in": oids}})
            clauses = [{"sub_category_id": {"$in": oids}}]
            if child_asset_ids:
                clauses.append({"source_id": {"$in": child_asset_ids}})
            await db[INSTANCE_ASSETS].delete_many({"$or": clauses} if len(clauses) > 1 else clauses[0])

        elif collection_name == CATEGORIES:
            from controller.asset_controller import delete_asset_file_from_disk

            child_assets = (
                await db[ASSETS].find({"category_id": {"$in": oids}}).to_list(length=None)
            )
            child_asset_ids = [c["_id"] for c in child_assets]
            for child in child_assets:
                delete_asset_file_from_disk(child)

            child_subs = (
                await db[SUBCATEGORIES].find({"category_id": {"$in": oids}}).to_list(length=None)
            )
            child_sub_ids = [s["_id"] for s in child_subs]

            await db[ASSETS].delete_many({"category_id": {"$in": oids}})
            await db[SUBCATEGORIES].delete_many({"category_id": {"$in": oids}})
            await db[INSTANCE_CATEGORIES].delete_many({"source_id": {"$in": oids}})

            sub_clauses = [{"category_id": {"$in": oids}}]
            if child_sub_ids:
                sub_clauses.append({"source_id": {"$in": child_sub_ids}})
            await db[INSTANCE_SUBCATEGORIES].delete_many({"$or": sub_clauses} if len(sub_clauses) > 1 else sub_clauses[0])

            asset_clauses: list[dict[str, Any]] = [{"category_id": {"$in": oids}}]
            if child_sub_ids:
                asset_clauses.append({"sub_category_id": {"$in": child_sub_ids}})
            if child_asset_ids:
                asset_clauses.append({"source_id": {"$in": child_asset_ids}})
            await db[INSTANCE_ASSETS].delete_many({"$or": asset_clauses} if len(asset_clauses) > 1 else asset_clauses[0])

        del_res = await db[collection_name].delete_many({"_id": {"$in": oids}})
        count = del_res.deleted_count
    else:
        upd_res = await db[collection_name].update_many(
            {"_id": {"$in": oids}, "deleted_at": None},
            {"$set": update_fields},
        )
        count = upd_res.modified_count

    action_labels = {
        "enable": "enabled",
        "disable": "disabled",
        "set_premium": "set to premium",
        "set_normal": "premium removed",
        "remove_premium": "premium removed",
        "delete": "deleted",
    }
    label = action_labels.get(action, "updated")

    return {
        "success": True,
        "modified_count": count,
        "action": action,
        "message": f"Successfully {label} {count} item(s)",
    }
