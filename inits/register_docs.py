"""Configures OpenAPI schema metadata, security schemes, and secured documentation routes."""

import secrets
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config.settings import settings

security = HTTPBasic()


def authenticate_docs(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Verify HTTP Basic Auth credentials for documentation access."""
    correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"), settings.DOCS_USERNAME.encode("utf8")
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"), settings.DOCS_PASSWORD.encode("utf8")
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def register_docs(app: FastAPI) -> None:
    """Customize OpenAPI documentation schema and register HTTP Basic Auth-secured docs routes."""

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title="Creative Asset Library & App Instance Management Platform API",
            version="1.0.0",
            description=(
                "Central asset library API with three-level hierarchy (Category → Subcategory → Asset), "
                "and App Instance reference management with sparse overrides, sequence ordering, "
                "monetization gating, and non-blocking usage analytics."
            ),
            routes=app.routes,
        )

        # Declare X-API-Key in OpenAPI security schemes
        openapi_schema["components"]["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "API Key formatted as: ak_<env>_<22char_id>_<32char_secret>",
            }
        }
        openapi_schema["security"] = [{"ApiKeyAuth": []}]

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    # Secured OpenAPI specification and documentation UI routes
    @app.get("/openapi.json", include_in_schema=False)
    async def get_open_api_endpoint(_: str = Depends(authenticate_docs)):
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    async def get_swagger_documentation(_: str = Depends(authenticate_docs)):
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"{app.title} - Swagger UI",
        )

    @app.get("/redoc", include_in_schema=False)
    async def get_redoc_documentation(_: str = Depends(authenticate_docs)):
        return get_redoc_html(
            openapi_url="/openapi.json",
            title=f"{app.title} - ReDoc",
        )
