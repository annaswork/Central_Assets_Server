"""Health check and readiness verification endpoints."""

from fastapi import APIRouter, Response

from database.connection import ping_database

health_router = APIRouter(tags=["Health"])


@health_router.get("/health", summary="Liveness Probe")
async def health_check() -> dict[str, str]:
    """Liveness probe returning 200 OK if service is up."""
    return {"status": "ok"}


@health_router.get("/ready", summary="Readiness Probe")
async def readiness_check(response: Response) -> dict[str, str]:
    """Readiness probe checking database connectivity."""
    is_db_ready = await ping_database()
    if not is_db_ready:
        response.status_code = 503
        return {"status": "unhealthy", "database": "disconnected"}
    return {"status": "ready", "database": "connected"}
