"""Admin operator authentication routes (login, logout)."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import (
    clear_admin_session_cookie,
    get_current_admin_session,
    set_admin_session_cookie,
)
from config.paths import TEMPLATES_DIR
from controller.authorization_controller import login_operator
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


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request) -> Response:
    response = RedirectResponse(url="/admin/login", status_code=303)
    clear_admin_session_cookie(response)
    return response
