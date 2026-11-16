"""Projections keep exact saved revisions separate from current availability."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.allocation_models import StockAllocation, StockAllocationRevision
from election.server.allocation_report_format import csv_report, pdf_report, preview_lines
from election.server.allocations import allocation_view
from election.server.models import Account
from election.server.stock import stock_scope
from election.server.stock_inventory import (
    allocation_fragments,
    availability,
    current_allocations,
    current_returns,
    received_ranges,
)
from election.server.stock_reports import LABELS as STOCK_LABELS
from election.server.stock_reports import ReportLocale

LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        **STOCK_LABELS["tc"],
        "title": "發票櫃台選票派發紀錄",
        "station_current": "本站目前已儲存資料",
        "allocation_revision": "所選派票修訂版本",
        "allocation_id": "派票記錄編號",
        "counter": "發票櫃台",
        "event_at": "派發時間（香港時間）",
        "ordinary_received_quantity": "已接收普通選票",
        "allocated_quantity": "已派發普通選票",
        "available_quantity": "未派發普通選票",
        "receipt_basis": "原接收記錄依據",
        "report_scope": "報表範圍",
        "allocations": "已儲存派票記錄",
        "availability": "目前本站庫存",
        "available_ranges": "目前未派發普通選票範圍",
        "range_line": "原範圍行號（由一開始）",
        "record_value": "資料說明",
        "field": "欄位",
        "value": "內容",
        "details": "派票記錄詳情",
        "empty_allocations": "尚無已儲存派票記錄。",
        "empty_ranges": "目前沒有未派發普通選票範圍。",
        "revision_legend": "顯示所選已儲存版本及當時的接收依據；不包含目前庫存。",
        "station_legend": "顯示產生報表時各派票記錄的目前版本及本站庫存；儲備選票分開列示。",
    },
    "sc": {
        **STOCK_LABELS["sc"],
        "title": "发票柜台选票分配记录",
        "station_current": "本站当前已保存资料",
        "allocation_revision": "所选分配修订版本",
        "allocation_id": "分配记录编号",
        "counter": "发票柜台",
        "event_at": "分配时间（香港时间）",
        "ordinary_received_quantity": "已接收普通选票",
        "allocated_quantity": "已分配普通选票",
        "available_quantity": "未分配普通选票",
        "receipt_basis": "原接收记录依据",
        "report_scope": "报表范围",
        "allocations": "已保存分配记录",
        "availability": "当前本站库存",
        "available_ranges": "当前未分配普通选票范围",
        "range_line": "原范围行号（从一开始）",
        "record_value": "资料说明",
        "field": "字段",
        "value": "内容",
        "details": "分配记录详情",
        "empty_allocations": "尚无已保存分配记录。",
        "empty_ranges": "当前没有未分配普通选票范围。",
        "revision_legend": "显示所选已保存版本及当时的接收依据；不包含当前库存。",
        "station_legend": "显示生成报表时各分配记录的当前版本及本站库存；储备选票分开列示。",
    },
    "en": {
        **STOCK_LABELS["en"],
        "title": "Counter ballot allocations",
        "station_current": "Current saved station records",
        "allocation_revision": "Selected allocation revision",
        "allocation_id": "Allocation ID",
        "counter": "Issuance counter",
        "event_at": "Allocated at (Hong Kong time)",
        "ordinary_received_quantity": "Received ordinary papers",
        "allocated_quantity": "Allocated ordinary papers",
        "available_quantity": "Unallocated ordinary papers",
        "receipt_basis": "Original receipt basis",
        "report_scope": "Report scope",
        "allocations": "Saved allocations",
        "availability": "Current station stock",
        "available_ranges": "Current unallocated ordinary ranges",
        "range_line": "Original range line (one based)",
        "record_value": "Record context",
        "field": "Field",
        "value": "Value",
        "details": "Allocation details",
        "empty_allocations": "No saved allocations yet.",
        "empty_ranges": "No unallocated ordinary ranges remain.",
        "revision_legend": (
            "The selected saved revision and its original receipt basis; current stock is excluded."
        ),
        "station_legend": (
            "Current allocation revisions and station stock at report generation; "
            "reserves are shown separately."
        ),
    },
}


def allocation_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/allocations", tags=["Allocation statements"]
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
                received_ranges(db, station_id),
                allocation_fragments(rows, current_returns(db, station_id)),
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
        projection = {
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
        return {**projection, "preview_lines": preview_lines(projection)}

    @router.get("/statement.csv")
    def download_csv(
        station_id: int,
        db: Database,
        actor: Ready,
        allocation_id: Annotated[int | None, Query(ge=1)] = None,
        revision: Annotated[int | None, Query(ge=1)] = None,
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, db, actor, allocation_id, revision, locale)
        identity = (
            f"{allocation_id}-r{revision}"
            if allocation_id is not None
            else f"station-{station_id}-current"
        )
        return Response(
            csv_report(projection),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="allocation-{identity}-{locale}.csv"'
            },
        )

    @router.get("/statement.pdf")
    def download_pdf(
        station_id: int,
        db: Database,
        actor: Ready,
        allocation_id: Annotated[int | None, Query(ge=1)] = None,
        revision: Annotated[int | None, Query(ge=1)] = None,
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, db, actor, allocation_id, revision, locale)
        identity = (
            f"{allocation_id}-r{revision}"
            if allocation_id is not None
            else f"station-{station_id}-current"
        )
        return Response(
            pdf_report(projection),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="allocation-{identity}-{locale}.pdf"'
            },
        )

    return router
