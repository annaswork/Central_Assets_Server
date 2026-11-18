"""CORS middleware helper for cross-origin client apps."""

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from config.settings import settings


def setup_cors_middleware(app: FastAPI) -> None:
    """Register CORSMiddleware onto the FastAPI instance."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
