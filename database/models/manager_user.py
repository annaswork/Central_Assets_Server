"""Manager user models for tenant-scoped portal authentication and management."""

from datetime import datetime

from pydantic import BaseModel, Field

from database.models.common import MongoInDBModel, MongoModel, TimestampMixin


class ManagerUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str | None = Field(default=None, max_length=150)
    password: str = Field(..., min_length=8)
    confirm_password: str | None = None


class ManagerUserUpdate(BaseModel):
    email: str | None = None
    display_name: str | None = None
    profile_picture: str | None = None
    status: str | None = None
    is_active: bool | None = None


class ManagerProfileUpdate(BaseModel):
    display_name: str | None = None
    profile_picture: str | None = None
    current_password: str | None = None
    new_password: str | None = None


class ManagerUserOut(MongoModel):
    id: str
    username: str
    email: str | None = None
    role: str = "manager"
    status: str = "active"
    is_active: bool = True
    display_name: str | None = None
    profile_picture: str | None = None
    is_2fa_enabled: bool = False
    created_at: datetime
    updated_at: datetime


class ManagerUserInDB(MongoInDBModel, TimestampMixin):
    username: str
    email: str | None = None
    password_hash: str
    encrypted_password: str | None = None
    role: str = "manager"
    status: str = "active"  # "active", "pending", "disabled"
    is_active: bool = True
    display_name: str | None = None
    profile_picture: str | None = None
    is_2fa_enabled: bool = False
    totp_secret: str | None = None
    totp_temp_secret: str | None = None
    backup_codes: list[str] = Field(default_factory=list)
