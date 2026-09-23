"""Migration 0002: Seed default analytics allowed paths from JSON allowlist."""

import json

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.paths import ROOT_DIR
from database.collections import MONITORED_ENDPOINTS
from utils.datetimes import utc_now_iso

MIGRATION_NAME = "0002_seed_allowed_paths"


async def apply(db: AsyncIOMotorDatabase) -> None:
    coll = db[MONITORED_ENDPOINTS]
    json_path = ROOT_DIR / "analytics" / "allowed_paths.json"
    if not json_path.exists():
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else data.get("endpoints", [])
    for item in items:
        method = item.get("method", "GET").upper()
        path_tmpl = item.get("path_template", "")
        existing = await coll.find_one({"method": method, "path_template": path_tmpl})
        if not existing:
            await coll.insert_one(
                {
                    "method": method,
                    "path_template": path_tmpl,
                    "sample_rate": float(item.get("sample_rate", 1.0)),
                    "retain_days": int(item.get("retain_days", 30)),
                    "notes": item.get("notes", "Default seed allowlist"),
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
            )
