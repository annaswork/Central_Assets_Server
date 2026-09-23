"""Subcategory API endpoints for the central creative library."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.subcategory_controller import (
    bulk_create_subcategories,
    create_subcategory,
    delete_subcategory,
    get_subcategory,
    list_subcategories,
    update_subcategory,
)
from database.models.subcategory import SubcategoryCreate, SubcategoryUpdate
from router.deps import get_db, get_pagination
from utils.pagination import PageParams

router = APIRouter(prefix="/subcategories", tags=["Central Subcategories"])


@router.get("", dependencies=[Depends(require_scope("categories:read"))])
async def list_subcategories_endpoint(
    categoryId: str | None = Query(default=None, description="Filter by parent category ID"),
    search: str | None = Query(default=None, description="Search term for subcategory name"),
    sort: str = Query(default="sequence", description="Sort by field: sequence, created_at, name"),
    order: str = Query(default="asc", description="Sort order: asc or desc"),
    pagination: PageParams = Depends(get_pagination),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await list_subcategories(
        db,
        category_id=categoryId,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        sort_by=sort,
        sort_order=order,
    )


@router.post("", status_code=201, dependencies=[Depends(require_scope("categories:write"))])
async def create_subcategory_endpoint(
    payload: SubcategoryCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await create_subcategory(db, payload)


@router.post("/bulk", status_code=207, dependencies=[Depends(require_scope("categories:write"))])
async def bulk_create_subcategories_endpoint(
    payload: list[SubcategoryCreate],
    atomic: bool = Query(default=False, description="Fail entire batch on any error if true"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await bulk_create_subcategories(db, items=payload, atomic=atomic)


@router.get("/{id}", dependencies=[Depends(require_scope("categories:read"))])
async def get_subcategory_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await get_subcategory(db, subcategory_id=id)


@router.patch("/{id}", dependencies=[Depends(require_scope("categories:write"))])
async def update_subcategory_endpoint(
    id: str,
    payload: SubcategoryUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await update_subcategory(db, subcategory_id=id, data=payload)


@router.delete("/{id}", dependencies=[Depends(require_scope("categories:write"))])
async def delete_subcategory_endpoint(
    id: str,
    cascade: bool = Query(default=False, description="Cascade delete child assets"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await delete_subcategory(db, subcategory_id=id, cascade=cascade)
