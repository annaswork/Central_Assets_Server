import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from authorization.encryption import hash_password
from config.settings import settings
from database.collections import ADMIN_USERS
from utils.datetimes import utc_now_iso


async def create_or_update_admin(
    username: str, password: str, full_name: str | None = None, email: str | None = None
) -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]
    coll = db[ADMIN_USERS]

    hashed = hash_password(password)
    now = utc_now_iso()

    existing = await coll.find_one({"username": username})
    if existing:
        await coll.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "password_hash": hashed,
                    "full_name": full_name or existing.get("full_name"),
                    "email": email or existing.get("email"),
                    "updated_at": now,
                }
            },
        )
        print(f"Admin user '{username}' password/profile successfully updated.")
    else:
        await coll.insert_one(
            {
                "username": username,
                "password_hash": hashed,
                "full_name": full_name or username.capitalize(),
                "email": email or f"{username}@admin.local",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
        print(f"Admin user '{username}' created successfully.")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update an admin user.")
    parser.add_argument("--username", "-u", required=True, help="Admin username")
    parser.add_argument("--password", "-p", help="Admin password (prompted if omitted)")
    parser.add_argument("--name", "-n", help="Full name")
    parser.add_argument("--email", "-e", help="Email address")
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("Enter admin password: ")
        confirm = getpass.getpass("Confirm admin password: ")
        if password != confirm:
            print("Error: Passwords do not match.")
            return

    asyncio.run(
        create_or_update_admin(
            username=args.username,
            password=password,
            full_name=args.name,
            email=args.email,
        )
    )


if __name__ == "__main__":
    main()
