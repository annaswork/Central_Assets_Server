"""Motor async client singleton and database dependency."""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config.settings import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    """Return the global Motor client instance, creating it if needed."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URI)
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """Return the global Motor database instance."""
    global _database
    if _database is None:
        client = get_client()
        _database = client[settings.MONGODB_DB_NAME]
    return _database


def set_database(db: AsyncIOMotorDatabase | None) -> None:
    """Explicitly set or override the active database instance (e.g. for testing)."""
    global _database
    _database = db


async def ping_database() -> bool:
    """Perform a ping command against the database to verify connectivity."""
    try:
        db = get_database()
        await db.command("ping")
        return True
    except Exception as exc:
        logger.error(f"Database ping failed: {exc}")
        return False


async def close_database() -> None:
    """Close the global client connection."""
    global _client, _database
    if _client is not None:
        _client.close()
        _client = None
        _database = None
        logger.info("MongoDB client closed")
