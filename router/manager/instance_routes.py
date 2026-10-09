"""Manager portal App Instance routes and central library importing."""

import re
from urllib.parse import quote_plus

from bson import ObjectId
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
from controller.asset_controller import asset_has_type, list_assets
from controller.base_controller import serialize_mongo_doc
from controller.catalog_controller import (
    get_resolved_assets,
    get_resolved_categories,
    get_resolved_subcategories,
)
from controller.category_controller import list_categories
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
from router.deps import get_db
from utils.datetimes import format_datetime_display, utc_now
from utils.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from utils.ids import to_object_id
from utils.sequencing import compute_next_sequence

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
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """View and manage content imported into this app instance with full folder hierarchy."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    user_id = session["user_id"]
    manager = await get_manager_by_id(db, user_id)

    # Scoping check: verify manager has access to this instance
    try:
        await verify_manager_instance_access(db, user_id, instance_id)
    except (ForbiddenError, NotFoundError):
        msg = quote_plus("Access to this app instance has been revoked or is not available.")
        return RedirectResponse(url=f"/manager/instances?msg={msg}&msg_type=error", status_code=303)

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

    # Build category ID alias map: maps both cat["id"] and cat["sourceId"] to cat["id"]
    cat_alias_map = {}
    for c in all_categories:
        cid = str(c.get("id") or "")
        csrc = str(c.get("sourceId") or "")
        if cid:
            cat_alias_map[cid] = cid
        if csrc:
            cat_alias_map[csrc] = cid

    for s in all_subcategories:
        raw_cat_id = str(s.get("categoryId") or "")
        s["canonicalCategoryId"] = cat_alias_map.get(raw_cat_id, raw_cat_id)
        s["categoryId"] = s["canonicalCategoryId"]
        s["category_id"] = s["canonicalCategoryId"]

    cat_id = category_id or categoryId
    sub_id = sub_category_id or subCategoryId
    search_query = (q or search or "").strip()
    clean_type = (type or "").strip().lower()
    s_order = sort or "sequence"

    # Identify all valid identifier forms for the selected category (id and sourceId)
    valid_cat_ids: set[str] = set()
    selected_cat_val = ""
    if cat_id:
        for c in all_categories:
            if str(c.get("id")) == cat_id or str(c.get("sourceId")) == cat_id:
                selected_cat_val = str(c.get("id") or cat_id)
                if c.get("id"):
                    valid_cat_ids.add(str(c["id"]))
                if c.get("sourceId"):
                    valid_cat_ids.add(str(c["sourceId"]))
                break
        if not valid_cat_ids:
            valid_cat_ids.add(str(cat_id))
            selected_cat_val = str(cat_id)

    filtered_subcategories = (
        [s for s in all_subcategories if str(s.get("canonicalCategoryId")) in valid_cat_ids or str(s.get("categoryId")) in valid_cat_ids]
        if cat_id
        else all_subcategories
    )

    selected_subcat_val = ""
    if sub_id:
        for s in all_subcategories:
            if str(s.get("id")) == sub_id or str(s.get("sourceId")) == sub_id:
                selected_subcat_val = str(s.get("id") or sub_id)
                break
        if not selected_subcat_val:
            selected_subcat_val = str(sub_id)

    resolved_assets = await get_resolved_assets(
        db,
        app_instance_id=instance_id,
        category_id=cat_id,
        sub_category_id=sub_id,
        sort=s_order,
    )

    # Filter assets by media type if requested
    if clean_type:
        resolved_assets = [
            a for a in resolved_assets
            if asset_has_type(a.get("more_fields") or a.get("moreFields"), clean_type, a.get("thumbnail_url"))
        ]

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

    # Filter assets by search query if requested
    if search_query:
        sq_lower = search_query.lower()
        resolved_assets = [
            a for a in resolved_assets
            if sq_lower in (a.get("name") or "").lower()
            or sq_lower in (a.get("category_name") or "").lower()
            or sq_lower in (a.get("subcategory_name") or "").lower()
            or any(sq_lower in str(t).lower() for t in a.get("tags", []))
        ]

    # Handle Category & Subcategory folder filtering (Section 1)
    displayed_categories = list(all_categories)
    if folder_cat:
        displayed_categories = [
            c for c in displayed_categories
            if str(c.get("id")) == folder_cat or str(c.get("sourceId")) == folder_cat
        ]

    if folder_search and folder_search.strip():
        fs_lower = folder_search.strip().lower()
        displayed_categories = [
            c for c in displayed_categories
            if fs_lower in (c.get("name") or "").lower()
            or any(
                fs_lower in (s.get("name") or "").lower()
                for s in all_subcategories
                if str(s.get("categoryId")) in (str(c.get("id")), str(c.get("sourceId")))
            )
        ]

    if folder_sort:
        fs_clean = folder_sort.strip().lower()
        if fs_clean == "name":
            displayed_categories.sort(key=lambda c: (c.get("name") or "").lower())
        elif fs_clean == "newest":
            displayed_categories.sort(key=lambda c: str(c.get("created_at") or ""), reverse=True)
        elif fs_clean == "oldest":
            displayed_categories.sort(key=lambda c: str(c.get("created_at") or ""))
        elif fs_clean == "sequence":
            displayed_categories.sort(key=lambda c: c.get("sequence", 0))

    # Auto-select active section
    if request.query_params.get("tab") == "assets" or request.query_params.get("active_section") == "assets" or cat_id or sub_id or clean_type or search_query:
        active_section = "assets"
    elif folder_cat or folder_search or (folder_sort and folder_sort not in ("sequence", "")):
        active_section = "folders"

    return templates.TemplateResponse(
        request=request,
        name="manager/instances/content.html",
        context={
            "session": session,
            "manager": manager,
            "instance": instance,
            "is_owner": is_owner,
            "categories": displayed_categories,
            "all_categories": all_categories,
            "subcategories": filtered_subcategories,
            "all_subcategories": all_subcategories,
            "assets": resolved_assets,
            "central_categories": central_cats.get("items", []),
            "central_subcategories": central_subs.get("items", []),
            "active_section": active_section,
            "selected_cat": selected_cat_val,
            "selected_subcat": selected_subcat_val,
            "selected_category_id": selected_cat_val,
            "selected_subcategory_id": selected_subcat_val,
            "selected_type": clean_type,
            "type": clean_type,
            "current_sort": s_order,
            "sort": s_order,
            "search": search_query,
            "q": search_query,
            "folder_cat": folder_cat or "",
            "folder_sort": folder_sort or "sequence",
            "folder_search": folder_search or "",
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

    is_enabled = payload.get("is_enabled")
    sequence = payload.get("sequence")
    is_premium = payload.get("is_premium")
    is_rewarded = payload.get("is_rewarded")
    if is_rewarded is None:
        is_rewarded = payload.get("isRewarded")
    rewarded_credits = payload.get("rewarded_credits")
    if rewarded_credits is None:
        rewarded_credits = payload.get("rewardedCredits") if "rewardedCredits" in payload else payload.get("credit")
    name = payload.get("name")
    overrides = {}
    if name is not None:
        overrides["name"] = str(name).strip()
    if "tags" in payload:
        raw_tags = payload.get("tags")
        if isinstance(raw_tags, str):
            clean_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            clean_tags = [str(t).strip() for t in raw_tags if str(t).strip()]
        else:
            clean_tags = []
        overrides["tags"] = clean_tags

    res = await update_item_settings_and_overrides(
        db,
        app_instance_id=instance_id,
        item_type="asset",
        item_id=assetId,
        is_enabled=is_enabled,
        sequence=sequence,
        is_premium=is_premium,
        is_rewarded=is_rewarded,
        rewarded_credits=rewarded_credits,
        overrides=overrides if overrides else None,
    )
    return JSONResponse(status_code=200, content={"success": True, "data": serialize_mongo_doc(res)})


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


@router.get("/{instance_id}/picker")
async def manager_instance_picker(
    request: Request,
    instance_id: str,
    target_category_id: str | None = None,
    target_sub_category_id: str | None = None,
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

    initial_assets = await list_assets(db, page=1, page_size=100)

    return templates.TemplateResponse(
        request=request,
        name="manager/instances/picker.html",
        context={
            "session": session,
            "manager": manager,
            "instance": instance,
            "categories": central_cats.get("items", []),
            "subcategories": central_subs.get("items", []),
            "initial_assets": initial_assets.get("items", []),
            "target_category_id": target_category_id or "",
            "target_sub_category_id": target_sub_category_id or "",
            "active_tab": "instances",
        },
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

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    clean_q = q.strip() if q and q.strip() else None
    result = await list_categories(db, search=clean_q, page=1, page_size=200)
    items = result.get("items", [])
    for cat in items:
        c_oid = to_object_id(cat["id"])
        cat["subcategory_count"] = await db[SUBCATEGORIES].count_documents(
            {"category_id": c_oid, "deleted_at": None}
        )
        cat["asset_count"] = await db[ASSETS].count_documents(
            {"category_id": c_oid, "deleted_at": None}
        )
    return JSONResponse(status_code=200, content={"success": True, "items": items})


@router.get("/{instance_id}/picker/subcategories")
async def manager_instance_picker_subcategories(
    request: Request,
    instance_id: str,
    categoryId: str | None = None,
    q: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    clean_cat = categoryId.strip() if categoryId and categoryId.strip() else None
    clean_q = q.strip() if q and q.strip() else None
    result = await list_subcategories(db, category_id=clean_cat, search=clean_q, page=1, page_size=500)
    items = result.get("items", [])
    for sub in items:
        s_oid = to_object_id(sub["id"])
        sub["asset_count"] = await db[ASSETS].count_documents(
            {"sub_category_id": s_oid, "deleted_at": None}
        )
    return JSONResponse(status_code=200, content={"success": True, "items": items})


@router.get("/{instance_id}/picker/assets")
async def manager_instance_picker_assets(
    request: Request,
    instance_id: str,
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_manager_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    clean_cat = categoryId.strip() if categoryId and categoryId.strip() else None
    clean_sub = subCategoryId.strip() if subCategoryId and subCategoryId.strip() else None
    clean_q = q.strip() if q and q.strip() else None

    result = await list_assets(
        db,
        category_id=clean_cat,
        sub_category_id=clean_sub,
        search=clean_q,
        page=page,
        page_size=page_size,
    )
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "items": result.get("items", []),
            "total": result.get("total", 0),
        },
    )


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

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    try:
        data = await request.json()
    except Exception:
        data = {}

    category_ids: list[str] = list(data.get("category_ids") or [])
    sub_category_ids: list[str] = list(data.get("sub_category_ids") or [])
    asset_ids: list[str] = list(data.get("asset_ids") or [])
    target_category_id = data.get("target_category_id") or None
    target_sub_category_id = data.get("target_sub_category_id") or None

    for item in data.get("items", []):
        t_type = item.get("target_type") or item.get("type")
        t_id = item.get("target_id") or item.get("id")
        if t_type == "asset" and t_id:
            asset_ids.append(t_id)
        elif t_type == "category" and t_id:
            category_ids.append(t_id)
        elif t_type in ("subcategory", "sub_category") and t_id:
            sub_category_ids.append(t_id)

    res = await add_references(
        db,
        app_instance_id=instance_id,
        category_ids=list(dict.fromkeys(category_ids)),
        sub_category_ids=list(dict.fromkeys(sub_category_ids)),
        asset_ids=list(dict.fromkeys(asset_ids)),
        target_category_id=target_category_id,
        target_sub_category_id=target_sub_category_id,
    )
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

    user_id = session["user_id"]
    await verify_manager_instance_access(db, user_id, instance_id)

    try:
        data = await request.json()
    except Exception:
        data = {}

    folder_type = str(data.get("folder_type", "category")).strip().lower()
    name = (data.get("name") or "").strip()
    parent_category_id = (data.get("parent_category_id") or "").strip()
    thumbnail_url = (data.get("thumbnail_url") or "").strip() or None

    if not name:
        return JSONResponse(
            status_code=400, content={"success": False, "message": "Folder name is required"}
        )

    inst_oid = to_object_id(instance_id)
    now = utc_now()

    if folder_type == "category":
        # Check if Category folder already exists in this app instance
        existing_cat = await db[INSTANCE_CATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            }
        )
        if existing_cat:
            if existing_cat.get("deleted_at") is not None:
                await db[INSTANCE_CATEGORIES].update_one(
                    {"_id": existing_cat["_id"]},
                    {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                )
                cat_oid = existing_cat["_id"]
            else:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": f"Category folder '{name}' already exists in this app instance"},
                )
        else:
            max_seq_doc = await db[INSTANCE_CATEGORIES].find_one(
                {"app_instance_id": inst_oid, "deleted_at": None},
                sort=[("sequence", -1)],
            )
            seq = compute_next_sequence(max_seq_doc.get("sequence") if max_seq_doc else None)
            cat_oid = ObjectId()
            await db[INSTANCE_CATEGORIES].insert_one(
                {
                    "_id": cat_oid,
                    "app_instance_id": inst_oid,
                    "source_id": None,
                    "name": name,
                    "thumbnail_url": thumbnail_url,
                    "is_enabled": True,
                    "sequence": seq,
                    "overrides": {"name": name, "thumbnail_url": thumbnail_url},
                    "created_at": now,
                    "updated_at": now,
                    "deleted_at": None,
                }
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "folder_type": "category",
                "id": str(cat_oid),
                "name": name,
            },
        )

    elif folder_type == "subcategory":
        if not parent_category_id:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Parent category is required for sub-folder"},
            )
        p_oid = to_object_id(parent_category_id)
        parent_cat = await db[INSTANCE_CATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "$or": [{"_id": p_oid}, {"source_id": p_oid}],
                "deleted_at": None,
            }
        )
        if not parent_cat:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Parent category not found in this app instance"},
            )

        cat_link_id = parent_cat["_id"]

        existing_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
            {
                "app_instance_id": inst_oid,
                "category_id": cat_link_id,
                "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            }
        )
        if existing_sub:
            if existing_sub.get("deleted_at") is not None:
                await db[INSTANCE_SUBCATEGORIES].update_one(
                    {"_id": existing_sub["_id"]},
                    {"$set": {"deleted_at": None, "is_enabled": True, "updated_at": now}},
                )
                sub_oid = existing_sub["_id"]
            else:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": f"Subcategory folder '{name}' already exists in this category"},
                )
        else:
            max_seq_sub = await db[INSTANCE_SUBCATEGORIES].find_one(
                {
                    "app_instance_id": inst_oid,
                    "category_id": cat_link_id,
                    "deleted_at": None,
                },
                sort=[("sequence", -1)],
            )
            sub_seq = compute_next_sequence(max_seq_sub.get("sequence") if max_seq_sub else None)
            sub_oid = ObjectId()
            await db[INSTANCE_SUBCATEGORIES].insert_one(
                {
                    "_id": sub_oid,
                    "app_instance_id": inst_oid,
                    "source_id": None,
                    "category_id": cat_link_id,
                    "name": name,
                    "thumbnail_url": thumbnail_url,
                    "is_enabled": True,
                    "sequence": sub_seq,
                    "overrides": {"name": name, "thumbnail_url": thumbnail_url},
                    "created_at": now,
                    "updated_at": now,
                    "deleted_at": None,
                }
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "folder_type": "subcategory",
                "id": str(sub_oid),
                "name": name,
            },
        )

    return JSONResponse(
        status_code=400, content={"success": False, "message": f"Unknown folder type: {folder_type}"}
    )


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

