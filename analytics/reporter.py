"""Query layer for analytics dashboards, aggregations, and CSV exports."""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import ANALYTICS_EVENTS, ANALYTICS_HOURLY


async def get_analytics_summary(
    db: AsyncIOMotorDatabase,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    app_instance_id: str | None = None,
) -> dict[str, Any]:
    """Return traffic summary. Uses raw events if window <= 24h, else uses hourly rollups."""
    now = datetime.now(timezone.utc)
    end = to_dt or now
    start = from_dt or (end - timedelta(hours=24))

    match_filter: dict[str, Any] = {}
    if app_instance_id:
        match_filter["app_instance_id"] = app_instance_id

    # If range is within 24 hours, query raw events
    if (end - start) <= timedelta(hours=24):
        match_filter["ts"] = {"$gte": start, "$lte": end}
        pipeline = [
            {"$match": match_filter},
            {
                "$group": {
                    "_id": None,
                    "total_requests": {"$sum": 1},
                    "total_errors": {"$sum": {"$cond": [{"$gte": ["$status_code", 400]}, 1, 0]}},
                    "avg_duration": {"$avg": "$duration_ms"},
                    "total_bytes": {"$sum": "$response_bytes"},
                }
            },
        ]
        res = await db[ANALYTICS_EVENTS].aggregate(pipeline).to_list(1)
    else:
        match_filter["hour"] = {"$gte": start, "$lte": end}
        pipeline = [
            {"$match": match_filter},
            {
                "$group": {
                    "_id": None,
                    "total_requests": {"$sum": "$count"},
                    "total_errors": {"$sum": "$error_count"},
                    "avg_duration": {"$avg": "$p50"},
                    "total_bytes": {"$sum": "$bytes_out"},
                }
            },
        ]
        res = await db[ANALYTICS_HOURLY].aggregate(pipeline).to_list(1)

    if not res:
        return {
            "total_requests": 0,
            "total_errors": 0,
            "error_rate": 0.0,
            "avg_duration_ms": 0.0,
            "total_bytes": 0,
            "time_range": {"from": start.isoformat(), "to": end.isoformat()},
        }

    stats = res[0]
    total_reqs = stats.get("total_requests", 0)
    total_errs = stats.get("total_errors", 0)
    error_rate = round((total_errs / total_reqs) * 100.0, 2) if total_reqs > 0 else 0.0

    return {
        "total_requests": total_reqs,
        "total_errors": total_errs,
        "error_rate": error_rate,
        "avg_duration_ms": round(float(stats.get("avg_duration", 0.0)), 2),
        "total_bytes": stats.get("total_bytes", 0),
        "time_range": {"from": start.isoformat(), "to": end.isoformat()},
    }


async def export_analytics_csv(
    db: AsyncIOMotorDatabase,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    app_instance_id: str | None = None,
) -> str:
    """Generate CSV string of hourly metrics for download."""
    now = datetime.now(timezone.utc)
    end = to_dt or now
    start = from_dt or (end - timedelta(days=7))

    match_filter: dict[str, Any] = {"hour": {"$gte": start, "$lte": end}}
    if app_instance_id:
        match_filter["app_instance_id"] = app_instance_id

    cursor = db[ANALYTICS_HOURLY].find(match_filter).sort("hour", -1)
    docs = await cursor.to_list(5000)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "hour",
            "path_template",
            "app_instance_id",
            "requests_count",
            "error_count",
            "p50_latency_ms",
            "p95_latency_ms",
            "p99_latency_ms",
            "bytes_transferred",
        ]
    )

    for doc in docs:
        writer.writerow(
            [
                doc["hour"].isoformat(),
                doc.get("path_template", ""),
                doc.get("app_instance_id") or "unbound",
                doc.get("count", 0),
                doc.get("error_count", 0),
                doc.get("p50", 0.0),
                doc.get("p95", 0.0),
                doc.get("p99", 0.0),
                doc.get("bytes_out", 0),
            ]
        )

    return output.getvalue()


async def get_error_analytics(
    db: AsyncIOMotorDatabase,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    app_instance_id: str | None = None,
    app_instance_ids: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Retrieve detailed error analytics, breakdown by reason/code, and recent error events."""
    now = datetime.now(timezone.utc)
    end = to_dt or now
    start = from_dt or (end - timedelta(hours=24))

    match_filter: dict[str, Any] = {
        "status_code": {"$gte": 400},
        "ts": {"$gte": start, "$lte": end},
    }

    if app_instance_ids is not None:
        match_filter["app_instance_id"] = {"$in": app_instance_ids}
    elif app_instance_id:
        match_filter["app_instance_id"] = app_instance_id

    # 1. Total errors in window
    total_errors = await db[ANALYTICS_EVENTS].count_documents(match_filter)

    # 2. Reasons and status breakdown pipeline
    reasons_pipeline = [
        {"$match": match_filter},
        {
            "$group": {
                "_id": {
                    "status_code": "$status_code",
                    "error_code": "$error_code",
                    "error_reason": "$error_reason",
                },
                "count": {"$sum": 1},
                "latest_ts": {"$max": "$ts"},
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 25},
    ]

    reasons_docs = await db[ANALYTICS_EVENTS].aggregate(reasons_pipeline).to_list(25)
    reasons_breakdown = [
        {
            "status_code": doc["_id"].get("status_code", 500),
            "error_code": doc["_id"].get("error_code") or f"HTTP_{doc['_id'].get('status_code', 500)}",
            "error_reason": doc["_id"].get("error_reason") or "No description recorded",
            "count": doc.get("count", 0),
            "latest_ts": doc["latest_ts"].strftime("%Y-%m-%d %H:%M:%S UTC")
            if isinstance(doc.get("latest_ts"), datetime)
            else str(doc.get("latest_ts", "")),
        }
        for doc in reasons_docs
    ]

    # 3. Status breakdown counts
    status_counts: dict[str, int] = {}
    for doc in reasons_docs:
        sc = str(doc["_id"].get("status_code", 500))
        status_counts[sc] = status_counts.get(sc, 0) + doc.get("count", 0)

    # 4. Recent error event logs
    cursor = db[ANALYTICS_EVENTS].find(match_filter).sort("ts", -1).limit(limit)
    error_docs = await cursor.to_list(limit)

    recent_errors = []
    for doc in error_docs:
        ts_val = doc.get("ts")
        ts_display = (
            ts_val.strftime("%Y-%m-%d %H:%M:%S UTC")
            if isinstance(ts_val, datetime)
            else str(ts_val or "")
        )
        recent_errors.append(
            {
                "id": str(doc["_id"]),
                "ts": ts_display,
                "path_template": doc.get("path_template", ""),
                "method": doc.get("method", "GET"),
                "status_code": doc.get("status_code", 500),
                "duration_ms": doc.get("duration_ms", 0.0),
                "api_key_id": doc.get("api_key_id"),
                "app_instance_id": doc.get("app_instance_id"),
                "asset_id": doc.get("asset_id"),
                "event_type": doc.get("event_type"),
                "country": doc.get("country"),
                "platform": doc.get("platform"),
                "app_version": doc.get("app_version"),
                "error_code": doc.get("error_code") or f"HTTP_{doc.get('status_code', 500)}",
                "error_reason": doc.get("error_reason") or "Unspecified error",
                "error_details": doc.get("error_details"),
            }
        )

    return {
        "total_errors": total_errors,
        "recent_errors": recent_errors,
        "reasons_breakdown": reasons_breakdown,
        "status_counts": status_counts,
        "time_range": {"from": start.isoformat(), "to": end.isoformat()},
    }


async def get_analytics_event_details(
    db: AsyncIOMotorDatabase,
    event_id: str,
    allowed_instance_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve full detail for a single analytics event document."""
    from utils.errors import ForbiddenError, NotFoundError
    from utils.ids import to_object_id

    oid = to_object_id(event_id)
    doc = await db[ANALYTICS_EVENTS].find_one({"_id": oid})
    if not doc:
        raise NotFoundError(f"Analytics event '{event_id}' not found")

    if allowed_instance_ids is not None:
        inst_id = doc.get("app_instance_id")
        if not inst_id or inst_id not in allowed_instance_ids:
            raise ForbiddenError("You do not have permission to view this analytics record")

    ts_val = doc.get("ts")
    ts_display = (
        ts_val.strftime("%Y-%m-%d %H:%M:%S UTC")
        if isinstance(ts_val, datetime)
        else str(ts_val or "")
    )

    return {
        "id": str(doc["_id"]),
        "ts": ts_display,
        "path_template": doc.get("path_template", ""),
        "method": doc.get("method", "GET"),
        "status_code": doc.get("status_code", 500),
        "duration_ms": doc.get("duration_ms", 0.0),
        "api_key_id": doc.get("api_key_id"),
        "app_instance_id": doc.get("app_instance_id"),
        "asset_id": doc.get("asset_id"),
        "event_type": doc.get("event_type"),
        "country": doc.get("country"),
        "platform": doc.get("platform"),
        "app_version": doc.get("app_version"),
        "request_bytes": doc.get("request_bytes", 0),
        "response_bytes": doc.get("response_bytes", 0),
        "error_code": doc.get("error_code"),
        "error_reason": doc.get("error_reason"),
        "error_details": doc.get("error_details"),
    }


async def delete_analytics_record(
    db: AsyncIOMotorDatabase,
    event_id: str,
    allowed_instance_ids: list[str] | None = None,
) -> bool:
    """Delete a single analytics event record by ID with manager permission check."""
    from utils.errors import ForbiddenError, NotFoundError
    from utils.ids import to_object_id

    oid = to_object_id(event_id)
    doc = await db[ANALYTICS_EVENTS].find_one({"_id": oid})
    if not doc:
        raise NotFoundError(f"Analytics event '{event_id}' not found")

    if allowed_instance_ids is not None:
        inst_id = doc.get("app_instance_id")
        if not inst_id or inst_id not in allowed_instance_ids:
            raise ForbiddenError("You do not have permission to delete this analytics record")

    res = await db[ANALYTICS_EVENTS].delete_one({"_id": oid})
    return res.deleted_count > 0


async def delete_error_analytics(
    db: AsyncIOMotorDatabase,
    app_instance_ids: list[str] | None = None,
    hours: int | None = None,
) -> int:
    """Purge error analytics records matching scope and optional window."""
    query: dict[str, Any] = {"status_code": {"$gte": 400}}

    if app_instance_ids is not None:
        query["app_instance_id"] = {"$in": app_instance_ids}

    if hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        query["ts"] = {"$gte": cutoff}

    res = await db[ANALYTICS_EVENTS].delete_many(query)
    return res.deleted_count
