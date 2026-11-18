"""v1 API router aggregation under prefix /api/v1."""

from fastapi import APIRouter

from router.v1.analytics_router import router as analytics_router
from router.v1.app_instance_router import router as app_instance_router
from router.v1.asset_router import router as asset_router
from router.v1.catalog_router import router as catalog_router
from router.v1.category_router import router as category_router
from router.v1.instance_content_router import router as instance_content_router
from router.v1.key_router import router as key_router
from router.v1.media_router import router as media_router
from router.v1.reference_router import router as reference_router
from router.v1.reorder_router import router as reorder_router
from router.v1.search_router import router as search_router
from router.v1.subcategory_router import router as subcategory_router

api_v1 = APIRouter(prefix="/api/v1")

api_v1.include_router(category_router)
api_v1.include_router(subcategory_router)
api_v1.include_router(asset_router)
api_v1.include_router(media_router)
api_v1.include_router(app_instance_router)
api_v1.include_router(reference_router)
api_v1.include_router(instance_content_router)
api_v1.include_router(catalog_router)
api_v1.include_router(analytics_router)
api_v1.include_router(key_router)
api_v1.include_router(search_router)
api_v1.include_router(reorder_router)

__all__ = ["api_v1"]
