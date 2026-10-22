"""Selected-revision queue history and freshness statements."""

import csv
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.queue import queue_freshness, queue_snapshot

type ReportLocale = Literal["tc", "sc", "en"]
HKT = timezone(timedelta(hours=8), "HKT")

LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        "title": "輪候觀察及提醒報表",
        "election": "選舉",
        "election_status": "選舉狀態",
        "constituency": "選區",
        "station": "投票站",
        "revision": "修訂版本",
        "revision_state": "版本狀態",
        "current": "目前版本",
        "historical": "歷史版本",
        "status": "觀察狀態",
        "missing": "尚無輪候觀察",
        "fresh": "已記錄；尚未到更新時間",
        "stale": "已到更新時間；輪候狀況尚待確認",
        "draft": "草稿",
        "active": "進行中",
        "finalized": "已完成",
        "band": "輪候時間",
        "under_30": "少於 30 分鐘",
        "30_59": "30–59 分鐘",
        "60_90": "60–90 分鐘",
        "over_90": "超過 90 分鐘",
        "kind": "記錄類別",
        "observation": "輪候觀察",
        "unchanged_confirmation": "確認輪候時間不變",
        "event_id": "記錄編號",
        "event_at": "觀察時間（香港時間）",
        "entered_at": "伺服器記錄時間（香港時間）",
        "actor_id": "記錄職員編號",
        "confirmed_event_id": "確認來源記錄編號",
        "reason": "原因／補充資料",
        "none": "不適用",
        "due_at": "下次更新時間（香港時間）",
        "reminder_due": "需要更新提醒",
        "overdue_periods": "已到期的 30 分鐘時段數",
        "yes": "是",
        "no": "否",
        "history": "輪候觀察歷史（所選版本範圍）",
        "empty_history": "尚無輪候觀察；不可視為沒有輪候人士。",
        "generated_at": "產生時間（香港時間）",
        "time_basis": "時間基準",
        "page": "頁",
    },
    "sc": {
        "title": "轮候观察及提醒报表",
        "election": "选举",
        "election_status": "选举状态",
        "constituency": "选区",
        "station": "投票站",
        "revision": "修订版本",
        "revision_state": "版本状态",
        "current": "当前版本",
        "historical": "历史版本",
        "status": "观察状态",
        "missing": "尚无轮候观察",
        "fresh": "已记录；尚未到更新时间",
        "stale": "已到更新时间；轮候状况尚待确认",
        "draft": "草稿",
        "active": "进行中",
        "finalized": "已完成",
        "band": "轮候时间",
        "under_30": "少于 30 分钟",
        "30_59": "30–59 分钟",
        "60_90": "60–90 分钟",
        "over_90": "超过 90 分钟",
        "kind": "记录类别",
        "observation": "轮候观察",
        "unchanged_confirmation": "确认轮候时间不变",
        "event_id": "记录编号",
        "event_at": "观察时间（香港时间）",
        "entered_at": "服务器记录时间（香港时间）",
        "actor_id": "记录职员编号",
        "confirmed_event_id": "确认来源记录编号",
        "reason": "原因／补充资料",
        "none": "不适用",
        "due_at": "下次更新时间（香港时间）",
        "reminder_due": "需要更新提醒",
        "overdue_periods": "已到期的 30 分钟时段数",
        "yes": "是",
        "no": "否",
        "history": "轮候观察历史（所选版本范围）",
        "empty_history": "尚无轮候观察；不可视为没有轮候人士。",
        "generated_at": "生成时间（香港时间）",
        "time_basis": "时间基准",
        "page": "页",
    },
    "en": {
        "title": "Queue observations and reminders",
        "election": "Election",
        "election_status": "Election status",
        "constituency": "Constituency",
        "station": "Polling station",
        "revision": "Revision",
        "revision_state": "Revision state",
        "current": "Current revision",
        "historical": "Historical revision",
        "status": "Observation status",
        "missing": "No queue observation recorded",
        "fresh": "Recorded; update not yet due",
        "stale": "Update due; current queue remains unconfirmed",
        "draft": "Draft",
        "active": "Active",
        "finalized": "Finalized",
        "band": "Waiting time",
        "under_30": "Under 30 minutes",
        "30_59": "30–59 minutes",
        "60_90": "60–90 minutes",
        "over_90": "Over 90 minutes",
        "kind": "Record type",
        "observation": "Queue observation",
        "unchanged_confirmation": "Waiting time confirmed unchanged",
        "event_id": "Event ID",
        "event_at": "Observed at (Hong Kong time)",
        "entered_at": "Server entry time (Hong Kong time)",
        "actor_id": "Recorded by account ID",
        "confirmed_event_id": "Confirmed source event ID",
        "reason": "Reason / details",
        "none": "Not applicable",
        "due_at": "Next update due (Hong Kong time)",
        "reminder_due": "Update reminder due",
        "overdue_periods": "Elapsed 30-minute update periods",
        "yes": "Yes",
        "no": "No",
        "history": "Queue observation history (selected revision)",
        "empty_history": "No queue observation recorded; this does not mean there is no queue.",
        "generated_at": "Generated at (Hong Kong time)",
        "time_basis": "Time basis",
        "page": "Page",
    },
}


def hong_kong_time(value: datetime | str) -> str:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    local = parsed.astimezone(HKT)
    fraction = f".{local.microsecond:06d}" if local.microsecond else ""
    return local.strftime("%Y-%m-%d %H:%M:%S") + fraction + " HKT"


def metadata_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels, scope, current = projection["labels"], projection["scope"], projection["current"]
    status = (
        "missing" if projection["missing"] else "stale" if projection["reminder_due"] else "fresh"
    )
    values = [
        ("election", scope["election"]["name"]),
        ("election_status", labels[scope["election"]["status"]]),
        ("constituency", scope["constituency"]["code"] + " · " + scope["constituency"]["name"]),
        ("station", scope["station"]["code"] + " · " + scope["station"]["name"]),
        ("revision", str(projection["revision"])),
        ("revision_state", labels[projection["revision_state"]]),
        ("status", labels[status]),
        ("band", labels[current["band"]] if current else labels["missing"]),
        ("event_id", str(current["id"]) if current else labels["none"]),
        ("event_at", hong_kong_time(current["event_at"]) if current else labels["none"]),
        ("entered_at", hong_kong_time(current["entered_at"]) if current else labels["none"]),
        ("actor_id", str(current["actor_id"]) if current else labels["none"]),
        ("due_at", hong_kong_time(projection["due_at"]) if current else labels["none"]),
        ("reminder_due", labels["yes" if projection["reminder_due"] else "no"]),
        ("overdue_periods", str(projection["overdue_periods"])),
        ("generated_at", hong_kong_time(projection["generated_at"])),
        ("time_basis", "Asia/Hong_Kong (UTC+08:00)"),
    ]
    return [[labels[key], value] for key, value in values]


def history_rows(projection: dict[str, Any]) -> list[list[str]]:
    labels = projection["labels"]
    keys = (
        "event_id",
        "revision",
        "kind",
        "band",
        "event_at",
        "entered_at",
        "actor_id",
        "confirmed_event_id",
        "reason",
    )
    return [
        [labels[key] for key in keys],
        *[
            [
                str(row["id"]),
                str(row["revision"]),
                labels[row["kind"]],
                labels[row["band"]],
                hong_kong_time(row["event_at"]),
                hong_kong_time(row["entered_at"]),
                str(row["actor_id"]),
                str(row["confirmed_event_id"]) if row["confirmed_event_id"] else labels["none"],
                row["reason"] or labels["none"],
            ]
            for row in projection["items"]
        ],
    ]


def preview_lines(projection: dict[str, Any]) -> list[str]:
    labels = projection["labels"]
    lines = [
        projection["title"],
        *[": ".join(row) for row in metadata_rows(projection)],
        "",
        labels["history"],
    ]
    if projection["missing"]:
        lines.append(labels["empty_history"])
    else:
        lines.extend(" · ".join(row) for row in history_rows(projection))
    return lines


def csv_report(projection: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([projection["title"]])
    writer.writerows(metadata_rows(projection))
    writer.writerow([])
    writer.writerow([projection["labels"]["history"]])
    writer.writerows(history_rows(projection))
    if projection["missing"]:
        writer.writerow([projection["labels"]["empty_history"]])
    return output.getvalue().encode("utf-8-sig")


def pdf_report(projection: dict[str, Any]) -> bytes:
    labels = projection["labels"]
    footer = (
        projection["scope"]["station"]["code"]
        + " · "
        + labels["revision"]
        + " "
        + str(projection["revision"])
        + " · "
        + labels[projection["revision_state"]]
    )
    section = HistoryTable(
        labels["history"],
        history_rows(projection),
        (0.055, 0.055, 0.13, 0.105, 0.16, 0.16, 0.065, 0.08, 0.19),
        labels["empty_history"] if projection["missing"] else "",
    )
    return history_pdf(
        projection["title"], metadata_rows(projection), [section], footer, labels["page"]
    )


def queue_reports_router(
    database: Callable[[], Generator[Session]],
    ready_account: Callable[..., Account],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/queue", tags=["Queue statements"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    @router.get("/statement")
    def statement(
        station_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=0)],
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        generated_at = timestamp().replace(tzinfo=UTC)
        snapshot = queue_snapshot(db, actor, station_id, generated_at)
        if revision > snapshot["revision"]:
            raise HTTPException(404, detail={"code": "queue_revision_not_found"})
        items = [row for row in snapshot["items"] if row["revision"] <= revision]
        current = max(
            items,
            key=lambda row: (datetime.fromisoformat(row["event_at"]), row["revision"]),
            default=None,
        )
        event_at = datetime.fromisoformat(current["event_at"]) if current else None
        projection = {
            "scope": snapshot["context"],
            "items": items,
            "current": current,
            "revision": revision,
            "revision_state": "current" if revision == snapshot["revision"] else "historical",
            **queue_freshness(event_at, generated_at),
            "title": LABELS[locale]["title"],
            "labels": LABELS[locale],
            "locale": locale,
            "generated_at": generated_at,
            "generation_timezone": "Asia/Hong_Kong",
        }
        projection["preview_lines"] = preview_lines(projection)
        return projection

    @router.get("/statement.csv")
    def download_csv(
        station_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=0)],
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, db, actor, revision, locale)
        filename = f"queue-history-{station_id}-r{revision}-{locale}.csv"
        return Response(
            csv_report(projection),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/statement.pdf")
    def download_pdf(
        station_id: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=0)],
        locale: ReportLocale = "tc",
    ) -> Response:
        projection = statement(station_id, db, actor, revision, locale)
        filename = f"queue-history-{station_id}-r{revision}-{locale}.pdf"
        return Response(
            pdf_report(projection),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
