"""Mounts static file directories for media and admin assets."""

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from config.paths import (
    STATIC_DIR,
    TEMPLATE_CSS_DIR,
    TEMPLATE_JS_DIR,
    ensure_directories_exist,
)


class MediaFiles(StaticFiles):
    """StaticFiles that serves .svg with a CSP, so script in an SVG opened directly can't run."""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        if path.lower().endswith(".svg"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; font-src data:"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def register_static_routes(app: FastAPI) -> None:
    """Mount /static for user-uploaded media and /admin-assets for templates css/js."""
    ensure_directories_exist()

    app.mount("/static", MediaFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/admin-assets/css", StaticFiles(directory=str(TEMPLATE_CSS_DIR)), name="admin_css")
    app.mount("/admin-assets/js", StaticFiles(directory=str(TEMPLATE_JS_DIR)), name="admin_js")
