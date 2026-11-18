"""Pydantic models for Manager instance access grants, access requests, and messaging."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from database.models.common import MongoInDBModel, MongoModel, TimestampMixin
from utils.ids import PyObjectId


class AppInstanceAccessGrant(BaseModel):
    manager_id: str
    app_instance_id: str


class AppInstanceAccessInDB(MongoInDBModel, TimestampMixin):
    manager_id: PyObjectId
    app_instance_id: PyObjectId
    granted_by: PyObjectId | str | None = None


class AppInstanceAccessRequestCreate(BaseModel):
    app_instance_id: str
    notes: str | None = Field(default=None, max_length=500)


class AppInstanceAccessRequestOut(MongoModel):
    id: str
    requesting_manager_id: str
    requesting_manager_name: str | None = None
    app_instance_id: str
    app_instance_name: str | None = None
    status: str = "pending"  # "pending", "approved", "denied"
    notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AppInstanceAccessRequestInDB(MongoInDBModel, TimestampMixin):
    requesting_manager_id: PyObjectId
    app_instance_id: PyObjectId
    status: str = "pending"
    notes: str | None = None
    reviewed_by: PyObjectId | str | None = None
    reviewed_at: datetime | None = None


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    subject: str | None = Field(default=None, max_length=200)
    payload_type: str | None = None  # "category", "subcategory", "asset", None
    data_payload: dict[str, Any] | None = None


class MessageOut(MongoModel):
    id: str
    manager_id: str
    manager_username: str | None = None
    sender_role: str  # "manager" or "admin"
    sender_id: str
    sender_name: str
    subject: str | None = None
    content: str
    payload_type: str | None = None
    data_payload: dict[str, Any] | None = None
    status: str = "unread"  # "unread", "read", "applied", "rejected"
    created_at: datetime
    updated_at: datetime


class MessageInDB(MongoInDBModel, TimestampMixin):
    manager_id: PyObjectId
    sender_role: str  # "manager" or "admin"
    sender_id: PyObjectId | str
    sender_name: str
    subject: str | None = None
    content: str
    payload_type: str | None = None
    data_payload: dict[str, Any] | None = None
    status: str = "unread"
