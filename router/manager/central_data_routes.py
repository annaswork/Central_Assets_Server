"""Manager portal central library read-only browsing routes."""

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.asset_controller import get_asset, list_assets
from controller.category_controller import list_categories
from controller.manager_controller import get_manager_by_id
from controller.subcategory_controller import list_subcategories
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
    search: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Read-only view of central categories."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    manager = await get_manager_by_id(db, session["user_id"])
    categories_page = await list_categories(
        db, page=page, page_size=20, search=search
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
            "pagination": categories_page.get("pagination", {}),
            "search": search or "",
            "active_tab": "categories",
        },
    )


@router.get("/subcategories")
async def manager_subcategories(
    request: Request,
    page: int = Query(default=1, ge=1),
    category_id: str | None = None,
    search: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Read-only view of central subcategories."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    manager = await get_manager_by_id(db, session["user_id"])
    subcategories_page = await list_subcategories(
        db, category_id=category_id, page=page, page_size=20, search=search
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
            "category_id": category_id or "",
            "pagination": subcategories_page.get("pagination", {}),
            "search": search or "",
            "active_tab": "subcategories",
        },
    )


@router.get("/assets")
async def manager_assets(
    request: Request,
    page: int = Query(default=1, ge=1),
    category_id: str | None = None,
    sub_category_id: str | None = None,
    search: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Read-only view of central assets."""
    session = get_current_manager_session(request)
    if not session:
        return RedirectResponse(url="/manager/login", status_code=303)

    manager = await get_manager_by_id(db, session["user_id"])
    assets_page = await list_assets(
        db,
        page=page,
        page_size=24,
        category_id=category_id,
        sub_category_id=sub_category_id,
        search=search,
    )
    all_categories = await list_categories(db, page=1, page_size=500)

    subcategories = []
    if category_id:
        subs_page = await list_subcategories(db, page=1, page_size=500, category_id=category_id)
        subcategories = subs_page.get("items", [])

    return templates.TemplateResponse(
        request=request,
        name="manager/assets/list.html",
        context={
            "session": session,
            "manager": manager,
            "assets": assets_page.get("items", []),
            "categories": all_categories.get("items", []),
            "subcategories": subcategories,
            "category_id": category_id or "",
            "sub_category_id": sub_category_id or "",
            "pagination": assets_page.get("pagination", {}),
            "search": search or "",
            "active_tab": "assets",
        },
    )
