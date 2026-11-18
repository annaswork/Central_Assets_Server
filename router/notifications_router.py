"""API endpoint for live notification badge polling."""

from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from authorization.admin_session import get_current_admin_session
from authorization.manager_session import get_current_manager_session
from database.collections import ADMIN_USERS, APP_INSTANCE_ACCESS_REQUESTS, MANAGERS, MESSAGES
from database.connection import get_database
from utils.datetimes import utc_now
from utils.ids import to_object_id

router = APIRouter(prefix="/api/notifications", tags=["Live Notifications"])

# This poll runs every 5s from any open portal tab, so it doubles as the presence heartbeat.
# Background tabs throttle timers to about once a minute, hence the wider window.
ONLINE_WINDOW = timedelta(seconds=90)


def _online_filter() -> dict:
    return {"last_seen_at": {"$gte": utc_now() - ONLINE_WINDOW}}


async def _online_ids(db, collection: str) -> list[str]:
    docs = await db[collection].find(_online_filter(), {"_id": 1}).to_list(length=1000)
    return [str(d["_id"]) for d in docs]


@router.get("/badge-counts")
async def get_badge_counts(request: Request, portal: str | None = None) -> JSONResponse:
    """Return unread message and pending request counts for live polling.

    `portal` (admin|manager) says which portal the polling page belongs to, so a browser logged into
    both portals is counted as the right user on each tab.
    """
    db = get_database()

    # 1. Admin session
    admin_session = get_current_admin_session(request) if portal != "manager" else None
    if admin_session:
        try:
            # Count number of distinct conversations (existing managers) that have unread messages
            unread_manager_ids = await db[MESSAGES].distinct(
                "manager_id",
                {"sender_role": "manager", "status": "unread", "channel_type": {"$ne": "admin_direct"}},
            )
            if unread_manager_ids:
                valid_ids = [to_object_id(mid) for mid in unread_manager_ids if mid]
                unread_mgr_count = await db[MANAGERS].count_documents({
                    "_id": {"$in": valid_ids}
                })
            else:
                unread_mgr_count = 0

            admin_id = admin_session.get("user_id")
            unread_team_count = 0
            if admin_id:
                admin_oid = to_object_id(admin_id)
                unread_admin_sender_ids = await db[MESSAGES].distinct(
                    "sender_id",
                    {
                        "channel_type": "admin_direct",
                        "recipient_id": {"$in": [admin_oid, str(admin_oid)]},
                        "status": "unread",
                    },
                )
                unread_team_count = len(unread_admin_sender_ids)

            pending_count = await db[APP_INSTANCE_ACCESS_REQUESTS].count_documents({
                "status": "pending",
            })
            if admin_id:
                await db[ADMIN_USERS].update_one(
                    {"_id": to_object_id(admin_id)}, {"$set": {"last_seen_at": utc_now()}}
                )
            return JSONResponse({
                "role": "admin",
                "unread_messages": unread_mgr_count + unread_team_count,
                "unread_manager_messages": unread_mgr_count,
                "unread_team_messages": unread_team_count,
                "pending_requests": pending_count,
                "online_ids": await _online_ids(db, MANAGERS) + await _online_ids(db, ADMIN_USERS),
            })
        except Exception:
            return JSONResponse({
                "role": "admin",
                "unread_messages": 0,
                "pending_requests": 0,
            })

    # 2. Manager session
    manager_session = get_current_manager_session(request) if portal != "admin" else None
    if manager_session and "user_id" in manager_session:
        try:
            m_oid = to_object_id(manager_session["user_id"])
            has_unread = await db[MESSAGES].count_documents({
                "$or": [{"manager_id": m_oid}, {"manager_id": str(m_oid)}],
                "sender_role": "admin",
                "status": "unread",
            })
            unread_count = 1 if has_unread > 0 else 0
            await db[MANAGERS].update_one({"_id": m_oid}, {"$set": {"last_seen_at": utc_now()}})
            # Managers only learn whether any admin is online, not which ones.
            admin_online = await db[ADMIN_USERS].count_documents(_online_filter(), limit=1)
            return JSONResponse({
                "role": "manager",
                "unread_messages": unread_count,
                "pending_requests": 0,
                "online_ids": ["admin"] if admin_online else [],
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
