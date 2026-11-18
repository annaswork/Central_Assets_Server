"""Filesystem synchronization for central static storage directories."""

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.paths import get_asset_dir, get_category_dir, get_subcategory_dir
from database.collections import ASSETS, CATEGORIES, SUBCATEGORIES
from utils.slugify import slugify

logger = logging.getLogger(__name__)


async def sync_central_storage_directories(db: AsyncIOMotorDatabase) -> None:
    """Ensure all active central categories, subcategories, and assets have filesystem directories."""
    try:
        # 1. Sync category directories
        cat_map: dict[str, str] = {}
        cursor = db[CATEGORIES].find({"deleted_at": None})
        async for cat in cursor:
            cat_id = str(cat["_id"])
            folder_name = cat.get("folder_name") or slugify(cat.get("name", "")) or "category"
            cat_dir = get_category_dir(folder_name)
            cat_dir.mkdir(parents=True, exist_ok=True)
            cat_map[cat_id] = folder_name

            if not cat.get("folder_name"):
                await db[CATEGORIES].update_one(
                    {"_id": cat["_id"]},
                    {"$set": {"folder_name": folder_name}},
                )

        # 2. Sync subcategory directories
        sub_map: dict[str, tuple[str, str]] = {}
        sub_cursor = db[SUBCATEGORIES].find({"deleted_at": None})
        async for sub in sub_cursor:
            sub_id = str(sub["_id"])
            parent_id = str(sub.get("category_id", ""))
            parent_folder = cat_map.get(parent_id)
            if not parent_folder:
                parent_doc = await db[CATEGORIES].find_one({"_id": sub.get("category_id")})
                parent_folder = (
                    (parent_doc.get("folder_name") or slugify(parent_doc.get("name", "")))
                    if parent_doc
                    else "category"
                )

            sub_folder = sub.get("folder_name") or slugify(sub.get("name", "")) or "subcategory"
            sub_dir = get_subcategory_dir(parent_folder, sub_folder)
            sub_dir.mkdir(parents=True, exist_ok=True)
            sub_map[sub_id] = (parent_folder, sub_folder)

            if not sub.get("folder_name"):
                await db[SUBCATEGORIES].update_one(
                    {"_id": sub["_id"]},
                    {"$set": {"folder_name": sub_folder}},
                )

        # 3. Sync asset directories
        asset_cursor = db[ASSETS].find({"deleted_at": None})
        async for asset in asset_cursor:
            parent_sub_id = str(asset.get("sub_category_id", ""))
            sub_info = sub_map.get(parent_sub_id)
            if not sub_info:
                sub_doc = await db[SUBCATEGORIES].find_one({"_id": asset.get("sub_category_id")})
                if sub_doc:
                    parent_cat_id = str(sub_doc.get("category_id", ""))
                    cat_f_val = cat_map.get(parent_cat_id) or "category"
                    sub_f_val = (
                        sub_doc.get("folder_name")
                        or slugify(sub_doc.get("name", ""))
                        or "subcategory"
                    )
                    sub_info = (cat_f_val, sub_f_val)
                else:
                    sub_info = ("category", "subcategory")

            cat_f, sub_f = sub_info
            asset_folder = asset.get("folder_name") or slugify(asset.get("name", "")) or "asset"
            asset_dir = get_asset_dir(cat_f, sub_f, asset_folder)
            asset_dir.mkdir(parents=True, exist_ok=True)

            if not asset.get("folder_name"):
                await db[ASSETS].update_one(
                    {"_id": asset["_id"]},
                    {"$set": {"folder_name": asset_folder}},
                )

        logger.info(
            "Synchronized central storage filesystem directories with database categories, subcategories, and assets."
        )
    except Exception as exc:
        logger.warning(f"Could not synchronize central storage directories: {exc}")
