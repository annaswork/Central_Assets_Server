"""Shared FastAPI router dependencies."""

from fastapi import Depends, Query, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from database.connection import get_database
from database.models.api_key import ApiKeyInDB
from utils.errors import UnauthorizedError
from utils.pagination import PageParams


async def get_db() -> AsyncIOMotorDatabase:
    """Dependency returning the active MongoDB database instance."""
    return get_database()


def get_current_api_key(request: Request) -> ApiKeyInDB:
    """Dependency returning the authenticated API key attached to request.state."""
    api_key = getattr(request.state, "api_key", None)
    if not api_key:
        raise UnauthorizedError("API key authentication required")
    return api_key


def get_pagination(
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Page size (max 100)"),
) -> PageParams:
    """Dependency extracting and validating pagination parameters."""
    return PageParams(page=page, page_size=page_size)


async def get_current_manager(
    request: Request, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    """Dependency returning authenticated manager document from database."""
    from authorization.manager_session import get_current_manager_session
    from database.collections import MANAGERS
    from utils.ids import to_object_id

    session = get_current_manager_session(request)
    if not session:
        raise UnauthorizedError("Manager authentication required")

    user_id = session.get("user_id")
    if not user_id:
        raise UnauthorizedError("Invalid manager session")

    user = await db[MANAGERS].find_one({"_id": to_object_id(user_id)})
    if not user or not user.get("is_active", True) or user.get("status") in ["disabled", "inactive"]:
        raise UnauthorizedError("Manager account is inactive or not found")

    return user


async def get_current_admin(
    request: Request, db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    """Dependency returning authenticated admin operator document from database."""
    from authorization.admin_session import get_current_admin_session
    from database.collections import ADMIN_USERS
    from utils.ids import to_object_id

    session = get_current_admin_session(request)
    if not session:
        raise UnauthorizedError("Admin authentication required")

    user_id = session.get("user_id")
    if not user_id:
        raise UnauthorizedError("Invalid admin session")

    user = await db[ADMIN_USERS].find_one({"_id": to_object_id(user_id)})
    if not user or not user.get("is_active", True):
        raise UnauthorizedError("Admin operator is inactive or not found")

    return user


def require_role(role: str):
    """Enforces role check ('admin' or 'manager') on route."""
    from authorization.admin_session import get_current_admin_session
    from authorization.manager_session import get_current_manager_session
    from utils.errors import ForbiddenError

    async def _role_checker(request: Request) -> dict:
        if role == "admin":
            session = get_current_admin_session(request)
            if not session:
                raise UnauthorizedError("Admin session required")
            return session
        elif role == "manager":
            session = get_current_manager_session(request)
            if not session:
                raise UnauthorizedError("Manager session required")
            return session
        else:
            raise ForbiddenError(f"Unknown role requirement: {role}")

    return _role_checker

