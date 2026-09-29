"""Admin portal Access Request Queue routes."""

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Query, Request, Response
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
    msg: str | None = Query(default=None),
    msg_type: str | None = Query(default="info"),
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
            "flash_message": msg,
            "flash_type": msg_type,
            "active_tab": "access_requests",
        },
    )


@router.post("/{request_id}/approve")
async def admin_approve_request(
    request_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Approve a manager's access or app creation request."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        res = await approve_access_request(db, request_id=request_id, admin_id=session.get("user_id"))
        msg = res.get("message", "Request approved successfully.")
        return RedirectResponse(
            url=f"/admin/access-requests?msg={quote_plus(msg)}&msg_type=success",
            status_code=303,
        )
    except Exception as err:
        return RedirectResponse(
            url=f"/admin/access-requests?msg={quote_plus(str(err))}&msg_type=error",
            status_code=303,
        )


@router.post("/{request_id}/deny")
async def admin_deny_request(
    request_id: str,
    request: Request,
    reason: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Deny a manager's access or app creation request."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        res = await deny_access_request(
            db, request_id=request_id, admin_id=session.get("user_id"), reason=reason
        )
        msg = res.get("message", "Request denied.")
        return RedirectResponse(
            url=f"/admin/access-requests?msg={quote_plus(msg)}&msg_type=info",
            status_code=303,
        )
    except Exception as err:
        return RedirectResponse(
            url=f"/admin/access-requests?msg={quote_plus(str(err))}&msg_type=error",
            status_code=303,
        )
