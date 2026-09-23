"""Admin panel routes for analytics dashboard and monitored endpoints management."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.analytics_controller import (
    create_monitored_endpoint,
    delete_monitored_endpoint,
    get_dashboard_summary,
    list_monitored_endpoints,
)
from database.models.analytics import MonitoredEndpointCreate
from router.deps import get_db

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/analytics", tags=["Admin Analytics"])


@router.get("")
@router.get("/dashboard")
async def admin_analytics_dashboard(
    request: Request, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    summary = await get_dashboard_summary(db)
    return templates.TemplateResponse(
        request=request,
        name="analytics/dashboard.html",
        context={"session": session, "summary": summary, "active_tab": "analytics"},
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
