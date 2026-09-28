from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.category_controller import get_category, list_categories
from controller.csv_update_controller import apply_csv_column_updates
from controller.media_controller import handle_upload, process_subcategory_media_upload
from controller.subcategory_controller import (
    bulk_create_subcategories,
    create_subcategory,
    delete_subcategory,
    get_subcategory,
    list_subcategories,
    update_subcategory,
)
from database.collections import ASSETS, SUBCATEGORIES
from database.models.subcategory import SubcategoryCreate, SubcategoryUpdate
from router.deps import get_db
from utils.csv_utils import parse_lines_list
from utils.datetimes import format_datetime_display
from utils.errors import ConflictError
from utils.ids import to_object_id
from utils.responses import append_query_params, safe_redirect_url
from utils.slugify import slugify

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display
router = APIRouter(prefix="/subcategories", tags=["Admin Subcategories"])


@router.get("")
async def admin_list_subcategories(
    request: Request,
    categoryId: str | None = None,
    page: int = Query(default=1, ge=1),
    search: str | None = None,
    sort: str = Query(default="sequence"),
    order: str = Query(default="asc"),
    deleted: int | None = None,
    name: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    s_clean = (sort or "sequence").lower()
    o_clean = (order or "asc").lower()
    if s_clean in ("sequence", "order", "custom"):
        sort_by = "sequence"
        sort_order = "asc" if o_clean != "desc" else "desc"
        current_sort = "sequence"
    elif s_clean == "oldest" or (s_clean in ("created_at", "created") and o_clean == "asc"):
        sort_by = "created_at"
        sort_order = "asc"
        current_sort = "oldest"
    elif s_clean in ("newest",) or (s_clean in ("created_at", "created") and o_clean == "desc"):
        sort_by = "created_at"
        sort_order = "desc"
        current_sort = "newest"
    else:
        sort_by = "sequence"
        sort_order = "asc"
        current_sort = "sequence"

    data = await list_subcategories(
        db,
        category_id=categoryId,
        page=page,
        page_size=20,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    all_cats = await list_categories(db, page=1, page_size=100)

    # Attach live asset count to each subcategory for critical warning checks
    for item in data.get("items", []):
        try:
            sub_oid = to_object_id(item["id"])
            cnt = await db[ASSETS].count_documents(
                {
                    "$or": [
                        {"sub_category_id": sub_oid},
                        {"sub_category_id": str(item["id"])},
                        {"subCategoryId": sub_oid},
                        {"subCategoryId": str(item["id"])},
                        {"subcategory_id": sub_oid},
                        {"subcategory_id": str(item["id"])},
                    ],
                    "deleted_at": {"$in": [None, False]},
                }
            )
            item["asset_count"] = cnt
            item["assets_count"] = cnt
        except Exception:
            item["asset_count"] = 0
            item["assets_count"] = 0

    toast_message = (
        f"Subcategory '{name}' and associated assets were deleted." if deleted and name else None
    )

    current_return_url = f"{request.url.path}?{request.url.query}" if request.url.query else request.url.path
    return templates.TemplateResponse(
        request=request,
        name="subcategories/list.html",
        context={
            "session": session,
            "data": data,
            "categories": all_cats.get("items", []),
            "selected_category_id": categoryId or "",
            "search": search or "",
            "sort": current_sort,
            "order": sort_order,
            "active_tab": "subcategories",
            "toast_message": toast_message,
            "return_url": current_return_url,
        },
    )


@router.get("/new")
async def admin_new_subcategory_page(
    request: Request,
    categoryId: str | None = None,
    return_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    all_cats = await list_categories(db, page=1, page_size=100)
    safe_return = safe_redirect_url(return_url, "/admin/subcategories")
    return templates.TemplateResponse(
        request=request,
        name="subcategories/form.html",
        context={
            "session": session,
            "subcategory": None,
            "categories": all_cats.get("items", []),
            "selected_category_id": categoryId or "",
            "error": None,
            "active_tab": "subcategories",
            "return_url": safe_return,
        },
    )


@router.post("/new")
async def admin_create_subcategory(
    request: Request,
    name: str = Form(...),
    category_id: str = Form(...),
    thumbnail_url: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    image_file: UploadFile | None = File(default=None),
    return_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        parent_cat = await get_category(db, category_id=category_id)
        parent_folder = parent_cat.get("folder_name") or slugify(parent_cat["name"]) or "category"
        sub_folder = slugify(name.strip()) or "subcategory"
        final_img_url, final_thumb_url = await process_subcategory_media_upload(
            category_folder=parent_folder,
            subcategory_folder=sub_folder,
            image_file=image_file,
            thumbnail_file=thumbnail_file,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            thumb_option=thumb_option,
        )
        await create_subcategory(
            db,
            SubcategoryCreate(
                name=name,
                category_id=category_id,
                thumbnail_url=final_thumb_url or None,
                image_url=final_img_url or None,
            ),
        )
        redirect_target = safe_redirect_url(return_url, "/admin/subcategories")
        return RedirectResponse(url=redirect_target, status_code=303)
    except ConflictError as err:
        all_cats = await list_categories(db, page=1, page_size=100)
        return templates.TemplateResponse(
            request=request,
            name="subcategories/form.html",
            context={
                "session": session,
                "subcategory": {
                    "name": name,
                    "thumbnail_url": thumbnail_url,
                    "image_url": image_url,
                },
                "categories": all_cats.get("items", []),
                "selected_category_id": category_id,
                "error": err.message,
                "active_tab": "subcategories",
                "return_url": safe_redirect_url(return_url, "/admin/subcategories"),
            },
            status_code=409,
        )


@router.get("/bulk")
async def admin_bulk_subcategories_page(
    request: Request,
    categoryId: str | None = None,
    return_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    all_cats = await list_categories(db, page=1, page_size=100)
    safe_return = safe_redirect_url(return_url, "/admin/subcategories")
    return templates.TemplateResponse(
        request=request,
        name="subcategories/bulk.html",
        context={
            "session": session,
            "categories": all_cats.get("items", []),
            "selected_category_id": categoryId or "",
            "results": None,
            "active_tab": "subcategories",
            "return_url": safe_return,
        },
    )


@router.post("/bulk")
async def admin_bulk_subcategories_submit(
    request: Request,
    category_id: str = Form(...),
    names_list: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    thumbnail_url: str | None = Form(default=None),
    return_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    items: list[SubcategoryCreate] = []

    final_thumb_url: str | None = (
        thumbnail_url.strip() if thumbnail_url and thumbnail_url.strip() else None
    )

    # Process uploaded thumbnail file if provided
    if thumbnail_file and hasattr(thumbnail_file, "filename") and thumbnail_file.filename:
        raw = await thumbnail_file.read()
        if raw:
            upload_res = await handle_upload(
                file_bytes=raw,
                filename=thumbnail_file.filename,
                target_subdir="thumbnails",
            )
            final_thumb_url = upload_res.get("thumbnail_url") or upload_res.get("url")

    if names_list and names_list.strip():
        for name in parse_lines_list(names_list):
            items.append(
                SubcategoryCreate(
                    name=name, category_id=category_id, thumbnail_url=final_thumb_url
                )
            )

    if items:
        await bulk_create_subcategories(db, items=items)

    redirect_target = safe_redirect_url(return_url, "/admin/subcategories")
    return RedirectResponse(url=redirect_target, status_code=303)


@router.post("/upload-csv")
async def admin_upload_csv_subcategories(
    request: Request,
    csv_file: UploadFile = File(...),
    categoryId: str | None = Form(default=None),
    search: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    if not csv_file or not csv_file.filename:
        return JSONResponse(
            status_code=400, content={"success": False, "message": "No CSV file provided"}
        )

    # Scoping filter: only apply updates to records in the active category or search filter
    cat_id = categoryId or request.query_params.get("categoryId") or None
    search_term = search or request.query_params.get("search") or None

    filter_query: dict = {}
    if cat_id and cat_id.strip():
        try:
            cat_oid = to_object_id(cat_id.strip())
            filter_query["$or"] = [{"category_id": cat_oid}, {"category_id": str(cat_id.strip())}]
        except Exception:
            filter_query["category_id"] = str(cat_id.strip())

    if search_term and search_term.strip():
        filter_query["name"] = {"$regex": search_term.strip(), "$options": "i"}

    content = await csv_file.read()
    result = await apply_csv_column_updates(
        db=db,
        collection_name=SUBCATEGORIES,
        content=content,
        filter_query=filter_query,
        is_asset=False,
    )
    return JSONResponse(content=result)


@router.get("/{id}/edit")
async def admin_edit_subcategory_page(
    request: Request,
    id: str,
    return_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    sub = await get_subcategory(db, subcategory_id=id)
    all_cats = await list_categories(db, page=1, page_size=100)
    safe_return = safe_redirect_url(return_url, "/admin/subcategories")
    return templates.TemplateResponse(
        request=request,
        name="subcategories/form.html",
        context={
            "session": session,
            "subcategory": sub,
            "categories": all_cats.get("items", []),
            "selected_category_id": sub.get("category_id", ""),
            "error": None,
            "active_tab": "subcategories",
            "return_url": safe_return,
        },
    )


@router.post("/{id}/edit")
async def admin_update_subcategory(
    request: Request,
    id: str,
    name: str = Form(...),
    thumbnail_url: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    image_file: UploadFile | None = File(default=None),
    return_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    try:
        sub = await get_subcategory(db, subcategory_id=id)
        parent_cat = await get_category(db, category_id=str(sub.get("category_id")))
        parent_folder = parent_cat.get("folder_name") or slugify(parent_cat["name"]) or "category"
        sub_folder = sub.get("folder_name") or slugify(name.strip()) or "subcategory"
        final_img_url, final_thumb_url = await process_subcategory_media_upload(
            category_folder=parent_folder,
            subcategory_folder=sub_folder,
            image_file=image_file,
            thumbnail_file=thumbnail_file,
            image_url=image_url if image_url is not None else sub.get("image_url"),
            thumbnail_url=thumbnail_url if thumbnail_url is not None else sub.get("thumbnail_url"),
            thumb_option=thumb_option,
        )
        await update_subcategory(
            db,
            subcategory_id=id,
            data=SubcategoryUpdate(
                name=name,
                thumbnail_url=final_thumb_url or None,
                image_url=final_img_url or None,
            ),
        )
        redirect_target = safe_redirect_url(return_url, "/admin/subcategories")
        return RedirectResponse(url=redirect_target, status_code=303)
    except ConflictError as err:
        sub = await get_subcategory(db, subcategory_id=id)
        all_cats = await list_categories(db, page=1, page_size=100)
        return templates.TemplateResponse(
            request=request,
            name="subcategories/form.html",
            context={
                "session": session,
                "subcategory": sub,
                "categories": all_cats.get("items", []),
                "selected_category_id": sub.get("category_id", ""),
                "error": err.message,
                "active_tab": "subcategories",
                "return_url": safe_redirect_url(return_url, "/admin/subcategories"),
            },
            status_code=409,
        )


@router.post("/{id}/delete")
async def admin_delete_subcategory(
    request: Request,
    id: str,
    cascade: bool = Form(default=False),
    return_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        sub = await get_subcategory(db, subcategory_id=id)
        sub_name = sub.get("name", "Subcategory")
    except Exception:
        sub_name = "Subcategory"

    try:
        await delete_subcategory(db, subcategory_id=id, cascade=cascade)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(
                content={"success": True, "message": f"Subcategory '{sub_name}' was deleted."}
            )
        base_target = safe_redirect_url(return_url, "/admin/subcategories")
        redirect_target = append_query_params(base_target, {"deleted": 1, "name": sub_name})
        return RedirectResponse(url=redirect_target, status_code=303)
    except ConflictError as err:
        return templates.TemplateResponse(
            request=request,
            name="subcategories/confirm_delete.html",
            context={
                "session": session,
                "subcategory": sub,
                "details": err.details,
                "message": err.message,
                "active_tab": "subcategories",
            },
            status_code=409,
        )


@router.get("/by-category/{category_id}")
@router.get("/api/list")
async def admin_get_subcategories_api(
    request: Request,
    category_id: str | None = None,
    categoryId: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    cat_id = category_id or categoryId
    data = await list_subcategories(db, category_id=cat_id, page=1, page_size=200)
    return JSONResponse(content={"items": data.get("items", [])})


@router.post("/bulk-actions")
async def admin_bulk_subcategory_actions(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    body = await request.json()
    ids = body.get("ids", [])
    action = body.get("action", "")

    from controller.base_controller import execute_central_bulk_action
    from database.collections import SUBCATEGORIES

    result = await execute_central_bulk_action(db, SUBCATEGORIES, ids, action)
    return JSONResponse(content=result)
