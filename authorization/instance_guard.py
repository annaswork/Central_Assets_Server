"""Instance isolation guard ensuring API keys bound to an app instance cannot leak or access another."""

from typing import Any

from fastapi import Request

from utils.errors import ForbiddenError, UnauthorizedError
from utils.ids import to_object_id


def _bound_instance(request: Request) -> str | None:
    """App instance id the calling key is bound to, or None for unbound keys / admin sessions."""
    api_key = getattr(request.state, "api_key", None)
    if not api_key:
        raise UnauthorizedError("Authentication required")
    bound = api_key.get("app_instance_id") if isinstance(api_key, dict) else getattr(api_key, "app_instance_id", None)
    return str(bound) if bound else None


def require_instance_access(request: Request, id: str) -> None:
    """Router dependency for `/…/{id}` instance routes: an app-bound key may only touch its own app instance."""
    get_instance_filter(request, target_instance_id=id)


def require_unbound_key(request: Request) -> None:
    """Router dependency for platform management (API keys, app instances): never usable by app-bound keys."""
    if _bound_instance(request):
        raise ForbiddenError("This API key is bound to an app instance and cannot manage keys or app instances.")


def get_instance_filter(request: Request, target_instance_id: str | None = None) -> dict[str, Any]:
    """Resolve mandatory app_instance_id query filter based on calling API key.

    If key is bound to an app_instance_id:
      - Validates that target_instance_id (if passed) equals the bound instance.
      - Injects {"app_instance_id": bound_instance_oid} filter.
    If key is unbound (central key with manage scopes):
      - If target_instance_id is passed, filters by that instance.
      - If none passed, allows cross-instance queries if permitted.
    """
    bound_str = _bound_instance(request)
    if bound_str:
        if target_instance_id and target_instance_id != bound_str:
            raise ForbiddenError("API key not matching with the instance, verify again.")
        return {"app_instance_id": to_object_id(bound_str)}

    # Unbound key
    if target_instance_id:
        return {"app_instance_id": to_object_id(target_instance_id)}

    return {}
