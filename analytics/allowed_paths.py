"""In-memory cache for monitored endpoint route templates."""

import logging
import random
import time
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import MONITORED_ENDPOINTS
from database.connection import get_database

logger = logging.getLogger(__name__)

# Key: (method, path_template) -> dict configuration
_cache: dict[tuple[str, str], dict[str, Any]] = {}
_last_refresh: float = 0.0
_TTL_SECONDS: float = 30.0


async def refresh_allowed_paths(db: AsyncIOMotorDatabase | None = None) -> None:
    """Reload active monitored endpoints from database into cache."""
    global _cache, _last_refresh
    database = db if db is not None else get_database()
    try:
        cursor = database[MONITORED_ENDPOINTS].find({"is_active": True})
        docs = await cursor.to_list(length=1000)

        new_cache: dict[tuple[str, str], dict[str, Any]] = {}
        for doc in docs:
            method = doc["method"].upper()
            template = doc["path_template"]
            new_cache[(method, template)] = doc

        _cache = new_cache
        _last_refresh = time.time()
        logger.debug(f"Refreshed analytics monitored endpoints cache: {len(_cache)} active rules")
    except Exception as exc:
        logger.warning(f"Failed to refresh monitored endpoints cache: {exc}")


async def is_monitored(method: str, path_template: str) -> dict[str, Any] | None:
    """Check if a route template is monitored and passes random sampling rate.

    Returns the endpoint config dict if should record, else None.
    """
    global _last_refresh
    # Periodic background refresh check
    if (time.time() - _last_refresh) > _TTL_SECONDS:
        await refresh_allowed_paths()

    rule = _cache.get((method.upper(), path_template))
    if not rule:
        return None

    sample_rate = float(rule.get("sample_rate", 1.0))
    if sample_rate < 1.0:
        if random.random() > sample_rate:
            return None

    return rule
