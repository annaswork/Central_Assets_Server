"""Analytics endpoints for managing the monitoring list and viewing traffic metrics."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.scopes import require_scope
from controller.analytics_controller import (
    create_monitored_endpoint,
    delete_monitored_endpoint,
    get_dashboard_csv,
    get_dashboard_summary,
    list_monitored_endpoints,
    update_monitored_endpoint,
)
from database.models.analytics import (
    MonitoredEndpointCreate,
    MonitoredEndpointUpdate,
)
from router.deps import get_db

router = APIRouter(prefix="/analytics", tags=["Analytics & Monitoring"])


@router.get("/endpoints", dependencies=[Depends(require_scope("analytics:read"))])
async def list_endpoints_endpoint(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[dict[str, Any]]:
    return await list_monitored_endpoints(db)


@router.post("/endpoints", status_code=201, dependencies=[Depends(require_scope("keys:manage"))])
async def create_endpoint_endpoint(
    payload: MonitoredEndpointCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await create_monitored_endpoint(db, payload)


@router.patch("/endpoints/{id}", dependencies=[Depends(require_scope("keys:manage"))])
async def update_endpoint_endpoint(
    id: str,
    payload: MonitoredEndpointUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await update_monitored_endpoint(db, endpoint_id=id, data=payload)


@router.delete("/endpoints/{id}", dependencies=[Depends(require_scope("keys:manage"))])
async def delete_endpoint_endpoint(
    id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await delete_monitored_endpoint(db, endpoint_id=id)


@router.get("/summary", dependencies=[Depends(require_scope("analytics:read"))])
async def get_analytics_summary_endpoint(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    instanceId: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    return await get_dashboard_summary(db, from_dt=from_dt, to_dt=to_dt, app_instance_id=instanceId)


@router.get("/export", dependencies=[Depends(require_scope("analytics:read"))])
async def export_analytics_csv_endpoint(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    instanceId: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    csv_data = await get_dashboard_csv(db, from_dt=from_dt, to_dt=to_dt, app_instance_id=instanceId)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="analytics_export.csv"'},
    )
