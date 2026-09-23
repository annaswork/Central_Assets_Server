"""Admin operator authentication routes (login, 2FA, logout)."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import (
    clear_admin_pre_auth_cookie,
    clear_admin_session_cookie,
    get_current_admin_session,
    get_current_pre_auth_session,
    set_admin_pre_auth_cookie,
    set_admin_session_cookie,
)
from config.paths import TEMPLATES_DIR
from controller.authorization_controller import login_operator, verify_login_2fa
from router.deps import get_db
from utils.errors import UnauthorizedError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["Admin Auth"])


@router.get("/login")
async def login_page(request: Request) -> Response:
    session = get_current_admin_session(request)
    if session:
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        request=request, name="auth/login.html", context={"error": None}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    try:
        user = await login_operator(db, username=username, password=password)

        # If user has 2FA enabled, issue temporary pre-auth token and redirect to 2FA challenge
        if user.get("is_2fa_enabled"):
            response = RedirectResponse(url="/admin/login/2fa", status_code=303)
            set_admin_pre_auth_cookie(
                response, username=user["username"], user_id=str(user["_id"])
            )
            return response

        # Standard direct login
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        set_admin_session_cookie(response, username=user["username"], user_id=str(user["_id"]))
        return response
    except UnauthorizedError as err:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": err.message, "username": username},
            status_code=401,
        )


@router.get("/login/2fa")
async def login_2fa_page(request: Request) -> Response:
    pre_auth = get_current_pre_auth_session(request)
    if not pre_auth:
        return RedirectResponse(url="/admin/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="auth/login_2fa.html",
        context={"error": None, "username": pre_auth.get("username", "Operator")},
    )


@router.post("/login/2fa")
async def login_2fa_submit(
    request: Request,
    code: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    pre_auth = get_current_pre_auth_session(request)
    if not pre_auth:
        return RedirectResponse(url="/admin/login", status_code=303)

    user_id = pre_auth["user_id"]
    username = pre_auth.get("username", "Operator")

    try:
        user = await verify_login_2fa(db, user_id=user_id, code=code)
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        set_admin_session_cookie(response, username=user["username"], user_id=str(user["_id"]))
        clear_admin_pre_auth_cookie(response)
        return response
    except UnauthorizedError as err:
        return templates.TemplateResponse(
            request=request,
            name="auth/login_2fa.html",
            context={"error": err.message, "username": username},
            status_code=401,
        )


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request) -> Response:
    response = RedirectResponse(url="/admin/login", status_code=303)
    clear_admin_session_cookie(response)
    clear_admin_pre_auth_cookie(response)
    return response
