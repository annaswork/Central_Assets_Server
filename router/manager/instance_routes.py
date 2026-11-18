"""Manager portal App Instance routes and central library importing."""

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.app_instance_controller import get_app_instance, list_app_instances
from controller.asset_preview_controller import get_asset_preview_details
from controller.base_controller import serialize_mongo_doc
from controller.instance_workspace_controller import (
    build_instance_content,
    build_picker_page,
    create_instance_folder,
    parse_asset_override_payload,
    parse_folder_override_payload,
    parse_reference_payload,
    picker_assets,
    picker_categories,
    picker_subcategories,
    set_category_super_category,
)
from controller.manager_controller import (
    create_access_request,
    create_instance_creation_request,
    get_manager_accessible_instance_ids,
    get_manager_by_id,
    list_manager_access_requests,
    verify_manager_instance_access,
)
from controller.override_controller import reorder_items, update_item_settings_and_overrides
from controller.reference_controller import add_references, remove_reference
from database.collections import APP_INSTANCES, INSTANCE_ASSETS
from router.deps import get_db
from utils.datetimes import format_datetime_display, utc_now
from utils.errors import ForbiddenError, NotFoundError, ValidationError
from utils.ids import to_object_id

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/instances", tags=["Manager App Instances"])


@router.get("")
async def manager_list_instances(
    request: Request,
    page: int = Query(default=1, ge=1),
    search: str | None = None,
    msg: str | None = Query(default=None),
    msg_type: str | None = Query(default="info"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """List app instances accessible to this manager, creation requests, and available apps to request access."""
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

    # Fetch user's existing requests
    requests = await list_manager_access_requests(db, user_id)
    pending_app_ids = {
        str(r.get("app_instance_id"))
        for r in requests
        if r.get("status") == "pending" and r.get("request_type") != "create_instance" and r.get("app_instance_id")
    }

    creation_requests = [
        r for r in requests if r.get("request_type") == "create_instance"
    ]
    for cr in creation_requests:
        target_id_str = str(cr.get("target_instance_id") or "")
        cr["is_pending_access_request"] = bool(target_id_str and target_id_str in pending_app_ids)

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
            "creation_requests": creation_requests,
            "flash_message": msg,
            "flash_type": msg_type,
            "search": search or "",
            "active_tab": "instances",
        },
    )


@router.post("/request-creation")
async def manager_request_creation(
    request: Request,
    name: str = Form(...),
    package_name: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Manager asks Admin to provision a new App Instance."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    try:
        await create_instance_creation_request(
            db,
            manager_id=user_id,
            requested_app_name=name,
            requested_package_name=package_name,
            notes=notes,
        )
        success_msg = f"Request to create app '{name.strip()}' submitted to administrators for review."
        return RedirectResponse(
            url=f"/manager/instances?msg={quote_plus(success_msg)}&msg_type=success",
            status_code=303,
        )
    except Exception as err:
        return RedirectResponse(
            url=f"/manager/instances?msg={quote_plus(str(err))}&msg_type=error",
            status_code=303,
        )


@router.get("/new")
@router.post("/new")
async def manager_create_instance_forbidden() -> Response:
    """Redirect manual /new to manager instances list."""
    return RedirectResponse(url="/manager/instances", status_code=303)


@router.get("/{instance_id}")
@router.get("/{instance_id}/content")
async def manager_instance_content(
    instance_id: str,
    request: Request,
    active_section: str = Query(default="folders"),
    category_id: str | None = None,
    sub_category_id: str | None = None,
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    type: str | None = None,
    sort: str | None = None,
    q: str | None = None,
    search: str | None = None,
    folder_cat: str | None = None,
    folder_sort: str | None = None,
    folder_search: str | None = None,
    folder_super: str | None = None,
    superCategoryId: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View and manage content imported into this app instance with full folder hierarchy."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    try:
        await verify_manager_instance_access(db, user_id, instance_id)
    except (ForbiddenError, NotFoundError):
        msg = quote_plus("Access to this app instance has been revoked or is not available.")
        return RedirectResponse(url=f"/manager/instances?msg={msg}&msg_type=error", status_code=303)

    instance = await get_app_instance(db, instance_id)
    m_oid = to_object_id(user_id)
    is_owner = instance.get("owner_id") in [m_oid, str(m_oid)]

    cat_id = category_id or categoryId
    sub_id = sub_category_id or subCategoryId
    search_query = (q or search or "").strip()

    ctx = await build_instance_content(
        db,
        instance_id,
        category_id=cat_id,
        sub_category_id=sub_id,
        sort=sort,
        asset_type=type,
        search_query=search_query,
        folder_cat=folder_cat,
        folder_sort=folder_sort,
        folder_search=folder_search,
        folder_super=folder_super,
        super_category_id=superCategoryId,
        page=page,
        page_size=page_size,
    )

    # Auto-select active section
    if request.query_params.get("tab") == "assets" or request.query_params.get("active_section") == "assets" or cat_id or sub_id or superCategoryId or ctx["selected_type"] or search_query:
        active_section = "assets"
    elif folder_cat or folder_search or (folder_sort and folder_sort not in ("sequence", "")):
        active_section = "folders"

    return templates.TemplateResponse(
        request=request,
        name="manager/instances/content.html",
        context={
            **ctx,
            "session": session,
            "manager": manager,
            "instance": instance,
            "is_owner": is_owner,
            "active_section": active_section,
            "selected_category_id": ctx["selected_cat"],
            "selected_subcategory_id": ctx["selected_subcat"],
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
    target_category_id = body.get("target_category_id") or None
    target_sub_category_id = body.get("target_sub_category_id") or None

    result = await add_references(
        db,
        app_instance_id=instance_id,
        category_ids=category_ids,
        sub_category_ids=sub_category_ids,
        asset_ids=asset_ids,
        target_category_id=target_category_id,
        target_sub_category_id=target_sub_category_id,
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
        msg = "Access request submitted to administrators for review."
        return RedirectResponse(url=f"/manager/instances?msg={quote_plus(msg)}&msg_type=success", status_code=303)
    except Exception as err:
        return RedirectResponse(url=f"/manager/instances?msg={quote_plus(str(err))}&msg_type=error", status_code=303)


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

    res = await update_item_settings_and_overrides(
        db, app_instance_id=instance_id, item_type="asset", item_id=assetId, **parse_asset_override_payload(payload)
    )
    return JSONResponse(status_code=200, content={"success": True, "data": serialize_mongo_doc(res)})


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


@router.post("/{instance_id}/assets/bulk-tags")
async def manager_bulk_add_asset_tags(
    request: Request,
    instance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Add, append, or replace tags on multiple selected assets in an app instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"success": False, "message": "Invalid JSON body"})

    asset_ids = payload.get("asset_ids") or []
    tags = payload.get("tags") or []
    mode = payload.get("mode", "add")  # "add", "replace", or "remove"

    if not asset_ids:
        return JSONResponse(status_code=400, content={"success": False, "message": "No assets selected"})

    # Parse and clean tags
    clean_tags: list[str] = []
    if isinstance(tags, str):
        clean_tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        for item in tags:
            if isinstance(item, str):
                for part in item.split(","):
                    p = part.strip()
                    if p and p not in clean_tags:
                        clean_tags.append(p)

    if not clean_tags and mode in ("add", "replace"):
        return JSONResponse(status_code=400, content={"success": False, "message": "Please enter at least one tag"})

    inst_oid = to_object_id(instance_id)
    oids = []
    for aid in asset_ids:
        try:
            oids.append(to_object_id(aid))
        except Exception:
            pass

    if not oids:
        return JSONResponse(status_code=400, content={"success": False, "message": "No valid asset IDs provided"})

    query = {
        "app_instance_id": inst_oid,
        "$or": [{"_id": {"$in": oids}}, {"source_id": {"$in": oids}}],
        "deleted_at": None,
    }

    if mode == "replace":
        update_op = {
            "$set": {
                "tags": clean_tags,
                "overrides.tags": clean_tags,
                "updated_at": utc_now(),
            }
        }
    elif mode == "remove":
        update_op = {
            "$pull": {
                "tags": {"$in": clean_tags},
                "overrides.tags": {"$in": clean_tags},
            },
            "$set": {"updated_at": utc_now()},
        }
    else:  # "add"
        update_op = {
            "$addToSet": {
                "tags": {"$each": clean_tags},
                "overrides.tags": {"$each": clean_tags},
            },
            "$set": {"updated_at": utc_now()},
        }

    res = await db[INSTANCE_ASSETS].update_many(query, update_op)

    # Fetch updated docs to return latest tag map for live UI DOM update
    updated_docs = await db[INSTANCE_ASSETS].find(
        query,
        {"_id": 1, "source_id": 1, "tags": 1, "overrides": 1}
    ).to_list(length=1000)

    asset_tags_map = {}
    for doc in updated_docs:
        doc_id = str(doc["_id"])
        src_id = str(doc.get("source_id") or "")
        t_list = doc.get("tags") or doc.get("overrides", {}).get("tags") or []
        asset_tags_map[doc_id] = t_list
        if src_id:
            asset_tags_map[src_id] = t_list

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": f"Successfully updated tags for {res.modified_count} asset(s)",
            "modified_count": res.modified_count,
            "tags": clean_tags,
            "mode": mode,
            "asset_tags": asset_tags_map,
        },
    )


@router.patch("/{instance_id}/folders/{folder_type}/{folder_id}/override")
async def manager_instance_folder_override(
    request: Request,
    instance_id: str,
    folder_type: str,
    folder_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Rename, reorder, enable or set premium on a super category / category / subcategory in this instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    res = await update_item_settings_and_overrides(
        db, app_instance_id=instance_id, item_id=folder_id, **parse_folder_override_payload(folder_type, payload)
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
        start=max(0, int(body.get("start") or 0)),
    )
    return JSONResponse(status_code=200, content={"success": True, "data": res})


@router.get("/{instance_id}/picker")
async def manager_instance_picker(
    request: Request,
    instance_id: str,
    target_category_id: str | None = None,
    target_sub_category_id: str | None = None,
    target_super_category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Manager picker for selecting and importing central categories, subcategories, and assets."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    try:
        await verify_manager_instance_access(db, user_id, instance_id)
    except (ForbiddenError, NotFoundError):
        msg = quote_plus("Access to this app instance has been revoked or is not available.")
        return RedirectResponse(url=f"/manager/instances?msg={msg}&msg_type=error", status_code=303)

    instance = await get_app_instance(db, instance_id=instance_id)
    manager = await get_manager_by_id(db, user_id)
    ctx = await build_picker_page(db, instance_id, target_category_id, target_sub_category_id, target_super_category_id)
    return templates.TemplateResponse(
        request=request,
        name="manager/instances/picker.html",
        context={**ctx, "session": session, "manager": manager, "instance": instance, "active_tab": "instances"},
    )


@router.get("/{instance_id}/picker/categories")
async def manager_instance_picker_categories(
    request: Request,
    instance_id: str,
    q: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    await verify_manager_instance_access(db, session["user_id"], instance_id)
    items = await picker_categories(db, instance_id, q)
    return JSONResponse(status_code=200, content={"success": True, "items": items})


@router.get("/{instance_id}/picker/subcategories")
async def manager_instance_picker_subcategories(
    request: Request,
    instance_id: str,
    categoryId: str | None = None,
    q: str | None = None,
    target_category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    await verify_manager_instance_access(db, session["user_id"], instance_id)
    items = await picker_subcategories(db, instance_id, categoryId, q, target_category_id)
    return JSONResponse(status_code=200, content={"success": True, "items": items})


@router.get("/{instance_id}/picker/assets")
async def manager_instance_picker_assets(
    request: Request,
    instance_id: str,
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    superCategoryId: str | None = None,
    q: str | None = None,
    target_category_id: str | None = None,
    target_sub_category_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    await verify_manager_instance_access(db, session["user_id"], instance_id)
    res = await picker_assets(db, instance_id, categoryId, subCategoryId, q, target_sub_category_id, page, page_size, superCategoryId)
    return JSONResponse(status_code=200, content={"success": True, **res})


@router.post("/{instance_id}/references")
async def manager_instance_add_references(
    request: Request,
    instance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Add central category, subcategory, or asset references into an app instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    await verify_manager_instance_access(db, session["user_id"], instance_id)

    try:
        data = await request.json()
    except Exception:
        data = {}

    res = await add_references(db, app_instance_id=instance_id, **parse_reference_payload(data))
    return JSONResponse(status_code=200, content={"success": True, "result": res})


@router.post("/{instance_id}/folders/create")
async def manager_instance_create_folder(
    request: Request,
    instance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Create a new category folder or subcategory folder directly inside this app instance."""
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    await verify_manager_instance_access(db, session["user_id"], instance_id)

    try:
        data = await request.json()
    except Exception:
        data = {}

    try:
        return JSONResponse(status_code=200, content=await create_instance_folder(db, instance_id, data))
    except ValidationError as err:
        return JSONResponse(status_code=400, content={"success": False, "message": err.message})


@router.post("/{instance_id}/categories/{cat_id}/super")
async def manager_instance_move_category_super(
    request: Request,
    instance_id: str,
    cat_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    await verify_manager_instance_access(db, session["user_id"], instance_id)
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        res = await set_category_super_category(db, instance_id, cat_id, data.get("super_category_id") or None)
    except ValidationError as err:
        return JSONResponse(status_code=400, content={"success": False, "message": err.message})
    return JSONResponse(status_code=200, content=res)


@router.delete("/{instance_id}/super-categories/{super_id}")
async def manager_instance_delete_super_category_reference(
    request: Request,
    instance_id: str,
    super_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    await verify_manager_instance_access(db, session["user_id"], instance_id)
    res = await remove_reference(db, app_instance_id=instance_id, item_type="super_category", item_id=super_id)
    return JSONResponse(status_code=200, content={"success": True, "data": res})


@router.delete("/{instance_id}/categories/{cat_id}")
async def manager_instance_delete_category_reference(
    request: Request,
    instance_id: str,
    cat_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    res = await remove_reference(db, app_instance_id=instance_id, item_type="category", item_id=cat_id)
    return JSONResponse(status_code=200, content={"success": True, "data": res})


@router.delete("/{instance_id}/subcategories/{sub_id}")
async def manager_instance_delete_subcategory_reference(
    request: Request,
    instance_id: str,
    sub_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    res = await remove_reference(db, app_instance_id=instance_id, item_type="subcategory", item_id=sub_id)
    return JSONResponse(status_code=200, content={"success": True, "data": res})


@router.delete("/{instance_id}/assets/{assetId}")
async def manager_instance_delete_asset_reference(
    request: Request,
    instance_id: str,
    assetId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    res = await remove_reference(db, app_instance_id=instance_id, item_type="asset", item_id=assetId)
    return JSONResponse(status_code=200, content={"success": True, "data": res})

