"""Admin portal Access Request Queue routes."""

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.admin_manager_controller import (
    approve_access_request,
    deny_access_request,
    list_access_requests,
)
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import NotFoundError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/access-requests", tags=["Admin Access Requests"])


@router.get("")
async def admin_access_requests_queue(
    request: Request,
    status: str = Query(default="pending"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View incoming access requests from managers."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    requests = await list_access_requests(db, status=status)

    return templates.TemplateResponse(
        request=request,
        name="admin/access_requests/index.html",
        context={
            "session": session,
            "requests": requests,
            "current_status": status,
            "active_tab": "access_requests",
        },
    )


@router.post("/{request_id}/approve")
async def admin_approve_request(
    request_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Approve a manager's access request."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        await approve_access_request(db, request_id=request_id, admin_id=session.get("user_id"))
    except NotFoundError:
        pass

    return RedirectResponse(url="/admin/access-requests", status_code=303)


@router.post("/{request_id}/deny")
async def admin_deny_request(
    request_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Deny a manager's access request."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        await deny_access_request(db, request_id=request_id, admin_id=session.get("user_id"))
    except NotFoundError:
        pass

    return RedirectResponse(url="/admin/access-requests", status_code=303)
