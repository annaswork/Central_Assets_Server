"""Standard API response envelopes."""

from collections.abc import Sequence
from typing import Any, TypeVar

T = TypeVar("T")


def page_response(
    items: Sequence[Any],
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Builds the canonical paginated list response envelope."""
    has_next = (page * page_size) < total
    return {
        "items": list(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
    }


def error_response(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Builds the canonical error response envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }


def bulk_item_result(
    index: int,
    status: str,
    id: str | None = None,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Constructs a single item outcome for a bulk response."""
    result: dict[str, Any] = {
        "index": index,
        "status": status,  # "created", "skipped", "failed"
    }
    if id:
        result["id"] = str(id)
    if error:
        result["error"] = error
    if details:
        result["details"] = details
    return result


def bulk_response(
    results: list[dict[str, Any]],
    atomic: bool = False,
) -> dict[str, Any]:
    """Builds the 207 Multi-Status summary envelope for bulk operations."""
    total = len(results)
    created_count = sum(1 for r in results if r.get("status") == "created")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")
    failed_count = sum(1 for r in results if r.get("status") == "failed")

    return {
        "items": results,
        "total": total,
        "created": created_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "atomic": atomic,
    }
