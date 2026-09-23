"""Named collection accessors — no string literals elsewhere."""

from typing import Final

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

# Central collections
CATEGORIES: Final[str] = "categories"
SUBCATEGORIES: Final[str] = "subcategories"
ASSETS: Final[str] = "assets"

CENTRAL_COLLECTIONS: Final[set[str]] = {CATEGORIES, SUBCATEGORIES, ASSETS}

# Instance collections
APP_INSTANCES: Final[str] = "app_instances"
INSTANCE_CATEGORIES: Final[str] = "instance_categories"
INSTANCE_SUBCATEGORIES: Final[str] = "instance_subcategories"
INSTANCE_ASSETS: Final[str] = "instance_assets"

INSTANCE_CONTENT_COLLECTIONS: Final[set[str]] = {
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    INSTANCE_ASSETS,
}

# Authorization, Admin & Manager
API_KEYS: Final[str] = "api_keys"
ADMIN_USERS: Final[str] = "admin_users"
MANAGERS: Final[str] = "managers"
APP_INSTANCE_ACCESS: Final[str] = "app_instance_access"
APP_INSTANCE_ACCESS_REQUESTS: Final[str] = "app_instance_access_requests"
MESSAGES: Final[str] = "messages"

# Analytics
MONITORED_ENDPOINTS: Final[str] = "monitored_endpoints"
ANALYTICS_EVENTS: Final[str] = "analytics_events"
ANALYTICS_HOURLY: Final[str] = "analytics_hourly"

# Migrations
MIGRATIONS: Final[str] = "_migrations"


def get_collection(db: AsyncIOMotorDatabase, name: str) -> AsyncIOMotorCollection:
    """Return a typed collection from database by canonical name."""
    return db[name]
