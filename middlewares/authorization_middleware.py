"""Authorization middleware inspecting X-API-Key on /api/v1 routes and protected static media."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from authorization.admin_session import get_current_admin_session
from authorization.api_key import verify_api_key
from authorization.manager_session import get_current_manager_session
from config.constants import ALL_SCOPES
from database.connection import get_database
from utils.errors import UnauthorizedError
from utils.responses import error_response

PUBLIC_PATHS = {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}


def is_public_static_path(path: str) -> bool:
    """Determine whether a /static path is a public thumbnail, icon, avatar, or cover image."""
    clean_path = path.split("?")[0].rstrip("/")
    if not clean_path.startswith("/static"):
        return True

    # Root /static or default audio thumbnail
    if clean_path in ("/static", "/static/") or clean_path.endswith("/thumbnail_default.png"):
        return True

    # User profile avatars and app instance icons are public
    if clean_path.startswith(("/static/profiles/", "/static/app_data/")):
        return True

    filename = clean_path.split("/")[-1].lower()

    # Any file explicitly named or generated as a thumbnail
    if filename.startswith(("thumb_", "thumbnail_")):
        return True

    # Category and subcategory cover images in central_data
    if clean_path.startswith("/static/central_data/"):
        rel_parts = clean_path[len("/static/central_data/") :].strip("/").split("/")
        # rel_parts: ['<category>', '<filename>'] -> length 2 (category cover)
        # rel_parts: ['<category>', '<subcategory>', '<filename>'] -> length 3 (subcategory cover)
        # rel_parts: ['<category>', '<subcategory>', '<asset>', '<filename>'] -> length 4+ (asset media)
        if len(rel_parts) <= 3:
            return True

    return False


class AuthorizationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Preflight CORS requests should bypass auth middleware
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # 1. Static media protection (/static/...)
        if path.startswith("/static"):
            if is_public_static_path(path):
                return await call_next(request)

            # Allow active Admin or Manager dashboard sessions to view media
            admin_session = get_current_admin_session(request)
            if admin_session:
                return await call_next(request)

            manager_session = get_current_manager_session(request)
            if manager_session:
                return await call_next(request)

            # Protected media requires X-API-Key header
            api_key_header = request.headers.get("X-API-Key")
            if not api_key_header:
                return JSONResponse(
                    status_code=401,
                    content=error_response(
                        "MISSING_API_KEY",
                        "X-API-Key header is required to access protected media files",
                    ),
                )

            try:
                db = get_database()
                key_in_db = await verify_api_key(db, api_key_header)
                request.state.api_key = key_in_db
                return await call_next(request)
            except UnauthorizedError as err:
                return JSONResponse(
                    status_code=401,
                    content=error_response(err.code, err.message, err.details),
                )
            except Exception as exc:
                return JSONResponse(
                    status_code=401,
                    content=error_response("INVALID_API_KEY", str(exc)),
                )

        # 2. Only apply API key validation to /api/v1 routes
        if not path.startswith("/api/v1") or path in PUBLIC_PATHS:
            return await call_next(request)

        # Allow OpenAPI JSON documentation on API paths
        if path.endswith("/openapi.json"):
            return await call_next(request)

        api_key_header = request.headers.get("X-API-Key")
        if not api_key_header:
            # Allow authenticated admin web sessions to access API endpoints
            admin_session = get_current_admin_session(request)
            if admin_session:
                request.state.api_key = {
                    "id": "session_admin",
                    "key_prefix": "session_admin",
                    "name": admin_session.get("username", "admin"),
                    "app_instance_id": None,
                    "scopes": list(ALL_SCOPES),
                    "rate_limit_per_min": 10000,
                    "app_surge_ceiling_per_min": 50000,
                }
                return await call_next(request)

            return JSONResponse(
                status_code=401,
                content=error_response("MISSING_API_KEY", "X-API-Key header is required"),
            )

        try:
            db = get_database()
            key_in_db = await verify_api_key(db, api_key_header)
            request.state.api_key = key_in_db
        except UnauthorizedError as err:
            return JSONResponse(
                status_code=401,
                content=error_response(err.code, err.message, err.details),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=401,
                content=error_response("INVALID_API_KEY", str(exc)),
            )

        return await call_next(request)
