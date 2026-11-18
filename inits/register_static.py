"""Mounts static file directories for media and admin assets."""

import re

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from config.paths import (
    STATIC_DIR,
    TEMPLATE_CSS_DIR,
    TEMPLATE_JS_DIR,
    ensure_directories_exist,
)


# Uploads stored as "<sha256[:16]>_<name>" never change at that URL; others (e.g. thumb_*.webp) are overwritten in place
_CONTENT_ADDRESSED = re.compile(r"(^|/)[0-9a-f]{16}_[^/]+$")


class MediaFiles(StaticFiles):
    """Media with a cache policy (immutable for content-addressed files, else revalidate) and a CSP on .svg."""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = (
            "private, max-age=31536000, immutable" if _CONTENT_ADDRESSED.search(path) else "private, no-cache"
        )
        if path.lower().endswith(".svg"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; font-src data:"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


class RevalidatedFiles(StaticFiles):
    """Admin css/js: browsers keep their copy but revalidate it (cheap 304), so edits show up on next load."""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def register_static_routes(app: FastAPI) -> None:
    """Mount /static for user-uploaded media and /admin-assets for templates css/js."""
    ensure_directories_exist()

    app.mount("/static", MediaFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/admin-assets/css", RevalidatedFiles(directory=str(TEMPLATE_CSS_DIR)), name="admin_css")
    app.mount("/admin-assets/js", RevalidatedFiles(directory=str(TEMPLATE_JS_DIR)), name="admin_js")
