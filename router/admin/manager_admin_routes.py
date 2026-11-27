from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.admin_manager_controller import (
    admin_reset_manager_password,
    admin_verify_and_reveal_manager_password,
    delete_manager_account,
    grant_instance_access,
    list_managers,
    revoke_instance_access,
    set_manager_central_access,
)
from controller.app_instance_controller import list_app_instances
from database.collections import ADMIN_USERS
from router.deps import extract_2fa_code, get_db
from utils.datetimes import format_datetime_display
from utils.errors import AppError, ConflictError, NotFoundError
from utils.ids import to_object_id

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/managers", tags=["Admin Manager Management"])


@router.get("")
async def admin_managers_list(
    request: Request,
    msg: str | None = Query(default=None),
    msg_type: str | None = Query(default="info"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """List all Manager accounts with instance assignments."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    managers = await list_managers(db)
    instances_res = await list_app_instances(db, page=1, page_size=500)
    all_instances = instances_res.get("items", [])

    admin_user = await db[ADMIN_USERS].find_one({"_id": to_object_id(session.get("user_id"))})
    admin_has_2fa = bool(admin_user and admin_user.get("is_2fa_enabled") and admin_user.get("totp_secret"))

    return templates.TemplateResponse(
        request=request,
        name="admin/managers/list.html",
        context={
            "session": session,
            "managers": managers,
            "all_instances": all_instances,
            "admin_has_2fa": admin_has_2fa,
            "active_tab": "managers",
            "flash_message": msg,
            "flash_type": msg_type,
        },
    )


@router.post("/{manager_id}/grant-access")
async def admin_grant_access(
    manager_id: str,
    request: Request,
    app_instance_id: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Grant manager access to an app instance."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        res = await grant_instance_access(
            db, manager_id=manager_id, app_instance_id=app_instance_id, admin_id=session.get("user_id")
        )
        msg = quote_plus(res.get("message", "Access granted successfully."))
        return RedirectResponse(url=f"/admin/managers?msg={msg}&msg_type=success", status_code=303)
    except (NotFoundError, ConflictError) as e:
        msg = quote_plus(e.message)
        return RedirectResponse(url=f"/admin/managers?msg={msg}&msg_type=error", status_code=303)


@router.post("/{manager_id}/revoke-access")
async def admin_revoke_access(
    manager_id: str,
    request: Request,
    app_instance_id: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Revoke manager access to an app instance."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    res = await revoke_instance_access(db, manager_id=manager_id, app_instance_id=app_instance_id)
    msg = quote_plus(res.get("message", "Access revoked successfully."))
    return RedirectResponse(url=f"/admin/managers?msg={msg}&msg_type=success", status_code=303)


@router.post("/{manager_id}/delete")
async def admin_delete_manager(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Delete manager account and clean up resources."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        res = await delete_manager_account(db, manager_id=manager_id, admin_id=session["user_id"])
        msg = quote_plus(res.get("message", "Manager deleted successfully."))
        return RedirectResponse(url=f"/admin/managers?msg={msg}&msg_type=success", status_code=303)
    except NotFoundError as e:
        msg = quote_plus(e.message)
        return RedirectResponse(url=f"/admin/managers?msg={msg}&msg_type=error", status_code=303)


@router.post("/{manager_id}/view-password")
async def admin_view_manager_password(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Verify admin 2FA and reveal manager password."""
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "detail": "Session expired. Please log in again."})

    code = await extract_2fa_code(request)

    try:
        res = await admin_verify_and_reveal_manager_password(
            db, admin_id=session["user_id"], manager_id=manager_id, two_factor_code=code
        )
        return JSONResponse(status_code=200, content=res)
    except AppError as e:
        return JSONResponse(status_code=e.status_code, content={"success": False, "detail": e.message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "detail": f"Unexpected error: {str(e)}"})


def _parse_bool_flag(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    if s in {"1", "true", "yes", "on", "allow", "allowed"}:
        return True
    if s in {"0", "false", "no", "off", "restrict", "restricted", "deny", "denied"}:
        return False
    return True


@router.post("/{manager_id}/central-access")
async def admin_set_manager_central_access(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Allow or restrict a manager account from viewing or accessing Central Data."""
    session = get_current_admin_session(request)
    is_json_request = "application/json" in request.headers.get("content-type", "").lower() or (
        "application/json" in request.headers.get("accept", "").lower()
    )
    if not session:
        if is_json_request:
            return JSONResponse(status_code=401, content={"success": False, "detail": "Unauthorized"})
        return RedirectResponse(url="/admin/login", status_code=303)

    can_access_raw: object = True
    try:
        if "application/json" in request.headers.get("content-type", "").lower():
            data = await request.json()
            can_access_raw = data.get("can_access_central_data", data.get("can_access", False))
        else:
            form = await request.form()
            can_access_raw = form.get("can_access_central_data") or form.get("can_access") or "false"
    except Exception:
        can_access_raw = False

    can_access = _parse_bool_flag(can_access_raw)

    try:
        updated = await set_manager_central_access(db, manager_id=manager_id, can_access=can_access)
    except NotFoundError as e:
        if is_json_request:
            return JSONResponse(status_code=404, content={"success": False, "detail": e.message})
        msg = quote_plus(e.message)
        return RedirectResponse(url=f"/admin/managers?msg={msg}&msg_type=error", status_code=303)

    status_label = "allowed" if updated["can_access_central_data"] else "restricted"
    message = f"Central Data access for '{updated['username']}' is now {status_label}."
    if is_json_request:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "manager_id": updated["id"],
                "username": updated["username"],
                "can_access_central_data": updated["can_access_central_data"],
                "message": message,
            },
        )
    return RedirectResponse(
        url=f"/admin/managers?msg={quote_plus(message)}&msg_type=success",
        status_code=303,
    )


@router.post("/{manager_id}/reset-password")
async def admin_reset_manager_password_route(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Verify admin 2FA and set/reset manager password."""
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "detail": "Session expired. Please log in again."})

    code = ""
    new_password = ""
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
            code = data.get("code", "")
            new_password = data.get("new_password", "")
        else:
            form = await request.form()
            code = str(form.get("code", ""))
            new_password = str(form.get("new_password", ""))
    except Exception:
        pass

    try:
        res = await admin_reset_manager_password(
            db,
            admin_id=session["user_id"],
            manager_id=manager_id,
            two_factor_code=code,
            new_password=new_password,
        )
        return JSONResponse(status_code=200, content=res)
    except AppError as e:
        return JSONResponse(status_code=e.status_code, content={"success": False, "detail": e.message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "detail": f"Unexpected error: {str(e)}"})


def _parse_bool_flag(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    if s in {"1", "true", "yes", "on", "allow", "allowed"}:
        return True
    if s in {"0", "false", "no", "off", "restrict", "restricted", "deny", "denied"}:
        return False
    return True


@router.post("/{manager_id}/central-access")
async def admin_set_manager_central_access(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Allow or restrict a manager account from viewing or accessing Central Data."""
    session = get_current_admin_session(request)
    is_json_request = "application/json" in request.headers.get("content-type", "").lower() or (
        "application/json" in request.headers.get("accept", "").lower()
    )
    if not session:
        if is_json_request:
            return JSONResponse(status_code=401, content={"success": False, "detail": "Unauthorized"})
        return RedirectResponse(url="/admin/login", status_code=303)

    can_access_raw: object = True
    try:
        if "application/json" in request.headers.get("content-type", "").lower():
            data = await request.json()
            can_access_raw = data.get("can_access_central_data", data.get("can_access", False))
        else:
            form = await request.form()
            can_access_raw = form.get("can_access_central_data") or form.get("can_access") or "false"
    except Exception:
        can_access_raw = False

    can_access = _parse_bool_flag(can_access_raw)

    try:
        updated = await set_manager_central_access(db, manager_id=manager_id, can_access=can_access)
    except NotFoundError as e:
        if is_json_request:
            return JSONResponse(status_code=404, content={"success": False, "detail": e.message})
        msg = quote_plus(e.message)
        return RedirectResponse(url=f"/admin/managers?msg={msg}&msg_type=error", status_code=303)

    status_label = "allowed" if updated["can_access_central_data"] else "restricted"
    message = f"Central Data access for '{updated['username']}' is now {status_label}."
    if is_json_request:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "manager_id": updated["id"],
                "username": updated["username"],
                "can_access_central_data": updated["can_access_central_data"],
                "message": message,
            },
        )
    return RedirectResponse(
        url=f"/admin/managers?msg={quote_plus(message)}&msg_type=success",
        status_code=303,
    )

