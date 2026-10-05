"""Manager portal central library read-only browsing routes."""

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.asset_controller import list_assets
from controller.category_controller import list_categories
from controller.manager_controller import get_manager_by_id
from controller.subcategory_controller import get_subcategory, list_subcategories
from database.collections import ASSETS, SUBCATEGORIES
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.ids import to_object_id

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(tags=["Manager Central Data"])


@router.get("/categories")
async def manager_categories(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500, alias="page_size"),
    limit: int | None = Query(default=None, ge=1, le=500),
    pageSize: int | None = Query(default=None, ge=1, le=500),
    search: str | None = None,
    sort: str = Query(default="sequence"),
    order: str = Query(default="asc"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Read-only view of central categories."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    effective_page_size = pageSize or limit or page_size or 20
    effective_page_size = max(1, min(effective_page_size, 500))

    manager = await get_manager_by_id(db, session["user_id"])

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

    categories_page = await list_categories(
        db, page=page, page_size=effective_page_size, search=search, sort_by=sort_by, sort_order=sort_order
    )

    items = categories_page.get("items", [])
    for item in items:
        try:
            cat_oid = to_object_id(item["id"])
            cnt = await db[SUBCATEGORIES].count_documents(
                {"category_id": cat_oid, "deleted_at": None}
            )
            item["subcategory_count"] = cnt
            item["subcategories_count"] = cnt
            item["asset_count"] = await db[ASSETS].count_documents(
                {"category_id": cat_oid, "deleted_at": None}
            )
        except Exception:
            item["subcategory_count"] = 0
            item["subcategories_count"] = 0
            item["asset_count"] = 0

    return templates.TemplateResponse(
        request=request,
        name="manager/categories/list.html",
        context={
            "session": session,
            "manager": manager,
            "categories": items,
            "data": categories_page,
            "pagination": categories_page,
            "search": search or "",
            "sort": current_sort,
            "order": sort_order,
            "active_tab": "categories",
        },
    )


@router.get("/subcategories")
async def manager_subcategories(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500, alias="page_size"),
    limit: int | None = Query(default=None, ge=1, le=500),
    pageSize: int | None = Query(default=None, ge=1, le=500),
    categoryId: str | None = None,
    category_id: str | None = None,
    search: str | None = None,
    sort: str = Query(default="sequence"),
    order: str = Query(default="asc"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Read-only view of central subcategories."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    effective_page_size = pageSize or limit or page_size or 20
    effective_page_size = max(1, min(effective_page_size, 500))

    effective_cat_id = categoryId or category_id

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

    manager = await get_manager_by_id(db, session["user_id"])
    subcategories_page = await list_subcategories(
        db,
        category_id=effective_cat_id,
        page=page,
        page_size=effective_page_size,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    all_categories = await list_categories(db, page=1, page_size=500)

    cat_map = {str(c["id"]): c.get("name", "") for c in all_categories.get("items", [])}
    sub_items = subcategories_page.get("items", [])
    for sub in sub_items:
        try:
            sub_oid = to_object_id(sub["id"])
            cnt = await db[ASSETS].count_documents(
                {
                    "$or": [
                        {"sub_category_id": sub_oid},
                        {"sub_category_id": str(sub["id"])},
                        {"subCategoryId": sub_oid},
                        {"subCategoryId": str(sub["id"])},
                        {"subcategory_id": sub_oid},
                        {"subcategory_id": str(sub["id"])},
                    ],
                    "deleted_at": {"$in": [None, False]},
                }
            )
            sub["asset_count"] = cnt
            sub["assets_count"] = cnt
            sub["category_name"] = cat_map.get(str(sub.get("category_id", "")), "Unassigned")
        except Exception:
            sub["asset_count"] = 0
            sub["assets_count"] = 0
            sub["category_name"] = "Unassigned"

    return templates.TemplateResponse(
        request=request,
        name="manager/subcategories/list.html",
        context={
            "session": session,
            "manager": manager,
            "subcategories": sub_items,
            "categories": all_categories.get("items", []),
            "categoryId": effective_cat_id or "",
            "category_id": effective_cat_id or "",
            "selected_category_id": effective_cat_id or "",
            "data": subcategories_page,
            "pagination": subcategories_page,
            "search": search or "",
            "sort": current_sort,
            "order": sort_order,
            "active_tab": "subcategories",
        },
    )


@router.get("/assets")
async def manager_assets(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500, alias="page_size"),
    limit: int | None = Query(default=None, ge=1, le=500),
    pageSize: int | None = Query(default=None, ge=1, le=500),
    categoryId: str | None = None,
    category_id: str | None = None,
    subCategoryId: str | None = None,
    sub_category_id: str | None = None,
    type: str | None = None,
    q: str | None = None,
    search: str | None = None,
    sort: str = Query(default="sequence"),
    order: str = Query(default="asc"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Read-only view of central assets."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    effective_page_size = pageSize or limit or page_size or 20
    effective_page_size = max(1, min(effective_page_size, 500))

    manager = await get_manager_by_id(db, session["user_id"])

    effective_cat = categoryId or category_id
    effective_sub = subCategoryId or sub_category_id
    search_query = q or search

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

    # If subcategory provided but category missing, resolve category from subcategory
    if effective_sub and not effective_cat:
        try:
            sub_doc = await get_subcategory(db, effective_sub)
            if sub_doc and "category_id" in sub_doc:
                effective_cat = str(sub_doc["category_id"])
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

    assets_page = await list_assets(
        db,
        category_id=effective_cat,
        sub_category_id=effective_sub,
        search=search_query,
        page=page,
        page_size=effective_page_size,
        sort_by=effective_sort_by,
        sort_order=effective_sort_order,
        asset_type=selected_type,
    )

    all_categories = await list_categories(db, page=1, page_size=200)
    all_subs = await list_subcategories(db, category_id=effective_cat, page=1, page_size=500)

    category_map = {str(c["id"]): c.get("name", "") for c in all_categories.get("items", [])}
    if effective_cat:
        all_subs_for_map = await list_subcategories(db, page=1, page_size=500)
        subcategory_map = {str(s["id"]): s.get("name", "") for s in all_subs_for_map.get("items", [])}
    else:
        subcategory_map = {str(s["id"]): s.get("name", "") for s in all_subs.get("items", [])}

    items = assets_page.get("items", [])
    for item in items:
        cat_id_str = str(item.get("category_id", ""))
        sub_id_str = str(item.get("sub_category_id", ""))
        item["category_name"] = category_map.get(cat_id_str, item.get("category_name") or "")
        item["sub_category_name"] = subcategory_map.get(sub_id_str, item.get("sub_category_name") or "")

    return templates.TemplateResponse(
        request=request,
        name="manager/assets/list.html",
        context={
            "session": session,
            "manager": manager,
            "assets": items,
            "data": assets_page,
            "pagination": assets_page,
            "page_size": effective_page_size,
            "categories": all_categories.get("items", []),
            "subcategories": all_subs.get("items", []),
            "selected_cat": effective_cat or "",
            "category_id": effective_cat or "",
            "categoryId": effective_cat or "",
            "selected_sub": effective_sub or "",
            "sub_category_id": effective_sub or "",
            "subCategoryId": effective_sub or "",
            "selected_type": selected_type,
            "type": selected_type,
            "search": search_query or "",
            "q": search_query or "",
            "sort": effective_sort_by,
            "order": effective_sort_order,
            "current_sort": current_sort,
            "active_tab": "assets",
        },
    )
