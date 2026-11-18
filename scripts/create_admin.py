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
    username: str,
    password: str | None = None,
    full_name: str | None = None,
    email: str | None = None,
    disable_2fa: bool = False,
) -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]
    coll = db[ADMIN_USERS]

    now = utc_now_iso()
    existing = await coll.find_one({"username": username})

    if disable_2fa:
        if not existing:
            print(f"Error: Admin user '{username}' not found.")
            client.close()
            return
        await coll.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "is_2fa_enabled": False,
                    "totp_secret": None,
                    "totp_temp_secret": None,
                    "backup_codes": [],
                    "updated_at": now,
                }
            },
        )
        print(f"Two-Factor Authentication for '{username}' has been successfully DISABLED.")
        client.close()
        return

    hashed = hash_password(password) if password else None
    if existing:
        update_fields = {
            "full_name": full_name or existing.get("full_name"),
            "email": email or existing.get("email"),
            "updated_at": now,
        }
        if hashed:
            update_fields["password_hash"] = hashed
        await coll.update_one({"_id": existing["_id"]}, {"$set": update_fields})
        print(f"Admin user '{username}' profile/password updated successfully.")
    else:
        if not hashed:
            print("Error: Password required to create a new admin.")
            client.close()
            return
        await coll.insert_one(
            {
                "username": username,
                "password_hash": hashed,
                "full_name": full_name or username.capitalize(),
                "email": email or f"{username}@admin.local",
                "is_active": True,
                "is_2fa_enabled": False,
                "created_at": now,
                "updated_at": now,
            }
        )
        print(f"Admin user '{username}' created successfully.")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, update, or recover an admin user.")
    parser.add_argument("--username", "-u", required=True, help="Admin username")
    parser.add_argument("--password", "-p", help="Admin password (prompted if omitted)")
    parser.add_argument("--name", "-n", help="Full name")
    parser.add_argument("--email", "-e", help="Email address")
    parser.add_argument("--disable-2fa", action="store_true", help="Emergency disable 2FA for this user")
    args = parser.parse_args()

    password = args.password
    if not args.disable_2fa and not password:
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
            disable_2fa=args.disable_2fa,
        )
    )


if __name__ == "__main__":
    main()
