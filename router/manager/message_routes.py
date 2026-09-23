"""Manager portal messaging routes for communication with Admin and proposal submissions."""

import json
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.admin_manager_controller import clear_conversation
from controller.category_controller import list_categories
from controller.manager_controller import (
    get_manager_by_id,
    get_manager_messages,
    send_manager_message,
)
from controller.subcategory_controller import list_subcategories
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import ValidationError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/messages", tags=["Manager Messaging"])


@router.get("")
async def manager_messages_view(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Manager messaging thread with Admin and proposal creation."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)
    messages = await get_manager_messages(db, user_id)

    # Categories and subcategories for the structured proposal submission modal
    categories_res = await list_categories(db, page=1, page_size=200)
    subcategories_res = await list_subcategories(db, page=1, page_size=500)

    return templates.TemplateResponse(
        request=request,
        name="manager/messages/index.html",
        context={
            "session": session,
            "manager": manager,
            "messages": messages,
            "categories": categories_res.get("items", []),
            "subcategories": subcategories_res.get("items", []),
            "active_tab": "messages",
        },
    )


@router.post("")
async def manager_send_message(
    request: Request,
    content: str = Form(...),
    subject: str | None = Form(default=None),
    payload_type: str | None = Form(default=None),
    data_payload_json: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Send free-text message or central data proposal to Admin."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    parsed_payload = None
    if data_payload_json and data_payload_json.strip():
        try:
            parsed_payload = json.loads(data_payload_json.strip())
        except Exception:
            pass

    try:
        await send_manager_message(
            db,
            manager_id=user_id,
            sender_name=manager.get("display_name") or manager["username"],
            content=content,
            subject=subject,
            payload_type=payload_type if (payload_type and payload_type != "none") else None,
            data_payload=parsed_payload,
        )
    except ValidationError:
        pass

    return RedirectResponse(url="/manager/messages", status_code=303)


@router.post("/clear")
async def manager_clear_conversation(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Clear all messages in the manager's conversation thread with Admin."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    try:
        await clear_conversation(db, manager_id=user_id)
    except Exception:
        pass

    return RedirectResponse(url="/manager/messages?msg=Conversation+cleared", status_code=303)

