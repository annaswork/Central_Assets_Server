from fastapi import APIRouter, Depends, Form, Request, Response
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
)
from controller.app_instance_controller import list_app_instances
from database.collections import ADMIN_USERS
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import AppError, ConflictError, NotFoundError
from utils.ids import to_object_id

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/managers", tags=["Admin Manager Management"])


@router.get("")
async def admin_managers_list(
    request: Request,
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
        await grant_instance_access(
            db, manager_id=manager_id, app_instance_id=app_instance_id, admin_id=session.get("user_id")
        )
    except (NotFoundError, ConflictError):
        pass

    return RedirectResponse(url="/admin/managers", status_code=303)


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

    await revoke_instance_access(db, manager_id=manager_id, app_instance_id=app_instance_id)
    return RedirectResponse(url="/admin/managers", status_code=303)


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
        await delete_manager_account(db, manager_id=manager_id)
    except NotFoundError:
        pass

    return RedirectResponse(url="/admin/managers", status_code=303)


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

    code = ""
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
            code = data.get("code", "")
        else:
            form = await request.form()
            code = str(form.get("code", ""))
    except Exception:
        code = ""

    try:
        res = await admin_verify_and_reveal_manager_password(
            db, admin_id=session["user_id"], manager_id=manager_id, two_factor_code=code
        )
        return JSONResponse(status_code=200, content=res)
    except AppError as e:
        return JSONResponse(status_code=e.status_code, content={"success": False, "detail": e.message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "detail": f"Unexpected error: {str(e)}"})


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

