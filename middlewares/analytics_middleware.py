"""Analytics middleware measuring handler timing and enqueueing events for monitored route templates."""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from analytics.allowed_paths import is_monitored
from analytics.event_builder import build_analytics_event
from analytics.recorder import enqueue_analytics_event


class AnalyticsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.perf_counter()
        response: Response | None = None
        error_code: str | None = None
        error_reason: str | None = None

        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            error_code = type(exc).__name__
            error_reason = str(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # Resolve route template from FastAPI scope if matched
            route = request.scope.get("route")
            path_template = route.path if route and hasattr(route, "path") else request.url.path

            status_code = response.status_code if response else 500
            is_error = status_code >= 400 or error_code is not None

            # Only track API paths — skip admin panel, static files, favicon, etc.
            is_api_path = path_template.startswith("/api/")

            should_record = False
            if is_api_path:
                if is_error:
                    # Record all API errors regardless of allowlist
                    should_record = True
                else:
                    rule = await is_monitored(request.method, path_template)
                    if rule:
                        should_record = True

            if should_record:
                event = build_analytics_event(
                    request=request,
                    response=response,
                    path_template=path_template,
                    duration_ms=duration_ms,
                    error_code=error_code,
                    error_reason=error_reason,
                )
                enqueue_analytics_event(event)
