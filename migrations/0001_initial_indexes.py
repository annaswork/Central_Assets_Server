"""Migration 0001: Ensure initial unique, compound, and TTL indexes across all collections."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.indexes import ensure_indexes

MIGRATION_NAME = "0001_initial_indexes"


async def apply(db: AsyncIOMotorDatabase) -> None:
    await ensure_indexes(db)
