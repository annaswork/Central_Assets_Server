"""API endpoint for live notification badge polling."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from authorization.admin_session import get_current_admin_session
from authorization.manager_session import get_current_manager_session
from database.collections import APP_INSTANCE_ACCESS_REQUESTS, MANAGERS, MESSAGES
from database.connection import get_database
from utils.ids import to_object_id

router = APIRouter(prefix="/api/notifications", tags=["Live Notifications"])


@router.get("/badge-counts")
async def get_badge_counts(request: Request) -> JSONResponse:
    """Return unread message and pending request counts for live polling."""
    db = get_database()

    # 1. Admin session
    admin_session = get_current_admin_session(request)
    if admin_session:
        try:
            # Count number of distinct conversations (existing managers) that have unread messages
            unread_manager_ids = await db[MESSAGES].distinct(
                "manager_id",
                {"sender_role": "manager", "status": "unread"},
            )
            if unread_manager_ids:
                valid_ids = [to_object_id(mid) for mid in unread_manager_ids if mid]
                unread_count = await db[MANAGERS].count_documents({
                    "_id": {"$in": valid_ids}
                })
            else:
                unread_count = 0

            pending_count = await db[APP_INSTANCE_ACCESS_REQUESTS].count_documents({
                "status": "pending",
            })
            return JSONResponse({
                "role": "admin",
                "unread_messages": unread_count,
                "pending_requests": pending_count,
            })
        except Exception:
            return JSONResponse({
                "role": "admin",
                "unread_messages": 0,
                "pending_requests": 0,
            })

    # 2. Manager session
    manager_session = get_current_manager_session(request)
    if manager_session and "user_id" in manager_session:
        try:
            m_oid = to_object_id(manager_session["user_id"])
            has_unread = await db[MESSAGES].count_documents({
                "$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}],
                "sender_role": "admin",
                "status": "unread",
            })
            unread_count = 1 if has_unread > 0 else 0
            return JSONResponse({
                "role": "manager",
                "unread_messages": unread_count,
                "pending_requests": 0,
            })
        except Exception:
            return JSONResponse({
                "role": "manager",
                "unread_messages": 0,
                "pending_requests": 0,
            })

    return JSONResponse({
        "role": "guest",
        "unread_messages": 0,
        "pending_requests": 0,
    })
