"""Authorization middleware inspecting X-API-Key on /api/v1 routes."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from authorization.admin_session import get_current_admin_session
from authorization.api_key import verify_api_key
from config.constants import ALL_SCOPES
from database.connection import get_database
from utils.errors import UnauthorizedError
from utils.responses import error_response

PUBLIC_PATHS = {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}


class AuthorizationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Only apply API key validation to /api/v1 routes
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
                    "name": admin_session.get("username", "admin"),
                    "app_instance_id": None,
                    "scopes": list(ALL_SCOPES),
                    "rate_limit_per_min": 10000,
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
