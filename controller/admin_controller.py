"""Admin panel view data assembler for Jinja2 templates."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from database.collections import (
    API_KEYS,
    APP_INSTANCES,
    ASSETS,
    CATEGORIES,
    SUBCATEGORIES,
)


async def get_dashboard_counts(db: AsyncIOMotorDatabase) -> dict[str, int]:
    """Retrieve overall asset platform metrics for admin dashboard."""
    cat_count = await db[CATEGORIES].count_documents({"deleted_at": None})
    sub_count = await db[SUBCATEGORIES].count_documents({"deleted_at": None})
    asset_count = await db[ASSETS].count_documents({"deleted_at": None})
    instance_count = await db[APP_INSTANCES].count_documents({})
    active_keys_count = await db[API_KEYS].count_documents({"is_active": True})

    return {
        "categories": cat_count,
        "subcategories": sub_count,
        "assets": asset_count,
        "app_instances": instance_count,
        "active_keys": active_keys_count,
    }
