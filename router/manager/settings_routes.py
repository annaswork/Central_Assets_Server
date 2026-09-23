"""Manager portal settings and 2FA configuration routes."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.manager_controller import (
    confirm_and_enable_manager_2fa,
    disable_manager_2fa,
    get_manager_by_id,
    initiate_manager_2fa,
)
from router.deps import get_db
from utils.errors import UnauthorizedError, ValidationError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/settings", tags=["Manager Settings"])


@router.get("")
async def manager_settings_page(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render manager settings page with 2FA security, theme toggle, and account overview."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)
    error = request.query_params.get("error")
    success = request.query_params.get("success")

    return templates.TemplateResponse(
        request=request,
        name="manager/settings/index.html",
        context={
            "session": session,
            "manager": manager,
            "error": error,
            "success": success,
            "active_tab": "settings",
        },
    )


# =========================================================================
# 2FA Enrollment & Disabling
# =========================================================================

@router.get("/2fa/setup")
async def manager_2fa_setup_page(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Show 2FA setup QR code and secret key."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)
    setup_data = await initiate_manager_2fa(db, user_id)

    return templates.TemplateResponse(
        request=request,
        name="manager/settings/2fa_setup.html",
        context={
            "session": session,
            "manager": manager,
            "setup": setup_data,
            "error": None,
            "active_tab": "settings",
        },
    )


@router.post("/2fa/confirm")
async def manager_2fa_confirm_submit(
    request: Request,
    code: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Verify submitted code and activate 2FA."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    try:
        backup_codes = await confirm_and_enable_manager_2fa(db, user_id, code=code)
        return templates.TemplateResponse(
            request=request,
            name="manager/settings/2fa_backup_codes.html",
            context={
                "session": session,
                "manager": manager,
                "backup_codes": backup_codes,
                "active_tab": "settings",
            },
        )
    except ValidationError as err:
        setup_data = await initiate_manager_2fa(db, user_id)
        return templates.TemplateResponse(
            request=request,
            name="manager/settings/2fa_setup.html",
            context={
                "session": session,
                "manager": manager,
                "setup": setup_data,
                "error": err.message,
                "active_tab": "settings",
            },
            status_code=400,
        )


@router.post("/2fa/disable")
async def manager_2fa_disable_submit(
    request: Request,
    password: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Disable 2FA after password confirmation."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    try:
        await disable_manager_2fa(db, user_id, password=password)
        return RedirectResponse(url="/manager/settings?success=Two-factor+authentication+has+been+disabled.", status_code=303)
    except UnauthorizedError as err:
        manager = await get_manager_by_id(db, user_id)
        return templates.TemplateResponse(
            request=request,
            name="manager/settings/index.html",
            context={
                "session": session,
                "manager": manager,
                "error": err.message,
                "success": None,
                "active_tab": "settings",
            },
            status_code=401,
        )
