"""Registers request middlewares in strict canonical order."""

from fastapi import FastAPI

from middlewares.analytics_middleware import AnalyticsMiddleware
from middlewares.authorization_middleware import AuthorizationMiddleware
from middlewares.cors_middleware import setup_cors_middleware
from middlewares.error_middleware import ErrorMiddleware
from middlewares.rate_limit_middleware import RateLimitMiddleware
from middlewares.request_id_middleware import RequestIdMiddleware


def register_middlewares(app: FastAPI) -> None:
    """Add application middlewares in the fixed canonical execution order.

    Execution order (request entry -> handler):
    1. RequestIdMiddleware (outermost: logs and propagates X-Request-ID)
    2. CORSMiddleware (handles cross-origin OPTIONS and headers)
    3. AnalyticsMiddleware (measures total latency and records all telemetry & 4xx/5xx errors)
    4. RateLimitMiddleware (enforces per-key sliding window)
    5. AuthorizationMiddleware (reads X-API-Key and attaches state.api_key)
    6. ErrorMiddleware (innermost: catches and shapes all exceptions into standard envelopes)
    """
    # In Starlette, app.add_middleware() pushes to front (onion layer),
    # so we add from innermost to outermost.
    app.add_middleware(ErrorMiddleware)
    app.add_middleware(AuthorizationMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AnalyticsMiddleware)
    setup_cors_middleware(app)
    app.add_middleware(RequestIdMiddleware)
