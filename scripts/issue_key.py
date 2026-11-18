import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from config.settings import settings
from controller.authorization_controller import create_key
from database.models.api_key import ApiKeyCreate


async def run_issue_key(
    name: str,
    app_instance_id: str | None,
    scopes: list[str],
    rate_limit: int,
) -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]

    created = await create_key(
        db,
        ApiKeyCreate(
            name=name,
            app_instance_id=app_instance_id,
            scopes=scopes,
            rate_limit_per_min=rate_limit,
        ),
    )

    print("\n" + "=" * 60)
    print("API KEY CREATED SUCCESSFULLY")
    print("=" * 60)
    print(f"Key ID:         {created.id}")
    print(f"Name:           {created.name}")
    print(f"Instance ID:    {created.app_instance_id or 'Global / Unscoped'}")
    print(f"Scopes:         {', '.join(created.scopes)}")
    print(f"Rate Limit:     {created.rate_limit_per_min} req/min")
    print("-" * 60)
    print(f"FULL SECRET KEY: {created.full_key}")
    print("-" * 60)
    print("WARNING: This full secret key will NEVER be shown again.")
    print("Store it immediately in a secure vault.")
    print("=" * 60 + "\n")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a new API access key.")
    parser.add_argument("--name", "-n", required=True, help="Descriptive name for key")
    parser.add_argument("--instance", "-i", help="Scoped App Instance ID (optional)")
    parser.add_argument(
        "--scopes",
        "-s",
        nargs="+",
        default=["read:assets", "read:categories"],
        help="Scopes to grant (space-separated, e.g. read:assets write:assets)",
    )
    parser.add_argument(
        "--rate-limit",
        "-r",
        type=int,
        default=60,
        help="Max requests per minute (default 60)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_issue_key(
            name=args.name,
            app_instance_id=args.instance,
            scopes=args.scopes,
            rate_limit=args.rate_limit,
        )
    )


if __name__ == "__main__":
    main()
