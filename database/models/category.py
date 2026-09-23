"""Category schemas for create, update, API response, and database storage."""

from datetime import datetime

from pydantic import BaseModel, Field

from database.models.common import (
    MongoInDBModel,
    MongoModel,
    SoftDeleteMixin,
    TimestampMixin,
)


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Unique category name")
    thumbnail_url: str | None = Field(default=None, description="Small grid image URL")
    image_url: str | None = Field(default=None, description="Banner or hero image URL")
    is_enabled: bool = Field(default=True, description="Whether category is enabled")
    is_premium: bool = Field(default=False, description="Whether category is premium")
    sequence: int | None = Field(
        default=None, description="Display sequence order; lower numbers appear first"
    )


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool | None = None
    is_premium: bool | None = None
    sequence: int | None = None


class CategoryOut(MongoModel):
    id: str
    name: str
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    sequence: int = 1
    created_at: datetime
    updated_at: datetime


class CategoryInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    name: str
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    sequence: int = 1
