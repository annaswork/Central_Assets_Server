"""Mounts API, admin, and health check routers onto the FastAPI application."""

from fastapi import FastAPI

from router.admin import admin
from router.health_router import health_router
from router.v1 import api_v1


def register_routers(app: FastAPI) -> None:
    """Mount all application routers."""
    app.include_router(health_router)
    app.include_router(api_v1)
    app.include_router(admin)
