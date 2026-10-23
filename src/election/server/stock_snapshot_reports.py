"""Selected P(12) statements preserve the exact saved snapshot and its stock basis."""

import csv
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.stock import stock_scope
from election.server.stock_reports import ReportLocale, hong_kong_time
from election.server.stock_snapshot_models import StockSnapshot, StockSnapshotRevision
from election.server.stock_snapshots import snapshot_view

LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        "title": "P(12) 發票櫃台結餘及發票紀錄",
        "field": "項目",
        "value": "內容",
        "reporting_status": "填報狀態",
        "page": "頁",
        "election": "選舉",
        "election_status": "選舉狀態",
        "draft": "草稿",
        "active": "進行中",
        "finalized": "已完成",
        "constituency": "選區",
        "station": "投票站",
        "report_scope": "報表基準",
        "snapshot_revision": "所選已儲存快照版本",
        "revision_state": "版本狀態",
        "current": "目前版本",
        "historical": "歷史版本",
        "snapshot_id": "快照記錄編號",
        "revision": "修訂版本",
        "status": "記錄狀態",
        "recorded": "已記錄",
        "completeness": "快照完整狀態",
        "complete": "完整",
        "incomplete": "未完整",
        "provenance": "數字來源",
        "stock_derived": "庫存推算",
        "provenance_note": "以下普通發票數量按庫存推算，並非已核實選民人數。",
        "scope_note": "保留所選快照版本的原有數字及來源基礎，不包含目前可用庫存或未儲存內容。",
        "event_at": "原始快照時間（香港時間）",
        "entered_at": "伺服器記錄時間（香港時間）",
        "actor_id": "記錄職員編號",
        "reason": "修正原因",
        "generated_at": "產生時間（香港時間）",
        "time_basis": "時間基準",
        "not_recorded": "尚未記錄",
        "none": "無",
        "summary": "此版本的全站合計",
        "counters": "此版本的櫃台明細",
        "counter": "發票櫃台",
        "reported": "已填報",
        "not_reported": "尚未填報",
        "no_counters": "此版本沒有櫃台資料。",
        "remaining_ranges": "已填報的剩餘普通選票範圍",
        "issued_ranges": "按庫存推算的已發出普通選票範圍",
        "range_fields": "選票系列 · 起始編號 · 結束編號 · 數量",
        "empty_ranges": "沒有範圍（明確零）",
        "ordinary_allocated_quantity": "普通選票派發總量",
        "ordinary_returned_quantity": "未發出普通選票退回總量",
        "ordinary_net_allocated_quantity": "普通選票淨派發量",
        "ordinary_remaining_quantity": "剩餘普通選票數量",
        "ordinary_issued_quantity": "庫存推算普通發票數量",
        "receipt_basis": "原接收記錄基礎",
        "allocation_basis": "原派發記錄基礎",
        "return_basis": "原未發出選票退回記錄基礎",
        "receipt_id": "接收記錄編號",
        "allocation_id": "派發記錄編號",
        "return_id": "退回記錄編號",
    },
    "sc": {
        "title": "P(12) 发票柜台结余及发票记录",
        "field": "项目",
        "value": "内容",
        "reporting_status": "填报状态",
        "page": "页",
        "election": "选举",
        "election_status": "选举状态",
        "draft": "草稿",
        "active": "进行中",
        "finalized": "已完成",
        "constituency": "选区",
        "station": "投票站",
        "report_scope": "报表依据",
        "snapshot_revision": "所选已保存快照版本",
        "revision_state": "版本状态",
        "current": "当前版本",
        "historical": "历史版本",
        "snapshot_id": "快照记录编号",
        "revision": "修订版本",
        "status": "记录状态",
        "recorded": "已记录",
        "completeness": "快照完整状态",
        "complete": "完整",
        "incomplete": "未完整",
        "provenance": "数字来源",
        "stock_derived": "库存推算",
        "provenance_note": "以下普通发票数量按库存推算，并非已核实选民人数。",
        "scope_note": "保留所选快照版本的原有数字及来源依据，不包含当前可用库存或未保存内容。",
        "event_at": "原始快照时间（香港时间）",
        "entered_at": "服务器记录时间（香港时间）",
        "actor_id": "记录职员编号",
        "reason": "修正原因",
        "generated_at": "生成时间（香港时间）",
        "time_basis": "时间基准",
        "not_recorded": "尚未记录",
        "none": "无",
        "summary": "此版本的全站合计",
        "counters": "此版本的柜台明细",
        "counter": "发票柜台",
        "reported": "已填报",
        "not_reported": "尚未填报",
        "no_counters": "此版本没有柜台数据。",
        "remaining_ranges": "已填报的剩余普通选票范围",
        "issued_ranges": "按库存推算的已发出普通选票范围",
        "range_fields": "选票系列 · 起始编号 · 结束编号 · 数量",
        "empty_ranges": "没有范围（明确零）",
        "ordinary_allocated_quantity": "普通选票派发总量",
        "ordinary_returned_quantity": "未发出普通选票退回总量",
        "ordinary_net_allocated_quantity": "普通选票净派发量",
        "ordinary_remaining_quantity": "剩余普通选票数量",
        "ordinary_issued_quantity": "库存推算普通发票数量",
        "receipt_basis": "原接收记录依据",
        "allocation_basis": "原派发记录依据",
        "return_basis": "原未发出选票退回记录依据",
        "receipt_id": "接收记录编号",
        "allocation_id": "派发记录编号",
        "return_id": "退回记录编号",
    },
    "en": {
        "title": "P(12) Counter remaining stock and issuance",
        "field": "Field",
        "value": "Value",
        "reporting_status": "Reporting status",
        "page": "Page",
        "election": "Election",
        "election_status": "Election status",
        "draft": "Draft",
        "active": "Active",
        "finalized": "Finalized",
        "constituency": "Constituency",
        "station": "Polling station",
        "report_scope": "Report basis",
        "snapshot_revision": "Selected saved snapshot revision",
        "revision_state": "Revision state",
        "current": "Current revision",
        "historical": "Historical revision",
        "snapshot_id": "Snapshot ID",
        "revision": "Revision",
        "status": "Record status",
        "recorded": "Recorded",
        "completeness": "Snapshot completeness",
        "complete": "Complete",
        "incomplete": "Incomplete",
        "provenance": "Figure provenance",
        "stock_derived": "Stock-derived",
        "provenance_note": (
            "Ordinary issuance is derived from ballot stock; these are not verified elector counts."
        ),
        "scope_note": (
            "Retain the selected saved snapshot and its original basis. "
            "Current available stock and unsaved input are excluded."
        ),
        "event_at": "Original snapshot time (Hong Kong time)",
        "entered_at": "Server entry time (Hong Kong time)",
        "actor_id": "Recorded by account ID",
        "reason": "Correction reason",
        "generated_at": "Generated at (Hong Kong time)",
        "time_basis": "Time basis",
        "not_recorded": "Not recorded",
        "none": "None",
        "summary": "Station totals at this revision",
        "counters": "Counter details at this revision",
        "counter": "Issuance counter",
        "reported": "Reported",
        "not_reported": "Not reported",
        "no_counters": "No counter data in this revision.",
        "remaining_ranges": "Reported remaining ordinary ranges",
        "issued_ranges": "Stock-derived issued ordinary ranges",
        "range_fields": "Ballot series · Serial from · Serial to · Quantity",
        "empty_ranges": "No ranges (explicit zero)",
        "ordinary_allocated_quantity": "Gross ordinary allocations",
        "ordinary_returned_quantity": "Unissued ordinary stock returned",
        "ordinary_net_allocated_quantity": "Net ordinary allocations",
        "ordinary_remaining_quantity": "Ordinary papers remaining",
        "ordinary_issued_quantity": "Stock-derived ordinary issuance",
        "receipt_basis": "Original receipt basis",
        "allocation_basis": "Original allocation basis",
        "return_basis": "Original unissued-return basis",
        "receipt_id": "Receipt ID",
        "allocation_id": "Allocation ID",
        "return_id": "Return ID",
    },
}

QUANTITY_FIELDS = (
    "ordinary_allocated_quantity",
    "ordinary_returned_quantity",
    "ordinary_net_allocated_quantity",
    "ordinary_remaining_quantity",
    "ordinary_issued_quantity",
)


def _display(value: Any, labels: dict[str, str]) -> str:
    return labels["not_recorded"] if value is None else str(value)


def _range_rows(ranges: list[dict[str, Any]] | None, labels: dict[str, str]) -> list[list[str]]:
    if ranges is None:
        return [[labels["not_reported"]]]
    return [
        [str(row[key]) for key in ("series", "serial_from", "serial_to", "quantity")]
        for row in ranges
    ] or [[labels["empty_ranges"]]]


def _metadata_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, scope, snapshot = projection["labels"], projection["scope"], projection["items"][0]
    metadata = [
        ("election", scope["election"]["name"]),
        ("election_status", labels[scope["election"]["status"]]),
        ("constituency", scope["constituency"]["code"] + " · " + scope["constituency"]["name"]),
        ("station", scope["station"]["code"] + " · " + scope["station"]["name"]),
        ("report_scope", labels[projection["report_scope"]]),
        ("revision_state", labels[projection["revision_state"]]),
        ("snapshot_id", str(snapshot["id"])),
        ("revision", str(snapshot["revision"])),
        ("status", labels[snapshot["status"]]),
        ("completeness", labels["complete" if snapshot["complete"] else "incomplete"]),
        ("provenance", labels[snapshot["provenance"]]),
        ("event_at", hong_kong_time(snapshot["event_at"])),
        ("entered_at", hong_kong_time(snapshot["entered_at"])),
        ("actor_id", str(snapshot["actor_id"])),
        ("reason", snapshot["reason"] or labels["none"]),
        ("generated_at", hong_kong_time(projection["generated_at"])),
        ("time_basis", "Asia/Hong_Kong (UTC+08:00)"),
    ]
    return [[labels[key], value] for key, value in metadata]


def _report_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, snapshot = projection["labels"], projection["items"][0]
    rows = [[projection["title"]], *_metadata_rows(projection)]
    rows.extend([[labels["scope_note"]], [labels["provenance_note"]], [], [labels["summary"]]])
    rows.extend([labels[key], _display(snapshot[key], labels)] for key in QUANTITY_FIELDS)
    rows.extend([[], [labels["counters"]]])
    if not snapshot["counters"]:
        rows.append([labels["no_counters"]])
    for counter in snapshot["counters"]:
        identity = counter["counter"]
        rows.extend(
            [
                [labels["counter"], identity["code"] + " · " + identity["name"]],
                [labels["reported"] if counter["reported"] else labels["not_reported"]],
            ]
        )
        rows.extend([labels[key], _display(counter[key], labels)] for key in QUANTITY_FIELDS)
        for key, ranges in (
            ("remaining_ranges", counter["ranges"]),
            ("issued_ranges", counter["issued_ranges"] if counter["reported"] else None),
        ):
            rows.extend([[labels[key]], labels["range_fields"].split(" · ")])
            rows.extend(_range_rows(ranges, labels))
    for name, identity_key in (
        ("receipt_basis", "receipt_id"),
        ("allocation_basis", "allocation_id"),
        ("return_basis", "return_id"),
    ):
        rows.extend([[], [labels[name]]])
        if not snapshot[name]:
            rows.append([labels["none"]])
        else:
            rows.append([labels[identity_key], labels["revision"]])
            rows.extend(
                [str(basis[identity_key]), str(basis["revision"])] for basis in snapshot[name]
            )
    return rows


def _preview_lines(projection: dict[str, Any]) -> list[str]:
    return [" · ".join(row) for row in _report_rows(projection)]


def _csv_report(projection: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    csv.writer(output).writerows(_report_rows(projection))
    return output.getvalue().encode("utf-8-sig")


def _pdf_tables(projection: dict[str, Any]) -> list[HistoryTable]:
    labels, snapshot = projection["labels"], projection["items"][0]
    sections = [
        HistoryTable(
            labels["summary"],
            [
                [labels["field"], labels["value"]],
                [labels["report_scope"], labels["scope_note"]],
                [labels["provenance"], labels["provenance_note"]],
            ]
            + [[labels[key], _display(snapshot[key], labels)] for key in QUANTITY_FIELDS],
            (0.50, 0.50),
        ),
    ]
    overview = [
        [labels["counters"] + "\n" + labels["counter"], labels["reporting_status"]]
        + [labels[key] for key in QUANTITY_FIELDS]
    ]
    for counter in snapshot["counters"]:
        identity = counter["counter"]
        overview.append(
            [
                identity["code"] + " · " + identity["name"],
                labels["reported"] if counter["reported"] else labels["not_reported"],
            ]
            + [_display(counter[key], labels) for key in QUANTITY_FIELDS]
        )
    sections.append(
        HistoryTable(
            "",
            overview,
            (0.20, 0.10, 0.14, 0.14, 0.14, 0.14, 0.14),
            labels["no_counters"] if not snapshot["counters"] else "",
            split_in_row=False,
        )
    )
    for counter in snapshot["counters"]:
        identity = counter["counter"]
        heading = labels["counter"] + " · " + identity["code"] + " · " + identity["name"]
        for key, ranges in (
            ("remaining_ranges", counter["ranges"]),
            ("issued_ranges", counter["issued_ranges"] if counter["reported"] else None),
        ):
            sections.append(
                HistoryTable(
                    heading + " · " + labels[key],
                    [labels["range_fields"].split(" · ")]
                    + (_range_rows(ranges, labels) if ranges else []),
                    (0.40, 0.22, 0.22, 0.16),
                    labels["not_reported"]
                    if ranges is None
                    else labels["empty_ranges"]
                    if not ranges
                    else "",
                    split_in_row=False,
                )
            )
    for name, identity_key in (
        ("receipt_basis", "receipt_id"),
        ("allocation_basis", "allocation_id"),
        ("return_basis", "return_id"),
    ):
        sections.append(
            HistoryTable(
                labels[name],
                [[labels[identity_key], labels["revision"]]]
                + (
                    [[str(basis[identity_key]), str(basis["revision"])] for basis in snapshot[name]]
                    if snapshot[name]
                    else [[labels["none"], labels["none"]]]
                ),
                (0.50, 0.50),
                split_in_row=False,
            )
        )
    return sections


def _pdf_report(projection: dict[str, Any]) -> bytes:
    labels = projection["labels"]
    footer = (
        projection["scope"]["station"]["code"]
        + " · "
        + labels["snapshot_id"]
        + " "
        + str(projection["snapshot_id"])
        + " · "
        + labels["revision"]
        + " "
        + str(projection["revision"])
    )
    return history_pdf(
        projection["title"],
        _metadata_rows(projection),
        _pdf_tables(projection),
        footer,
        labels["page"],
    )


def stock_snapshot_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/stock-snapshots", tags=["P(12) statements"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/statement")
    def statement(
        station_id: int,
        db: Database,
        actor: Ready,
        snapshot_id: Annotated[int, Query(ge=1)],
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        scope = stock_scope(db, actor, station_id)
        head = db.scalar(
            select(StockSnapshot).where(
                StockSnapshot.id == snapshot_id, StockSnapshot.station_id == station_id
            )
        )
        if head is None:
            raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
        row = db.scalar(
            select(StockSnapshotRevision).where(
                StockSnapshotRevision.snapshot_id == snapshot_id,
                StockSnapshotRevision.revision == revision,
            )
        )
        if row is None:
            raise HTTPException(404, detail={"code": "stock_snapshot_not_found"})
        projection = {
            "scope": scope,
            "items": [snapshot_view(row, station_id)],
            "availability": None,
            "report_scope": "snapshot_revision",
            "snapshot_id": snapshot_id,
            "revision": revision,
            "revision_state": "current" if head.revision == revision else "historical",
            "locale": locale,
            "title": LABELS[locale]["title"],
            "labels": LABELS[locale],
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }
        return {**projection, "preview_lines": _preview_lines(projection)}

    @router.get("/statement.csv")
    def statement_csv(
        station_id: int,
        db: Database,
        actor: Ready,
        snapshot_id: Annotated[int, Query(ge=1)],
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, db, actor, snapshot_id, revision, locale)
        filename = f"p12-snapshot-{snapshot_id}-r{revision}-{locale}.csv"
        return Response(
            _csv_report(projection),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/statement.pdf")
    def statement_pdf(
        station_id: int,
        db: Database,
        actor: Ready,
        snapshot_id: Annotated[int, Query(ge=1)],
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, db, actor, snapshot_id, revision, locale)
        filename = f"p12-snapshot-{snapshot_id}-r{revision}-{locale}.pdf"
        return Response(
            _pdf_report(projection),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
