"""Analytics controller managing monitored endpoints configuration and dashboard data."""

from datetime import datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from analytics.allowed_paths import refresh_allowed_paths
from analytics.reporter import (
    delete_analytics_record,
    delete_error_analytics,
    export_analytics_csv,
    get_analytics_event_details,
    get_analytics_summary,
    get_error_analytics,
)
from controller.base_controller import serialize_mongo_doc, serialize_mongo_docs
from database.collections import ANALYTICS_EVENTS, MONITORED_ENDPOINTS
from database.models.analytics import (
    MonitoredEndpointCreate,
    MonitoredEndpointUpdate,
)
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError
from utils.ids import to_object_id


async def list_monitored_endpoints(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """List all monitored endpoint route templates."""
    cursor = db[MONITORED_ENDPOINTS].find({}).sort([("method", 1), ("path_template", 1)])
    docs = await cursor.to_list(length=1000)
    return serialize_mongo_docs(docs)


async def create_monitored_endpoint(
    db: AsyncIOMotorDatabase, data: MonitoredEndpointCreate
) -> dict[str, Any]:
    """Add a new route template to the monitoring list."""
    method_upper = data.method.strip().upper()
    template_clean = data.path_template.strip()

    existing = await db[MONITORED_ENDPOINTS].find_one(
        {
            "method": method_upper,
            "path_template": template_clean,
        }
    )
    if existing:
        raise ConflictError(
            f"Route template '{method_upper} {template_clean}' is already monitored"
        )

    now = utc_now()
    doc = {
        "method": method_upper,
        "path_template": template_clean,
        "is_active": data.is_active,
        "sample_rate": data.sample_rate,
        "retain_days": data.retain_days,
        "notes": data.notes.strip(),
        "created_at": now,
        "updated_at": now,
    }
    res = await db[MONITORED_ENDPOINTS].insert_one(doc)
    doc["_id"] = res.inserted_id

    # Refresh in-memory cache
    await refresh_allowed_paths(db)
    return serialize_mongo_doc(doc)  # type: ignore


async def update_monitored_endpoint(
    db: AsyncIOMotorDatabase, endpoint_id: str, data: MonitoredEndpointUpdate
) -> dict[str, Any]:
    """Update settings for a monitored endpoint."""
    oid = to_object_id(endpoint_id)
    existing = await db[MONITORED_ENDPOINTS].find_one({"_id": oid})
    if not existing:
        raise NotFoundError("Monitored endpoint not found")

    update_fields: dict[str, Any] = {}
    if data.is_active is not None:
        update_fields["is_active"] = data.is_active
    if data.sample_rate is not None:
        update_fields["sample_rate"] = data.sample_rate
    if data.retain_days is not None:
        update_fields["retain_days"] = data.retain_days
    if data.notes is not None:
        update_fields["notes"] = data.notes.strip()

    if update_fields:
        update_fields["updated_at"] = utc_now()
        await db[MONITORED_ENDPOINTS].update_one({"_id": oid}, {"$set": update_fields})
        await refresh_allowed_paths(db)

    updated = await db[MONITORED_ENDPOINTS].find_one({"_id": oid})
    return serialize_mongo_doc(updated)  # type: ignore


async def delete_monitored_endpoint(db: AsyncIOMotorDatabase, endpoint_id: str) -> dict[str, Any]:
    """Remove a route template from active monitoring."""
    oid = to_object_id(endpoint_id)
    res = await db[MONITORED_ENDPOINTS].delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise NotFoundError("Monitored endpoint not found")

    await refresh_allowed_paths(db)
    return {"success": True, "deleted_endpoint_id": str(oid)}


async def get_dashboard_summary(
    db: AsyncIOMotorDatabase,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    app_instance_id: str | None = None,
) -> dict[str, Any]:
    """Fetch complete dashboard metrics including per-endpoint breakdown."""
    raw = await get_analytics_summary(
        db, from_dt=from_dt, to_dt=to_dt, app_instance_id=app_instance_id
    )

    # Count active monitored endpoints
    monitored_count = await db[MONITORED_ENDPOINTS].count_documents({"is_active": True})

    # Build per-endpoint breakdown from raw events (last 24h by default)
    now = datetime.now(timezone.utc)
    end = to_dt or now
    start = from_dt or (end - timedelta(hours=24))

    match_filter: dict[str, Any] = {"ts": {"$gte": start, "$lte": end}}
    if app_instance_id:
        match_filter["app_instance_id"] = app_instance_id

    endpoint_pipeline = [
        {"$match": match_filter},
        {
            "$group": {
                "_id": {"method": "$method", "path_template": "$path_template"},
                "hits": {"$sum": 1},
                "errors": {"$sum": {"$cond": [{"$gte": ["$status_code", 400]}, 1, 0]}},
                "avg_latency_ms": {"$avg": "$duration_ms"},
            }
        },
        {"$sort": {"hits": -1}},
        {"$limit": 100},
    ]

    endpoint_docs = await db[ANALYTICS_EVENTS].aggregate(endpoint_pipeline).to_list(100)
    endpoint_stats = [
        {
            "method": doc["_id"]["method"],
            "path_template": doc["_id"]["path_template"],
            "hits": doc["hits"],
            "errors": doc["errors"],
            "avg_latency_ms": round(float(doc.get("avg_latency_ms", 0.0)), 1),
        }
        for doc in endpoint_docs
    ]

    error_analytics = await get_error_analytics(
        db, from_dt=from_dt, to_dt=to_dt, app_instance_id=app_instance_id
    )

    return {
        "total_events": raw.get("total_requests", 0),
        "monitored_endpoints_count": monitored_count,
        "avg_latency_ms": raw.get("avg_duration_ms", 0.0),
        "error_rate": raw.get("error_rate", 0.0),
        "total_errors": raw.get("total_errors", 0),
        "total_bytes": raw.get("total_bytes", 0),
        "time_range": raw.get("time_range", {}),
        "endpoint_stats": endpoint_stats,
        "error_analytics": error_analytics,
    }


async def get_dashboard_csv(
    db: AsyncIOMotorDatabase,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    app_instance_id: str | None = None,
) -> str:
    """Fetch CSV export string."""
    return await export_analytics_csv(
        db, from_dt=from_dt, to_dt=to_dt, app_instance_id=app_instance_id
    )


async def get_analytics_event_by_id(
    db: AsyncIOMotorDatabase,
    event_id: str,
    allowed_instance_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve details for a single analytics event with scope enforcement."""
    return await get_analytics_event_details(
        db, event_id=event_id, allowed_instance_ids=allowed_instance_ids
    )


async def delete_analytics_event(
    db: AsyncIOMotorDatabase,
    event_id: str,
    allowed_instance_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Delete a single analytics event record with optional scope check."""
    deleted = await delete_analytics_record(
        db, event_id=event_id, allowed_instance_ids=allowed_instance_ids
    )
    return {"success": deleted, "deleted_id": event_id}


async def clear_analytics_errors(
    db: AsyncIOMotorDatabase,
    app_instance_ids: list[str] | None = None,
    hours: int | None = None,
) -> dict[str, Any]:
    """Bulk delete error analytics records."""
    count = await delete_error_analytics(
        db, app_instance_ids=app_instance_ids, hours=hours
    )
    return {"success": True, "deleted_count": count}

