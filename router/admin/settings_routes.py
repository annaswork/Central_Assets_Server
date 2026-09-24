"""Admin panel routes for API key issuance and system settings."""

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
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


@router.get("/profile")
async def admin_profile_page(
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
        name="settings/profile.html",
        context={
            "session": session,
            "user": user,
            "error": error,
            "success": success,
            "active_tab": "profile",
        },
    )


@router.post("/profile")
async def admin_profile_update(
    request: Request,
    full_name: str | None = Form(default=None),
    email: str | None = Form(default=None),
    avatar_file: UploadFile | None = File(default=None),
    avatar_data_url: str | None = Form(default=None),
    remove_avatar: str | None = Form(default=None),
    action_type: str | None = Form(default=None),
    current_password: str | None = Form(default=None),
    new_password: str | None = Form(default=None),
    confirm_password: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    from authorization.encryption import hash_password, verify_password
    from controller.authorization_controller import get_admin_user_by_id
    from controller.media_controller import handle_upload
    from database.collections import ADMIN_USERS
    from utils.datetimes import utc_now_iso
    from utils.ids import to_object_id
    import urllib.parse
    import base64

    user_id = session["user_id"]
    oid = to_object_id(user_id)
    user = await get_admin_user_by_id(db, user_id)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=303)

    error = None
    update_fields = {"updated_at": utc_now_iso()}

    # 1. Update Name & Display Name
    if full_name is not None and full_name.strip():
        clean_name = full_name.strip()
        update_fields["full_name"] = clean_name
        update_fields["display_name"] = clean_name

    # 2. Update Email
    if email is not None:
        clean_email = email.strip().lower()
        update_fields["email"] = clean_email if clean_email else None

    # 3. Handle Avatar Removal or Upload
    if remove_avatar in ("1", "true", "yes"):
        update_fields["profile_picture"] = None
    elif avatar_data_url and avatar_data_url.startswith("data:image/"):
        try:
            header, base64_str = avatar_data_url.split(",", 1)
            file_bytes = base64.b64decode(base64_str)
            ext = "png"
            if "image/jpeg" in header or "image/jpg" in header:
                ext = "jpg"
            elif "image/webp" in header:
                ext = "webp"
            filename = f"avatar_{user['username']}.{ext}"
            uploaded = await handle_upload(
                file_bytes=file_bytes,
                filename=filename,
                target_subdir="profiles",
            )
            if uploaded.get("url"):
                update_fields["profile_picture"] = uploaded["url"]
        except Exception as e:
            error = f"Failed to save profile picture: {str(e)}"
    elif avatar_file and avatar_file.filename:
        try:
            content = await avatar_file.read()
            if content:
                uploaded = await handle_upload(
                    file_bytes=content,
                    filename=avatar_file.filename,
                    target_subdir="profiles",
                )
                if uploaded.get("url"):
                    update_fields["profile_picture"] = uploaded["url"]
        except Exception as e:
            error = f"Failed to upload avatar: {str(e)}"

    # 4. Handle Password if submitted in this form
    if current_password or new_password:
        if not current_password or not new_password:
            error = "Both current and new password are required to change password."
        elif new_password != confirm_password:
            error = "New passwords do not match."
        elif len(new_password) < 8:
            error = "New password must be at least 8 characters long."
        elif not verify_password(current_password, user.get("password_hash", "")):
            error = "Incorrect current password."
        else:
            update_fields["password_hash"] = hash_password(new_password)

    if not error:
        await db[ADMIN_USERS].update_one({"_id": oid}, {"$set": update_fields})
        return RedirectResponse(
            url="/admin/profile?success=Profile+details+updated+successfully",
            status_code=303,
        )

    # Re-fetch user in case of error
    user = await get_admin_user_by_id(db, user_id)
    return templates.TemplateResponse(
        request=request,
        name="settings/profile.html",
        context={
            "session": session,
            "user": user,
            "error": error,
            "success": None,
            "active_tab": "profile",
        },
    )


@router.post("/profile/password")
async def admin_profile_password_update(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Dedicated endpoint for admin password changes."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    from authorization.encryption import hash_password, verify_password
    from controller.authorization_controller import get_admin_user_by_id
    from database.collections import ADMIN_USERS
    from utils.datetimes import utc_now_iso
    from utils.ids import to_object_id

    user_id = session["user_id"]
    oid = to_object_id(user_id)
    user = await get_admin_user_by_id(db, user_id)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=303)

    error = None
    if not current_password or not new_password:
        error = "Both current and new password are required."
    elif new_password != confirm_password:
        error = "New passwords do not match."
    elif len(new_password) < 8:
        error = "New password must be at least 8 characters long."
    elif not verify_password(current_password, user.get("password_hash", "")):
        error = "Incorrect current password."

    if error:
        return templates.TemplateResponse(
            request=request,
            name="settings/profile.html",
            context={
                "session": session,
                "user": user,
                "error": error,
                "success": None,
                "active_tab": "profile",
            },
        )

    new_hash = hash_password(new_password)
    await db[ADMIN_USERS].update_one(
        {"_id": oid},
        {"$set": {"password_hash": new_hash, "updated_at": utc_now_iso()}},
    )

    return RedirectResponse(
        url="/admin/profile?success=Password+updated+successfully",
        status_code=303,
    )


