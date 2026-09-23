"""Manager authentication and registration routes."""

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import (
    clear_manager_pre_auth_cookie,
    clear_manager_session_cookie,
    get_current_manager_pre_auth_session,
    get_current_manager_session,
    set_manager_pre_auth_cookie,
    set_manager_session_cookie,
)
from config.paths import TEMPLATES_DIR
from controller.manager_controller import (
    check_username_available,
    login_manager,
    register_manager,
    verify_manager_login_2fa,
)
from database.models.manager_user import ManagerUserCreate
from router.deps import get_db
from utils.errors import ConflictError, UnauthorizedError, ValidationError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["Manager Auth"])


@router.get("/register")
async def register_page(request: Request) -> Response:
    """Render manager registration page."""
    session = get_current_manager_session(request)
    if session:
        return RedirectResponse(url="/manager/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="manager/auth/register.html",
        context={"error": None, "username": "", "email": ""},
    )


@router.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str | None = Form(default=None),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Handle manager account registration."""
    try:
        data = ManagerUserCreate(
            username=username,
            email=email.strip() if email and email.strip() else None,
            password=password,
            confirm_password=confirm_password,
        )
        manager = await register_manager(db, data)

        # Login immediately upon active registration
        response = RedirectResponse(url="/manager/dashboard", status_code=303)
        set_manager_session_cookie(response, username=manager["username"], user_id=manager["id"])
        return response

    except (ValidationError, ConflictError) as err:
        return templates.TemplateResponse(
            request=request,
            name="manager/auth/register.html",
            context={
                "error": err.message,
                "username": username,
                "email": email or "",
            },
            status_code=400 if isinstance(err, ValidationError) else 409,
        )


@router.get("/login")
async def login_page(request: Request) -> Response:
    """Render manager login page."""
    session = get_current_manager_session(request)
    if session:
        return RedirectResponse(url="/manager/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="manager/auth/login.html",
        context={"error": None, "username": ""},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Handle manager login."""
    try:
        user = await login_manager(db, username=username, password=password)

        if user.get("is_2fa_enabled"):
            response = RedirectResponse(url="/manager/login/2fa", status_code=303)
            set_manager_pre_auth_cookie(
                response, username=user["username"], user_id=str(user["_id"])
            )
            return response

        # Standard direct login
        response = RedirectResponse(url="/manager/dashboard", status_code=303)
        set_manager_session_cookie(response, username=user["username"], user_id=str(user["_id"]))
        return response

    except UnauthorizedError as err:
        return templates.TemplateResponse(
            request=request,
            name="manager/auth/login.html",
            context={"error": err.message, "username": username},
            status_code=401,
        )


@router.get("/login/2fa")
async def login_2fa_page(request: Request) -> Response:
    """Render manager 2FA challenge page."""
    pre_auth = get_current_manager_pre_auth_session(request)
    if not pre_auth:
        return RedirectResponse(url="/manager/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="manager/auth/login_2fa.html",
        context={"error": None, "username": pre_auth.get("username", "Manager")},
    )


@router.post("/login/2fa")
async def login_2fa_submit(
    request: Request,
    code: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Verify manager 2FA code or backup code."""
    pre_auth = get_current_manager_pre_auth_session(request)
    if not pre_auth:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = pre_auth["user_id"]
    username = pre_auth.get("username", "Manager")

    try:
        user = await verify_manager_login_2fa(db, user_id=user_id, code=code)
        response = RedirectResponse(url="/manager/dashboard", status_code=303)
        set_manager_session_cookie(response, username=user["username"], user_id=str(user["_id"]))
        clear_manager_pre_auth_cookie(response)
        return response
    except UnauthorizedError as err:
        return templates.TemplateResponse(
            request=request,
            name="manager/auth/login_2fa.html",
            context={"error": err.message, "username": username},
            status_code=401,
        )


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request) -> Response:
    """Log out manager and clear cookies."""
    response = RedirectResponse(url="/manager/login", status_code=303)
    clear_manager_session_cookie(response)
    clear_manager_pre_auth_cookie(response)
    return response


# =========================================================================
# Live Username Check API
# =========================================================================

api_router = APIRouter(prefix="/api/manager", tags=["Manager API"])


@api_router.get("/check-username")
async def check_username_api(
    u: str = Query(default="", min_length=1),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Async check for username availability during manager registration."""
    res = await check_username_available(db, username=u)
    return JSONResponse(content=res)
