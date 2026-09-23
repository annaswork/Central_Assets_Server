"""In-memory sliding window rate limiter per API key."""

import time
from collections import defaultdict

# Map of key_prefix -> list of request timestamps (epoch seconds)
_rate_limits: defaultdict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS: float = 60.0


def check_rate_limit(key_id: str, limit_per_minute: int) -> tuple[bool, int]:
    """Check if request is within sliding window rate limit.

    Returns:
        (is_allowed, retry_after_seconds)
    """
    now = time.time()
    window_start = now - _WINDOW_SECONDS

    # Filter out entries older than sliding window
    timestamps = [ts for ts in _rate_limits[key_id] if ts > window_start]
    _rate_limits[key_id] = timestamps

    if len(timestamps) >= limit_per_minute:
        oldest_ts = timestamps[0]
        retry_after = max(1, int(oldest_ts + _WINDOW_SECONDS - now))
        return False, retry_after

    _rate_limits[key_id].append(now)
    return True, 0
