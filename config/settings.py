"""Typed application settings loaded via pydantic-settings."""

import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    ENV: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "INFO"

    # Database
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "admin_assets_db"

    # Security
    SECRET_KEY: str = "change_this_to_a_secure_random_string_in_production_min_32_chars"
    ADMIN_SESSION_SECRET: str = "change_this_admin_session_secret_in_production_min_32_chars"
    ADMIN_SESSION_COOKIE_NAME: str = "admin_session"
    ADMIN_SESSION_MAX_AGE_SECONDS: int = 86400

    # CORS
    CORS_ORIGINS: list[str] = ["*"]

    # Analytics queue & batching
    ANALYTICS_QUEUE_MAX_SIZE: int = 10000
    ANALYTICS_BATCH_SIZE: int = 100
    ANALYTICS_FLUSH_INTERVAL_SECONDS: float = 2.0
    ANALYTICS_DEFAULT_RETENTION_DAYS: int = 30

    # Seed Admin Operator Credentials (strictly loaded from .env / environment)
    BOOTSTRAP_ADMIN_USERNAME: str
    BOOTSTRAP_ADMIN_PASSWORD: str

    # API Documentation Auth (HTTP Basic Auth for /docs, /redoc, /openapi.json - strictly loaded from .env)
    DOCS_USERNAME: str
    DOCS_PASSWORD: str

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                try:
                    return json.loads(v_stripped)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, set)):
            return list(v)
        return ["*"]

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    @property
    def mongodb_uri(self) -> str:
        return self.MONGODB_URI

    @property
    def mongodb_db_name(self) -> str:
        return self.MONGODB_DB_NAME

    @property
    def app_name(self) -> str:
        return "Creative Asset Library Platform"

    @property
    def app_env(self) -> str:
        return self.ENV

    @property
    def debug(self) -> bool:
        return not self.is_production

    @property
    def media_upload_dir(self) -> str:
        from config.paths import MEDIA_UPLOAD_DIR

        return str(MEDIA_UPLOAD_DIR)

    @property
    def media_max_bytes(self) -> int:
        return 150 * 1024 * 1024


settings: Settings = Settings()
