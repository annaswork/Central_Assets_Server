from datetime import datetime, timedelta, timezone

PKT_TIMEZONE = timezone(timedelta(hours=5))


def format_pkt_datetime(val: object, fmt: str = "%Y-%m-%d %H:%M:%S PKT") -> str:
    """Convert UTC datetime or ISO string to PKT (Pakistan Standard Time, UTC+5)."""
    if not val:
        return "—"
    dt = None
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, str):
        try:
            clean_str = val.replace("Z", "+00:00") if val.endswith("Z") else val
            dt = datetime.fromisoformat(clean_str)
        except Exception:
            return str(val)
    if dt:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        pkt_dt = dt.astimezone(PKT_TIMEZONE)
        return pkt_dt.strftime(fmt)
    return str(val)



def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def to_iso_z(dt: datetime | None) -> str | None:
    """Format datetime as ISO 8601 string with trailing 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_now_iso() -> str:
    """Return current timezone-aware UTC datetime formatted as ISO 8601 string with 'Z'."""
    return to_iso_z(utc_now())  # type: ignore[return-value]


def format_datetime_display(val: object) -> str:
    """Format datetime or ISO string as 'M/D/YYYY, h:mm A' in local timezone."""
    if not val:
        return "—"
    dt = None
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, str):
        try:
            clean_str = val.replace("Z", "+00:00") if val.endswith("Z") else val
            dt = datetime.fromisoformat(clean_str)
        except Exception:
            return str(val)
    if dt:
        if dt.tzinfo is not None:
            local_dt = dt.astimezone()
        else:
            local_dt = dt.replace(tzinfo=timezone.utc).astimezone()
        try:
            return local_dt.strftime("%-m/%-d/%Y, %-I:%M %p")
        except ValueError:
            return local_dt.strftime("%m/%d/%Y, %I:%M %p").lstrip("0")
    return str(val)
