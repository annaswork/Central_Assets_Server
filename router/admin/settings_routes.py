"""Admin panel routes for API key issuance and system settings."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.constants import ALL_SCOPES
from config.paths import TEMPLATES_DIR
from config.settings import settings
from controller.app_instance_controller import list_app_instances
from controller.authorization_controller import (
    activate_key,
    create_key,
    delete_key,
    list_keys,
    revoke_key,
    update_key_rate_limit,
)
from database.models.api_key import ApiKeyCreate
from router.deps import get_db

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["Admin Settings & Keys"])


@router.get("/keys")
async def admin_list_keys(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    keys = await list_keys(db)
    instances = await list_app_instances(db, page=1, page_size=100)

    return templates.TemplateResponse(
        request=request,
        name="keys/list.html",
        context={
            "session": session,
            "keys": keys,
            "instances": instances.get("items", []),
            "scopes": ALL_SCOPES,
            "active_tab": "keys",
        },
    )


@router.post("/keys/new")
async def admin_create_key(
    request: Request,
    name: str = Form(...),
    app_instance_id: str | None = Form(default=None),
    scopes: list[str] = Form(default_factory=list),
    rate_limit_per_min: int = Form(default=60),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    key_out = await create_key(
        db,
        ApiKeyCreate(
            name=name,
            app_instance_id=app_instance_id or None,
            scopes=scopes,
            rate_limit_per_min=rate_limit_per_min,
        ),
    )

    return templates.TemplateResponse(
        request=request,
        name="keys/created.html",
        context={"session": session, "key": key_out, "active_tab": "keys"},
    )


@router.post("/keys/{id}/revoke")
async def admin_revoke_key(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    await revoke_key(db, key_id=id)
    return RedirectResponse(url="/admin/keys", status_code=303)


@router.post("/keys/{id}/activate")
async def admin_activate_key(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    await activate_key(db, key_id=id)
    return RedirectResponse(url="/admin/keys", status_code=303)


@router.post("/keys/{id}/delete")
async def admin_delete_key(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    await delete_key(db, key_id=id)
    return RedirectResponse(url="/admin/keys", status_code=303)


@router.post("/keys/{id}/rate-limit")
async def admin_update_key_rate_limit(
    request: Request,
    id: str,
    rate_limit_per_min: int = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    clamped = max(1, min(10000, rate_limit_per_min))
    await update_key_rate_limit(db, key_id=id, rate_limit=clamped)
    return RedirectResponse(url="/admin/keys", status_code=303)


@router.get("/settings")
async def admin_settings_page(
    request: Request,
    error: str | None = None,
    success: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    from controller.authorization_controller import get_admin_user_by_id

    user = await get_admin_user_by_id(db, session["user_id"])
    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={
            "session": session,
            "settings": settings,
            "user": user,
            "error": error,
            "success": success,
            "active_tab": "settings",
        },
    )


@router.get("/settings/2fa/setup")
async def admin_2fa_setup_page(
    request: Request, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    from controller.authorization_controller import initiate_2fa_setup

    setup_data = await initiate_2fa_setup(db, user_id=session["user_id"])
    return templates.TemplateResponse(
        request=request,
        name="settings/2fa_setup.html",
        context={
            "session": session,
            "secret": setup_data["secret"],
            "qr_code_url": setup_data["qr_code_url"],
            "error": None,
            "active_tab": "settings",
        },
    )


@router.post("/settings/2fa/confirm")
async def admin_2fa_confirm(
    request: Request,
    code: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    from controller.authorization_controller import confirm_and_enable_2fa, get_admin_user_by_id
    from utils.errors import ValidationError

    try:
        backup_codes = await confirm_and_enable_2fa(
            db, user_id=session["user_id"], code=code
        )
        return templates.TemplateResponse(
            request=request,
            name="settings/2fa_backup_codes.html",
            context={
                "session": session,
                "backup_codes": backup_codes,
                "active_tab": "settings",
            },
        )
    except ValidationError as err:
        from authorization.totp import generate_provisioning_uri, generate_qr_code_base64

        user = await get_admin_user_by_id(db, session["user_id"])
        temp_secret = user.get("totp_temp_secret", "")
        uri = generate_provisioning_uri(user["username"], temp_secret)
        qr_url = generate_qr_code_base64(uri)

        return templates.TemplateResponse(
            request=request,
            name="settings/2fa_setup.html",
            context={
                "session": session,
                "secret": temp_secret,
                "qr_code_url": qr_url,
                "error": err.message,
                "active_tab": "settings",
            },
            status_code=400,
        )


@router.post("/settings/2fa/disable")
async def admin_2fa_disable(
    request: Request,
    password: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    from controller.authorization_controller import disable_2fa
    from utils.errors import UnauthorizedError

    try:
        await disable_2fa(db, user_id=session["user_id"], password=password)
        return RedirectResponse(url="/admin/settings?success=2FA+has+been+disabled", status_code=303)
    except UnauthorizedError as err:
        return RedirectResponse(
            url=f"/admin/settings?error={err.message}", status_code=303
        )
