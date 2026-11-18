"""Dual-layer sliding-window rate limiting middleware.

Enforces:
1. User-wise limit by client IP address (default: 60 req/min, editable by Manager/Admin).
2. App surge ceiling across all users combined (default: 10,000 req/min, editable by Manager/Admin).
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from authorization.rate_limiter import check_dual_layer_rate_limit
from utils.responses import error_response


def get_client_ip(request: Request) -> str:
    """Extract client IP address from proxy headers or direct socket connection."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()

    x_forwarded = request.headers.get("X-Forwarded-For")
    if x_forwarded and x_forwarded.strip():
        # First IP in comma-separated chain is the client IP
        return x_forwarded.split(",")[0].strip()

    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip and x_real_ip.strip():
        return x_real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        api_key = getattr(request.state, "api_key", None)
        if api_key:
            # 1. Resolve key prefix / bucket ID
            if isinstance(api_key, dict):
                prefix = api_key.get("key_prefix") or api_key.get("id") or "unknown"
                user_limit = api_key.get("rate_limit_per_min") or 60
                surge_ceiling = api_key.get("app_surge_ceiling_per_min") or 10000
            else:
                prefix = getattr(api_key, "key_prefix", None) or getattr(api_key, "id", "unknown")
                user_limit = getattr(api_key, "rate_limit_per_min", 60)
                surge_ceiling = getattr(api_key, "app_surge_ceiling_per_min", 10000)

            user_limit = max(1, int(user_limit or 60))
            surge_ceiling = max(1, int(surge_ceiling or 10000))

            # 2. Extract Client IP for Layer 1
            client_ip = get_client_ip(request)

            # 3. Check Dual Layer Rate Limiting
            is_allowed, violated_layer, retry_after = check_dual_layer_rate_limit(
                key_prefix=str(prefix),
                client_ip=client_ip,
                user_limit_per_min=user_limit,
                app_surge_ceiling_per_min=surge_ceiling,
            )

            if not is_allowed:
                if violated_layer == "user_ip_limit":
                    err_message = (
                        f"User rate limit of {user_limit} requests/min exceeded for IP {client_ip}. "
                        f"Please retry in {retry_after} seconds."
                    )
                    details = {
                        "layer": "user_ip_limit",
                        "client_ip": client_ip,
                        "limit": user_limit,
                        "retry_after": retry_after,
                    }
                else:
                    err_message = (
                        f"Application surge ceiling of {surge_ceiling} requests/min exceeded. "
                        f"Please retry in {retry_after} seconds."
                    )
                    details = {
                        "layer": "app_surge_ceiling",
                        "limit": surge_ceiling,
                        "retry_after": retry_after,
                    }

                return JSONResponse(
                    status_code=429,
                    content=error_response("RATE_LIMITED", err_message, details=details),
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit-User": str(user_limit),
                        "X-RateLimit-Limit-App": str(surge_ceiling),
                        "X-RateLimit-Violation": str(violated_layer),
                    },
                )

        return await call_next(request)
