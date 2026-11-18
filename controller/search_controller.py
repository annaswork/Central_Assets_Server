"""Search controller for unified global library search across categories, subcategories, and assets."""

import re
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.constants import ALLOWED_AUDIO_EXTENSIONS, DEFAULT_AUDIO_THUMBNAIL_URL
from database.collections import API_KEYS, APP_INSTANCES, ASSETS, CATEGORIES, SUBCATEGORIES
from database.repository import CentralRepository


async def global_search(
    db: AsyncIOMotorDatabase,
    query: str,
    limit: int = 6,
) -> dict[str, Any]:
    """Search categories, subcategories, assets, app instances, and api keys across the system.

    Returns structured, categorized results with hierarchy and isolation metadata.
    """
    clean_q = query.strip() if query else ""
    if not clean_q:
        return {
            "query": "",
            "categories": [],
            "subcategories": [],
            "assets": [],
            "instances": [],
            "keys": [],
            "total_count": 0,
        }

    escaped_pat = re.escape(clean_q)
    regex_filter = {"$regex": escaped_pat, "$options": "i"}

    cat_repo = CentralRepository(db, CATEGORIES)
    sub_repo = CentralRepository(db, SUBCATEGORIES)
    asset_repo = CentralRepository(db, ASSETS)

    # 1. Search Categories
    cat_query = {"name": regex_filter, "deleted_at": None}
    cat_docs = await cat_repo.find_many(
        query=cat_query,
        limit=limit,
        sort=[("name", 1)],
    )

    # 2. Search Subcategories
    sub_query = {"name": regex_filter, "deleted_at": None}
    sub_docs = await sub_repo.find_many(
        query=sub_query,
        limit=limit,
        sort=[("name", 1)],
    )

    # 3. Search Assets
    asset_query = {"name": regex_filter, "deleted_at": None}
    asset_docs = await asset_repo.find_many(
        query=asset_query,
        limit=limit,
        sort=[("name", 1)],
    )

    # 4. Search App Instances
    inst_query = {
        "$or": [
            {"name": regex_filter},
            {"package_name": regex_filter},
        ]
    }
    inst_docs = (
        await db[APP_INSTANCES]
        .find(inst_query)
        .limit(limit)
        .sort("name", 1)
        .to_list(length=limit)
    )

    # 5. Search API Keys (exclude secret_hash)
    key_query = {
        "$or": [
            {"name": regex_filter},
            {"key_prefix": regex_filter},
            {"scopes": regex_filter},
        ]
    }
    key_docs = (
        await db[API_KEYS]
        .find(key_query, {"secret_hash": 0})
        .limit(limit)
        .sort("created_at", -1)
        .to_list(length=limit)
    )

    # Resolve Category and Subcategory names for breadcrumbs
    needed_cat_ids = set()
    needed_sub_ids = set()

    for s in sub_docs:
        if s.get("category_id"):
            needed_cat_ids.add(s["category_id"])
    for a in asset_docs:
        if a.get("category_id"):
            needed_cat_ids.add(a["category_id"])
        if a.get("sub_category_id"):
            needed_sub_ids.add(a["sub_category_id"])

    # Resolve App Instance names for API Keys
    needed_inst_ids = set()
    for k in key_docs:
        if k.get("app_instance_id"):
            needed_inst_ids.add(k["app_instance_id"])

    cat_name_map: dict[str, str] = {}
    if needed_cat_ids:
        c_list = (
            await db[CATEGORIES]
            .find({"_id": {"$in": list(needed_cat_ids)}}, {"_id": 1, "name": 1})
            .to_list(length=100)
        )
        for c in c_list:
            cat_name_map[str(c["_id"])] = c.get("name", "")

    sub_name_map: dict[str, str] = {}
    if needed_sub_ids:
        s_list = (
            await db[SUBCATEGORIES]
            .find({"_id": {"$in": list(needed_sub_ids)}}, {"_id": 1, "name": 1})
            .to_list(length=100)
        )
        for s in s_list:
            sub_name_map[str(s["_id"])] = s.get("name", "")

    inst_name_map: dict[str, str] = {}
    if needed_inst_ids:
        i_list = (
            await db[APP_INSTANCES]
            .find({"_id": {"$in": list(needed_inst_ids)}}, {"_id": 1, "name": 1})
            .to_list(length=100)
        )
        for i in i_list:
            inst_name_map[str(i["_id"])] = i.get("name", "")

    # Format Category results
    categories_res = [
        {
            "id": str(c["_id"]),
            "name": c.get("name", ""),
            "folder_name": c.get("folder_name", ""),
            "thumbnail_url": c.get("thumbnail_url") or c.get("icon_url") or "",
            "is_enabled": c.get("is_enabled", True),
            "type": "category",
        }
        for c in cat_docs
    ]

    # Format Subcategory results
    subcategories_res = [
        {
            "id": str(s["_id"]),
            "name": s.get("name", ""),
            "category_id": str(s.get("category_id", "")),
            "category_name": cat_name_map.get(str(s.get("category_id", "")), ""),
            "folder_name": s.get("folder_name", ""),
            "thumbnail_url": s.get("thumbnail_url") or s.get("icon_url") or "",
            "is_enabled": s.get("is_enabled", True),
            "type": "subcategory",
        }
        for s in sub_docs
    ]

    # Format Asset results
    assets_res = [
        {
            "id": str(a["_id"]),
            "name": a.get("name", ""),
            "category_id": str(a.get("category_id", "")),
            "category_name": cat_name_map.get(str(a.get("category_id", "")), ""),
            "sub_category_id": str(a.get("sub_category_id", "")),
            "subcategory_name": sub_name_map.get(str(a.get("sub_category_id", "")), ""),
            "folder_name": a.get("folder_name", ""),
            "thumbnail_url": (
                DEFAULT_AUDIO_THUMBNAIL_URL
                if (
                    not a.get("thumbnail_url")
                    or Path(str(a.get("thumbnail_url")).split("?")[0]).suffix.lower().lstrip(".")
                    in ALLOWED_AUDIO_EXTENSIONS
                )
                and any("audio" in str(k).lower() for k in (a.get("more_fields") or {}).keys())
                else (a.get("thumbnail_url") or "")
            ),
            "is_enabled": a.get("is_enabled", True),
            "is_premium": a.get("is_premium", False),
            "type": "asset",
        }
        for a in asset_docs
    ]

    # Format App Instance results
    instances_res = [
        {
            "id": str(inst["_id"]),
            "name": inst.get("name", ""),
            "package_name": inst.get("package_name") or inst.get("packageName") or "",
            "icon_url": inst.get("app_icon") or inst.get("icon_url") or "",
            "is_active": inst.get("is_active", True),
            "type": "instance",
        }
        for inst in inst_docs
    ]

    # Format API Key results
    keys_res = [
        {
            "id": str(k["_id"]),
            "name": k.get("name", ""),
            "key_prefix": k.get("key_prefix", ""),
            "app_instance_id": str(k.get("app_instance_id", "")),
            "app_instance_name": inst_name_map.get(str(k.get("app_instance_id", "")), ""),
            "scopes": k.get("scopes", []),
            "rate_limit_per_min": k.get("rate_limit_per_min", 60),
            "is_active": bool(k.get("is_active", True) and not k.get("is_revoked")),
            "type": "key",
        }
        for k in key_docs
    ]

    total_count = (
        len(categories_res)
        + len(subcategories_res)
        + len(assets_res)
        + len(instances_res)
        + len(keys_res)
    )

    return {
        "query": clean_q,
        "categories": categories_res,
        "subcategories": subcategories_res,
        "assets": assets_res,
        "instances": instances_res,
        "keys": keys_res,
        "total_count": total_count,
    }
