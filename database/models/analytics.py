"""Analytics models: monitored endpoints, raw events, and hourly rollups."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from database.models.common import MongoInDBModel, MongoModel, TimestampMixin


class MonitoredEndpointCreate(BaseModel):
    method: str = Field(..., description="HTTP method in uppercase: GET, POST, etc.")
    path_template: str = Field(..., description="FastAPI route template, e.g. /api/v1/assets/{id}")
    is_active: bool = True
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    retain_days: int = Field(default=30, ge=1, le=365)
    notes: str = ""


class MonitoredEndpointUpdate(BaseModel):
    is_active: bool | None = None
    sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    retain_days: int | None = Field(default=None, ge=1, le=365)
    notes: str | None = None


class MonitoredEndpointOut(MongoModel):
    id: str
    method: str
    path_template: str
    is_active: bool
    sample_rate: float
    retain_days: int
    notes: str
    created_at: datetime
    updated_at: datetime


class MonitoredEndpointInDB(MongoInDBModel, TimestampMixin):
    method: str
    path_template: str
    is_active: bool = True
    sample_rate: float = 1.0
    retain_days: int = 30
    notes: str = ""


class AnalyticsEventInDB(MongoInDBModel):
    path_template: str
    method: str
    status_code: int
    duration_ms: float
    api_key_id: str | None = None
    app_instance_id: str | None = None
    country: str | None = None
    platform: str | None = None
    app_version: str | None = None
    request_bytes: int = 0
    response_bytes: int = 0
    error_code: str | None = None
    error_reason: str | None = None
    error_details: Any | None = None
    ts: datetime


class HourlyRollupInDB(MongoInDBModel):
    path_template: str
    hour: datetime
    app_instance_id: str | None = None
    count: int = 0
    error_count: int = 0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    bytes_out: int = 0
