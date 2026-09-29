"""Manager portal router aggregation under prefix /manager."""

from fastapi import APIRouter

from router.manager.analytics_routes import router as manager_analytics_router
from router.manager.auth_routes import api_router as manager_api_router
from router.manager.auth_routes import router as manager_auth_router
from router.manager.central_data_routes import router as manager_central_data_router
from router.manager.dashboard_routes import router as manager_dashboard_router
from router.manager.instance_routes import router as manager_instance_router
from router.manager.key_routes import router as manager_key_router
from router.manager.message_routes import router as manager_message_router
from router.manager.profile_routes import router as manager_profile_router
from router.manager.settings_routes import router as manager_settings_router

manager = APIRouter(prefix="/manager")

manager.include_router(manager_auth_router)
manager.include_router(manager_dashboard_router)
manager.include_router(manager_central_data_router)
manager.include_router(manager_instance_router)
manager.include_router(manager_key_router)
manager.include_router(manager_message_router)
manager.include_router(manager_profile_router)
manager.include_router(manager_settings_router)
manager.include_router(manager_analytics_router)


@manager.get("", include_in_schema=False)
async def manager_root_redirect():
    """Redirect /manager directly to /manager/dashboard."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/manager/dashboard", status_code=303)


@manager.get("/propose", include_in_schema=False)
@manager.get("/proposals", include_in_schema=False)
async def manager_proposals_shortcut_redirect():
    """Redirect /manager/propose and /manager/proposals to /manager/messages?propose=1."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/manager/messages?propose=1", status_code=303)


__all__ = ["manager", "manager_api_router"]
