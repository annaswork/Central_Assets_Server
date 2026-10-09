from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.analytics_controller import (
    clear_analytics_errors,
    create_monitored_endpoint,
    delete_analytics_event,
    delete_monitored_endpoint,
    get_analytics_event_by_id,
    get_dashboard_summary,
    list_monitored_endpoints,
)
from database.collections import APP_INSTANCES
from database.models.analytics import MonitoredEndpointCreate
from router.deps import get_db

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/analytics", tags=["Admin Analytics"])


@router.get("")
@router.get("/dashboard")
async def admin_analytics_dashboard(
    request: Request,
    hours: int = Query(default=24),
    msg: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=max(1, hours))
    summary = await get_dashboard_summary(db, from_dt=start, to_dt=now)

    # Fetch app instance mapping for clear display in tables
    instances_cursor = db[APP_INSTANCES].find({}, {"name": 1})
    instances_list = await instances_cursor.to_list(1000)
    app_names_map = {str(i["_id"]): i.get("name", "Unknown") for i in instances_list}

    return templates.TemplateResponse(
        request=request,
        name="analytics/dashboard.html",
        context={
            "session": session,
            "summary": summary,
            "hours": hours,
            "msg": msg,
            "error": error,
            "app_names_map": app_names_map,
            "active_tab": "analytics",
        },
    )


@router.get("/events/{id}")
async def admin_get_event_detail(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    try:
        event = await get_analytics_event_by_id(db, event_id=id)
        from controller.base_controller import serialize_mongo_doc
        return JSONResponse({"success": True, "event": serialize_mongo_doc(event)})
    except Exception as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})


@router.post("/events/{id}/delete")
async def admin_delete_analytics_event(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        await delete_analytics_event(db, event_id=id)
        if request.headers.get("accept", "").find("application/json") >= 0 or request.headers.get("x-requested-with"):
            return JSONResponse({"success": True, "deleted_id": id})
        return RedirectResponse(url="/admin/analytics?msg=Analytics+record+deleted+successfully", status_code=303)
    except Exception as exc:
        if request.headers.get("accept", "").find("application/json") >= 0:
            return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
        return RedirectResponse(url=f"/admin/analytics?error={str(exc)}", status_code=303)


@router.post("/clear-errors")
async def admin_clear_error_analytics(
    request: Request,
    hours: int = Form(default=0),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    window_hours = hours if hours > 0 else None
    res = await clear_analytics_errors(db, hours=window_hours)
    count = res.get("deleted_count", 0)
    return RedirectResponse(
        url=f"/admin/analytics?msg=Successfully+deleted+{count}+error+records",
        status_code=303,
    )


@router.get("/allowed-paths")
async def admin_analytics_paths(
    request: Request, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    endpoints = await list_monitored_endpoints(db)
    return templates.TemplateResponse(
        request=request,
        name="analytics/allowed_paths.html",
        context={"session": session, "endpoints": endpoints, "active_tab": "analytics"},
    )


@router.post("/allowed-paths/new")
async def admin_create_allowed_path(
    request: Request,
    method: str = Form(...),
    path_template: str = Form(...),
    sample_rate: float = Form(default=1.0),
    retain_days: int = Form(default=30),
    notes: str = Form(default=""),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    await create_monitored_endpoint(
        db,
        MonitoredEndpointCreate(
            method=method,
            path_template=path_template,
            sample_rate=sample_rate,
            retain_days=retain_days,
            notes=notes,
        ),
    )
    return RedirectResponse(url="/admin/analytics/allowed-paths", status_code=303)


@router.post("/allowed-paths/{id}/delete")
async def admin_delete_allowed_path(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    await delete_monitored_endpoint(db, endpoint_id=id)
    return RedirectResponse(url="/admin/analytics/allowed-paths", status_code=303)
