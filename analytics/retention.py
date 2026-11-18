"""Retention and TTL policy verification for raw analytics data."""

import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import ANALYTICS_EVENTS, MONITORED_ENDPOINTS

logger = logging.getLogger(__name__)


async def prune_events_by_custom_retention(db: AsyncIOMotorDatabase) -> int:
    """Prune raw events that have exceeded per-endpoint retain_days setting.

    Supplement to the standard MongoDB TTL index for endpoints with custom retention periods.
    """
    endpoints_cursor = db[MONITORED_ENDPOINTS].find({"is_active": True})
    endpoints = await endpoints_cursor.to_list(1000)

    total_pruned = 0
    now = datetime.now(timezone.utc)

    for ep in endpoints:
        retain_days = int(ep.get("retain_days", 30))
        cutoff = now - timedelta(days=retain_days)
        res = await db[ANALYTICS_EVENTS].delete_many(
            {
                "path_template": ep["path_template"],
                "ts": {"$lt": cutoff},
            }
        )
        total_pruned += res.deleted_count

    if total_pruned > 0:
        logger.info(
            f"Pruned {total_pruned} expired analytics events matching custom retention rules"
        )

    return total_pruned
