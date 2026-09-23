"""Admin messaging routes for communicating with Managers and reviewing proposals."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.admin_manager_controller import (
    admin_reply_message,
    apply_message_proposal_to_central,
    clear_conversation,
    delete_chat_thread,
    get_thread_messages,
    list_message_threads,
)
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import NotFoundError, ValidationError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/messages", tags=["Admin Messaging"])


@router.get("")
async def admin_message_threads(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View all manager message threads."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    threads = await list_message_threads(db)
    if threads and len(threads) > 0:
        return RedirectResponse(url=f"/admin/messages/{threads[0]['manager_id']}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="admin/messages/index.html",
        context={
            "session": session,
            "threads": threads,
            "current_thread": None,
            "messages": [],
            "active_tab": "messages",
        },
    )


@router.get("/{manager_id}")
async def admin_thread_detail(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View thread with a specific manager."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    threads = await list_message_threads(db)
    try:
        manager, messages = await get_thread_messages(db, manager_id)
    except NotFoundError:
        return RedirectResponse(url="/admin/messages", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="admin/messages/index.html",
        context={
            "session": session,
            "threads": threads,
            "current_thread": manager,
            "messages": messages,
            "active_tab": "messages",
        },
    )


@router.post("/{manager_id}/reply")
async def admin_send_reply(
    manager_id: str,
    request: Request,
    content: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Send admin reply into manager thread."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    admin_name = session.get("username", "Administrator")
    admin_id = session.get("user_id", "")

    try:
        await admin_reply_message(
            db,
            manager_id=manager_id,
            admin_id=admin_id,
            admin_name=admin_name,
            content=content,
        )
    except (ValidationError, NotFoundError):
        pass

    return RedirectResponse(url=f"/admin/messages/{manager_id}", status_code=303)


@router.post("/{message_id}/apply-proposal")
async def admin_apply_proposal(
    message_id: str,
    request: Request,
    manager_id: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Approve and apply a manager's structured proposal into central data."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        await apply_message_proposal_to_central(db, message_id=message_id)
    except Exception:
        pass

    return RedirectResponse(url=f"/admin/messages/{manager_id}", status_code=303)


@router.post("/{manager_id}/clear")
async def admin_clear_conversation(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Clear all messages in the conversation thread with this manager."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        await clear_conversation(db, manager_id=manager_id)
    except Exception:
        pass

    return RedirectResponse(url=f"/admin/messages/{manager_id}?msg=Conversation+cleared", status_code=303)


@router.post("/{manager_id}/delete")
async def admin_delete_chat(
    manager_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Delete this chat thread completely from admin inbox."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        await delete_chat_thread(db, manager_id=manager_id)
    except Exception:
        pass

    return RedirectResponse(url="/admin/messages?msg=Chat+deleted", status_code=303)

