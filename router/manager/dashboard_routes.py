"""Manager portal dashboard routes."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
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
