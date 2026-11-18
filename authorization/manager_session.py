"""Manager session manager for server-rendered manager portal."""

from typing import Any

from fastapi import Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.encryption import read_session, sign_session, verify_password
from config.settings import settings
from database.collections import MANAGERS
from utils.errors import UnauthorizedError

MANAGER_SESSION_COOKIE_NAME: str = "manager_session"
MANAGER_SESSION_MAX_AGE_SECONDS: int = 86400  # 24 hours

MANAGER_2FA_COOKIE_NAME: str = "manager_2fa_pending"
MANAGER_2FA_MAX_AGE_SECONDS: int = 300  # 5 minutes


async def authenticate_manager_user(
    db: AsyncIOMotorDatabase, username: str, password: str
) -> dict[str, Any]:
    """Verify manager credentials, returning user document on success."""
    user = await db[MANAGERS].find_one({"username": username})
    if not user:
        raise UnauthorizedError("Invalid manager username or password")

    if not user.get("is_active", True) or user.get("status") in ["disabled", "inactive"]:
        raise UnauthorizedError("Manager account is inactive or disabled")

    if not verify_password(password, user["password_hash"]):
        raise UnauthorizedError("Invalid manager username or password")

    return user


def set_manager_session_cookie(response: Response, username: str, user_id: str) -> None:
    """Attach signed manager session cookie to HTTP response."""
    payload = {"username": username, "user_id": user_id, "role": "manager"}
    token = sign_session(payload)

    response.set_cookie(
        key=MANAGER_SESSION_COOKIE_NAME,
        value=token,
        max_age=MANAGER_SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


def clear_manager_session_cookie(response: Response) -> None:
    """Clear manager session cookie on logout."""
    response.delete_cookie(
        key=MANAGER_SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )


def get_current_manager_session(request: Request) -> dict[str, Any] | None:
    """Extract and verify manager session cookie from incoming request."""
    cookie = request.cookies.get(MANAGER_SESSION_COOKIE_NAME)
    if not cookie:
        return None
    data = read_session(cookie, max_age_seconds=MANAGER_SESSION_MAX_AGE_SECONDS)
    if not data or data.get("role") != "manager":
        return None
    return data


def set_manager_pre_auth_cookie(response: Response, username: str, user_id: str) -> None:
    """Attach temporary signed pre-auth cookie during manager 2FA verification."""
    payload = {"username": username, "user_id": user_id, "stage": "manager_2fa_pending", "role": "manager"}
    token = sign_session(payload)

    response.set_cookie(
        key=MANAGER_2FA_COOKIE_NAME,
        value=token,
        max_age=MANAGER_2FA_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


def clear_manager_pre_auth_cookie(response: Response) -> None:
    """Clear manager 2FA pre-auth cookie."""
    response.delete_cookie(
        key=MANAGER_2FA_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )


def get_current_manager_pre_auth_session(request: Request) -> dict[str, Any] | None:
    """Extract and verify manager 2FA pre-auth cookie from incoming request."""
    cookie = request.cookies.get(MANAGER_2FA_COOKIE_NAME)
    if not cookie:
        return None
    data = read_session(cookie, max_age_seconds=MANAGER_2FA_MAX_AGE_SECONDS)
    if not data or data.get("stage") != "manager_2fa_pending":
        return None
    return data
