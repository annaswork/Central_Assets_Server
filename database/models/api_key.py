"""API key models for issuance, validation, scoping, and revocation."""

from datetime import datetime

from pydantic import BaseModel, Field

from database.models.common import MongoInDBModel, MongoModel, TimestampMixin
from utils.ids import PyObjectId


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    app_instance_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    rate_limit_per_min: int = Field(default=60, ge=1, le=10000)
    expires_at: datetime | None = None


class ApiKeyOut(MongoModel):
    id: str
    name: str
    key_prefix: str
    app_instance_id: str | None = None
    scopes: list[str]
    rate_limit_per_min: int
    is_active: bool
    is_revoked: bool = False
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    revoked_at: datetime | None = None
    # Returned only at creation
    full_key: str | None = None


class ApiKeyInDB(MongoInDBModel, TimestampMixin):
    name: str
    key_prefix: str
    secret_hash: str
    app_instance_id: PyObjectId | None = None
    scopes: list[str] = Field(default_factory=list)
    rate_limit_per_min: int = 60
    is_active: bool = True
    is_revoked: bool = False
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
