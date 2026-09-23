"""Manager profile settings and 2FA configuration routes."""

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.manager_controller import (
    change_manager_password,
    get_manager_by_id,
    update_manager_profile,
)
from controller.media_controller import handle_upload
from router.deps import get_db
from utils.errors import ValidationError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/profile", tags=["Manager Profile"])


@router.get("")
async def manager_profile_page(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render manager profile view."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    manager = await get_manager_by_id(db, session["user_id"])
    return templates.TemplateResponse(
        request=request,
        name="manager/profile/index.html",
        context={
            "session": session,
            "manager": manager,
            "error": None,
            "success": None,
            "active_tab": "profile",
        },
    )


@router.post("")
async def manager_profile_update_submit(
    request: Request,
    display_name: str | None = Form(default=None),
    avatar_file: UploadFile | None = File(default=None),
    current_password: str | None = Form(default=None),
    new_password: str | None = Form(default=None),
    confirm_password: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Update profile details (display name, avatar) and/or password. Username cannot be changed."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    error = None
    success = None

    # Handle avatar file upload if provided
    profile_pic_url = None
    if avatar_file and avatar_file.filename:
        try:
            content = await avatar_file.read()
            if content:
                uploaded = await handle_upload(
                    file_bytes=content,
                    filename=avatar_file.filename,
                    target_subdir="avatars",
                )
                profile_pic_url = uploaded.get("url")
        except Exception:
            pass

    # Update basic profile info
    await update_manager_profile(
        db,
        manager_id=user_id,
        display_name=display_name,
        profile_picture=profile_pic_url,
    )
    success = "Profile details updated successfully."

    # Handle password change if requested
    if current_password and new_password:
        try:
            await change_manager_password(
                db,
                manager_id=user_id,
                current_password=current_password,
                new_password=new_password,
                confirm_new_password=confirm_password,
            )
            success = "Profile and password updated successfully."
        except (UnauthorizedError, ValidationError) as err:
            error = err.message
            success = None

    if not error:
        return RedirectResponse(
            url="/manager/dashboard?msg=Profile+Updated+Successfully",
            status_code=303,
        )

    manager = await get_manager_by_id(db, user_id)
    return templates.TemplateResponse(
        request=request,
        name="manager/profile/index.html",
        context={
            "session": session,
            "manager": manager,
            "error": error,
            "success": None,
            "active_tab": "profile",
        },
    )


# =========================================================================
# 2FA Redirects to Settings
# =========================================================================

@router.get("/2fa/setup")
async def manager_2fa_setup_redirect() -> Response:
    """Redirect legacy 2FA setup route to new Settings page."""
    return RedirectResponse(url="/manager/settings/2fa/setup", status_code=301)


@router.post("/2fa/confirm")
async def manager_2fa_confirm_redirect() -> Response:
    """Redirect legacy 2FA confirm route to new Settings page."""
    return RedirectResponse(url="/manager/settings/2fa/setup", status_code=307)


@router.post("/2fa/disable")
async def manager_2fa_disable_redirect() -> Response:
    """Redirect legacy 2FA disable route to new Settings page."""
    return RedirectResponse(url="/manager/settings", status_code=307)
