"""Atomic views and downloads tracking for instance assets."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import INSTANCE_ASSETS
from utils.errors import NotFoundError
from utils.ids import to_object_id


async def increment_asset_counter(
    db: AsyncIOMotorDatabase,
    app_instance_id: str,
    asset_id: str,
    event_type: str,
) -> dict[str, int]:
    """Atomically increment views or downloads counter on the instance asset document."""
    inst_oid = to_object_id(app_instance_id)
    asset_oid = to_object_id(asset_id)

    field = "views" if event_type.lower() == "view" else "downloads"

    # Match by either reference row _id or source_id
    query = {
        "app_instance_id": inst_oid,
        "$or": [{"_id": asset_oid}, {"source_id": asset_oid}],
        "deleted_at": None,
    }

    res = await db[INSTANCE_ASSETS].find_one_and_update(
        query,
        {"$inc": {field: 1}},
        projection={"views": 1, "downloads": 1},
        return_document=True,
    )

    if not res:
        raise NotFoundError("Referenced asset not found in this app instance")

    try:
        from analytics.recorder import enqueue_analytics_event
        from utils.datetimes import utc_now

        enqueue_analytics_event(
            {
                "path_template": "/api/v1/instance/{id}/assets/{assetId}/track",
                "method": "POST",
                "status_code": 200,
                "duration_ms": 0.0,
                "app_instance_id": str(app_instance_id),
                "asset_id": str(asset_id),
                "event_type": event_type.lower(),
                "ts": utc_now(),
            }
        )
    except Exception:
        pass

    return {
        "views": res.get("views", 0),
        "downloads": res.get("downloads", 0),
    }
