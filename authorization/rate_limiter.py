"""In-memory sliding window rate limiter per API key and client IP."""

import time
from collections import defaultdict

# Map of identifier -> list of request timestamps (epoch seconds)
_rate_limits: defaultdict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS: float = 60.0
_PRUNE_INTERVAL: float = 300.0
_last_prune_time: float = time.time()


def _prune_expired_entries(now: float) -> None:
    """Prune keys that have had no traffic within the sliding window."""
    global _last_prune_time
    if now - _last_prune_time < _PRUNE_INTERVAL:
        return
    _last_prune_time = now
    window_start = now - _WINDOW_SECONDS
    keys_to_delete = [
        k for k, timestamps in _rate_limits.items()
        if not timestamps or timestamps[-1] <= window_start
    ]
    for k in keys_to_delete:
        del _rate_limits[k]


def check_rate_limit(key_id: str, limit_per_minute: int) -> tuple[bool, int]:
    """Check if request is within sliding window rate limit.

    Returns:
        (is_allowed, retry_after_seconds)
    """
    now = time.time()
    _prune_expired_entries(now)
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


def check_dual_layer_rate_limit(
    key_prefix: str,
    client_ip: str,
    user_limit_per_min: int = 60,
    app_surge_ceiling_per_min: int = 10000,
) -> tuple[bool, str | None, int]:
    """Check both Layer 1 (User IP limit) and Layer 2 (App Surge ceiling).

    Returns:
        (is_allowed, violated_layer, retry_after_seconds)
        where violated_layer is 'user_ip_limit', 'app_surge_ceiling', or None.
    """
    now = time.time()
    _prune_expired_entries(now)
    window_start = now - _WINDOW_SECONDS

    user_key = f"{key_prefix}:ip:{client_ip}"
    app_key = f"{key_prefix}:surge"

    # Layer 1: Check User IP Limit
    user_timestamps = [ts for ts in _rate_limits[user_key] if ts > window_start]
    if len(user_timestamps) >= user_limit_per_min:
        oldest_ts = user_timestamps[0]
        retry_after = max(1, int(oldest_ts + _WINDOW_SECONDS - now))
        _rate_limits[user_key] = user_timestamps
        return False, "user_ip_limit", retry_after

    # Layer 2: Check App Surge Ceiling
    app_timestamps = [ts for ts in _rate_limits[app_key] if ts > window_start]
    if len(app_timestamps) >= app_surge_ceiling_per_min:
        oldest_ts = app_timestamps[0]
        retry_after = max(1, int(oldest_ts + _WINDOW_SECONDS - now))
        _rate_limits[app_key] = app_timestamps
        return False, "app_surge_ceiling", retry_after

    # Both layers passed: record timestamp in both buckets
    user_timestamps.append(now)
    app_timestamps.append(now)
    _rate_limits[user_key] = user_timestamps
    _rate_limits[app_key] = app_timestamps

    return True, None, 0
