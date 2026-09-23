"""Admin panel dashboard view routes."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.admin_controller import get_dashboard_counts
from controller.analytics_controller import get_dashboard_summary
from controller.asset_preview_controller import (
    get_asset_preview_details,
    reset_asset_stats,
    toggle_asset_status,
)
from controller.reorder_controller import get_reorder_items, reorder_central_items
from controller.search_controller import global_search
from database.models.instance_content import ReorderPayload
from router.deps import get_db

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["Admin Dashboard"])


@router.get("/")
@router.get("/dashboard")
async def dashboard_view(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    counts = await get_dashboard_counts(db)
    summary = await get_dashboard_summary(db)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "session": session,
            "counts": counts,
            "summary": summary,
            "active_tab": "dashboard",
        },
    )


@router.get("/api/search")
async def admin_global_search_api(
    request: Request,
    q: str = "",
    limit: int = 6,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    data = await global_search(db=db, query=q, limit=limit)
    return JSONResponse(content=data)


@router.get("/api/reorder/items")
async def admin_get_reorder_items_api(
    request: Request,
    type: str,
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    items = await get_reorder_items(
        db=db,
        item_type=type,
        category_id=categoryId,
        sub_category_id=subCategoryId,
    )
    return JSONResponse(content={"items": items, "total_count": len(items)})


@router.post("/api/reorder")
async def admin_reorder_items_api(
    request: Request,
    payload: ReorderPayload,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    res = await reorder_central_items(
        db=db,
        item_type=payload.type,
        ordered_ids=payload.ordered_ids,
    )
    return JSONResponse(content=res)


@router.get("/api/assets/{asset_id}/preview")
async def admin_get_asset_preview_api(
    request: Request,
    asset_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    data = await get_asset_preview_details(db=db, asset_id=asset_id)
    return JSONResponse(content=data)


@router.post("/api/assets/{asset_id}/reset-stats")
async def admin_reset_asset_stats_api(
    request: Request,
    asset_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    res = await reset_asset_stats(db=db, asset_id=asset_id)
    return JSONResponse(content=res)


@router.post("/api/assets/{asset_id}/toggle-status")
async def admin_toggle_asset_status_api(
    request: Request,
    asset_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    res = await toggle_asset_status(db=db, asset_id=asset_id)
    return JSONResponse(content=res)
