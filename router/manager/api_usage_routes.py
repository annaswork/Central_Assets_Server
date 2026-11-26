"""Manager portal API Usage Method documentation route."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import ROOT_DIR, TEMPLATES_DIR
from controller.app_instance_controller import list_app_instances
from controller.manager_controller import (
    get_manager_accessible_instance_ids,
    get_manager_by_id,
    list_manager_keys,
)
from router.deps import get_db
from utils.markdown_doc import load_api_usage_document

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/api-usage", tags=["Manager API Usage Method"])

ENDPOINT_QUICK_CARDS = [
    {
        "method": "GET",
        "path": "/api/v1/instance/{instanceId}/catalog",
        "anchor": "41-get-full-catalog-tree",
        "scope": "assets:read",
        "summary": "Full nested tree (super categories, categories, subcategories, enabled assets) in one request.",
    },
    {
        "method": "GET",
        "path": "/api/v1/instance/{instanceId}/super-categories",
        "anchor": "41a-list-super-categories",
        "scope": "categories:read",
        "summary": "Optional top-level grouping above categories (supports only_enabled).",
    },
    {
        "method": "GET",
        "path": "/api/v1/instance/{instanceId}/categories",
        "anchor": "42-list-categories",
        "scope": "categories:read",
        "summary": "Categories assigned to this app (filter by superCategoryId, only_enabled).",
    },
    {
        "method": "GET",
        "path": "/api/v1/instance/{instanceId}/subcategories",
        "anchor": "43-list-subcategories",
        "scope": "categories:read",
        "summary": "Subcategories inside a category (filter by categoryId, only_enabled).",
    },
    {
        "method": "GET",
        "path": "/api/v1/instance/{instanceId}/assets",
        "anchor": "44-list-assets",
        "scope": "assets:read",
        "summary": "Resolved assets list (filter by categoryId, subCategoryId, only_enabled, tag; sort & order).",
    },
    {
        "method": "GET",
        "path": "/api/v1/instance/{instanceId}/assets/{assetId}",
        "anchor": "45-get-single-asset",
        "scope": "assets:read",
        "summary": "Single resolved asset details, media blocks, and monetization flags.",
    },
    {
        "method": "POST",
        "path": "/api/v1/instance/{instanceId}/assets/{assetId}/track",
        "anchor": "46-track-view--download-event",
        "scope": "assets:read",
        "summary": "Atomic per-instance counter increment for view or download analytics events.",
    },
]


@router.get("")
async def manager_api_usage_page(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render the interactive API Usage Method reference powered by API_Usage.md."""
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

    keys = await list_manager_keys(db, user_id)
    active_keys = [k for k in keys if k.get("is_active") and not k.get("is_revoked")]

    api_doc = load_api_usage_document(ROOT_DIR / "API_Usage.md")
    server_origin = str(request.base_url).rstrip("/")
    api_base_url = f"{server_origin}/api/v1"

    return templates.TemplateResponse(
        request=request,
        name="manager/api_usage/index.html",
        context={
            "session": session,
            "manager": manager,
            "instances": instances,
            "keys": active_keys,
            "api_doc": api_doc,
            "quick_endpoints": ENDPOINT_QUICK_CARDS,
            "server_origin": server_origin,
            "api_base_url": api_base_url,
            "active_tab": "api_usage",
        },
    )
