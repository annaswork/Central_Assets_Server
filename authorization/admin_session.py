"""Admin operator session manager for server-rendered admin panel."""

from typing import Any

from fastapi import Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.encryption import read_session, sign_session, verify_password
from config.settings import settings
from database.collections import ADMIN_USERS
from utils.errors import UnauthorizedError


async def authenticate_admin_user(
    db: AsyncIOMotorDatabase, username: str, password: str
) -> dict[str, Any]:
    """Verify operator credentials, returning user document on success."""
    user = await db[ADMIN_USERS].find_one({"username": username})
    if not user:
        raise UnauthorizedError("Invalid operator username or password")

    if not user.get("is_active", True):
        raise UnauthorizedError("Operator account is deactivated")

    if not verify_password(password, user["password_hash"]):
        raise UnauthorizedError("Invalid operator username or password")

    return user


def set_admin_session_cookie(response: Response, username: str, user_id: str) -> None:
    """Attach signed session cookie to HTTP response."""
    payload = {"username": username, "user_id": user_id}
    token = sign_session(payload)

    response.set_cookie(
        key=settings.ADMIN_SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.ADMIN_SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


def clear_admin_session_cookie(response: Response) -> None:
    """Clear session cookie on logout."""
    response.delete_cookie(
        key=settings.ADMIN_SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )


def get_current_admin_session(request: Request) -> dict[str, Any] | None:
    """Extract and verify session cookie from incoming request."""
    cookie = request.cookies.get(settings.ADMIN_SESSION_COOKIE_NAME)
    if not cookie:
        return None
    return read_session(cookie)
