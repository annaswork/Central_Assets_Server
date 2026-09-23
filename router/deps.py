"""Shared FastAPI router dependencies."""

from fastapi import Query, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from database.connection import get_database
from database.models.api_key import ApiKeyInDB
from utils.errors import UnauthorizedError
from utils.pagination import PageParams


def get_db() -> AsyncIOMotorDatabase:
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
