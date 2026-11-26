"""Manager portal Help & Learning Guide route."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.app_instance_controller import list_app_instances
from controller.manager_controller import get_manager_accessible_instance_ids, get_manager_by_id
from router.deps import get_db

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/help", tags=["Manager Help"])


@router.get("")
async def manager_help_page(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render comprehensive Manager Portal learning guide covering reading, writing, files, and tier rules."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)
    accessible_ids = await get_manager_accessible_instance_ids(db, user_id)

    instances: list[dict] = []
    if accessible_ids:
        instances_res = await list_app_instances(
            db, page=1, page_size=200, instance_ids=accessible_ids
        )
        instances = instances_res.get("items", [])

    manager_has_2fa = bool(manager and manager.get("is_2fa_enabled") and manager.get("totp_secret"))
    server_origin = str(request.base_url).rstrip("/")

    return templates.TemplateResponse(
        request=request,
        name="manager/help/index.html",
        context={
            "session": session,
            "manager": manager,
            "manager_has_2fa": manager_has_2fa,
            "instances": instances,
            "server_origin": server_origin,
            "active_tab": "help",
        },
    )
