"""Schemas for per-instance reference rows, overrides, and catalog resolution."""

from typing import Any, Literal

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
    type: str = Field(..., description="'super_category', 'category', 'subcategory', or 'asset'")
    ordered_ids: list[str]


class ResetOverridesPayload(BaseModel):
    fields: list[str] | None = None  # None or empty means reset all


class DistributeTiersPayload(BaseModel):
    scope_type: str = Field(..., description="'category' or 'subcategory'")
    scope_id: str = Field(..., description="ID of the parent category or subcategory")
    target_type: str = Field(..., description="'subcategory' or 'asset'")
    premium_count: int = Field(default=0, ge=0, description="Total items to mark premium")
    rewarded_count: int = Field(default=0, ge=0, description="Total items to mark rewarded")
    normal_frequency: int = Field(default=1, ge=1, description="Consecutive normal items per cycle")
    premium_frequency: int = Field(default=1, ge=1, description="Consecutive premium items per cycle")
    rewarded_frequency: int = Field(default=1, ge=1, description="Consecutive rewarded items per cycle")
    alternate_paid: bool = Field(
        default=False,
        description="Alternate premium and rewarded paid batches across separate free batches",
    )


class BulkDistributeSubcategoryAssetsPayload(BaseModel):
    subcategory_ids: list[str] = Field(default_factory=list, description="Explicit instance subcategory IDs to target")
    parent_category_id: str | None = Field(default=None, description="Target all subcategories inside this category")
    apply_to_all: bool = Field(default=False, description="If true, target all non-deleted subcategories in the instance")
    count_mode: Literal["fixed", "percentage"] = Field(default="fixed", description="'fixed' counts or 'percentage' per subcategory")
    premium_count: int = Field(default=0, ge=0, description="Target premium items per subcategory (fixed mode)")
    rewarded_count: int = Field(default=0, ge=0, description="Target rewarded items per subcategory (fixed mode)")
    premium_percent: float = Field(default=0, ge=0, le=99, description="Target premium % per subcategory (percentage mode)")
    rewarded_percent: float = Field(default=0, ge=0, le=99, description="Target rewarded % per subcategory (percentage mode)")
    normal_frequency: int = Field(default=1, ge=1, description="Consecutive normal items per cycle")
    premium_frequency: int = Field(default=1, ge=1, description="Consecutive premium items per cycle")
    rewarded_frequency: int = Field(default=1, ge=1, description="Consecutive rewarded items per cycle")
    alternate_paid: bool = Field(
        default=False,
        description="Alternate premium and rewarded paid batches across separate free batches",
    )


# MongoDB InDB representations for reference rows
class InstanceCategoryInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    app_instance_id: PyObjectId
    source_id: PyObjectId | None = None
    name: str | None = None
    thumbnail_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    sequence: int = 1
    tier_distribution_settings: dict[str, Any] | None = None
    bulk_asset_tier_distribution_settings: dict[str, Any] | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class InstanceSubcategoryInDB(MongoInDBModel, TimestampMixin, SoftDeleteMixin):
    app_instance_id: PyObjectId
    source_id: PyObjectId | None = None
    category_id: PyObjectId
    name: str | None = None
    thumbnail_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    is_rewarded: bool = False
    sequence: int = 1
    tier_distribution_settings: dict[str, Any] | None = None
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
    name: str
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    is_rewarded: bool = False
    sequence: int
    tier_distribution_settings: dict[str, Any] | None = None
    bulk_asset_tier_distribution_settings: dict[str, Any] | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class ResolvedSubcategoryOut(MongoModel):
    id: str
    category_id: str = Field(..., serialization_alias="categoryId")
    name: str
    thumbnail_url: str | None = None
    image_url: str | None = None
    is_enabled: bool = True
    is_premium: bool = False
    is_rewarded: bool = Field(default=False, serialization_alias="isRewarded")
    sequence: int
    tier_distribution_settings: dict[str, Any] | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class ResolvedAssetOut(MongoModel):
    id: str
    category_id: str = Field(..., serialization_alias="categoryId")
    sub_category_id: str = Field(..., serialization_alias="subCategoryId")
    category_name: str | None = None
    subcategory_name: str | None = None
    name: str
    description: str = ""
    thumbnail_url: str | None = None
    more_fields: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    is_premium: bool = False
    is_rewarded: bool = Field(default=False, serialization_alias="isRewarded")
    rewarded_credits: int = Field(default=5, serialization_alias="rewardedCredits")
    sequence: int
    views: int = 0
    downloads: int = 0
    tags: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)
