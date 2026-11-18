import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from analytics.aggregator import aggregate_hourly_window
from config.settings import settings


async def run_rebuild(hour_str: str | None = None) -> None:
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]

    if hour_str:
        target_hour = datetime.fromisoformat(hour_str).replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        target_hour = now.replace(minute=0, second=0, microsecond=0)

    from datetime import timedelta

    next_hour = target_hour + timedelta(hours=1)

    print(
        f"Rebuilding hourly rollups for window: {target_hour.isoformat()} to {next_hour.isoformat()}..."
    )
    count = await aggregate_hourly_window(db, start_hour=target_hour, end_hour=next_hour)
    print(f"Rollup rebuild complete. Generated {count} aggregated bucket(s).")
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild hourly analytics rollups.")
    parser.add_argument(
        "--hour",
        "-t",
        help="Target hour in ISO format (e.g. 2026-09-16T12:00:00). Defaults to current hour.",
    )
    args = parser.parse_args()
    asyncio.run(run_rebuild(hour_str=args.hour))


if __name__ == "__main__":
    main()
