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
