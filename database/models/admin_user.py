"""Admin user operator models for session-based panel authentication."""

from datetime import datetime

from pydantic import BaseModel, Field

from database.models.common import MongoInDBModel, MongoModel, TimestampMixin


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class AdminUserOut(MongoModel):
    id: str
    username: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminUserInDB(MongoInDBModel, TimestampMixin):
    username: str
    password_hash: str
    is_active: bool = True
