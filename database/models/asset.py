"""Asset schemas for create, update, API response, and database storage."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from database.models.common import (
    MongoInDBModel,
    MongoModel,
    SoftDeleteMixin,
    TimestampMixin,
)
from database.models.more_fields import TypedBlock
from utils.ids import PyObjectId


class AssetCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    category_id: str = Field(..., alias="categoryId", description="Parent category ObjectId")
    sub_category_id: str = Field(
        ..., alias="subCategoryId", description="Parent subcategory ObjectId"
    )
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")
    is_enabled: bool = Field(default=True, alias="isEnabled")
    is_premium: bool = Field(default=False, alias="isPremium")
    sequence: int | None = Field(
        default=None, description="Display sequence order within parent subcategory"
    )
    more_fields: dict[str, TypedBlock | list[dict[str, Any]] | list[Any] | dict[str, Any] | Any] = (
        Field(default_factory=dict, alias="moreFields")
    )


class AssetUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category_id: str | None = Field(default=None, alias="categoryId")
    sub_category_id: str | None = Field(default=None, alias="subCategoryId")
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")
    is_enabled: bool | None = Field(default=None, alias="isEnabled")
    is_premium: bool | None = Field(default=None, alias="isPremium")
    sequence: int | None = None
    more_fields: (
        dict[str, TypedBlock | list[dict[str, Any]] | list[Any] | dict[str, Any] | Any] | None
    ) = Field(default=None, alias="moreFields")


class AssetOut(MongoModel):
    id: str
    name: str
    description: str
    category_id: str = Field(..., serialization_alias="categoryId")
    sub_category_id: str = Field(..., serialization_alias="subCategoryId")
    folder_name: str | None = None
    thumbnail_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    sequence: int = 1
    views: int = 0
    downloads: int = 0
    more_fields: dict[str, Any] = Field(default_factory=dict, serialization_alias="moreFields")
    created_at: datetime
    updated_at: datetime


class AssetInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    name: str
    description: str = ""
    category_id: PyObjectId
    sub_category_id: PyObjectId
    folder_name: str | None = None
    thumbnail_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    sequence: int = 1
    views: int = 0
    downloads: int = 0
    more_fields: dict[str, Any] = Field(default_factory=dict)
