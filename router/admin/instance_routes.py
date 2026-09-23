import re

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.app_instance_controller import (
    create_app_instance,
    delete_app_instance,
    get_app_instance,
    list_app_instances,
    update_app_instance,
)
from database.models.app_instance import AppInstanceCreate, AppInstanceUpdate
from controller.asset_controller import list_assets
from controller.base_controller import serialize_mongo_doc
from controller.catalog_controller import (
    get_resolved_assets,
    get_resolved_categories,
    get_resolved_subcategories,
)
from controller.category_controller import create_category, list_categories
from controller.override_controller import reorder_items, update_item_settings_and_overrides
from controller.reference_controller import (
    add_references,
    get_unresolved_references,
    remove_reference,
)
from controller.subcategory_controller import create_subcategory, list_subcategories
from database.collections import (
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
    SUBCATEGORIES,
)
from bson import ObjectId
from database.models.app_instance import AppInstanceCreate
from database.models.category import CategoryCreate
from database.models.subcategory import SubcategoryCreate
from router.deps import get_db
from utils.datetimes import utc_now
from utils.ids import to_object_id
from utils.sequencing import compute_next_sequence

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/instances", tags=["Admin App Instances"])


@router.get("")
async def admin_list_instances(
    request: Request,
    page: int = Query(default=1, ge=1),
    search: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    data = await list_app_instances(db, page=page, page_size=20, search=search)
    return templates.TemplateResponse(
        request=request,
        name="instances/list.html",
        context={
            "session": session,
            "data": data,
            "search": search or "",
            "active_tab": "instances",
        },
    )


@router.get("/new")
async def admin_new_instance_page(request: Request) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="instances/form.html",
        context={
            "session": session,
            "instance": None,
            "error": None,
            "active_tab": "instances",
        },
    )


@router.post("/new")
async def admin_create_instance(
    request: Request,
    name: str = Form(...),
    package_name: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    clean_pkg = (
        package_name.strip()
        if (package_name and package_name.strip() and package_name.strip().lower() != "none")
        else None
    )
    try:
        created = await create_app_instance(
            db,
            AppInstanceCreate(
                name=name.strip(),
                package_name=clean_pkg,
            ),
        )
        return RedirectResponse(url="/admin/instances", status_code=303)
    except Exception as err:
        return templates.TemplateResponse(
            request=request,
            name="instances/form.html",
            context={
                "session": session,
                "instance": {"name": name, "package_name": package_name},
                "error": str(err),
                "active_tab": "instances",
            },
            status_code=400,
        )


@router.get("/{id}/edit")
async def admin_edit_instance_view(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    instance = await get_app_instance(db, instance_id=id)
    return templates.TemplateResponse(
        request=request,
        name="instances/form.html",
        context={
            "session": session,
            "instance": instance,
            "error": None,
            "active_tab": "instances",
        },
    )


@router.post("/{id}/edit")
async def admin_update_instance(
    request: Request,
    id: str,
    name: str = Form(...),
    package_name: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    clean_pkg = (
        package_name.strip()
        if (package_name and package_name.strip() and package_name.strip().lower() != "none")
        else None
    )
    try:
        await update_app_instance(
            db,
            instance_id=id,
            data=AppInstanceUpdate(
                name=name.strip(),
                package_name=clean_pkg,
            ),
        )
        return RedirectResponse(url="/admin/instances", status_code=303)
    except Exception as err:
        return templates.TemplateResponse(
            request=request,
            name="instances/form.html",
            context={
                "session": session,
                "instance": {"id": id, "name": name, "package_name": package_name},
                "error": str(err),
                "active_tab": "instances",
            },
            status_code=400,
        )


@router.get("/{id}/content")
async def admin_instance_content_view(
    request: Request,
    id: str,
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    tab: str | None = None,
    sort: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    inst_oid = to_object_id(id)
    instance = await get_app_instance(db, instance_id=id)
    categories = await get_resolved_categories(db, app_instance_id=id)

    # Calculate live subcategory and asset counts for each category in this instance
    for cat in categories:
        c_src_oid = to_object_id(cat.get("sourceId") or cat.get("id"))
        cat["subcategories_count"] = await db[INSTANCE_SUBCATEGORIES].count_documents(
            {"app_instance_id": inst_oid, "category_id": c_src_oid, "deleted_at": None}
        )
        cat["assets_count"] = await db[INSTANCE_ASSETS].count_documents(
            {"app_instance_id": inst_oid, "category_id": c_src_oid, "deleted_at": None}
        )

    all_subcategories = await get_resolved_subcategories(db, app_instance_id=id)
    for sub in all_subcategories:
        s_src_oid = to_object_id(sub.get("sourceId") or sub.get("id"))
        sub["assets_count"] = await db[INSTANCE_ASSETS].count_documents(
            {"app_instance_id": inst_oid, "sub_category_id": s_src_oid, "deleted_at": None}
        )

    # Identify all valid identifier forms for the selected category (id and sourceId)
    valid_cat_ids: set[str] = set()
    selected_cat_val = ""
    if categoryId:
        for c in categories:
            if str(c.get("id")) == categoryId or str(c.get("sourceId")) == categoryId:
                selected_cat_val = str(c.get("id") or categoryId)
                if c.get("id"):
                    valid_cat_ids.add(str(c["id"]))
                if c.get("sourceId"):
                    valid_cat_ids.add(str(c["sourceId"]))
                break
        if not valid_cat_ids:
            valid_cat_ids.add(str(categoryId))
            selected_cat_val = str(categoryId)

    # Filter relevant subcategories belonging to the chosen category
    filtered_subcategories = (
        [s for s in all_subcategories if str(s.get("categoryId")) in valid_cat_ids]
        if categoryId
        else all_subcategories
    )

    selected_subcat_val = ""
    if subCategoryId:
        for s in all_subcategories:
            if str(s.get("id")) == subCategoryId or str(s.get("sourceId")) == subCategoryId:
                selected_subcat_val = str(s.get("id") or subCategoryId)
                break
        if not selected_subcat_val:
            selected_subcat_val = str(subCategoryId)

    assets = await get_resolved_assets(
        db,
        app_instance_id=id,
        category_id=categoryId,
        sub_category_id=subCategoryId,
        sort=sort,
    )

    # In-memory mapping fallback for instant display
    cat_map = {}
    for c in categories:
        if c.get("id"):
            cat_map[str(c["id"])] = c.get("name")
        if c.get("sourceId"):
            cat_map[str(c["sourceId"])] = c.get("name")

    sub_map = {}
    for s in all_subcategories:
        if s.get("id"):
            sub_map[str(s["id"])] = s.get("name")
        if s.get("sourceId"):
            sub_map[str(s["sourceId"])] = s.get("name")

    for a in assets:
        c_id = str(a.get("categoryId") or "")
        s_id = str(a.get("subCategoryId") or "")
        if not a.get("category_name") or a["category_name"] == "—":
            a["category_name"] = cat_map.get(c_id) or a.get("category_name") or "—"
        a["categoryName"] = a["category_name"]

        if not a.get("subcategory_name") or a["subcategory_name"] == "—":
            a["subcategory_name"] = sub_map.get(s_id) or a.get("subcategory_name") or "—"
        a["subCategoryName"] = a["subcategory_name"]

    unresolved = await get_unresolved_references(db, app_instance_id=id)

    return templates.TemplateResponse(
        request=request,
        name="instances/content.html",
        context={
            "session": session,
            "instance": instance,
            "categories": categories,
            "subcategories": filtered_subcategories,
            "all_subcategories": all_subcategories,
            "assets": assets,
            "selected_cat": selected_cat_val,
            "selected_subcat": selected_subcat_val,
            "selected_tab": tab or ("assets" if (categoryId or subCategoryId) else "folders"),
            "current_sort": sort or "sequence",
            "unresolved_count": unresolved["total_unresolved"],
            "active_tab": "instances",
        },
    )


@router.get("/{id}/picker")
async def admin_instance_picker(
    request: Request,
    id: str,
    target_category_id: str | None = None,
    target_sub_category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    instance = await get_app_instance(db, instance_id=id)
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
        name="instances/picker.html",
        context={
            "session": session,
            "instance": instance,
            "categories": central_cats.get("items", []),
            "subcategories": central_subs.get("items", []),
            "initial_assets": initial_assets.get("items", []),
            "target_category_id": target_category_id or "",
            "target_sub_category_id": target_sub_category_id or "",
            "active_tab": "instances",
        },
    )


@router.get("/{id}/picker/categories")
async def admin_instance_picker_categories(
    request: Request,
    id: str,
    q: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

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


@router.get("/{id}/picker/subcategories")
async def admin_instance_picker_subcategories(
    request: Request,
    id: str,
    categoryId: str | None = None,
    q: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

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


@router.get("/{id}/picker/assets")
async def admin_instance_picker_assets(
    request: Request,
    id: str,
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

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


@router.post("/{id}/references")
async def admin_instance_add_references(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    try:
        data = await request.json()
    except Exception:
        data = {}

    category_ids: list[str] = list(data.get("category_ids") or [])
    sub_category_ids: list[str] = list(data.get("sub_category_ids") or [])
    asset_ids: list[str] = list(data.get("asset_ids") or [])
    target_category_id = data.get("target_category_id") or None
    target_sub_category_id = data.get("target_sub_category_id") or None

    # Support polymorphic items array if passed from client
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
        app_instance_id=id,
        category_ids=list(dict.fromkeys(category_ids)),
        sub_category_ids=list(dict.fromkeys(sub_category_ids)),
        asset_ids=list(dict.fromkeys(asset_ids)),
        target_category_id=target_category_id,
        target_sub_category_id=target_sub_category_id,
    )
    return JSONResponse(status_code=200, content={"success": True, "result": res})


@router.post("/{id}/folders/create")
async def admin_instance_create_folder(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

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

    inst_oid = to_object_id(id)
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

        cat_link_id = parent_cat.get("source_id") or parent_cat["_id"]

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


@router.delete("/{id}/categories/{catId}")
async def admin_instance_delete_category_reference(
    request: Request,
    id: str,
    catId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    res = await remove_reference(db, app_instance_id=id, item_type="category", item_id=catId)
    return JSONResponse(status_code=200, content={"success": True, "data": res})


@router.delete("/{id}/subcategories/{subId}")
async def admin_instance_delete_subcategory_reference(
    request: Request,
    id: str,
    subId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    res = await remove_reference(db, app_instance_id=id, item_type="subcategory", item_id=subId)
    return JSONResponse(status_code=200, content={"success": True, "data": res})



@router.patch("/{id}/assets/{assetId}/override")
async def admin_instance_asset_override(
    request: Request,
    id: str,
    assetId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

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
        app_instance_id=id,
        item_type="asset",
        item_id=assetId,
        is_enabled=is_enabled,
        sequence=sequence,
        is_premium=is_premium,
        overrides=overrides if overrides else None,
    )
    return JSONResponse(status_code=200, content={"success": True, "data": serialize_mongo_doc(res)})


@router.delete("/{id}/assets/{assetId}")
async def admin_instance_delete_asset_reference(
    request: Request,
    id: str,
    assetId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    res = await remove_reference(db, app_instance_id=id, item_type="asset", item_id=assetId)
    return JSONResponse(status_code=200, content={"success": True, "data": res})


@router.post("/{id}/reorder")
async def admin_instance_reorder(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    body = await request.json()
    item_type = body.get("type", "asset")
    ordered_ids = body.get("ordered_ids", [])

    res = await reorder_items(
        db,
        app_instance_id=id,
        item_type=item_type,
        ordered_ids=ordered_ids,
    )
    return JSONResponse(status_code=200, content={"success": True, "data": res})


@router.get("/{id}/unresolved")
async def admin_instance_unresolved(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    instance = await get_app_instance(db, instance_id=id)
    unresolved = await get_unresolved_references(db, app_instance_id=id)

    return templates.TemplateResponse(
        request=request,
        name="instances/unresolved.html",
        context={
            "session": session,
            "instance": instance,
            "unresolved": unresolved,
            "active_tab": "instances",
        },
    )


@router.post("/{id}/prune-unresolved")
async def admin_instance_prune_all_unresolved(
    request: Request,
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    unresolved = await get_unresolved_references(db, app_instance_id=id)
    now = utc_now()

    # Permanently delete all unresolved reference documents
    cat_ids = [to_object_id(c["reference_id"]) for c in unresolved.get("categories", []) if c.get("reference_id")]
    if cat_ids:
        await db[INSTANCE_CATEGORIES].delete_many({"_id": {"$in": cat_ids}})

    sub_ids = [to_object_id(s["reference_id"]) for s in unresolved.get("subcategories", []) if s.get("reference_id")]
    if sub_ids:
        await db[INSTANCE_SUBCATEGORIES].delete_many({"_id": {"$in": sub_ids}})

    asset_ids = [to_object_id(a["reference_id"]) for a in unresolved.get("assets", []) if a.get("reference_id")]
    if asset_ids:
        await db[INSTANCE_ASSETS].delete_many({"_id": {"$in": asset_ids}})

    return JSONResponse(
        status_code=200,
        content={"success": True, "pruned_count": unresolved.get("total_unresolved", 0)},
    )


@router.post("/{id}/delete")
async def admin_delete_instance(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    await delete_app_instance(db, instance_id=id)
    return RedirectResponse(url="/admin/instances", status_code=303)
