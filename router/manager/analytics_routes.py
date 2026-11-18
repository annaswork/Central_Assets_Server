"""Manager portal scoped analytics routes."""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from analytics.reporter import get_error_analytics
from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.analytics_controller import (
    clear_analytics_errors,
    delete_analytics_event,
    get_analytics_event_by_id,
)
from controller.app_instance_controller import list_app_instances
from controller.manager_controller import (
    get_manager_accessible_instance_ids,
    get_manager_by_id,
)
from database.collections import ANALYTICS_EVENTS, APP_INSTANCES
from router.deps import get_db

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/analytics", tags=["Manager Analytics"])


@router.get("")
async def manager_analytics_view(
    request: Request,
    app_id: str | None = Query(default=None),
    hours: int = Query(default=24),
    msg: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Scoped analytics view showing metrics strictly for manager's accessible app instances."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    # 1. Fetch accessible instance IDs
    accessible_ids = await get_manager_accessible_instance_ids(db, user_id)

    # If manager filtered by a specific instance, ensure they have access to it
    target_ids = accessible_ids
    if app_id:
        if app_id in accessible_ids:
            target_ids = [app_id]
        else:
            target_ids = []

    # Fetch app instance names for the dropdown filter
    instances_res = await list_app_instances(db, page=1, page_size=200, instance_ids=accessible_ids)
    instances = instances_res.get("items", [])
    app_names_map = {inst["id"]: inst["name"] for inst in instances}

    # If no accessible instances, show zero-data state
    if not target_ids:
        summary = {
            "total_requests": 0,
            "total_errors": 0,
            "error_rate": 0.0,
            "avg_duration": 0.0,
            "total_bytes": 0,
        }
        endpoint_metrics: list[dict[str, Any]] = []
        error_analytics = {
            "total_errors": 0,
            "recent_errors": [],
            "reasons_breakdown": [],
            "status_counts": {},
        }
        return templates.TemplateResponse(
            request=request,
            name="manager/analytics/dashboard.html",
            context={
                "session": session,
                "manager": manager,
                "instances": instances,
                "app_names_map": app_names_map,
                "selected_app_id": app_id or "",
                "hours": hours,
                "msg": msg,
                "error": error,
                "summary": summary,
                "endpoint_metrics": endpoint_metrics,
                "error_analytics": error_analytics,
                "active_tab": "analytics",
            },
        )

    # Query events strictly matching target_ids
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=max(1, hours))

    match_filter: dict[str, Any] = {
        "ts": {"$gte": start, "$lte": now},
        "app_instance_id": {"$in": target_ids},
    }

    summary_pipeline = [
        {"$match": match_filter},
        {
            "$group": {
                "_id": None,
                "total_requests": {"$sum": 1},
                "total_errors": {"$sum": {"$cond": [{"$gte": ["$status_code", 400]}, 1, 0]}},
                "avg_duration": {"$avg": "$duration_ms"},
                "total_bytes": {"$sum": "$response_bytes"},
            }
        },
    ]

    res = await db[ANALYTICS_EVENTS].aggregate(summary_pipeline).to_list(1)
    if res:
        doc = res[0]
        reqs = doc.get("total_requests", 0)
        errs = doc.get("total_errors", 0)
        summary = {
            "total_requests": reqs,
            "total_errors": errs,
            "error_rate": round((errs / reqs * 100), 2) if reqs > 0 else 0.0,
            "avg_duration": round(doc.get("avg_duration") or 0.0, 1),
            "total_bytes": doc.get("total_bytes", 0),
        }
    else:
        summary = {
            "total_requests": 0,
            "total_errors": 0,
            "error_rate": 0.0,
            "avg_duration": 0.0,
            "total_bytes": 0,
        }

    # Per-endpoint breakdown
    endpoint_pipeline = [
        {"$match": match_filter},
        {
            "$group": {
                "_id": {"method": "$method", "path_template": "$path_template"},
                "hits": {"$sum": 1},
                "errors": {"$sum": {"$cond": [{"$gte": ["$status_code", 400]}, 1, 0]}},
                "avg_latency_ms": {"$avg": "$duration_ms"},
            }
        },
        {"$sort": {"hits": -1}},
        {"$limit": 50},
    ]

    endpoint_rows = await db[ANALYTICS_EVENTS].aggregate(endpoint_pipeline).to_list(50)
    endpoint_metrics = []
    for r in endpoint_rows:
        hits = r.get("hits", 0)
        errors = r.get("errors", 0)
        endpoint_metrics.append({
            "method": r["_id"].get("method", "GET"),
            "path_template": r["_id"].get("path_template", ""),
            "hits": hits,
            "errors": errors,
            "error_rate": round((errors / hits * 100), 2) if hits > 0 else 0.0,
            "avg_latency_ms": round(r.get("avg_latency_ms") or 0.0, 1),
        })

    # Error Analytics breakdown and recent error records strictly matching target_ids
    error_analytics = await get_error_analytics(
        db,
        from_dt=start,
        to_dt=now,
        app_instance_ids=target_ids,
        limit=50,
    )

    return templates.TemplateResponse(
        request=request,
        name="manager/analytics/dashboard.html",
        context={
            "session": session,
            "manager": manager,
            "instances": instances,
            "app_names_map": app_names_map,
            "selected_app_id": app_id or "",
            "hours": hours,
            "msg": msg,
            "error": error,
            "summary": summary,
            "endpoint_metrics": endpoint_metrics,
            "error_analytics": error_analytics,
            "active_tab": "analytics",
        },
    )


@router.get("/events/{id}")
async def manager_get_event_detail(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    user_id = session["user_id"]
    accessible_ids = await get_manager_accessible_instance_ids(db, user_id)

    try:
        event = await get_analytics_event_by_id(db, event_id=id, allowed_instance_ids=accessible_ids)
        from controller.base_controller import serialize_mongo_doc
        return JSONResponse({"success": True, "event": serialize_mongo_doc(event)})
    except Exception as exc:
        return JSONResponse(status_code=403, content={"success": False, "error": str(exc)})


@router.post("/events/{id}/delete")
async def manager_delete_analytics_event(
    request: Request,
    id: str,
    app_id: str | None = Form(default=None),
    hours: int = Form(default=24),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    accessible_ids = await get_manager_accessible_instance_ids(db, user_id)

    redirect_url = f"/manager/analytics?hours={hours}"
    if app_id:
        redirect_url += f"&app_id={app_id}"

    try:
        await delete_analytics_event(db, event_id=id, allowed_instance_ids=accessible_ids)
        if request.headers.get("accept", "").find("application/json") >= 0 or request.headers.get("x-requested-with"):
            return JSONResponse({"success": True, "deleted_id": id})
        return RedirectResponse(url=f"{redirect_url}&msg=Analytics+record+deleted+successfully", status_code=303)
    except Exception as exc:
        if request.headers.get("accept", "").find("application/json") >= 0:
            return JSONResponse(status_code=403, content={"success": False, "error": str(exc)})
        return RedirectResponse(url=f"{redirect_url}&error={str(exc)}", status_code=303)


@router.post("/clear-errors")
async def manager_clear_error_analytics(
    request: Request,
    app_id: str | None = Form(default=None),
    hours: int = Form(default=0),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    accessible_ids = await get_manager_accessible_instance_ids(db, user_id)

    target = [app_id] if (app_id and app_id in accessible_ids) else accessible_ids
    window_hours = hours if hours > 0 else None

    redirect_url = f"/manager/analytics?hours={hours or 24}"
    if app_id:
        redirect_url += f"&app_id={app_id}"

    res = await clear_analytics_errors(db, app_instance_ids=target, hours=window_hours)
    count = res.get("deleted_count", 0)
    return RedirectResponse(
        url=f"{redirect_url}&msg=Successfully+deleted+{count}+error+records",
        status_code=303,
    )
