"""Current station handover and timeline statements with preserved event history."""

import csv
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from election.server.boxes import (
    MILESTONE_KINDS,
    box_event_view,
    box_events,
    box_snapshot,
)
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account

type ReportLocale = Literal["tc", "sc", "en"]
HKT = timezone(timedelta(hours=8), "HKT")

LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        "title": "票箱交收及點票工作時間表",
        "election": "選舉",
        "election_status": "選舉狀態",
        "constituency": "選區",
        "station": "票站／點票站",
        "draft": "草稿",
        "active": "進行中",
        "finalized": "已完成",
        "basis": "報表基準",
        "current_server": "產生時伺服器內的已儲存記錄",
        "box_count": "已記錄票箱數目",
        "counting_applicable": "本站進行點票",
        "yes": "是",
        "no": "否",
        "count_completion": "點票完成時間",
        "not_recorded": "尚未記錄",
        "not_applicable": "不適用（本站送箱至點票站）",
        "generated_at": "產生時間（香港時間）",
        "time_basis": "時間基準",
        "boxes": "票箱目前記錄",
        "empty_boxes": "尚無已記錄的票箱；不代表實際沒有票箱。",
        "box_reference": "票箱識別資料",
        "seal_reference": "封條識別資料",
        "origin": "來源票站",
        "destination": "指定點票站",
        "status": "記錄狀態",
        "revision": "修訂版本",
        "prepared": "已記錄封箱準備",
        "departed": "已記錄離站",
        "received": "已記錄接收",
        "prepared_at": "準備時間（香港時間）",
        "departure_at": "離站時間（香港時間）",
        "receipt_at": "接收時間（香港時間）",
        "event_history": "票箱交收及修正歷史",
        "empty_history": "尚無已儲存的交收事項。",
        "kind": "事項",
        "departure": "票箱離站",
        "receipt": "接收票箱",
        "departure_correction": "修正離站時間",
        "receipt_correction": "修正接收時間",
        "event_at": "實際時間（香港時間）",
        "entered_at": "伺服器記錄時間（香港時間）",
        "actor_id": "記錄職員編號",
        "reason": "修正原因／說明",
        "none": "不適用",
        "milestones": "點票工作事項目前記錄",
        "milestone_history": "點票工作事項修正歷史",
        "empty_milestones": "尚無已儲存的點票工作事項。",
        "conversion_complete": "完成場地轉換",
        "first_box_opening": "開啟第一個票箱",
        "questionable_determination_start": "開始判定問題選票",
        "page": "頁",
    },
    "sc": {
        "title": "票箱交收及点票工作时间表",
        "election": "选举",
        "election_status": "选举状态",
        "constituency": "选区",
        "station": "票站／点票站",
        "draft": "草稿",
        "active": "进行中",
        "finalized": "已完成",
        "basis": "报表基准",
        "current_server": "生成时服务器内的已保存记录",
        "box_count": "已记录票箱数目",
        "counting_applicable": "本站进行点票",
        "yes": "是",
        "no": "否",
        "count_completion": "点票完成时间",
        "not_recorded": "尚未记录",
        "not_applicable": "不适用（本站送箱至点票站）",
        "generated_at": "生成时间（香港时间）",
        "time_basis": "时间基准",
        "boxes": "票箱当前记录",
        "empty_boxes": "尚无已记录的票箱；不代表实际没有票箱。",
        "box_reference": "票箱识别资料",
        "seal_reference": "封条识别资料",
        "origin": "来源票站",
        "destination": "指定点票站",
        "status": "记录状态",
        "revision": "修订版本",
        "prepared": "已记录封箱准备",
        "departed": "已记录离站",
        "received": "已记录接收",
        "prepared_at": "准备时间（香港时间）",
        "departure_at": "离站时间（香港时间）",
        "receipt_at": "接收时间（香港时间）",
        "event_history": "票箱交收及修正历史",
        "empty_history": "尚无已保存的交收事项。",
        "kind": "事项",
        "departure": "票箱离站",
        "receipt": "接收票箱",
        "departure_correction": "修正离站时间",
        "receipt_correction": "修正接收时间",
        "event_at": "实际时间（香港时间）",
        "entered_at": "服务器记录时间（香港时间）",
        "actor_id": "记录职员编号",
        "reason": "修正原因／说明",
        "none": "不适用",
        "milestones": "点票工作事项当前记录",
        "milestone_history": "点票工作事项修正历史",
        "empty_milestones": "尚无已保存的点票工作事项。",
        "conversion_complete": "完成场地转换",
        "first_box_opening": "开启第一个票箱",
        "questionable_determination_start": "开始判定问题选票",
        "page": "页",
    },
    "en": {
        "title": "Ballot-box handover and counting timeline",
        "election": "Election",
        "election_status": "Election status",
        "constituency": "Constituency",
        "station": "Polling / counting station",
        "draft": "Draft",
        "active": "Active",
        "finalized": "Finalized",
        "basis": "Report basis",
        "current_server": "Saved server records at generation time",
        "box_count": "Recorded boxes",
        "counting_applicable": "Counting takes place here",
        "yes": "Yes",
        "no": "No",
        "count_completion": "Count completion time",
        "not_recorded": "Not recorded",
        "not_applicable": "Not applicable (boxes sent to the counting destination)",
        "generated_at": "Generated at (Hong Kong time)",
        "time_basis": "Time basis",
        "boxes": "Current saved boxes",
        "empty_boxes": "No boxes recorded; this does not mean there are no physical boxes.",
        "box_reference": "Box reference",
        "seal_reference": "Seal reference",
        "origin": "Origin polling station",
        "destination": "Designated counting station",
        "status": "Record status",
        "revision": "Revision",
        "prepared": "Preparation recorded",
        "departed": "Departure recorded",
        "received": "Receipt recorded",
        "prepared_at": "Prepared at (Hong Kong time)",
        "departure_at": "Departed at (Hong Kong time)",
        "receipt_at": "Received at (Hong Kong time)",
        "event_history": "Box handover and correction history",
        "empty_history": "No saved handover events.",
        "kind": "Event",
        "departure": "Box departure",
        "receipt": "Box receipt",
        "departure_correction": "Departure correction",
        "receipt_correction": "Receipt correction",
        "event_at": "Occurred at (Hong Kong time)",
        "entered_at": "Server entry time (Hong Kong time)",
        "actor_id": "Recorded by account ID",
        "reason": "Correction reason / note",
        "none": "Not applicable",
        "milestones": "Current counting milestones",
        "milestone_history": "Counting milestone correction history",
        "empty_milestones": "No saved counting milestones.",
        "conversion_complete": "Conversion complete",
        "first_box_opening": "First box opening",
        "questionable_determination_start": "Questionable-paper determination started",
        "page": "Page",
    },
}


def hong_kong_time(value: datetime | str) -> str:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    local = parsed.astimezone(HKT)
    fraction = f".{local.microsecond:06d}" if local.microsecond else ""
    return local.strftime("%Y-%m-%d %H:%M:%S") + fraction + " HKT"


def station_name(value: dict[str, Any]) -> str:
    return f"{value['code']} · {value['name']}"


def metadata_rows(report: dict[str, Any]) -> list[list[str]]:
    labels, scope = report["labels"], report["scope"]
    values = [
        ("election", scope["election"]["name"]),
        ("election_status", labels[scope["election"]["status"]]),
        ("constituency", station_name(scope["constituency"])),
        ("station", station_name(scope["station"])),
        ("basis", labels["current_server"]),
        ("box_count", str(len(report["items"]))),
        ("counting_applicable", labels["yes" if report["counting_applicable"] else "no"]),
        (
            "count_completion",
            hong_kong_time(report["count_completion"])
            if report["count_completion"]
            else labels["not_recorded"]
            if report["counting_applicable"]
            else labels["not_applicable"],
        ),
        ("generated_at", hong_kong_time(report["generated_at"])),
        ("time_basis", "Asia/Hong_Kong (UTC+08:00)"),
    ]
    return [[labels[key], value] for key, value in values]


def report_tables(report: dict[str, Any]) -> list[HistoryTable]:
    labels = report["labels"]
    boxes = {box["id"]: box for box in report["items"]}

    def recorded_time(value: str | None) -> str:
        return hong_kong_time(value) if value else labels["not_recorded"]

    box_keys = (
        "box_reference",
        "seal_reference",
        "origin",
        "destination",
        "status",
        "revision",
        "prepared_at",
        "departure_at",
        "receipt_at",
    )
    box_rows = [
        [labels[key] for key in box_keys],
        *[
            [
                box["box_reference"],
                box["seal_reference"],
                station_name(box["origin"]),
                station_name(box["destination"]),
                labels[box["status"]],
                str(box["revision"]),
                recorded_time(box["prepared_at"]),
                recorded_time(box["departure_at"]),
                recorded_time(box["receipt_at"]),
            ]
            for box in report["items"]
        ],
    ]
    event_keys = (
        "box_reference",
        "origin",
        "revision",
        "kind",
        "event_at",
        "entered_at",
        "actor_id",
        "reason",
    )
    event_rows = [
        [labels[key] for key in event_keys],
        *[
            [
                boxes[row["box_id"]]["box_reference"],
                station_name(boxes[row["box_id"]]["origin"]),
                str(row["revision"]),
                labels[row["kind"]],
                recorded_time(row["event_at"]),
                recorded_time(row["entered_at"]),
                str(row["actor_id"]),
                row["reason"] or labels["none"],
            ]
            for row in report["box_history"]
        ],
    ]
    milestone_keys = (
        "kind",
        "revision",
        "event_at",
        "entered_at",
        "actor_id",
        "box_reference",
        "origin",
        "reason",
    )
    milestone_rows = [
        [labels[key] for key in milestone_keys],
        *[
            [
                labels[row["kind"]],
                str(row["revision"]),
                recorded_time(row["event_at"]),
                recorded_time(row["entered_at"]),
                str(row["actor_id"]),
                boxes[row["box_id"]]["box_reference"] if row["box_id"] else labels["none"],
                station_name(boxes[row["box_id"]]["origin"])
                if row["box_id"]
                else labels["none"],
                row["reason"] or labels["none"],
            ]
            for row in report["milestone_history"]
        ],
    ]
    latest = {row["kind"]: row for row in report["milestones"]}
    current_rows = [[labels["kind"], labels["event_at"], labels["revision"]]]
    if report["counting_applicable"]:
        current_rows += [
            [
                labels[kind],
                recorded_time(latest[kind]["event_at"])
                if kind in latest
                else labels["not_recorded"],
                str(latest[kind]["revision"]) if kind in latest else labels["none"],
            ]
            for kind in MILESTONE_KINDS
        ]
    return [
        HistoryTable(
            labels["boxes"],
            box_rows,
            (0.12, 0.10, 0.115, 0.115, 0.09, 0.065, 0.13, 0.13, 0.135),
            labels["empty_boxes"] if not boxes else "",
            split_in_row=False,
        ),
        HistoryTable(
            labels["event_history"],
            event_rows,
            (0.12, 0.12, 0.06, 0.13, 0.13, 0.13, 0.07, 0.24),
            labels["empty_history"] if not report["box_history"] else "",
        ),
        HistoryTable(
            labels["milestones"],
            current_rows,
            (0.4, 0.4, 0.2),
            labels["not_applicable"] if not report["counting_applicable"] else "",
        ),
        HistoryTable(
            labels["milestone_history"],
            milestone_rows,
            (0.14, 0.06, 0.13, 0.13, 0.07, 0.11, 0.12, 0.24),
            labels["empty_milestones"] if not report["milestone_history"] else "",
        ),
    ]


def preview_lines(report: dict[str, Any]) -> list[str]:
    lines = [report["title"], *[": ".join(row) for row in metadata_rows(report)]]
    for section in report_tables(report):
        lines += ["", section.title, *[" · ".join(row) for row in section.rows]]
        if section.empty_message:
            lines.append(section.empty_message)
    return lines


def csv_report(report: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([report["title"]])
    writer.writerows(metadata_rows(report))
    for section in report_tables(report):
        writer.writerow([])
        writer.writerow([section.title])
        writer.writerows(section.rows)
        if section.empty_message:
            writer.writerow([section.empty_message])
    return output.getvalue().encode("utf-8-sig")


def pdf_report(report: dict[str, Any]) -> bytes:
    labels = report["labels"]
    return history_pdf(
        report["title"],
        metadata_rows(report),
        report_tables(report),
        report["scope"]["station"]["code"] + " · " + labels["current_server"],
        labels["page"],
    )


def box_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/api/workspace/stations/{station_id}/boxes", tags=["Box statements"])
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/statement")
    def statement(
        station_id: int, db: Database, actor: Ready, locale: ReportLocale = "tc"
    ) -> dict[str, Any]:
        snapshot = box_snapshot(db, actor, station_id)
        items = snapshot["items"]
        report = {
            "scope": snapshot["context"],
            "items": items,
            "box_history": [
                box_event_view(event) for event in box_events(db, [row["id"] for row in items])
            ],
            "milestones": snapshot["milestones"],
            "milestone_history": snapshot["milestone_history"],
            "counting_applicable": snapshot["counting_applicable"],
            "count_completion": snapshot["count_completion"],
            "locale": locale,
            "title": LABELS[locale]["title"],
            "labels": LABELS[locale],
            "generated_at": timestamp().replace(tzinfo=UTC),
            "generation_timezone": "Asia/Hong_Kong",
        }
        report["preview_lines"] = preview_lines(report)
        return report

    @router.get("/statement.csv")
    def download_csv(
        station_id: int, db: Database, actor: Ready, locale: ReportLocale = "tc"
    ) -> Response:
        report = statement(station_id, db, actor, locale)
        filename = f"box-handover-{station_id}-{locale}.csv"
        return Response(
            csv_report(report),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/statement.pdf")
    def download_pdf(
        station_id: int, db: Database, actor: Ready, locale: ReportLocale = "tc"
    ) -> Response:
        report = statement(station_id, db, actor, locale)
        filename = f"box-handover-{station_id}-{locale}.pdf"
        return Response(
            pdf_report(report),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
