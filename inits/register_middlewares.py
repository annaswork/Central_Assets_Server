"""Registers request middlewares in strict canonical order."""

from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

from middlewares.analytics_middleware import AnalyticsMiddleware
from middlewares.authorization_middleware import AuthorizationMiddleware
from middlewares.cors_middleware import setup_cors_middleware
from middlewares.error_middleware import ErrorMiddleware
from middlewares.notifications_middleware import NotificationsMiddleware
from middlewares.rate_limit_middleware import RateLimitMiddleware
from middlewares.request_id_middleware import RequestIdMiddleware


def register_middlewares(app: FastAPI) -> None:
    """Add application middlewares in the fixed canonical execution order."""
    app.add_middleware(ErrorMiddleware)
    app.add_middleware(NotificationsMiddleware)
    app.add_middleware(AuthorizationMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AnalyticsMiddleware)
    setup_cors_middleware(app)
    app.add_middleware(RequestIdMiddleware)
    # Outermost: compresses the final HTML/JSON/JS (~7x on the instance page); images, video and 206s are skipped
    app.add_middleware(GZipMiddleware, minimum_size=1024)
