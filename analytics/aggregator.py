"""Hourly analytics rollup aggregator computing traffic, error counts, and latency percentiles."""

import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import ANALYTICS_EVENTS, ANALYTICS_HOURLY
from database.connection import get_database

logger = logging.getLogger(__name__)


async def aggregate_hourly_window(
    db: AsyncIOMotorDatabase,
    start_hour: datetime,
    end_hour: datetime,
) -> int:
    """Aggregate raw events for a specific hourly window into analytics_hourly collection.

    Calculates: count, error_count, p50, p95, p99 latency, bytes_out.
    """
    pipeline = [
        {
            "$match": {
                "ts": {"$gte": start_hour, "$lt": end_hour},
            }
        },
        {
            "$group": {
                "_id": {
                    "path_template": "$path_template",
                    "app_instance_id": "$app_instance_id",
                },
                "count": {"$sum": 1},
                "error_count": {"$sum": {"$cond": [{"$gte": ["$status_code", 400]}, 1, 0]}},
                "durations": {"$push": "$duration_ms"},
                "bytes_out": {"$sum": "$response_bytes"},
            }
        },
    ]

    cursor = db[ANALYTICS_EVENTS].aggregate(pipeline)
    results = await cursor.to_list(length=None)

    rollup_docs = []
    for item in results:
        durations = sorted(item.get("durations", []))
        n = len(durations)
        p50 = durations[int(n * 0.50)] if n > 0 else 0.0
        p95 = durations[int(n * 0.95)] if n > 0 else 0.0
        p99 = durations[int(n * 0.99)] if n > 0 else 0.0

        rollup_docs.append(
            {
                "path_template": item["_id"]["path_template"],
                "app_instance_id": item["_id"]["app_instance_id"],
                "hour": start_hour,
                "count": item["count"],
                "error_count": item["error_count"],
                "p50": round(float(p50), 2),
                "p95": round(float(p95), 2),
                "p99": round(float(p99), 2),
                "bytes_out": item["bytes_out"],
            }
        )

    if rollup_docs:
        for doc in rollup_docs:
            await db[ANALYTICS_HOURLY].update_one(
                {
                    "path_template": doc["path_template"],
                    "app_instance_id": doc["app_instance_id"],
                    "hour": doc["hour"],
                },
                {"$set": doc},
                upsert=True,
            )
        logger.info(
            f"Aggregated {len(rollup_docs)} hourly rollups for window {start_hour} to {end_hour}"
        )

    return len(rollup_docs)


async def run_previous_hour_rollup(db: AsyncIOMotorDatabase | None = None) -> None:
    """Convenience method to compute rollups for the preceding completed hour."""
    database = db if db is not None else get_database()
    now = datetime.now(timezone.utc)
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)
    previous_hour_start = current_hour_start - timedelta(hours=1)
    await aggregate_hourly_window(database, previous_hour_start, current_hour_start)
