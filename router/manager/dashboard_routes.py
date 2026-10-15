"""Manager portal dashboard routes."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.asset_preview_controller import get_asset_preview_details
from controller.manager_controller import get_manager_by_id, get_manager_dashboard_counts
from router.deps import get_db

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["Manager Dashboard"])


@router.get("/")
@router.get("/dashboard")
async def manager_dashboard(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Manager dashboard with scoped instance, category, subcategory, and asset counts."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)
    counts = await get_manager_dashboard_counts(db, user_id)

    return templates.TemplateResponse(
        request=request,
        name="manager/dashboard/index.html",
        context={
            "session": session,
            "manager": manager,
            "counts": counts,
            "active_tab": "dashboard",
        },
    )


@router.get("/api/assets/{asset_id}/preview")
async def manager_get_asset_preview_api(
    request: Request,
    asset_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Retrieve full preview data for an asset including more_fields and frame placeholders."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    data = await get_asset_preview_details(db=db, asset_id=asset_id)
    return JSONResponse(content=data)

