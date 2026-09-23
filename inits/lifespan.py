"""Application lifespan management for startup and graceful shutdown."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from analytics.allowed_paths import refresh_allowed_paths
from analytics.recorder import start_analytics_recorder, stop_analytics_recorder
from config.logging_config import setup_logging
from config.paths import ensure_directories_exist
from config.settings import settings
from database.connection import close_database, get_database, ping_database
from database.indexes import create_indexes
from database.seed import seed_database
from database.sync_storage import sync_central_storage_directories

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Execute application startup and graceful shutdown sequences."""
    # 1. Logging and filesystem directories
    setup_logging(settings.LOG_LEVEL)
    ensure_directories_exist()
    logger.info("Initializing Creative Asset Library Platform...")

    # 2. Database connectivity
    db = get_database()
    is_connected = await ping_database()
    if not is_connected:
        logger.error("Failed to connect to MongoDB. Please check MONGODB_URI.")
    else:
        logger.info(f"Connected to MongoDB database: '{settings.MONGODB_DB_NAME}'")

        # 3. Declarative indexes & first-run seeds
        try:
            await create_indexes(db)
            await seed_database(db)
            await sync_central_storage_directories(db)
        except Exception as exc:
            logger.error(f"Error initializing indexes or seeds: {exc}")

        # 4. Analytics cache & background queue drain task
        try:
            await refresh_allowed_paths(db)
            start_analytics_recorder(db)
        except Exception as exc:
            logger.error(f"Error starting analytics recorder: {exc}")

    yield

    # Shutdown sequence
    logger.info("Initiating platform shutdown...")
    try:
        await stop_analytics_recorder(db)
    except Exception as exc:
        logger.warning(f"Error stopping analytics recorder: {exc}")

    await close_database()
    logger.info("Application shutdown complete.")
