import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config.settings import settings
from utils.datetimes import utc_now_iso

logger = logging.getLogger(__name__)

# Registered migrations in chronological execution order
MIGRATIONS = [
    ("0001_initial_indexes", "migrations.0001_initial_indexes"),
    ("0002_seed_allowed_paths", "migrations.0002_seed_allowed_paths"),
    ("0003_manager_schema_indexes", "migrations.0003_manager_schema_indexes"),
]


async def run_migrations(db: AsyncIOMotorDatabase) -> list[str]:
    """Applies any pending migrations and records them in _migrations collection."""
    migrations_coll = db["_migrations"]
    applied_docs = await migrations_coll.find({}).to_list(length=1000)
    applied_names = {doc["name"] for doc in applied_docs}

    newly_applied: list[str] = []

    for name, module_path in MIGRATIONS:
        if name in applied_names:
            logger.info("Migration %s already applied, skipping", name)
            continue

        logger.info("Applying migration %s...", name)
        module = __import__(module_path, fromlist=["apply"])
        await module.apply(db)

        await migrations_coll.insert_one(
            {
                "name": name,
                "applied_at": utc_now_iso(),
            }
        )
        newly_applied.append(name)
        logger.info("Migration %s successfully applied", name)

    return newly_applied


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]
    applied = await run_migrations(db)
    print(f"Migration run complete. Applied: {applied}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
