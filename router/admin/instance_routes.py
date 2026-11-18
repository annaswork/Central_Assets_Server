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
from controller.override_controller import reorder_items, update_item_settings_and_overrides
from controller.reference_controller import (
    add_references,
    get_unresolved_references,
    remove_reference,
)
from database.collections import (
    INSTANCE_ASSETS,
    INSTANCE_CATEGORIES,
    INSTANCE_SUBCATEGORIES,
)
from database.models.app_instance import AppInstanceCreate, AppInstanceUpdate
from router.deps import get_db
from utils.errors import ValidationError
from utils.ids import to_object_id

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
    type: str | None = None,
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
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    instance = await get_app_instance(db, instance_id=id)
    search_query = (q or search or "").strip()
    ctx = await build_instance_content(
        db,
        id,
        category_id=categoryId,
        sub_category_id=subCategoryId,
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
    unresolved = await get_unresolved_references(db, app_instance_id=id)

    active_tab_selection = tab or (
        "assets" if (categoryId or subCategoryId or superCategoryId or ctx["selected_type"] or search_query) else "folders"
    )

    return templates.TemplateResponse(
        request=request,
        name="instances/content.html",
        context={
            **ctx,
            "session": session,
            "instance": instance,
            "selected_tab": active_tab_selection,
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
    target_super_category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    instance = await get_app_instance(db, instance_id=id)
    ctx = await build_picker_page(db, id, target_category_id, target_sub_category_id, target_super_category_id)
    return templates.TemplateResponse(
        request=request,
        name="instances/picker.html",
        context={**ctx, "session": session, "instance": instance, "active_tab": "instances"},
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

    items = await picker_categories(db, id, q)
    return JSONResponse(status_code=200, content={"success": True, "items": items})


@router.get("/{id}/picker/subcategories")
async def admin_instance_picker_subcategories(
    request: Request,
    id: str,
    categoryId: str | None = None,
    q: str | None = None,
    target_category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    items = await picker_subcategories(db, id, categoryId, q, target_category_id)
    return JSONResponse(status_code=200, content={"success": True, "items": items})


@router.get("/{id}/picker/assets")
async def admin_instance_picker_assets(
    request: Request,
    id: str,
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
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    res = await picker_assets(db, id, categoryId, subCategoryId, q, target_sub_category_id, page, page_size, superCategoryId)
    return JSONResponse(status_code=200, content={"success": True, **res})


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

    res = await add_references(db, app_instance_id=id, **parse_reference_payload(data))
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

    try:
        return JSONResponse(status_code=200, content=await create_instance_folder(db, id, data))
    except ValidationError as err:
        return JSONResponse(status_code=400, content={"success": False, "message": err.message})


@router.post("/{id}/categories/{catId}/super")
async def admin_instance_move_category_super(
    request: Request,
    id: str,
    catId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        res = await set_category_super_category(db, id, catId, data.get("super_category_id") or None)
    except ValidationError as err:
        return JSONResponse(status_code=400, content={"success": False, "message": err.message})
    return JSONResponse(status_code=200, content=res)


@router.delete("/{id}/super-categories/{superId}")
async def admin_instance_delete_super_category_reference(
    request: Request,
    id: str,
    superId: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    res = await remove_reference(db, app_instance_id=id, item_type="super_category", item_id=superId)
    return JSONResponse(status_code=200, content={"success": True, "data": res})


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

    res = await update_item_settings_and_overrides(
        db, app_instance_id=id, item_type="asset", item_id=assetId, **parse_asset_override_payload(payload)
    )
    return JSONResponse(status_code=200, content={"success": True, "data": serialize_mongo_doc(res)})


@router.patch("/{id}/folders/{folder_type}/{folder_id}/override")
async def admin_instance_folder_override(
    request: Request,
    id: str,
    folder_type: str,
    folder_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Rename, reorder, enable or set premium on a super category / category / subcategory in this instance."""
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    res = await update_item_settings_and_overrides(
        db, app_instance_id=id, item_id=folder_id, **parse_folder_override_payload(folder_type, payload)
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
        start=max(0, int(body.get("start") or 0)),
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
