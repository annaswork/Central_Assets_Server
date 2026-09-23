"""Sliding-window rate limiting middleware for authenticated keys."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from authorization.rate_limiter import check_rate_limit
from utils.responses import error_response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        api_key = getattr(request.state, "api_key", None)
        if api_key:
            limit = getattr(api_key, "rate_limit_per_min", 60)
            prefix = getattr(api_key, "key_prefix", "unknown")
            is_allowed, retry_after = check_rate_limit(prefix, limit)
            if not is_allowed:
                return JSONResponse(
                    status_code=429,
                    content=error_response(
                        "RATE_LIMITED",
                        f"Rate limit of {limit} requests/min exceeded",
                        details={"retry_after": retry_after},
                    ),
                    headers={"Retry-After": str(retry_after)},
                )

        return await call_next(request)
