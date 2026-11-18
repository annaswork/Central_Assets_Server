"""Global exception catching and JSON error response envelope formatter."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from utils.errors import AppError
from utils.responses import error_response

logger = logging.getLogger(__name__)


class ErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except AppError as app_err:
            logger.warning(
                f"Application domain error: {app_err.code} - {app_err.message} (path: {request.url.path})"
            )
            return JSONResponse(
                status_code=app_err.status_code,
                content=error_response(app_err.code, app_err.message, app_err.details),
            )
        except Exception as exc:
            logger.error(f"Unhandled server error on {request.url.path}: {exc}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content=error_response(
                    "INTERNAL_SERVER_ERROR",
                    "An unexpected error occurred. Please try again later.",
                ),
            )
