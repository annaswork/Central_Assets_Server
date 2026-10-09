"""Migration script to ensure all instance_subcategories and instance_assets

reference their parent instance_categories and instance_subcategories by their
assigned instance _id rather than central source_ids.
"""

import asyncio
import logging
from database.connection import get_database, close_database
from database.collections import INSTANCE_CATEGORIES, INSTANCE_SUBCATEGORIES, INSTANCE_ASSETS, APP_INSTANCES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_instance_links():
    db = get_database()
    instances = await db[APP_INSTANCES].find().to_list(100)
    total_subs_fixed = 0
    total_assets_fixed = 0

    for inst in instances:
        inst_id = inst["_id"]
        cats = await db[INSTANCE_CATEGORIES].find({"app_instance_id": inst_id}).to_list(1000)
        cat_src_to_id = {c["source_id"]: c["_id"] for c in cats if c.get("source_id")}

        subs = await db[INSTANCE_SUBCATEGORIES].find({"app_instance_id": inst_id}).to_list(1000)
        sub_src_to_id = {s["source_id"]: s["_id"] for s in subs if s.get("source_id")}

        for s in subs:
            if s.get("category_id") in cat_src_to_id:
                new_cat_id = cat_src_to_id[s["category_id"]]
                await db[INSTANCE_SUBCATEGORIES].update_one(
                    {"_id": s["_id"]},
                    {"$set": {"category_id": new_cat_id}}
                )
                total_subs_fixed += 1

        assets = await db[INSTANCE_ASSETS].find({"app_instance_id": inst_id}).to_list(10000)
        for a in assets:
            updates = {}
            if a.get("category_id") in cat_src_to_id:
                updates["category_id"] = cat_src_to_id[a["category_id"]]
            if a.get("sub_category_id") in sub_src_to_id:
                updates["sub_category_id"] = sub_src_to_id[a["sub_category_id"]]
            if updates:
                await db[INSTANCE_ASSETS].update_one(
                    {"_id": a["_id"]},
                    {"$set": updates}
                )
                total_assets_fixed += 1

        logger.info(f"Instance '{inst.get('name')}' migrated successfully.")

    logger.info(f"Done! Fixed {total_subs_fixed} subcategories and {total_assets_fixed} assets.")
    await close_database()


if __name__ == "__main__":
    asyncio.run(migrate_instance_links())
