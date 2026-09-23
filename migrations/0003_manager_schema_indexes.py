"""Migration 0003: Create manager, instance access, requests, and messaging indexes."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.indexes import ensure_indexes

MIGRATION_NAME = "0003_manager_schema_indexes"


async def apply(db: AsyncIOMotorDatabase) -> None:
    """Apply new manager indexes and ensure schema constraints."""
    await ensure_indexes(db)
