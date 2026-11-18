import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from config.settings import settings


async def scan_and_reap(delete: bool = False) -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]

    upload_dir = Path(settings.media_upload_dir)
    if not upload_dir.exists():
        print(f"Media upload directory does not exist: {upload_dir}")
        return

    print("Gathering media references from MongoDB...")
    referenced_filenames: set[str] = set()

    # Collect from categories
    async for cat in db["categories"].find({}, {"thumbnail_url": 1}):
        thumb = cat.get("thumbnail_url")
        if thumb:
            referenced_filenames.add(Path(thumb).name)

    # Collect from subcategories
    async for sub in db["subcategories"].find({}, {"thumbnail_url": 1}):
        thumb = sub.get("thumbnail_url")
        if thumb:
            referenced_filenames.add(Path(thumb).name)

    # Collect from assets
    async for asset in db["assets"].find({}, {"thumbnail_url": 1, "more_fields": 1}):
        thumb = asset.get("thumbnail_url")
        if thumb:
            referenced_filenames.add(Path(thumb).name)

        # Recursively search strings in more_fields
        def _extract_strings(val: object) -> None:
            if isinstance(val, str):
                referenced_filenames.add(Path(val).name)
            elif isinstance(val, dict):
                for v in val.values():
                    _extract_strings(v)
            elif isinstance(val, list):
                for v in val:
                    _extract_strings(v)

        more = asset.get("more_fields")
        if more and isinstance(more, dict):
            _extract_strings(more)

    print(f"Found {len(referenced_filenames)} distinct referenced media files in database.")

    # Scan disk
    disk_files = [p for p in upload_dir.rglob("*") if p.is_file() and not p.name.startswith(".")]
    print(f"Found {len(disk_files)} files on disk in {upload_dir}.")

    orphan_files: list[Path] = []
    for p in disk_files:
        if p.name not in referenced_filenames:
            orphan_files.append(p)

    print(f"\nDiscovered {len(orphan_files)} orphan file(s):")
    for o in orphan_files[:50]:
        print(f"  - {o.relative_to(upload_dir)}")
    if len(orphan_files) > 50:
        print(f"  ... and {len(orphan_files) - 50} more")

    if delete:
        print(f"\nDeleting {len(orphan_files)} orphan files...")
        deleted_count = 0
        for o in orphan_files:
            try:
                o.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting {o}: {e}")
        print(f"Successfully removed {deleted_count} orphan file(s).")
    else:
        print("\n[DRY RUN] No files were deleted. Re-run with --delete to remove orphan files.")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan and prune orphan media files.")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Physically delete orphan files (default is dry-run)",
    )
    args = parser.parse_args()
    asyncio.run(scan_and_reap(delete=args.delete))


if __name__ == "__main__":
    main()
