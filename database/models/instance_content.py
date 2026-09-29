"""Schemas for per-instance reference rows, overrides, and catalog resolution."""

from typing import Any

from pydantic import BaseModel, Field

from database.models.common import (
    MongoInDBModel,
    MongoModel,
    SoftDeleteMixin,
    TimestampMixin,
)
from utils.ids import PyObjectId


class ReferenceAddPayload(BaseModel):
    category_ids: list[str] = Field(default_factory=list)
    sub_category_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)


class ReferenceCopyPayload(BaseModel):
    source_instance_id: str
    include_overrides: bool = True


class InstanceContentUpdate(BaseModel):
    is_enabled: bool | None = None
    sequence: int | None = None
    is_premium: bool | None = None
    name: str | None = None
    description: str | None = None
    overrides: dict[str, Any] | None = None


AssetOverrideUpdate = InstanceContentUpdate


class BulkFlagsPayload(BaseModel):
    ids: list[str]
    is_enabled: bool | None = None
    is_premium: bool | None = None


class ReorderPayload(BaseModel):
    type: str = Field(..., description="'category', 'subcategory', or 'asset'")
    ordered_ids: list[str]


class ResetOverridesPayload(BaseModel):
    fields: list[str] | None = None  # None or empty means reset all


# MongoDB InDB representations for reference rows
class InstanceCategoryInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    app_instance_id: PyObjectId
    source_id: PyObjectId | None = None
    name: str | None = None
    thumbnail_url: str | None = None
    is_enabled: bool = True
    sequence: int = 1
    overrides: dict[str, Any] = Field(default_factory=dict)


class InstanceSubcategoryInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    app_instance_id: PyObjectId
    source_id: PyObjectId | None = None
    category_id: PyObjectId
    name: str | None = None
    thumbnail_url: str | None = None
    is_enabled: bool = True
    sequence: int = 1
    overrides: dict[str, Any] = Field(default_factory=dict)


class InstanceAssetInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    app_instance_id: PyObjectId
    source_id: PyObjectId
    category_id: PyObjectId
    sub_category_id: PyObjectId
    is_enabled: bool = True
    sequence: int = 1
    is_premium: bool = False
    is_rewarded: bool = False
    rewarded_credits: int = 5
    views: int = 0
    downloads: int = 0
    tags: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)


# API response representations (Resolved with central data)
class ResolvedCategoryOut(MongoModel):
    id: str
    source_id: str = Field(..., serialization_alias="sourceId")
    name: str
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    sequence: int
    overrides: dict[str, Any] = Field(default_factory=dict)


class ResolvedSubcategoryOut(MongoModel):
    id: str
    source_id: str = Field(..., serialization_alias="sourceId")
    category_id: str = Field(..., serialization_alias="categoryId")
    name: str
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    sequence: int
    overrides: dict[str, Any] = Field(default_factory=dict)


class ResolvedAssetOut(MongoModel):
    id: str
    source_id: str = Field(..., serialization_alias="sourceId")
    category_id: str = Field(..., serialization_alias="categoryId")
    sub_category_id: str = Field(..., serialization_alias="subCategoryId")
    name: str
    description: str = ""
    thumbnail_url: str | None = None
    more_fields: dict[str, Any] = Field(default_factory=dict, serialization_alias="moreFields")
    is_enabled: bool = True
    is_premium: bool = False
    is_rewarded: bool = Field(default=False, serialization_alias="isRewarded")
    rewarded_credits: int = Field(default=5, serialization_alias="rewardedCredits")
    sequence: int
    views: int = 0
    downloads: int = 0
    tags: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)
