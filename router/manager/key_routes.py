"""Manager portal API Key management routes."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.app_instance_controller import list_app_instances
from controller.manager_controller import (
    create_manager_key,
    delete_manager_key,
    get_manager_accessible_instance_ids,
    get_manager_by_id,
    list_manager_keys,
    revoke_manager_key,
    update_manager_key_rate_limit,
)
from database.models.api_key import ApiKeyCreate
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import ForbiddenError, ValidationError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/keys", tags=["Manager API Keys"])


@router.get("")
async def manager_keys_list(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """List API keys scoped to this manager."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)
    keys = await list_manager_keys(db, user_id)

    # Fetch manager's accessible app instances for key generation modal
    accessible_ids = await get_manager_accessible_instance_ids(db, user_id)
    instances_res = await list_app_instances(db, page=1, page_size=200, instance_ids=accessible_ids)
    instances = instances_res.get("items", [])

    # Map instance names onto keys
    inst_map = {inst["id"]: inst["name"] for inst in instances}
    for k in keys:
        k["app_name"] = inst_map.get(k.get("app_instance_id"), "None / Unassigned")

    return templates.TemplateResponse(
        request=request,
        name="manager/keys/list.html",
        context={
            "session": session,
            "manager": manager,
            "keys": keys,
            "instances": instances,
            "active_tab": "keys",
        },
    )


@router.post("")
async def manager_create_key(
    request: Request,
    name: str = Form(...),
    app_instance_id: str = Form(...),
    rate_limit_per_min: int = Form(default=60),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Generate a new API key scoped to manager's app instance and reveal once."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    try:
        data = ApiKeyCreate(
            name=name.strip(),
            app_instance_id=app_instance_id,
            scopes=["assets:read", "categories:read", "subcategories:read"],
            rate_limit_per_min=max(1, rate_limit_per_min),
        )
        created_key = await create_manager_key(db, user_id, data)

        return templates.TemplateResponse(
            request=request,
            name="manager/keys/created.html",
            context={
                "session": session,
                "manager": manager,
                "key": created_key,
                "active_tab": "keys",
            },
        )
    except (ValidationError, ForbiddenError) as err:
        return RedirectResponse(url="/manager/keys", status_code=303)


@router.post("/{key_id}/revoke")
async def manager_revoke_key_endpoint(
    key_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Revoke an API key owned by this manager."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    try:
        await revoke_manager_key(db, manager_id=session["user_id"], key_id=key_id)
    except ForbiddenError:
        pass

    return RedirectResponse(url="/manager/keys", status_code=303)


@router.post("/{key_id}/delete")
async def manager_delete_key_endpoint(
    key_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Permanently delete an API key owned by this manager."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    try:
        await delete_manager_key(db, manager_id=session["user_id"], key_id=key_id)
    except ForbiddenError:
        pass

    return RedirectResponse(url="/manager/keys", status_code=303)


@router.post("/{key_id}/rate-limit")
async def manager_update_rate_limit(
    key_id: str,
    request: Request,
    rate_limit: int = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Update rate limit for an API key owned by this manager."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    try:
        await update_manager_key_rate_limit(
            db, manager_id=session["user_id"], key_id=key_id, rate_limit=rate_limit
        )
    except ForbiddenError:
        pass

    return RedirectResponse(url="/manager/keys", status_code=303)
