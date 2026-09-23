"""Scope enforcement dependency for FastAPI endpoints."""

from collections.abc import Callable

from fastapi import Request

from utils.errors import ForbiddenError, UnauthorizedError


def require_scope(required_scope: str) -> Callable[[Request], None]:
    """Dependency factory checking that the authenticated API key possesses required scope."""

    def _scope_checker(request: Request) -> None:
        api_key = getattr(request.state, "api_key", None)
        if not api_key:
            raise UnauthorizedError("Authentication required")

        if isinstance(api_key, dict):
            granted_scopes: list[str] = api_key.get("scopes", [])
        else:
            granted_scopes = getattr(api_key, "scopes", [])

        # Wildcard or admin superuser scope
        if "*" in granted_scopes or "admin" in granted_scopes:
            return

        # Resource wildcard check (e.g. 'assets:*' matches 'assets:read')
        resource = required_scope.split(":")[0] if ":" in required_scope else ""
        if f"{resource}:*" in granted_scopes:
            return

        if required_scope not in granted_scopes:
            raise ForbiddenError(
                f"API key lacks the required scope '{required_scope}'",
                details={"required_scope": required_scope, "granted_scopes": granted_scopes},
            )

    return _scope_checker
