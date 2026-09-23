"""Admin panel routes for managing central creative assets."""

import json
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.asset_controller import (
    check_asset_name_availability,
    create_asset,
    delete_asset,
    derive_asset_name,
    get_asset,
    get_asset_references,
    list_assets,
    update_asset,
)
from controller.category_controller import list_categories
from controller.csv_update_controller import apply_csv_column_updates
from controller.subcategory_controller import get_subcategory, list_subcategories
from database.collections import ASSETS
from database.models.asset import AssetCreate, AssetUpdate
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import ConflictError
from utils.ids import to_object_id

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display
router = APIRouter(prefix="/assets", tags=["Admin Assets"])


@router.get("/check-name")
async def admin_check_asset_name(
    request: Request,
    name: str = Query(default=""),
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    assetId: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return JSONResponse(
            status_code=401, content={"available": False, "message": "Unauthorized"}
        )

    result = await check_asset_name_availability(
        db=db,
        name=name,
        category_id=categoryId,
        sub_category_id=subCategoryId,
        asset_id=assetId,
    )
    return JSONResponse(content=result)


@router.get("")
async def admin_list_assets(
    request: Request,
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    page: int = Query(default=1, ge=1),
    q: str | None = None,
    type: str | None = Query(default=None),
    sort: str = Query(default="sequence"),
    order: str = Query(default="asc"),
    deleted: int | None = None,
    name: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    # Normalize data type filter (images, videos, audios, json, frames)
    clean_type = (type or "").strip().lower()
    if clean_type in ("image", "images"):
        selected_type = "images"
    elif clean_type in ("video", "videos"):
        selected_type = "videos"
    elif clean_type in ("audio", "audios"):
        selected_type = "audios"
    elif clean_type in ("json", "json_data"):
        selected_type = "json"
    elif clean_type in ("frame", "frames"):
        selected_type = "frames"
    else:
        selected_type = ""

    # If subCategoryId is provided but categoryId is missing, resolve category from subcategory
    if subCategoryId and not categoryId:
        try:
            sub_obj = await get_subcategory(db, subCategoryId)
            if sub_obj and "category_id" in sub_obj:
                categoryId = sub_obj["category_id"]
        except Exception:
            pass

    # Normalize sort & order
    s_clean = (sort or "sequence").lower()
    o_clean = (order or "asc").lower()
    if s_clean in ("sequence", "order", "custom"):
        effective_sort_by = "sequence"
        effective_sort_order = "asc" if o_clean != "desc" else "desc"
        current_sort = "sequence"
    elif s_clean in ("name", "by_name", "title"):
        effective_sort_by = "name"
        effective_sort_order = "asc" if o_clean != "desc" else "desc"
        current_sort = "name"
    elif s_clean == "oldest" or (s_clean in ("created_at", "created") and o_clean == "asc"):
        effective_sort_by = "created_at"
        effective_sort_order = "asc"
        current_sort = "oldest"
    elif s_clean == "most_viewed" or (s_clean == "views" and o_clean != "asc"):
        effective_sort_by = "views"
        effective_sort_order = "desc"
        current_sort = "most_viewed"
    elif s_clean == "views" and o_clean == "asc":
        effective_sort_by = "views"
        effective_sort_order = "asc"
        current_sort = "views"
    elif s_clean == "most_downloaded" or (s_clean == "downloads" and o_clean != "asc"):
        effective_sort_by = "downloads"
        effective_sort_order = "desc"
        current_sort = "most_downloaded"
    elif s_clean == "downloads" and o_clean == "asc":
        effective_sort_by = "downloads"
        effective_sort_order = "asc"
        current_sort = "downloads"
    elif s_clean in ("newest",) or (s_clean in ("created_at", "created") and o_clean == "desc"):
        effective_sort_by = "created_at"
        effective_sort_order = "desc"
        current_sort = "newest"
    else:
        effective_sort_by = "sequence"
        effective_sort_order = "asc"
        current_sort = "sequence"

    data = await list_assets(
        db,
        category_id=categoryId,
        sub_category_id=subCategoryId,
        search=q,
        page=page,
        page_size=20,
        sort_by=effective_sort_by,
        sort_order=effective_sort_order,
        asset_type=selected_type,
    )
    all_cats = await list_categories(db, page=1, page_size=100)
    all_subs = await list_subcategories(db, category_id=categoryId, page=1, page_size=200)

    toast_message = (
        f"Asset '{name}' and its storage file were permanently deleted from disk."
        if deleted and name
        else None
    )

    category_map = {str(c["id"]): c["name"] for c in all_cats.get("items", [])}
    if categoryId:
        all_subs_for_map = await list_subcategories(db, page=1, page_size=500)
        subcategory_map = {str(s["id"]): s["name"] for s in all_subs_for_map.get("items", [])}
    else:
        subcategory_map = {str(s["id"]): s["name"] for s in all_subs.get("items", [])}

    return templates.TemplateResponse(
        request=request,
        name="assets/list.html",
        context={
            "session": session,
            "data": data,
            "categories": all_cats.get("items", []),
            "subcategories": all_subs.get("items", []),
            "category_map": category_map,
            "subcategory_map": subcategory_map,
            "selected_cat": categoryId or "",
            "selected_sub": subCategoryId or "",
            "selected_type": selected_type,
            "type": selected_type,
            "search": q or "",
            "sort": effective_sort_by,
            "order": effective_sort_order,
            "current_sort": current_sort,
            "active_tab": "assets",
            "toast_message": toast_message,
        },
    )


@router.post("/upload-csv")
async def admin_upload_csv_assets(
    request: Request,
    csv_file: UploadFile = File(...),
    categoryId: str | None = Form(default=None),
    subCategoryId: str | None = Form(default=None),
    q: str | None = Form(default=None),
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

    # Scoping filter: only apply updates to records in the active category, subcategory, or search filter
    cat_id = categoryId or request.query_params.get("categoryId") or None
    sub_id = subCategoryId or request.query_params.get("subCategoryId") or None
    q_search = (
        q or search or request.query_params.get("q") or request.query_params.get("search") or None
    )

    filter_query: dict = {}
    if cat_id and cat_id.strip():
        try:
            filter_query["category_id"] = to_object_id(cat_id.strip())
        except Exception:
            filter_query["category_id"] = str(cat_id.strip())

    if sub_id and sub_id.strip():
        try:
            filter_query["sub_category_id"] = to_object_id(sub_id.strip())
        except Exception:
            filter_query["sub_category_id"] = str(sub_id.strip())

    if q_search and q_search.strip():
        filter_query["name"] = {"$regex": q_search.strip(), "$options": "i"}

    content = await csv_file.read()
    result = await apply_csv_column_updates(
        db=db,
        collection_name=ASSETS,
        content=content,
        filter_query=filter_query,
        is_asset=True,
    )
    return JSONResponse(content=result)


@router.get("/new")
async def admin_new_asset_redirect(
    request: Request,
    categoryId: str | None = None,
    category_id: str | None = None,
    subCategoryId: str | None = None,
    sub_category_id: str | None = None,
) -> Response:
    cat_id = categoryId or category_id
    sub_id = subCategoryId or sub_category_id
    params = []
    if cat_id:
        params.append(f"categoryId={cat_id}")
    if sub_id:
        params.append(f"subCategoryId={sub_id}")
    query = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(url=f"/admin/assets/new-multi{query}", status_code=303)


@router.get("/new-single")
async def admin_new_single_asset_page(
    request: Request,
    categoryId: str | None = None,
    category_id: str | None = None,
    subCategoryId: str | None = None,
    sub_category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    target_cat_id = categoryId or category_id
    target_sub_id = subCategoryId or sub_category_id

    if target_sub_id and not target_cat_id:
        try:
            sub_doc = await get_subcategory(db, subcategory_id=target_sub_id)
            if sub_doc and sub_doc.get("category_id"):
                target_cat_id = str(sub_doc["category_id"])
        except Exception:
            pass

    all_cats = await list_categories(db, page=1, page_size=100)
    all_subs = (
        await list_subcategories(db, category_id=target_cat_id, page=1, page_size=200)
        if target_cat_id
        else {"items": []}
    )
    return templates.TemplateResponse(
        request=request,
        name="assets/form_single.html",
        context={
            "session": session,
            "categories": all_cats.get("items", []),
            "subcategories": all_subs.get("items", []),
            "selected_cat": target_cat_id or "",
            "selected_sub": target_sub_id or "",
            "active_tab": "assets",
        },
    )


@router.get("/new-multi")
async def admin_new_multi_asset_page(
    request: Request,
    categoryId: str | None = None,
    category_id: str | None = None,
    subCategoryId: str | None = None,
    sub_category_id: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    target_cat_id = categoryId or category_id
    target_sub_id = subCategoryId or sub_category_id

    if target_sub_id and not target_cat_id:
        try:
            sub_doc = await get_subcategory(db, subcategory_id=target_sub_id)
            if sub_doc and sub_doc.get("category_id"):
                target_cat_id = str(sub_doc["category_id"])
        except Exception:
            pass

    all_cats = await list_categories(db, page=1, page_size=100)
    all_subs = (
        await list_subcategories(db, category_id=target_cat_id, page=1, page_size=200)
        if target_cat_id
        else {"items": []}
    )
    return templates.TemplateResponse(
        request=request,
        name="assets/form_multi.html",
        context={
            "session": session,
            "asset": None,
            "categories": all_cats.get("items", []),
            "subcategories": all_subs.get("items", []),
            "selected_cat": target_cat_id or "",
            "selected_sub": target_sub_id or "",
            "active_tab": "assets",
        },
    )


@router.get("/{id}/edit")
async def admin_edit_asset_page(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    asset = await get_asset(db, asset_id=id)
    if "more_fields" in asset and "moreFields" not in asset:
        asset["moreFields"] = asset["more_fields"]
    if "moreFields" in asset and "more_fields" not in asset:
        asset["more_fields"] = asset["moreFields"]
    if "thumbnail_url" in asset and "thumbnailUrl" not in asset:
        asset["thumbnailUrl"] = asset["thumbnail_url"]
    if "thumbnailUrl" in asset and "thumbnail_url" not in asset:
        asset["thumbnail_url"] = asset["thumbnailUrl"]
    if "category_id" in asset and "categoryId" not in asset:
        asset["categoryId"] = asset["category_id"]
    if "sub_category_id" in asset and "subCategoryId" not in asset:
        asset["subCategoryId"] = asset["sub_category_id"]

    all_cats = await list_categories(db, page=1, page_size=100)
    target_cat_id = asset.get("categoryId") or asset.get("category_id")
    all_subs = await list_subcategories(db, category_id=target_cat_id, page=1, page_size=200)
    references = await get_asset_references(db, asset_id=id)

    return templates.TemplateResponse(
        request=request,
        name="assets/form_multi.html",
        context={
            "session": session,
            "asset": asset,
            "categories": all_cats.get("items", []),
            "subcategories": all_subs.get("items", []),
            "references": references,
            "active_tab": "assets",
        },
    )


@router.get("/{id}/frames")
async def admin_frame_editor_page(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    asset = await get_asset(db, asset_id=id)
    if "more_fields" in asset and "moreFields" not in asset:
        asset["moreFields"] = asset["more_fields"]
    if "moreFields" in asset and "more_fields" not in asset:
        asset["more_fields"] = asset["moreFields"]
    if "thumbnail_url" in asset and "thumbnailUrl" not in asset:
        asset["thumbnailUrl"] = asset["thumbnail_url"]

    return templates.TemplateResponse(
        request=request,
        name="assets/frames_editor.html",
        context={"session": session, "asset": asset, "active_tab": "assets"},
    )


@router.post("/save")
async def admin_save_asset(
    request: Request,
    id: str | None = Form(default=None),
    name: str | None = Form(default=None),
    description: str = Form(default=""),
    category_id: str = Form(...),
    sub_category_id: str = Form(...),
    thumbnail_url: str | None = Form(default=None),
    more_fields_json: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    more_fields: dict[str, Any] = {}
    if more_fields_json and more_fields_json.strip():
        try:
            more_fields = json.loads(more_fields_json)
        except Exception:
            pass

    # If Asset name is not provided, pick the name of very first file that is uploaded
    clean_name = name.strip() if name and name.strip() else ""
    clean_thumb_url = thumbnail_url.strip() if thumbnail_url and thumbnail_url.strip() else None
    if not clean_name:
        clean_name = derive_asset_name(clean_thumb_url, more_fields)

    try:
        if id:
            await update_asset(
                db,
                asset_id=id,
                data=AssetUpdate(
                    name=clean_name,
                    description=description,
                    category_id=category_id,
                    sub_category_id=sub_category_id,
                    thumbnail_url=clean_thumb_url,
                    more_fields=more_fields if more_fields_json is not None else None,
                ),
            )
        else:
            await create_asset(
                db,
                AssetCreate(
                    name=clean_name,
                    description=description,
                    category_id=category_id,
                    sub_category_id=sub_category_id,
                    thumbnail_url=clean_thumb_url,
                    more_fields=more_fields,
                ),
            )
        return RedirectResponse(url="/admin/assets", status_code=303)
    except ConflictError as err:
        all_cats = await list_categories(db, page=1, page_size=100)
        all_subs = await list_subcategories(db, category_id=category_id, page=1, page_size=200)
        return templates.TemplateResponse(
            request=request,
            name="assets/form_multi.html",
            context={
                "session": session,
                "asset": {
                    "id": id,
                    "name": clean_name,
                    "description": description,
                    "categoryId": category_id,
                    "category_id": category_id,
                    "subCategoryId": sub_category_id,
                    "sub_category_id": sub_category_id,
                    "thumbnailUrl": thumbnail_url,
                    "thumbnail_url": thumbnail_url,
                    "moreFields": more_fields,
                    "more_fields": more_fields,
                },
                "categories": all_cats.get("items", []),
                "subcategories": all_subs.get("items", []),
                "error": f"{err.message} Please provide a different name to rename the asset.",
                "active_tab": "assets",
            },
            status_code=409,
        )


@router.post("/{id}/delete")
async def admin_delete_asset(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        asset = await get_asset(db, asset_id=id)
        asset_name = asset.get("name", "Asset")
    except Exception:
        asset_name = "Asset"

    result = await delete_asset(db, asset_id=id)

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            content={
                "success": True,
                "message": f"Asset '{asset_name}' and its storage file were permanently deleted from disk.",
                "deleted_files": result.get("deleted_files", []),
            }
        )

    return RedirectResponse(
        url=f"/admin/assets?deleted=1&name={quote_plus(asset_name)}", status_code=303
    )


@router.post("/bulk-actions")
async def admin_bulk_asset_actions(
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
    from database.collections import ASSETS

    result = await execute_central_bulk_action(db, ASSETS, ids, action)
    return JSONResponse(content=result)
