"""Constructs structured analytics event documents from HTTP request/response metrics."""

from typing import Any

from fastapi import Request, Response

from utils.datetimes import utc_now


def build_analytics_event(
    request: Request,
    response: Response | None,
    path_template: str,
    duration_ms: float,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Assemble a complete event document to be persisted."""
    api_key_obj = getattr(request.state, "api_key", None)
    api_key_id = str(api_key_obj.id) if (api_key_obj and hasattr(api_key_obj, "id")) else None
    app_instance_id = (
        str(api_key_obj.app_instance_id)
        if (api_key_obj and hasattr(api_key_obj, "app_instance_id") and api_key_obj.app_instance_id)
        else None
    )

    # Check path params if app_instance_id is in the URL
    if not app_instance_id and "instance_id" in request.path_params:
        app_instance_id = str(request.path_params["instance_id"])
    elif not app_instance_id and "id" in request.path_params and ("/instance/" in path_template or "/app-instances/" in path_template):
        app_instance_id = str(request.path_params["id"])

    # Extract asset_id and tracking event_type if present
    asset_id = (
        str(request.path_params["assetId"])
        if "assetId" in request.path_params
        else (str(request.path_params["asset_id"]) if "asset_id" in request.path_params else None)
    )
    event_type = getattr(request.state, "tracking_event_type", None)

    # Client hints
    country = request.headers.get("cf-ipcountry") or request.headers.get("x-country")
    platform = request.headers.get("x-platform")
    app_version = request.headers.get("x-app-version")

    # Byte counts
    content_length_req = request.headers.get("content-length")
    request_bytes = (
        int(content_length_req) if content_length_req and content_length_req.isdigit() else 0
    )

    response_bytes = 0
    status_code = 500
    if response:
        status_code = response.status_code
        content_length_res = response.headers.get("content-length")
        if content_length_res and content_length_res.isdigit():
            response_bytes = int(content_length_res)

    return {
        "path_template": path_template,
        "method": request.method.upper(),
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2),
        "api_key_id": api_key_id,
        "app_instance_id": app_instance_id,
        "asset_id": asset_id,
        "event_type": event_type,
        "country": country,
        "platform": platform,
        "app_version": app_version,
        "request_bytes": request_bytes,
        "response_bytes": response_bytes,
        "error_code": error_code,
        "ts": utc_now(),
    }
