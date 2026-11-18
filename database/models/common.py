"""Common base models, mixins, and serialization configs for Pydantic v2."""

from datetime import datetime, timezone
from typing import Generic, TypeVar

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from utils.ids import PyObjectId

T = TypeVar("T")


def to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


class MongoModel(BaseModel):
    """Base model with MongoDB ObjectId handling and camelCase alias generation."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        arbitrary_types_allowed=True,
        json_encoders={
            ObjectId: str,
            datetime: lambda dt: (
                dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                if dt.tzinfo is None
                else dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            ),
        },
    )


class MongoInDBModel(BaseModel):
    """Base model for internal storage in MongoDB (using snake_case in database)."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="ignore",
    )

    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")


class TimestampMixin(BaseModel):
    """Timezone-aware UTC timestamp mixin."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SoftDeleteMixin(BaseModel):
    """Soft delete mixin tracking when a document was removed."""

    deleted_at: datetime | None = None


class Page(BaseModel, Generic[T]):
    """Generic pagination response wrapper."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool
