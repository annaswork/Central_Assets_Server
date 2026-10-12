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


def extract_api_key(request: Request) -> str | None:
    """Extract raw API key from headers or query parameters.

    Supported channels:
    1. Custom Header: X-API-Key / x-api-key
    2. Query Parameter: api_key, apiKey, or key (enables Chrome address bar & <img> tag access)
    3. Authorization Header: Bearer <key> or ApiKey <key>
    """
    # 1. Custom Header: X-API-Key
    key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if key and key.strip():
        return key.strip()

    # 2. Query Parameter: api_key, apiKey, key
    query_key = (
        request.query_params.get("api_key")
        or request.query_params.get("apiKey")
        or request.query_params.get("key")
    )
    if query_key and query_key.strip():
        return query_key.strip()

    # 3. Standard Authorization Header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.strip():
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() in ("bearer", "apikey"):
            return parts[1]
        elif len(parts) == 1 and parts[0].startswith("ak_"):
            return parts[0]

    return None


def is_public_static_path(path: str) -> bool:
    """Determine whether a /static path is a public asset (default fallback icon, app icons, avatars).

    All central library assets in /static/central_data/ (thumbnails, images, videos, audios,
    animations, documents, frames, HTML widgets) require an API key or an active dashboard session.
    """
    clean_path = path.split("?")[0].rstrip("/")
    if not clean_path.startswith("/static"):
        return True

    # Root /static or fallback placeholder icon
    if clean_path in ("/static", "/static/") or clean_path.endswith("/thumbnail_default.png"):
        return True

    # User profile avatars and app instance icons are public
    if clean_path.startswith(("/static/profiles/", "/static/app_data/")):
        return True

    # Everything else under /static (including ALL /static/central_data/ assets) is strictly protected
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

            # Protected media requires API key via X-API-Key header, query param (?api_key=...), or Authorization header
            raw_key = extract_api_key(request)
            if not raw_key:
                return JSONResponse(
                    status_code=401,
                    content=error_response(
                        "MISSING_API_KEY",
                        "API key is required to access protected media files",
                    ),
                )

            try:
                db = get_database()
                key_in_db = await verify_api_key(db, raw_key)
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

        raw_key = extract_api_key(request)
        if not raw_key:
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
                content=error_response(
                    "MISSING_API_KEY",
                    "API key is required",
                ),
            )

        try:
            db = get_database()
            key_in_db = await verify_api_key(db, raw_key)
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
