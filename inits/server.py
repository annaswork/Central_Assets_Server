"""FastAPI application factory and wiring assembler."""

from fastapi import FastAPI

from inits.lifespan import lifespan
from inits.register_docs import register_docs
from inits.register_handlers import register_exception_handlers
from inits.register_middlewares import register_middlewares
from inits.register_routers import register_routers
from inits.register_static import register_static_routes


def create_app() -> FastAPI:
    """Build, configure, and wire the FastAPI application."""
    app = FastAPI(
        title="Creative Asset Library Platform",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    # 1. OpenAPI documentation customization
    register_docs(app)

    # 2. Global domain exception handlers
    register_exception_handlers(app)

    # 3. Static and template asset routes (/static, /admin-assets)
    register_static_routes(app)

    # 4. API and Admin routers (/health, /api/v1, /admin)
    register_routers(app)

    # 5. Middlewares in canonical fixed order
    register_middlewares(app)

    return app
