"""Declarative index definitions applied at application startup."""

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel
from pymongo.collation import Collation

from database.collections import (
    ADMIN_USERS,
    ANALYTICS_EVENTS,
    ANALYTICS_HOURLY,
    API_KEYS,
    APP_INSTANCE_ACCESS,
    APP_INSTANCE_ACCESS_REQUESTS,
    APP_INSTANCES,
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    MANAGERS,
    MESSAGES,
    MONITORED_ENDPOINTS,
    SUBCATEGORIES,
)

logger = logging.getLogger(__name__)

# Case-insensitive collation for category/subcategory names
CASE_INSENSITIVE_COLLATION = Collation(locale="en", strength=2)


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create all required declarative indexes across collections."""
    logger.info("Applying database index declarations...")

    # 1. Categories
    await db[CATEGORIES].create_indexes(
        [
            IndexModel(
                [("name", ASCENDING)],
                unique=True,
                collation=CASE_INSENSITIVE_COLLATION,
                name="uniq_category_name_ci",
            ),
            IndexModel([("deleted_at", ASCENDING)], name="idx_category_deleted_at"),
        ]
    )

    # 2. Subcategories
    await db[SUBCATEGORIES].create_indexes(
        [
            IndexModel(
                [("category_id", ASCENDING), ("name", ASCENDING)],
                unique=True,
                collation=CASE_INSENSITIVE_COLLATION,
                name="uniq_subcategory_parent_name_ci",
            ),
            IndexModel([("category_id", ASCENDING)], name="idx_subcategory_category_id"),
            IndexModel([("deleted_at", ASCENDING)], name="idx_subcategory_deleted_at"),
        ]
    )

    # 3. Assets
    await db[ASSETS].create_indexes(
        [
            IndexModel(
                [("category_id", ASCENDING), ("sub_category_id", ASCENDING)],
                name="idx_asset_parents",
            ),
            IndexModel([("name", TEXT)], name="idx_asset_name_text"),
            IndexModel([("created_at", DESCENDING)], name="idx_asset_created_at"),
            IndexModel([("deleted_at", ASCENDING)], name="idx_asset_deleted_at"),
        ]
    )

    # 4. App Instances
    # Clean up legacy records where package_name was stored as null or "None"
    try:
        await db[APP_INSTANCES].update_many(
            {"$or": [{"package_name": None}, {"package_name": "None"}, {"package_name": ""}]},
            {"$unset": {"package_name": ""}},
        )
    except Exception:
        pass

    try:
        await db[APP_INSTANCES].drop_index("uniq_app_instance_package_name")
    except Exception:
        pass

    await db[APP_INSTANCES].create_indexes(
        [
            IndexModel([("name", ASCENDING)], unique=True, name="uniq_app_instance_name"),
            IndexModel(
                [("package_name", ASCENDING)],
                unique=True,
                partialFilterExpression={"package_name": {"$type": "string"}},
                name="uniq_app_instance_package_name",
            ),
        ]
    )

    # 5. Instance Categories
    try:
        await db[INSTANCE_CATEGORIES].drop_index("uniq_instance_category_source")
    except Exception:
        pass

    await db[INSTANCE_CATEGORIES].create_indexes(
        [
            IndexModel(
                [("app_instance_id", ASCENDING), ("source_id", ASCENDING)],
                unique=True,
                partialFilterExpression={"source_id": {"$type": "objectId"}},
                name="uniq_instance_category_source",
            ),
            IndexModel(
                [("app_instance_id", ASCENDING), ("sequence", ASCENDING)],
                name="idx_instance_category_sequence",
            ),
            IndexModel(
                [("app_instance_id", ASCENDING), ("is_enabled", ASCENDING)],
                name="idx_instance_category_enabled",
            ),
            IndexModel([("source_id", ASCENDING)], name="idx_instance_category_reverse_lookup"),
            IndexModel([("deleted_at", ASCENDING)], name="idx_instance_category_deleted_at"),
        ]
    )

    # 6. Instance Subcategories
    try:
        await db[INSTANCE_SUBCATEGORIES].drop_index("uniq_instance_subcategory_source")
    except Exception:
        pass

    await db[INSTANCE_SUBCATEGORIES].create_indexes(
        [
            IndexModel(
                [("app_instance_id", ASCENDING), ("source_id", ASCENDING)],
                unique=True,
                partialFilterExpression={"source_id": {"$type": "objectId"}},
                name="uniq_instance_subcategory_source",
            ),
            IndexModel(
                [
                    ("app_instance_id", ASCENDING),
                    ("category_id", ASCENDING),
                    ("sequence", ASCENDING),
                ],
                name="idx_instance_subcategory_sequence",
            ),
            IndexModel(
                [("app_instance_id", ASCENDING), ("is_enabled", ASCENDING)],
                name="idx_instance_subcategory_enabled",
            ),
            IndexModel([("source_id", ASCENDING)], name="idx_instance_subcategory_reverse_lookup"),
            IndexModel([("deleted_at", ASCENDING)], name="idx_instance_subcategory_deleted_at"),
        ]
    )

    # 7. Instance Assets
    await db[INSTANCE_ASSETS].create_indexes(
        [
            IndexModel(
                [("app_instance_id", ASCENDING), ("source_id", ASCENDING)],
                unique=True,
                name="uniq_instance_asset_source",
            ),
            IndexModel(
                [
                    ("app_instance_id", ASCENDING),
                    ("category_id", ASCENDING),
                    ("sub_category_id", ASCENDING),
                    ("sequence", ASCENDING),
                ],
                name="idx_instance_asset_hierarchy_seq",
            ),
            IndexModel(
                [("app_instance_id", ASCENDING), ("is_enabled", ASCENDING)],
                name="idx_instance_asset_enabled",
            ),
            IndexModel(
                [("app_instance_id", ASCENDING), ("is_premium", ASCENDING)],
                name="idx_instance_asset_premium",
            ),
            IndexModel([("source_id", ASCENDING)], name="idx_instance_asset_reverse_lookup"),
            IndexModel([("deleted_at", ASCENDING)], name="idx_instance_asset_deleted_at"),
        ]
    )

    # 8. API Keys
    await db[API_KEYS].create_indexes(
        [
            IndexModel([("key_prefix", ASCENDING)], unique=True, name="uniq_api_key_prefix"),
            IndexModel([("is_active", ASCENDING)], name="idx_api_key_active"),
            IndexModel([("app_instance_id", ASCENDING)], name="idx_api_key_app_instance"),
            IndexModel([("owner_id", ASCENDING)], name="idx_api_key_owner"),
        ]
    )

    # 9. Admin Users
    await db[ADMIN_USERS].create_indexes(
        [
            IndexModel([("username", ASCENDING)], unique=True, name="uniq_admin_username"),
        ]
    )

    # 10. Manager Users
    await db[MANAGERS].create_indexes(
        [
            IndexModel([("username", ASCENDING)], unique=True, name="uniq_manager_username"),
            IndexModel([("status", ASCENDING)], name="idx_manager_status"),
            IndexModel([("email", ASCENDING)], name="idx_manager_email"),
        ]
    )

    # 11. App Instance Access Grants
    await db[APP_INSTANCE_ACCESS].create_indexes(
        [
            IndexModel(
                [("manager_id", ASCENDING), ("app_instance_id", ASCENDING)],
                unique=True,
                name="uniq_manager_instance_access",
            ),
            IndexModel([("manager_id", ASCENDING)], name="idx_access_manager_id"),
            IndexModel([("app_instance_id", ASCENDING)], name="idx_access_app_instance_id"),
        ]
    )

    # 12. App Instance Access Requests
    await db[APP_INSTANCE_ACCESS_REQUESTS].create_indexes(
        [
            IndexModel([("requesting_manager_id", ASCENDING)], name="idx_req_manager_id"),
            IndexModel([("app_instance_id", ASCENDING)], name="idx_req_app_instance_id"),
            IndexModel([("status", ASCENDING)], name="idx_req_status"),
            IndexModel([("created_at", DESCENDING)], name="idx_req_created_at"),
        ]
    )

    # 13. Messages (Manager ↔ Admin & Admin ↔ Admin Direct)
    await db[MESSAGES].create_indexes(
        [
            IndexModel([("manager_id", ASCENDING), ("created_at", ASCENDING)], name="idx_msg_manager_created"),
            IndexModel([("status", ASCENDING)], name="idx_msg_status"),
            IndexModel([("payload_type", ASCENDING)], name="idx_msg_payload_type"),
            IndexModel([("channel_type", ASCENDING), ("recipient_id", ASCENDING), ("status", ASCENDING)], name="idx_msg_direct_status"),
            IndexModel([("channel_type", ASCENDING), ("created_at", ASCENDING)], name="idx_msg_direct_created"),
        ]
    )

    # 14. Monitored Endpoints
    await db[MONITORED_ENDPOINTS].create_indexes(
        [
            IndexModel(
                [("method", ASCENDING), ("path_template", ASCENDING)],
                unique=True,
                name="uniq_monitored_endpoint",
            ),
        ]
    )

    # 15. Analytics Events (TTL index on ts default 30 days = 2592000s)
    await db[ANALYTICS_EVENTS].create_indexes(
        [
            IndexModel(
                [("path_template", ASCENDING), ("ts", DESCENDING)], name="idx_analytics_path_ts"
            ),
            IndexModel(
                [("app_instance_id", ASCENDING), ("ts", DESCENDING)], name="idx_analytics_inst_ts"
            ),
            IndexModel(
                [("ts", ASCENDING)], expireAfterSeconds=2592000, name="ttl_analytics_events_ts"
            ),
        ]
    )

    # 16. Hourly Rollups
    await db[ANALYTICS_HOURLY].create_indexes(
        [
            IndexModel(
                [
                    ("path_template", ASCENDING),
                    ("hour", DESCENDING),
                    ("app_instance_id", ASCENDING),
                ],
                unique=True,
                name="uniq_hourly_rollup",
            ),
            IndexModel([("hour", DESCENDING)], name="idx_hourly_hour"),
        ]
    )

    logger.info("Database indexes applied successfully")


ensure_indexes = create_indexes
