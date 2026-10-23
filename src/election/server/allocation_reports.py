"""P(14) projections keep exact saved revisions separate from current availability."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation, StockAllocationRevision
from election.server.allocations import allocation_view
from election.server.models import Account
from election.server.stock import stock_scope
from election.server.stock_inventory import availability, current_allocations, received_ranges
from election.server.stock_reports import LABELS as STOCK_LABELS
from election.server.stock_reports import ReportLocale

LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        **STOCK_LABELS["tc"],
        "title": "P(14) 發票櫃台選票派發紀錄",
        "station_current": "本站目前已儲存資料",
        "allocation_revision": "所選派票修訂版本",
        "allocation_id": "派票記錄編號",
        "counter": "發票櫃台",
        "event_at": "派發時間（香港時間）",
        "ordinary_received_quantity": "已接收普通選票",
        "allocated_quantity": "已派發普通選票",
        "available_quantity": "未派發普通選票",
        "receipt_basis": "原接收記錄依據",
    },
    "sc": {
        **STOCK_LABELS["sc"],
        "title": "P(14) 发票柜台选票分配记录",
        "station_current": "本站当前已保存资料",
        "allocation_revision": "所选分配修订版本",
        "allocation_id": "分配记录编号",
        "counter": "发票柜台",
        "event_at": "分配时间（香港时间）",
        "ordinary_received_quantity": "已接收普通选票",
        "allocated_quantity": "已分配普通选票",
        "available_quantity": "未分配普通选票",
        "receipt_basis": "原接收记录依据",
    },
    "en": {
        **STOCK_LABELS["en"],
        "title": "P(14) Counter ballot allocations",
        "station_current": "Current saved station records",
        "allocation_revision": "Selected allocation revision",
        "allocation_id": "Allocation ID",
        "counter": "Issuance counter",
        "event_at": "Allocated at (Hong Kong time)",
        "ordinary_received_quantity": "Received ordinary papers",
        "allocated_quantity": "Allocated ordinary papers",
        "available_quantity": "Unallocated ordinary papers",
        "receipt_basis": "Original receipt basis",
    },
}


def allocation_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/allocations", tags=["P(14) statements"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/statement")
    def statement(
        station_id: int,
        db: Database,
        actor: Ready,
        allocation_id: Annotated[int | None, Query(ge=1)] = None,
        revision: Annotated[int | None, Query(ge=1)] = None,
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        if allocation_id is None:
            if revision is not None:
                raise HTTPException(422, detail={"code": "allocation_required"})
            rows = current_allocations(db, station_id)
            balances: list[dict[str, Any]] | None = availability(
                received_ranges(db, station_id), rows
            )
            report_scope, revision_state = "station_current", "current"
        else:
            if revision is None:
                raise HTTPException(422, detail={"code": "allocation_revision_required"})
            head = db.scalar(
                select(StockAllocation).where(
                    StockAllocation.id == allocation_id, StockAllocation.station_id == station_id
                )
            )
            if head is None:
                raise HTTPException(404, detail={"code": "allocation_not_found"})
            row = db.scalar(
                select(StockAllocationRevision).where(
                    StockAllocationRevision.allocation_id == allocation_id,
                    StockAllocationRevision.revision == revision,
                )
            )
            if row is None:
                raise HTTPException(404, detail={"code": "allocation_not_found"})
            rows, balances = [row], None
            report_scope = "allocation_revision"
            revision_state = "current" if head.revision == revision else "historical"
        return {
            "scope": scope,
            "items": [allocation_view(row, scope) for row in rows],
            "availability": balances,
            "report_scope": report_scope,
            "allocation_id": allocation_id,
            "revision": revision,
            "revision_state": revision_state,
            "locale": locale,
            "title": LABELS[locale]["title"],
            "labels": LABELS[locale],
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }

    return router
