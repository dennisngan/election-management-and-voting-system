"""Revision-bound received-stock statements for the desktop and exported reports."""

import csv
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO, StringIO
from typing import Annotated, Any, Literal
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Query, Response
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from election.server.models import Account
from election.server.report_fonts import font_for_pdf
from election.server.stock import stock_statement

type ReportLocale = Literal["tc", "sc", "en"]
HKT = timezone(timedelta(hours=8), "HKT")

LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        "title": "選票接收及儲備報表",
        "election": "選舉",
        "election_status": "選舉狀態",
        "constituency": "選區",
        "station": "投票站",
        "receipt_id": "接收記錄編號",
        "revision": "修訂版本",
        "revision_state": "版本狀態",
        "current": "目前版本",
        "historical": "歷史版本",
        "status": "記錄狀態",
        "recorded": "已記錄",
        "draft": "草稿",
        "active": "進行中",
        "finalized": "已完成",
        "series": "選票系列",
        "event_at": "接收時間（香港時間）",
        "entered_at": "伺服器記錄時間（香港時間）",
        "actor_id": "記錄職員編號",
        "reason": "修正原因",
        "none": "不適用",
        "ordinary_quantity": "普通選票",
        "replacement_quantity": "替換選票儲備",
        "tendered_quantity": "重複選票儲備",
        "total_quantity": "接收總數",
        "generated_at": "產生時間（香港時間）",
        "time_basis": "時間基準",
        "ranges": "接收的選票編號範圍",
        "pool": "選票類別",
        "serial_from": "起始編號",
        "serial_to": "結束編號",
        "quantity": "數量",
        "page": "頁",
    },
    "sc": {
        "title": "选票接收及储备报表",
        "election": "选举",
        "election_status": "选举状态",
        "constituency": "选区",
        "station": "投票站",
        "receipt_id": "接收记录编号",
        "revision": "修订版本",
        "revision_state": "版本状态",
        "current": "当前版本",
        "historical": "历史版本",
        "status": "记录状态",
        "recorded": "已记录",
        "draft": "草稿",
        "active": "进行中",
        "finalized": "已完成",
        "series": "选票系列",
        "event_at": "接收时间（香港时间）",
        "entered_at": "服务器记录时间（香港时间）",
        "actor_id": "记录职员编号",
        "reason": "修正原因",
        "none": "不适用",
        "ordinary_quantity": "普通选票",
        "replacement_quantity": "替换选票储备",
        "tendered_quantity": "重复选票储备",
        "total_quantity": "接收总数",
        "generated_at": "生成时间（香港时间）",
        "time_basis": "时间基准",
        "ranges": "接收的选票编号范围",
        "pool": "选票类别",
        "serial_from": "起始编号",
        "serial_to": "结束编号",
        "quantity": "数量",
        "page": "页",
    },
    "en": {
        "title": "Ballot stock receipt and reserves",
        "election": "Election",
        "election_status": "Election status",
        "constituency": "Constituency",
        "station": "Polling station",
        "receipt_id": "Receipt ID",
        "revision": "Revision",
        "revision_state": "Revision state",
        "current": "Current revision",
        "historical": "Historical revision",
        "status": "Record status",
        "recorded": "Recorded",
        "draft": "Draft",
        "active": "Active",
        "finalized": "Finalized",
        "series": "Ballot series",
        "event_at": "Received at (Hong Kong time)",
        "entered_at": "Server entry time (Hong Kong time)",
        "actor_id": "Recorded by account ID",
        "reason": "Correction reason",
        "none": "Not applicable",
        "ordinary_quantity": "Ordinary papers",
        "replacement_quantity": "Replacement reserve",
        "tendered_quantity": "Tendered reserve",
        "total_quantity": "Total received",
        "generated_at": "Generated at (Hong Kong time)",
        "time_basis": "Time basis",
        "ranges": "Received serial ranges",
        "pool": "Pool",
        "serial_from": "Serial from",
        "serial_to": "Serial to",
        "quantity": "Quantity",
        "page": "Page",
    },
}


def hong_kong_time(value: datetime) -> str:
    local = value.astimezone(HKT)
    fraction = f".{local.microsecond:06d}" if local.microsecond else ""
    return local.strftime("%Y-%m-%d %H:%M:%S") + fraction + " HKT"


def metadata_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, scope, receipt = projection["labels"], projection["scope"], projection["items"][0]
    values = [
        ("election", scope["election"]["name"]),
        ("election_status", labels[scope["election"]["status"]]),
        ("constituency", scope["constituency"]["code"] + " · " + scope["constituency"]["name"]),
        ("station", scope["station"]["code"] + " · " + scope["station"]["name"]),
        ("receipt_id", str(receipt["id"])),
        ("revision", str(receipt["revision"])),
        ("revision_state", labels[projection["revision_state"]]),
        ("status", labels[receipt["status"]]),
        ("series", receipt["series"]),
        ("event_at", hong_kong_time(receipt["event_at"])),
        ("entered_at", hong_kong_time(receipt["entered_at"])),
        ("actor_id", str(receipt["actor_id"])),
        ("reason", receipt["reason"] or labels["none"]),
        ("ordinary_quantity", str(receipt["ordinary_quantity"])),
        ("replacement_quantity", str(receipt["replacement_quantity"])),
        ("tendered_quantity", str(receipt["tendered_quantity"])),
        ("total_quantity", str(receipt["total_quantity"])),
        ("generated_at", hong_kong_time(projection["generated_at"])),
        ("time_basis", "Asia/Hong_Kong (UTC+08:00)"),
    ]
    return [[labels[key], value] for key, value in values]


def range_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, receipt = projection["labels"], projection["items"][0]
    return [
        [labels[key] for key in ("pool", "serial_from", "serial_to", "quantity")],
        *[
            [
                labels[row["pool"] + "_quantity"],
                row["serial_from"],
                row["serial_to"],
                str(row["quantity"]),
            ]
            for row in receipt["ranges"]
        ],
    ]


def csv_report(projection: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([projection["title"]])
    writer.writerows(metadata_rows(projection))
    writer.writerow([])
    writer.writerows(range_rows(projection))
    return output.getvalue().encode("utf-8-sig")


def pdf_report(projection: dict[str, Any]) -> bytes:
    labels, receipt = projection["labels"], projection["items"][0]
    metadata, ranges = metadata_rows(projection), range_rows(projection)
    footer = (
        labels["receipt_id"]
        + " "
        + str(receipt["id"])
        + " · "
        + labels["revision"]
        + " "
        + str(receipt["revision"])
        + " · "
        + labels[projection["revision_state"]]
    )
    rendered_text = [projection["title"], labels["ranges"], labels["page"], footer]
    rendered_text += [value for row in metadata + ranges for value in row]
    with font_for_pdf(rendered_text) as font_name:
        return _render_pdf(projection, metadata, ranges, footer, font_name)


def _render_pdf(
    projection: dict[str, Any],
    metadata: list[list[str]],
    ranges: list[list[str]],
    footer: str,
    font_name: str,
) -> bytes:
    labels = projection["labels"]
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=17 * mm,
        title=projection["title"],
    )
    body = ParagraphStyle(
        "ReceiptBody", fontName=font_name, fontSize=10, leading=14, wordWrap="CJK"
    )
    title = ParagraphStyle("ReceiptTitle", parent=body, fontSize=18, leading=25, spaceAfter=16)
    heading = ParagraphStyle("ReceiptHeading", parent=body, fontSize=12, leading=17, spaceAfter=10)

    def paragraph(value: str, style: Any = body) -> Any:
        return Paragraph(escape(value).replace("\n", "<br/>"), style)

    metadata_table = Table(
        [[paragraph(value) for value in row] for row in metadata],
        colWidths=[document.width * 0.32, document.width * 0.68],
        hAlign="LEFT",
    )
    metadata_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f5fa")),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce3ed")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce3ed")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    range_table = Table(
        [[paragraph(value) for value in row] for row in ranges],
        colWidths=[document.width * fraction for fraction in (0.28, 0.27, 0.27, 0.18)],
        repeatRows=1,
        hAlign="LEFT",
    )
    range_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6eef9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce3ed")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    def page_footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#52637b"))
        canvas.drawString(document.leftMargin, 9 * mm, footer)
        canvas.drawRightString(
            A4[0] - document.rightMargin, 9 * mm, labels["page"] + " " + str(doc.page)
        )
        canvas.restoreState()

    document.build(
        [
            paragraph(projection["title"], title),
            metadata_table,
            Spacer(1, 18),
            paragraph(labels["ranges"], heading),
            range_table,
        ],
        onFirstPage=page_footer,
        onLaterPages=page_footer,
    )
    return output.getvalue()


def stock_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/stock/{receipt_id}",
        tags=["Received-stock statements"],
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/statement")
    def statement(
        station_id: int,
        receipt_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        current = stock_statement(db, actor, station_id, receipt_id=receipt_id)
        projection = stock_statement(
            db, actor, station_id, receipt_id=receipt_id, revision=revision
        )
        return {
            **projection,
            "locale": locale,
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
            "revision_state": "current"
            if current["items"][0]["revision"] == revision
            else "historical",
            "title": LABELS[locale]["title"],
            "labels": LABELS[locale],
        }

    @router.get("/statement.csv")
    def download_csv(
        station_id: int,
        receipt_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, receipt_id, db, actor, revision, locale)
        filename = f"stock-receipt-{receipt_id}-r{revision}-{locale}.csv"
        return Response(
            csv_report(projection),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/statement.pdf")
    def download_pdf(
        station_id: int,
        receipt_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, receipt_id, db, actor, revision, locale)
        filename = f"stock-receipt-{receipt_id}-r{revision}-{locale}.pdf"
        return Response(
            pdf_report(projection),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
