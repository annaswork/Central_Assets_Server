"""Admin messaging routes for communicating with Managers and reviewing proposals, and Admin Team cross-communication."""

from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.admin_manager_controller import (
    admin_reply_message,
    apply_message_proposal_to_central,
    clear_admin_direct_conversation,
    clear_conversation,
    delete_chat_thread,
    get_admin_direct_messages,
    get_thread_messages,
    list_admin_conversations,
    list_message_threads,
    send_admin_direct_message,
)
from controller.category_controller import list_categories
from controller.subcategory_controller import list_subcategories
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
    """View manager message threads or redirect appropriately."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    tab = request.query_params.get("tab")
    if tab == "team":
        return RedirectResponse(url="/admin/messages/team", status_code=303)

    admin_id = session.get("user_id", "")
    threads = await list_message_threads(db)
    admin_conversations = await list_admin_conversations(db, current_admin_id=admin_id)

    if threads and len(threads) > 0:
        return RedirectResponse(url=f"/admin/messages/{threads[0]['manager_id']}", status_code=303)

    # If no manager threads exist, but admin conversations exist, default to team
    if admin_conversations and len(admin_conversations) > 0:
        return RedirectResponse(url=f"/admin/messages/team/{admin_conversations[0]['admin_id']}", status_code=303)

    categories_res = await list_categories(db, page=1, page_size=200)
    subcategories_res = await list_subcategories(db, page=1, page_size=500)

    unread_manager_count = sum(th.get("unread_count", 0) for th in threads)
    unread_team_count = sum(conv.get("unread_count", 0) for conv in admin_conversations)

    return templates.TemplateResponse(
        request=request,
        name="admin/messages/index.html",
        context={
            "session": session,
            "chat_mode": "manager",
            "threads": threads,
            "admin_conversations": admin_conversations,
            "unread_manager_count": unread_manager_count,
            "unread_team_count": unread_team_count,
            "current_thread": None,
            "messages": [],
            "categories": categories_res.get("items", []),
            "subcategories": subcategories_res.get("items", []),
            "active_tab": "messages",
        },
    )


# -------------------------------------------------------------------------
# Admin Team Direct Messages (Admin ↔ Admin)
# -------------------------------------------------------------------------

@router.get("/team")
async def admin_team_threads(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View Admin team conversations (admin to admin)."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    admin_id = session.get("user_id", "")
    admin_conversations = await list_admin_conversations(db, current_admin_id=admin_id)
    if admin_conversations and len(admin_conversations) > 0:
        return RedirectResponse(url=f"/admin/messages/team/{admin_conversations[0]['admin_id']}", status_code=303)

    threads = await list_message_threads(db)
    unread_manager_count = sum(th.get("unread_count", 0) for th in threads)
    unread_team_count = sum(conv.get("unread_count", 0) for conv in admin_conversations)

    return templates.TemplateResponse(
        request=request,
        name="admin/messages/index.html",
        context={
            "session": session,
            "chat_mode": "admin",
            "threads": threads,
            "admin_conversations": admin_conversations,
            "unread_manager_count": unread_manager_count,
            "unread_team_count": unread_team_count,
            "current_thread": None,
            "messages": [],
            "categories": [],
            "subcategories": [],
            "active_tab": "messages",
        },
    )


@router.get("/team/{other_admin_id}")
async def admin_team_detail(
    other_admin_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View direct chat thread with a fellow administrator."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    current_admin_id = session.get("user_id", "")
    admin_conversations = await list_admin_conversations(db, current_admin_id=current_admin_id)
    threads = await list_message_threads(db)

    try:
        other_admin, messages = await get_admin_direct_messages(
            db, current_admin_id=current_admin_id, other_admin_id=other_admin_id
        )
    except NotFoundError:
        return RedirectResponse(url="/admin/messages/team", status_code=303)

    unread_manager_count = sum(th.get("unread_count", 0) for th in threads)
    unread_team_count = sum(conv.get("unread_count", 0) for conv in admin_conversations)

    return templates.TemplateResponse(
        request=request,
        name="admin/messages/index.html",
        context={
            "session": session,
            "chat_mode": "admin",
            "threads": threads,
            "admin_conversations": admin_conversations,
            "unread_manager_count": unread_manager_count,
            "unread_team_count": unread_team_count,
            "current_thread": other_admin,
            "messages": messages,
            "categories": [],
            "subcategories": [],
            "active_tab": "messages",
        },
    )


@router.post("/team/{other_admin_id}/send")
async def admin_send_team_message(
    other_admin_id: str,
    request: Request,
    content: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Send direct message to a fellow administrator."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    sender_id = session.get("user_id", "")
    admin_name = session.get("username", "Administrator")
    if hasattr(request.state, "current_user") and request.state.current_user:
        admin_name = request.state.current_user.get("name") or admin_name

    try:
        await send_admin_direct_message(
            db,
            sender_id=sender_id,
            sender_name=admin_name,
            recipient_id=other_admin_id,
            content=content,
        )
    except (ValidationError, NotFoundError) as e:
        return RedirectResponse(
            url=f"/admin/messages/team/{other_admin_id}?error={quote_plus(str(e))}",
            status_code=303,
        )

    return RedirectResponse(url=f"/admin/messages/team/{other_admin_id}", status_code=303)


@router.post("/team/{other_admin_id}/clear")
async def admin_clear_team_conversation(
    other_admin_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Clear all direct messages between current admin and another admin."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    current_admin_id = session.get("user_id", "")
    try:
        await clear_admin_direct_conversation(
            db, current_admin_id=current_admin_id, other_admin_id=other_admin_id
        )
    except Exception:
        pass

    return RedirectResponse(
        url=f"/admin/messages/team/{other_admin_id}?msg=Conversation+cleared",
        status_code=303,
    )


# -------------------------------------------------------------------------
# Manager Messages & Proposals
# -------------------------------------------------------------------------

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

    current_admin_id = session.get("user_id", "")
    threads = await list_message_threads(db)
    admin_conversations = await list_admin_conversations(db, current_admin_id=current_admin_id)

    try:
        manager, messages = await get_thread_messages(db, manager_id)
    except NotFoundError:
        return RedirectResponse(url="/admin/messages", status_code=303)

    categories_res = await list_categories(db, page=1, page_size=200)
    subcategories_res = await list_subcategories(db, page=1, page_size=500)

    unread_manager_count = sum(th.get("unread_count", 0) for th in threads)
    unread_team_count = sum(conv.get("unread_count", 0) for conv in admin_conversations)

    return templates.TemplateResponse(
        request=request,
        name="admin/messages/index.html",
        context={
            "session": session,
            "chat_mode": "manager",
            "threads": threads,
            "admin_conversations": admin_conversations,
            "unread_manager_count": unread_manager_count,
            "unread_team_count": unread_team_count,
            "current_thread": manager,
            "messages": messages,
            "categories": categories_res.get("items", []),
            "subcategories": subcategories_res.get("items", []),
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
    category_id: str | None = Form(default=None),
    sub_category_id: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Approve and apply a manager's structured proposal into central data."""
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        await apply_message_proposal_to_central(
            db,
            message_id=message_id,
            category_id=category_id,
            sub_category_id=sub_category_id,
        )
        return RedirectResponse(
            url=f"/admin/messages/{manager_id}?msg=Proposal+successfully+applied+to+central+data",
            status_code=303,
        )
    except Exception as err:
        return RedirectResponse(
            url=f"/admin/messages/{manager_id}?error={quote_plus(str(err))}",
            status_code=303,
        )


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

