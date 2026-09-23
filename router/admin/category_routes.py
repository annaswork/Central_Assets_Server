from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.category_controller import (
    bulk_create_categories,
    create_category,
    delete_category,
    get_category,
    list_categories,
    update_category,
)
from controller.csv_update_controller import apply_csv_column_updates
from controller.media_controller import handle_upload, process_category_media_upload
from database.collections import ASSETS, CATEGORIES, SUBCATEGORIES
from database.models.category import CategoryCreate, CategoryUpdate
from router.deps import get_db
from utils.csv_utils import parse_lines_list
from utils.datetimes import format_datetime_display
from utils.errors import ConflictError
from utils.ids import to_object_id
from utils.slugify import slugify

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display
router = APIRouter(prefix="/categories", tags=["Admin Categories"])


@router.get("")
async def admin_list_categories(
    request: Request,
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

    data = await list_categories(
        db, page=page, page_size=20, search=search, sort_by=sort_by, sort_order=sort_order
    )

    # Attach live subcategory & asset counts for critical warning checks
    for item in data.get("items", []):
        try:
            cat_oid = to_object_id(item["id"])
            item["subcategory_count"] = await db[SUBCATEGORIES].count_documents(
                {"category_id": cat_oid, "deleted_at": None}
            )
            item["asset_count"] = await db[ASSETS].count_documents(
                {"category_id": cat_oid, "deleted_at": None}
            )
        except Exception:
            item["subcategory_count"] = 0
            item["asset_count"] = 0

    toast_message = (
        f"Category '{name}' and all child contents were deleted." if deleted and name else None
    )

    return templates.TemplateResponse(
        request=request,
        name="categories/list.html",
        context={
            "session": session,
            "data": data,
            "search": search or "",
            "sort": current_sort,
            "order": sort_order,
            "active_tab": "categories",
            "toast_message": toast_message,
        },
    )


@router.get("/new")
async def admin_new_category_page(request: Request) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="categories/form.html",
        context={
            "session": session,
            "category": None,
            "error": None,
            "active_tab": "categories",
        },
    )


@router.post("/new")
async def admin_create_category(
    request: Request,
    name: str = Form(...),
    thumbnail_url: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    image_file: UploadFile | None = File(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    folder_name = slugify(name.strip()) or "category"
    try:
        final_img_url, final_thumb_url = await process_category_media_upload(
            category_folder=folder_name,
            image_file=image_file,
            thumbnail_file=thumbnail_file,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            thumb_option=thumb_option,
        )
        await create_category(
            db,
            CategoryCreate(
                name=name,
                thumbnail_url=final_thumb_url or None,
                image_url=final_img_url or None,
            ),
        )
        return RedirectResponse(url="/admin/categories", status_code=303)
    except ConflictError as err:
        return templates.TemplateResponse(
            request=request,
            name="categories/form.html",
            context={
                "session": session,
                "category": {"name": name, "thumbnail_url": thumbnail_url, "image_url": image_url},
                "error": err.message,
                "active_tab": "categories",
            },
            status_code=409,
        )


@router.get("/bulk")
async def admin_bulk_categories_page(request: Request) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="categories/bulk.html",
        context={"session": session, "results": None, "active_tab": "categories"},
    )


@router.post("/bulk")
async def admin_bulk_categories_submit(
    request: Request,
    names_list: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    thumbnail_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    items: list[CategoryCreate] = []

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

    # Plain text lines
    if names_list and names_list.strip():
        for name in parse_lines_list(names_list):
            items.append(CategoryCreate(name=name, thumbnail_url=final_thumb_url))

    if items:
        await bulk_create_categories(db, items=items)

    return RedirectResponse(url="/admin/categories", status_code=303)


@router.post("/upload-csv")
async def admin_upload_csv_categories(
    request: Request,
    csv_file: UploadFile = File(...),
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

    # Scoping filter: only apply updates to records in the active search filter
    search_term = search or request.query_params.get("search") or None
    filter_query: dict = {}
    if search_term and search_term.strip():
        filter_query["name"] = {"$regex": search_term.strip(), "$options": "i"}

    content = await csv_file.read()
    result = await apply_csv_column_updates(
        db=db,
        collection_name=CATEGORIES,
        content=content,
        filter_query=filter_query,
        is_asset=False,
    )
    return JSONResponse(content=result)


@router.get("/{id}/edit")
async def admin_edit_category_page(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    cat = await get_category(db, category_id=id)
    return templates.TemplateResponse(
        request=request,
        name="categories/form.html",
        context={
            "session": session,
            "category": cat,
            "error": None,
            "active_tab": "categories",
        },
    )


@router.post("/{id}/edit")
async def admin_update_category(
    request: Request,
    id: str,
    name: str = Form(...),
    thumbnail_url: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    image_file: UploadFile | None = File(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    try:
        cat = await get_category(db, category_id=id)
        folder_name = cat.get("folder_name") or slugify(name.strip()) or "category"
        final_img_url, final_thumb_url = await process_category_media_upload(
            category_folder=folder_name,
            image_file=image_file,
            thumbnail_file=thumbnail_file,
            image_url=image_url if image_url is not None else cat.get("image_url"),
            thumbnail_url=thumbnail_url if thumbnail_url is not None else cat.get("thumbnail_url"),
            thumb_option=thumb_option,
        )
        await update_category(
            db,
            category_id=id,
            data=CategoryUpdate(
                name=name,
                thumbnail_url=final_thumb_url or None,
                image_url=final_img_url or None,
            ),
        )
        return RedirectResponse(url="/admin/categories", status_code=303)
    except ConflictError as err:
        cat = await get_category(db, category_id=id)
        return templates.TemplateResponse(
            request=request,
            name="categories/form.html",
            context={
                "session": session,
                "category": cat,
                "error": err.message,
                "active_tab": "categories",
            },
            status_code=409,
        )


@router.post("/{id}/delete")
async def admin_delete_category(
    request: Request,
    id: str,
    cascade: bool = Form(default=False),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        cat = await get_category(db, category_id=id)
        cat_name = cat.get("name", "Category")
    except Exception:
        cat_name = "Category"

    try:
        await delete_category(db, category_id=id, cascade=cascade)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(
                content={"success": True, "message": f"Category '{cat_name}' was deleted."}
            )
        return RedirectResponse(
            url=f"/admin/categories?deleted=1&name={quote_plus(cat_name)}", status_code=303
        )
    except ConflictError as err:
        # Re-render with cascade confirmation blast-radius details
        return templates.TemplateResponse(
            request=request,
            name="categories/confirm_delete.html",
            context={
                "session": session,
                "category": cat,
                "details": err.details,
                "message": err.message,
                "active_tab": "categories",
            },
            status_code=409,
        )


@router.post("/bulk-actions")
async def admin_bulk_category_actions(
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
    from database.collections import CATEGORIES

    result = await execute_central_bulk_action(db, CATEGORIES, ids, action)
    return JSONResponse(content=result)
