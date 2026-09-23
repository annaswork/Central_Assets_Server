"""Mounts static file directories for media and admin assets."""

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from config.paths import (
    STATIC_DIR,
    TEMPLATE_CSS_DIR,
    TEMPLATE_JS_DIR,
    ensure_directories_exist,
)


def register_static_routes(app: FastAPI) -> None:
    """Mount /static for user-uploaded media and /admin-assets for templates css/js."""
    ensure_directories_exist()

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/admin-assets/css", StaticFiles(directory=str(TEMPLATE_CSS_DIR)), name="admin_css")
    app.mount("/admin-assets/js", StaticFiles(directory=str(TEMPLATE_JS_DIR)), name="admin_js")
