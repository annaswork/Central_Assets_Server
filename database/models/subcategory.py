"""Subcategory schemas for create, update, API response, and database storage."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from database.models.common import (
    MongoInDBModel,
    MongoModel,
    SoftDeleteMixin,
    TimestampMixin,
)
from utils.ids import PyObjectId


class SubcategoryCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=120)
    category_id: str = Field(..., alias="categoryId", description="Parent category ObjectId")
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")
    image_url: str | None = Field(default=None, alias="imageUrl")
    is_enabled: bool = Field(default=True, alias="isEnabled")
    is_premium: bool = Field(default=False, alias="isPremium")
    sequence: int | None = Field(
        default=None, description="Display sequence order within parent category"
    )


class SubcategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool | None = None
    is_premium: bool | None = None
    sequence: int | None = None


class SubcategoryOut(MongoModel):
    id: str
    name: str
    category_id: str = Field(..., serialization_alias="categoryId")
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    sequence: int = 1
    created_at: datetime
    updated_at: datetime


class SubcategoryInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    name: str
    category_id: PyObjectId
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    sequence: int = 1
