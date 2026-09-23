"""Admin portal Manager user management routes."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.admin_manager_controller import (
    delete_manager_account,
    grant_instance_access,
    list_managers,
    revoke_instance_access,
)
from controller.app_instance_controller import list_app_instances
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import ConflictError, NotFoundError

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

    return templates.TemplateResponse(
        request=request,
        name="admin/managers/list.html",
        context={
            "session": session,
            "managers": managers,
            "all_instances": all_instances,
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
