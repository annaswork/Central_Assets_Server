"""Manager portal App Instance routes and central library importing."""

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.app_instance_controller import (
    create_app_instance,
    get_app_instance,
    list_app_instances,
    update_app_instance,
)
from controller.base_controller import serialize_mongo_doc
from controller.catalog_controller import (
    get_resolved_assets,
    get_resolved_categories,
    get_resolved_subcategories,
)
from controller.category_controller import list_categories
from controller.manager_controller import (
    create_access_request,
    get_manager_accessible_instance_ids,
    get_manager_by_id,
    list_manager_access_requests,
    verify_manager_instance_access,
)
from controller.override_controller import reorder_items, update_item_settings_and_overrides
from controller.reference_controller import add_references, remove_reference
from controller.subcategory_controller import list_subcategories
from database.collections import (
    APP_INSTANCES,
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    SUBCATEGORIES,
)
from database.models.app_instance import AppInstanceCreate, AppInstanceUpdate
from database.models.instance_content import ReorderPayload
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from utils.ids import to_object_id

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/instances", tags=["Manager App Instances"])


@router.get("")
async def manager_list_instances(
    request: Request,
    page: int = Query(default=1, ge=1),
    search: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """List app instances accessible to this manager, and list available apps to request access."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    accessible_ids = await get_manager_accessible_instance_ids(db, user_id)
    instances_page = await list_app_instances(
        db, page=page, page_size=20, search=search, instance_ids=accessible_ids
    )

    # Decorate accessible instances
    m_oid = to_object_id(user_id)
    for inst in instances_page.get("items", []):
        is_owner = inst.get("owner_id") in [m_oid, str(m_oid)]
        inst["is_owner"] = is_owner
        inst["access_type"] = "Granted"

    # Also fetch all other existing instances that manager does NOT have access to, for "Request Access"
    other_query = {
        "_id": {"$nin": [to_object_id(i) for i in accessible_ids]},
    }
    other_cursor = db[APP_INSTANCES].find(other_query).sort("name", 1).limit(50)
    other_instances_raw = await other_cursor.to_list(length=50)

    # Fetch user's existing pending requests to show pending badges
    requests = await list_manager_access_requests(db, user_id)
    pending_app_ids = {r["app_instance_id"] for r in requests if r.get("status") == "pending"}

    other_instances = []
    for o in other_instances_raw:
        oid_str = str(o["_id"])
        other_instances.append({
            "id": oid_str,
            "name": o.get("name", "Untitled"),
            "package_name": o.get("package_name"),
            "is_pending_request": oid_str in pending_app_ids,
        })

    return templates.TemplateResponse(
        request=request,
        name="manager/instances/list.html",
        context={
            "session": session,
            "manager": manager,
            "instances": instances_page.get("items", []),
            "pagination": instances_page.get("pagination", {}),
            "other_instances": other_instances,
            "search": search or "",
            "active_tab": "instances",
        },
    )


@router.get("/new")
@router.post("/new")
async def manager_create_instance_forbidden() -> Response:
    """Managers cannot create app instances; they can only request access to available apps."""
    return RedirectResponse(url="/manager/instances", status_code=303)


@router.get("/{instance_id}")
@router.get("/{instance_id}/content")
async def manager_instance_content(
    instance_id: str,
    request: Request,
    active_section: str = Query(default="folders"),
    category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View and manage content imported into this app instance with full folder hierarchy."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    # Scoping check: verify manager has access to this instance
    await verify_manager_instance_access(db, user_id, instance_id)

    inst_oid = to_object_id(instance_id)
    instance = await get_app_instance(db, instance_id)
    m_oid = to_object_id(user_id)
    is_owner = instance.get("owner_id") in [m_oid, str(m_oid)]

    # Resolve categories and calculate live child counts in this instance
    all_categories = await get_resolved_categories(db, app_instance_id=instance_id)
    for cat in all_categories:
        c_src_oid = to_object_id(cat.get("sourceId") or cat.get("id"))
        cat["subcategories_count"] = await db[INSTANCE_SUBCATEGORIES].count_documents(
            {"app_instance_id": inst_oid, "category_id": c_src_oid, "deleted_at": None}
        )
        cat["assets_count"] = await db[INSTANCE_ASSETS].count_documents(
            {"app_instance_id": inst_oid, "category_id": c_src_oid, "deleted_at": None}
        )

    # Resolve all subcategories and calculate live child assets in this instance
    all_subcategories = await get_resolved_subcategories(db, app_instance_id=instance_id)
    for sub in all_subcategories:
        s_src_oid = to_object_id(sub.get("sourceId") or sub.get("id"))
        sub["assets_count"] = await db[INSTANCE_ASSETS].count_documents(
            {"app_instance_id": inst_oid, "sub_category_id": s_src_oid, "deleted_at": None}
        )

    resolved_assets = await get_resolved_assets(db, app_instance_id=instance_id, category_id=category_id)

    # Also load central library categories & subcategories for the import picker modal
    central_cats = await list_categories(db, page=1, page_size=200)
    for cat in central_cats.get("items", []):
        c_oid = to_object_id(cat["id"])
        cat["subcategory_count"] = await db[SUBCATEGORIES].count_documents(
            {"category_id": c_oid, "deleted_at": None}
        )
        cat["asset_count"] = await db[ASSETS].count_documents(
            {"category_id": c_oid, "deleted_at": None}
        )

    central_subs = await list_subcategories(db, page=1, page_size=500)
    for sub in central_subs.get("items", []):
        s_oid = to_object_id(sub["id"])
        sub["asset_count"] = await db[ASSETS].count_documents(
            {"sub_category_id": s_oid, "deleted_at": None}
        )

    # In-memory mapping fallback for category and subcategory names
    cat_map = {}
    for c in all_categories + central_cats.get("items", []):
        if c.get("id"):
            cat_map[str(c["id"])] = c.get("name")
        if c.get("sourceId"):
            cat_map[str(c["sourceId"])] = c.get("name")

    sub_map = {}
    for s in all_subcategories + central_subs.get("items", []):
        if s.get("id"):
            sub_map[str(s["id"])] = s.get("name")
        if s.get("sourceId"):
            sub_map[str(s["sourceId"])] = s.get("name")

    for a in resolved_assets:
        c_id = str(a.get("categoryId") or "")
        s_id = str(a.get("subCategoryId") or "")
        if not a.get("category_name") or a["category_name"] == "—":
            a["category_name"] = cat_map.get(c_id) or a.get("category_name") or "—"
        a["categoryName"] = a["category_name"]

        if not a.get("subcategory_name") or a["subcategory_name"] == "—":
            a["subcategory_name"] = sub_map.get(s_id) or a.get("subcategory_name") or "—"
        a["subCategoryName"] = a["subcategory_name"]

    return templates.TemplateResponse(
        request=request,
        name="manager/instances/content.html",
        context={
            "session": session,
            "manager": manager,
            "instance": instance,
            "is_owner": is_owner,
            "categories": all_categories,
            "all_subcategories": all_subcategories,
            "assets": resolved_assets,
            "central_categories": central_cats.get("items", []),
            "central_subcategories": central_subs.get("items", []),
            "active_section": active_section,
            "selected_category_id": category_id or "",
            "active_tab": "instances",
        },
    )


@router.post("/{instance_id}/import")
async def manager_import_references(
    instance_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Import selected central categories, subcategories, or assets into this instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    body = await request.json()
    category_ids = body.get("category_ids") or []
    sub_category_ids = body.get("sub_category_ids") or []
    asset_ids = body.get("asset_ids") or []

    result = await add_references(
        db,
        app_instance_id=instance_id,
        category_ids=category_ids,
        sub_category_ids=sub_category_ids,
        asset_ids=asset_ids,
    )

    return JSONResponse(content={"success": True, "result": result})


@router.post("/{instance_id}/remove-reference")
async def manager_remove_reference(
    instance_id: str,
    request: Request,
    content_type: str = Form(...),
    reference_id: str = Form(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Remove a central content reference from this app instance."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    try:
        await remove_reference(
            db,
            app_instance_id=instance_id,
            item_type=content_type,
            item_id=reference_id,
        )
    except Exception:
        pass

    return RedirectResponse(
        url=f"/manager/instances/{instance_id}/content?active_section={content_type}",
        status_code=303,
    )


@router.post("/request-access")
async def manager_request_access_submit(
    request: Request,
    app_instance_id: str = Form(...),
    notes: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Submit an access request for an app instance."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    try:
        await create_access_request(db, manager_id=user_id, app_instance_id=app_instance_id, notes=notes)
    except (ConflictError, NotFoundError):
        pass

    return RedirectResponse(url="/manager/instances", status_code=303)


@router.patch("/{instance_id}/assets/{assetId}/override")
async def manager_instance_asset_override(
    request: Request,
    instance_id: str,
    assetId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Update asset instance overrides (is_enabled, sequence, is_premium) for an accessible instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    is_enabled = payload.get("is_enabled")
    sequence = payload.get("sequence")
    is_premium = payload.get("is_premium")
    name = payload.get("name")
    overrides = {}
    if name is not None:
        overrides["name"] = str(name).strip()

    res = await update_item_settings_and_overrides(
        db,
        app_instance_id=instance_id,
        item_type="asset",
        item_id=assetId,
        is_enabled=is_enabled,
        sequence=sequence,
        is_premium=is_premium,
        overrides=overrides if overrides else None,
    )
    return JSONResponse(status_code=200, content={"success": True, "data": serialize_mongo_doc(res)})


@router.patch("/{instance_id}/folders/{folder_type}/{folder_id}/override")
async def manager_instance_folder_override(
    request: Request,
    instance_id: str,
    folder_type: str,
    folder_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Update sequence or status for categories and subcategories in this instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    sequence = payload.get("sequence")
    is_enabled = payload.get("is_enabled")

    res = await update_item_settings_and_overrides(
        db,
        app_instance_id=instance_id,
        item_type=folder_type,
        item_id=folder_id,
        is_enabled=is_enabled,
        sequence=sequence,
    )
    return JSONResponse(status_code=200, content={"success": True, "data": serialize_mongo_doc(res)})


@router.post("/{instance_id}/reorder")
async def manager_instance_reorder(
    request: Request,
    instance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Reorder categories, subcategories, or assets in this instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    body = await request.json()
    item_type = body.get("type", "asset")
    ordered_ids = body.get("ordered_ids", [])

    res = await reorder_items(
        db,
        app_instance_id=instance_id,
        item_type=item_type,
        ordered_ids=ordered_ids,
    )
    return JSONResponse(status_code=200, content={"success": True, "data": res})
