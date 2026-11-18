"""First-run database seeding for root admin operator and initial monitored endpoints."""

import json
import logging
from pathlib import Path

import bcrypt
from motor.motor_asyncio import AsyncIOMotorDatabase

from config.settings import settings
from database.collections import ADMIN_USERS, MONITORED_ENDPOINTS
from utils.datetimes import utc_now

logger = logging.getLogger(__name__)


async def seed_database(db: AsyncIOMotorDatabase) -> None:
    """Run initial idempotent seeds for admin operator and monitored endpoints."""
    await _seed_admin_user(db)
    await _seed_allowed_paths(db)


async def _seed_admin_user(db: AsyncIOMotorDatabase) -> None:
    """Seed or update initial operator account based on bootstrap settings."""
    salt = bcrypt.gensalt()
    pw_hash = bcrypt.hashpw(settings.BOOTSTRAP_ADMIN_PASSWORD.encode("utf-8"), salt).decode("utf-8")
    now = utc_now()

    existing_admin = await db[ADMIN_USERS].find_one({"username": settings.BOOTSTRAP_ADMIN_USERNAME})
    if existing_admin is not None:
        stored_hash = existing_admin.get("password_hash", "")
        if not stored_hash or not bcrypt.checkpw(
            settings.BOOTSTRAP_ADMIN_PASSWORD.encode("utf-8"), stored_hash.encode("utf-8")
        ):
            await db[ADMIN_USERS].update_one(
                {"_id": existing_admin["_id"]},
                {"$set": {"password_hash": pw_hash, "is_active": True, "updated_at": now}},
            )
            logger.info(f"Updated bootstrap admin operator password: '{settings.BOOTSTRAP_ADMIN_USERNAME}'")
        return

    doc = {
        "username": settings.BOOTSTRAP_ADMIN_USERNAME,
        "password_hash": pw_hash,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await db[ADMIN_USERS].insert_one(doc)
    logger.info(f"Seeded initial admin operator: '{settings.BOOTSTRAP_ADMIN_USERNAME}'")


async def _seed_allowed_paths(db: AsyncIOMotorDatabase) -> None:
    """Seed or update allowed paths from analytics/allowed_paths.json."""
    seed_file = Path(__file__).resolve().parent.parent / "analytics" / "allowed_paths.json"
    if not seed_file.exists():
        logger.warning(f"Seed file not found: {seed_file}")
        return

    try:
        with open(seed_file, "r", encoding="utf-8") as f:
            items = json.load(f)

        now = utc_now()
        for item in items:
            method = item.get("method", "GET").upper()
            template = item["path_template"]
            await db[MONITORED_ENDPOINTS].update_one(
                {"method": method, "path_template": template},
                {
                    "$setOnInsert": {
                        "method": method,
                        "path_template": template,
                        "is_active": item.get("is_active", True),
                        "sample_rate": float(item.get("sample_rate", 1.0)),
                        "retain_days": int(item.get("retain_days", 30)),
                        "notes": item.get("notes", "Initial seed"),
                        "created_at": now,
                    },
                    "$set": {
                        "updated_at": now,
                    },
                },
                upsert=True,
            )
        logger.info(f"Synchronized {len(items)} monitored endpoint route templates")
    except Exception as exc:
        logger.error(f"Error seeding allowed paths: {exc}")
