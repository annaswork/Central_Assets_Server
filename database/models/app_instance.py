"""App instance models for app entity management."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from database.models.common import MongoInDBModel, MongoModel, TimestampMixin
from utils.validators import is_valid_package_name


class AppInstanceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    package_name: str | None = Field(default=None, max_length=150)
    app_icon: str | None = None

    @field_validator("package_name")
    @classmethod
    def validate_pkg(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            v_clean = v.strip()
            if v_clean.lower() == "none":
                return None
            if not is_valid_package_name(v_clean):
                raise ValueError("Invalid package name format (e.g. com.example.app)")
            return v_clean
        return None


class AppInstanceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    package_name: str | None = None
    app_icon: str | None = None

    @field_validator("package_name")
    @classmethod
    def validate_pkg(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            v_clean = v.strip()
            if v_clean.lower() == "none":
                return None
            if not is_valid_package_name(v_clean):
                raise ValueError("Invalid package name format (e.g. com.example.app)")
            return v_clean
        return None


class AppInstanceOut(MongoModel):
    id: str
    name: str
    package_name: str | None = None
    app_icon: str | None = None
    created_at: datetime
    updated_at: datetime


class AppInstanceInDB(MongoInDBModel, TimestampMixin):
    name: str
    package_name: str | None = None
    app_icon: str | None = None
