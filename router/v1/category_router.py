"""Category API endpoints for the central creative library."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.category_controller import (
    bulk_create_categories,
    create_category,
    delete_category,
    get_category,
    list_categories,
    update_category,
)
from database.models.category import CategoryCreate, CategoryUpdate
from router.deps import get_db, get_pagination
from utils.pagination import PageParams

router = APIRouter(prefix="/categories", tags=["Central Categories"])


@router.get("", dependencies=[Depends(require_scope("categories:read"))])
async def list_categories_endpoint(
    search: str | None = Query(default=None, description="Search term for category name"),
    sort: str = Query(default="sequence", description="Sort by field: sequence, created_at, name"),
    order: str = Query(default="asc", description="Sort order: asc or desc"),
    pagination: PageParams = Depends(get_pagination),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await list_categories(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        sort_by=sort,
        sort_order=order,
    )


@router.post("", status_code=201, dependencies=[Depends(require_scope("categories:write"))])
async def create_category_endpoint(
    payload: CategoryCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await create_category(db, payload)


@router.post("/bulk", status_code=207, dependencies=[Depends(require_scope("categories:write"))])
async def bulk_create_categories_endpoint(
    payload: list[CategoryCreate],
    atomic: bool = Query(default=False, description="Fail entire batch on any error if true"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await bulk_create_categories(db, items=payload, atomic=atomic)


@router.get("/{id}", dependencies=[Depends(require_scope("categories:read"))])
async def get_category_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await get_category(db, category_id=id)


@router.patch("/{id}", dependencies=[Depends(require_scope("categories:write"))])
async def update_category_endpoint(
    id: str,
    payload: CategoryUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await update_category(db, category_id=id, data=payload)


@router.delete("/{id}", dependencies=[Depends(require_scope("categories:write"))])
async def delete_category_endpoint(
    id: str,
    cascade: bool = Query(
        default=False, description="Cascade delete child subcategories and assets"
    ),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await delete_category(db, category_id=id, cascade=cascade)
