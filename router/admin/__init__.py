"""Admin panel router aggregation under prefix /admin."""

from fastapi import APIRouter

from router.admin.access_request_routes import router as admin_access_requests_router
from router.admin.admin_message_routes import router as admin_messages_router
from router.admin.analytics_routes import router as admin_analytics_router
from router.admin.asset_routes import router as admin_asset_router
from router.admin.auth_routes import router as admin_auth_router
from router.admin.category_routes import router as admin_category_router
from router.admin.dashboard_routes import router as admin_dashboard_router
from router.admin.instance_routes import router as admin_instance_router
from router.admin.manager_admin_routes import router as admin_managers_router
from router.admin.settings_routes import router as admin_settings_router
from router.admin.subcategory_routes import router as admin_subcategory_router

admin = APIRouter(prefix="/admin")

admin.include_router(admin_auth_router)
admin.include_router(admin_dashboard_router)
admin.include_router(admin_category_router)
admin.include_router(admin_subcategory_router)
admin.include_router(admin_asset_router)
admin.include_router(admin_instance_router)
admin.include_router(admin_analytics_router)
admin.include_router(admin_settings_router)
admin.include_router(admin_managers_router)
admin.include_router(admin_messages_router)
admin.include_router(admin_access_requests_router)

__all__ = ["admin"]
