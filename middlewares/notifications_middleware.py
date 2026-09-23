"""Middleware for populating unread message and pending request counts on request.state."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from authorization.admin_session import get_current_admin_session
from authorization.manager_session import get_current_manager_session
from database.collections import ADMIN_USERS, APP_INSTANCE_ACCESS_REQUESTS, MANAGERS, MESSAGES
from database.connection import get_database
from utils.ids import to_object_id


class NotificationsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Default counts & user state
        request.state.admin_unread_messages_count = 0
        request.state.admin_pending_requests_count = 0
        request.state.manager_unread_messages_count = 0
        request.state.current_user = None

        path = request.url.path

        # If accessing admin portal
        if path.startswith("/admin"):
            admin_session = get_current_admin_session(request)
            if admin_session:
                try:
                    db = get_database()
                    # Count number of distinct conversations (existing managers) that have unread messages
                    unread_manager_ids = await db[MESSAGES].distinct(
                        "manager_id",
                        {"sender_role": "manager", "status": "unread"},
                    )
                    if unread_manager_ids:
                        valid_ids = [to_object_id(mid) for mid in unread_manager_ids if mid]
                        unread_conversations_count = await db[MANAGERS].count_documents({
                            "_id": {"$in": valid_ids}
                        })
                    else:
                        unread_conversations_count = 0

                    pending_count = await db[APP_INSTANCE_ACCESS_REQUESTS].count_documents({
                        "status": "pending",
                    })
                    request.state.admin_unread_messages_count = unread_conversations_count
                    request.state.admin_pending_requests_count = pending_count

                    # Load Admin user details
                    admin_id = admin_session.get("user_id")
                    if admin_id:
                        admin_user = await db[ADMIN_USERS].find_one({"_id": to_object_id(admin_id)})
                        if admin_user:
                            name = admin_user.get("full_name") or admin_user.get("display_name")
                            if not name:
                                name = (admin_user.get("username") or "Admin").capitalize()
                            initial = (name or "A")[:1].upper()
                            request.state.current_user = {
                                "id": str(admin_user["_id"]),
                                "username": admin_user.get("username"),
                                "name": name,
                                "profile_picture": admin_user.get("profile_picture"),
                                "role": "admin",
                                "initial": initial,
                            }
                except Exception:
                    pass

        # If accessing manager portal
        elif path.startswith("/manager"):
            manager_session = get_current_manager_session(request)
            if manager_session and "user_id" in manager_session:
                try:
                    db = get_database()
                    m_oid = to_object_id(manager_session["user_id"])
                    has_unread = await db[MESSAGES].count_documents({
                        "$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}],
                        "sender_role": "admin",
                        "status": "unread",
                    })
                    request.state.manager_unread_messages_count = 1 if has_unread > 0 else 0

                    # Load Manager user details
                    manager_user = await db[MANAGERS].find_one({"_id": m_oid})
                    if manager_user:
                        name = manager_user.get("display_name") or manager_user.get("full_name")
                        if not name:
                            name = (manager_user.get("username") or "Manager").capitalize()
                        initial = (name or "M")[:1].upper()
                        request.state.current_user = {
                            "id": str(manager_user["_id"]),
                            "username": manager_user.get("username"),
                            "name": name,
                            "profile_picture": manager_user.get("profile_picture"),
                            "role": "manager",
                            "initial": initial,
                        }
                except Exception:
                    pass

        return await call_next(request)
