"""Super Category schemas: optional top level that groups central categories."""

from pydantic import BaseModel, Field


class SuperCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Unique super category name")
    thumbnail_url: str | None = None
    image_url: str | None = None
    sequence: int | None = Field(default=None, description="Display order; lower first")


class SuperCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    thumbnail_url: str | None = None
    image_url: str | None = None
    sequence: int | None = None
