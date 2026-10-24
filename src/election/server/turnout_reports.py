"""Saved P(15) station overviews and exact period-revision statements."""

import csv
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.polling import as_utc, station_scope
from election.server.turnout import (
    approved_prefix,
    current_records,
    period_bounds,
    period_count,
    turnout_record_view,
)
from election.server.turnout_basis import locked_schedule
from election.server.turnout_models import TurnoutRecord

type ReportLocale = Literal["tc", "sc", "en"]
HKT = timezone(timedelta(hours=8), "HKT")
LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        "title": "P(15) 時段及累計投票人數報表",
        "election": "選舉",
        "election_status": "選舉狀態",
        "constituency": "選區",
        "station": "投票站",
        "report_scope": "報表基準",
        "basis_note": "報表涵蓋說明",
        "station_current": "伺服器目前已儲存的本站 P(15)",
        "period_revision": "所選已儲存時段版本",
        "current": "目前版本",
        "historical": "歷史版本",
        "revision_state": "版本狀態",
        "draft": "草稿",
        "submitted": "已提交待確認",
        "approved": "已確認",
        "active": "進行中",
        "finalized": "已完成",
        "not_recorded": "尚未記錄",
        "yes": "是",
        "no": "否",
        "field": "項目",
        "value": "內容",
        "period_index": "時段編號",
        "window": "涵蓋時段（香港時間）",
        "status": "原版本狀態",
        "revision": "修訂版本",
        "validity": "目前確認有效性",
        "valid": "有效確認",
        "needs_review": "須重新覆核",
        "not_approved": "未納入有效確認",
        "historical_not_current": "歷史版本，不屬目前確認範圍",
        "period_count": "已設定時段總數",
        "saved_period_count": "已儲存時段數",
        "missing_period_count": "尚無記錄的時段數",
        "approved_periods": "連續有效確認時段數",
        "approved_total": "有效確認範圍的累計人數",
        "covered_until": "有效確認至（香港時間）",
        "coverage_legend": (
            "只計入從首時段開始連續且有效的主管確認；缺漏、草稿及須重新覆核的資料不當作零加入。"
            "下表只列已儲存時段。"
        ),
        "period_legend": (
            "本報表保留所選已儲存版本的數字及原有確認資料，不包含目前全站累計或未儲存內容。"
        ),
        "overview": "已儲存時段概覽",
        "details": "時段版本詳情",
        "empty": "尚無已儲存時段；這不代表投票人數為零。",
        "schedule_revision": "時間表版本",
        "planned_opening_at": "計劃開站（香港時間）",
        "planned_closing_at": "計劃關站（香港時間）",
        "reporting_interval_minutes": "報告間隔（分鐘）",
        "id": "記錄編號",
        "start_at": "時段開始（香港時間）",
        "end_at": "時段結束（香港時間）",
        "supplied_hourly": "外部提供的本時段人數",
        "supplied_cumulative": "外部提供的時段末累計人數",
        "derived_hourly": "確認時計算的本時段人數",
        "derived_cumulative_start": "確認時起始累計基礎",
        "derived_cumulative_end": "確認時計算的結束累計",
        "source_context": "外部來源及涵蓋資料",
        "provenance": "數字來源類別",
        "external_manual": "人工提供的外部數字",
        "event_at": "原始事件時間（香港時間）",
        "entered_at": "伺服器記錄時間（香港時間）",
        "actor_id": "記錄職員編號",
        "submitted_at": "提交時間（香港時間）",
        "submitted_by": "提交職員編號",
        "approved_at": "原確認時間（香港時間）",
        "approved_by": "原確認主管編號",
        "amendment_reason": "修訂原因",
        "basis_predecessor_record_id": "前一確認基礎記錄編號",
        "basis_predecessor_revision": "前一確認基礎修訂版本",
        "generated_at": "產生時間（香港時間）",
        "time_basis": "時間基準",
        "page": "頁",
    },
    "sc": {
        "title": "P(15) 时段及累计投票人数报表",
        "election": "选举",
        "election_status": "选举状态",
        "constituency": "选区",
        "station": "投票站",
        "report_scope": "报表依据",
        "basis_note": "报表覆盖说明",
        "station_current": "服务器当前已保存的本站 P(15)",
        "period_revision": "所选已保存时段版本",
        "current": "当前版本",
        "historical": "历史版本",
        "revision_state": "版本状态",
        "draft": "草稿",
        "submitted": "已提交待确认",
        "approved": "已确认",
        "active": "进行中",
        "finalized": "已完成",
        "not_recorded": "尚未记录",
        "yes": "是",
        "no": "否",
        "field": "项目",
        "value": "内容",
        "period_index": "时段编号",
        "window": "覆盖时段（香港时间）",
        "status": "原版本状态",
        "revision": "修订版本",
        "validity": "当前确认有效性",
        "valid": "有效确认",
        "needs_review": "须重新复核",
        "not_approved": "未纳入有效确认",
        "historical_not_current": "历史版本，不属于当前确认范围",
        "period_count": "已设定时段总数",
        "saved_period_count": "已保存时段数",
        "missing_period_count": "尚无记录的时段数",
        "approved_periods": "连续有效确认时段数",
        "approved_total": "有效确认范围的累计人数",
        "covered_until": "有效确认至（香港时间）",
        "coverage_legend": (
            "只计入从首时段开始连续且有效的主管确认；缺漏、草稿及须重新复核的资料不当作零加入。"
            "下表只列已保存时段。"
        ),
        "period_legend": (
            "本报表保留所选已保存版本的数字及原有确认资料，不包含当前全站累计或未保存内容。"
        ),
        "overview": "已保存时段概览",
        "details": "时段版本详情",
        "empty": "尚无已保存时段；这不代表投票人数为零。",
        "schedule_revision": "时间表版本",
        "planned_opening_at": "计划开站（香港时间）",
        "planned_closing_at": "计划关站（香港时间）",
        "reporting_interval_minutes": "报告间隔（分钟）",
        "id": "记录编号",
        "start_at": "时段开始（香港时间）",
        "end_at": "时段结束（香港时间）",
        "supplied_hourly": "外部提供的本时段人数",
        "supplied_cumulative": "外部提供的时段末累计人数",
        "derived_hourly": "确认时计算的本时段人数",
        "derived_cumulative_start": "确认时起始累计基础",
        "derived_cumulative_end": "确认时计算的结束累计",
        "source_context": "外部来源及覆盖资料",
        "provenance": "数字来源类别",
        "external_manual": "人工提供的外部数字",
        "event_at": "原始事件时间（香港时间）",
        "entered_at": "服务器记录时间（香港时间）",
        "actor_id": "记录职员编号",
        "submitted_at": "提交时间（香港时间）",
        "submitted_by": "提交职员编号",
        "approved_at": "原确认时间（香港时间）",
        "approved_by": "原确认主管编号",
        "amendment_reason": "修订原因",
        "basis_predecessor_record_id": "前一确认基础记录编号",
        "basis_predecessor_revision": "前一确认基础修订版本",
        "generated_at": "生成时间（香港时间）",
        "time_basis": "时间依据",
        "page": "页",
    },
    "en": {
        "title": "P(15) period and cumulative turnout",
        "election": "Election",
        "election_status": "Election status",
        "constituency": "Constituency",
        "station": "Polling station",
        "report_scope": "Report basis",
        "basis_note": "Coverage and revision note",
        "station_current": "Current saved station P(15)",
        "period_revision": "Selected saved period revision",
        "current": "Current revision",
        "historical": "Historical revision",
        "revision_state": "Revision state",
        "draft": "Draft",
        "submitted": "Submitted for review",
        "approved": "Approved",
        "active": "Active",
        "finalized": "Finalized",
        "not_recorded": "Not recorded",
        "yes": "Yes",
        "no": "No",
        "field": "Field",
        "value": "Value",
        "period_index": "Period",
        "window": "Covered interval (HKT)",
        "status": "Original revision status",
        "revision": "Revision",
        "validity": "Current approval validity",
        "valid": "Valid approval",
        "needs_review": "Renewed review required",
        "not_approved": "Outside valid approved coverage",
        "historical_not_current": "Historical, outside current coverage",
        "period_count": "Configured period count",
        "saved_period_count": "Saved period count",
        "missing_period_count": "Periods with no saved record",
        "approved_periods": "Continuous valid approved periods",
        "approved_total": "Cumulative turnout within valid approved coverage",
        "covered_until": "Approved coverage ends at (HKT)",
        "coverage_legend": (
            "Only consecutive still-valid Supervisor approvals from the first period contribute. "
            "Missing, draft and invalidated periods are not added as zero. "
            "Only saved periods are listed below."
        ),
        "period_legend": (
            "This statement retains the selected saved revision's figures and original "
            "approval metadata. Current station totals and unsaved input are excluded."
        ),
        "overview": "Saved period overview",
        "details": "Period revision details",
        "empty": "No period has been saved. This does not mean turnout is zero.",
        "schedule_revision": "Schedule revision",
        "planned_opening_at": "Planned opening (HKT)",
        "planned_closing_at": "Planned closing (HKT)",
        "reporting_interval_minutes": "Report interval (minutes)",
        "id": "Record ID",
        "start_at": "Period start (HKT)",
        "end_at": "Period end (HKT)",
        "supplied_hourly": "Externally supplied period turnout",
        "supplied_cumulative": "Externally supplied cumulative turnout",
        "derived_hourly": "Period turnout derived at approval",
        "derived_cumulative_start": "Starting cumulative basis at approval",
        "derived_cumulative_end": "Ending cumulative turnout derived at approval",
        "source_context": "External source and coverage context",
        "provenance": "Figure provenance",
        "external_manual": "Manually supplied external figures",
        "event_at": "Original event time (HKT)",
        "entered_at": "Server entry time (HKT)",
        "actor_id": "Recorded by account ID",
        "submitted_at": "Submitted at (HKT)",
        "submitted_by": "Submitted by account ID",
        "approved_at": "Original approval time (HKT)",
        "approved_by": "Original approving account ID",
        "amendment_reason": "Reason for amendment",
        "basis_predecessor_record_id": "Preceding approved basis record ID",
        "basis_predecessor_revision": "Preceding approved basis revision",
        "generated_at": "Generated at (HKT)",
        "time_basis": "Time basis",
        "page": "Page",
    },
}


def hong_kong_time(value: datetime | str) -> str:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    utc = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    fraction = f".{utc.microsecond:06d}" if utc.microsecond else ""
    try:
        local = utc.astimezone(HKT)
        return local.strftime("%Y-%m-%d %H:%M:%S") + fraction + " HKT"
    except OverflowError:
        # UTC's final representable day can become 10000-01-01 in HKT. The fixed
        # eight-hour offset crosses only that one day; preserve the configured time.
        seconds = utc.hour * 3600 + utc.minute * 60 + utc.second + 8 * 3600 - 86400
        hour, remainder = divmod(seconds, 3600)
        minute, second = divmod(remainder, 60)
        return f"10000-01-01 {hour:02d}:{minute:02d}:{second:02d}{fraction} HKT"


def amount(value: Any, labels: dict[str, str]) -> str:
    return labels["not_recorded"] if value is None else str(value)


def validity(row: dict[str, Any], labels: dict[str, str]) -> str:
    return labels[
        "historical_not_current"
        if not row["is_current"]
        else "valid"
        if row["approval_valid"]
        else "needs_review"
        if row["review_required"]
        else "not_approved"
    ]


def metadata_rows(report: dict[str, Any]) -> list[list[str]]:
    labels, scope, schedule = report["labels"], report["scope"], report["schedule"]
    values = [
        ("report_scope", labels[report["report_scope"]]),
        ("election", scope["election"]["name"]),
        ("election_status", labels[scope["election"]["status"]]),
        ("constituency", scope["constituency"]["code"] + " · " + scope["constituency"]["name"]),
        ("station", scope["station"]["code"] + " · " + scope["station"]["name"]),
    ]
    if report["report_scope"] == "station_current":
        prefix = report["approved_prefix"]
        values += [
            ("period_count", str(report["period_count"])),
            ("saved_period_count", str(report["saved_period_count"])),
            ("missing_period_count", str(report["missing_period_count"])),
            ("approved_periods", str(prefix["periods"])),
            ("approved_total", amount(prefix["cumulative_end"], labels)),
            (
                "covered_until",
                hong_kong_time(prefix["covered_until"])
                if prefix["covered_until"]
                else labels["not_recorded"],
            ),
            ("schedule_revision", str(schedule["revision"])),
            ("planned_opening_at", hong_kong_time(schedule["planned_opening_at"])),
            ("planned_closing_at", hong_kong_time(schedule["planned_closing_at"])),
            ("reporting_interval_minutes", str(schedule["reporting_interval_minutes"])),
        ]
    else:
        values += [
            ("period_index", str(report["selected_period"])),
            ("revision", str(report["revision"])),
            ("revision_state", labels[report["revision_state"]]),
            ("schedule_revision", str(schedule["revision"])),
        ]
    values += [
        (
            "basis_note",
            labels[
                "coverage_legend"
                if report["report_scope"] == "station_current"
                else "period_legend"
            ],
        ),
        ("generated_at", hong_kong_time(report["generated_at"])),
        ("time_basis", "Asia/Hong_Kong (UTC+08:00)"),
    ]
    return [[labels[key], value] for key, value in values]


def report_tables(report: dict[str, Any]) -> list[HistoryTable]:
    labels = report["labels"]
    overview = [
        [
            labels[key]
            for key in (
                "period_index",
                "window",
                "status",
                "revision",
                "validity",
                "derived_hourly",
                "derived_cumulative_end",
            )
        ]
    ]
    for row in report["items"]:
        overview.append(
            [
                str(row["period_index"]),
                hong_kong_time(row["start_at"]) + "\n" + hong_kong_time(row["end_at"]),
                labels[row["status"]],
                str(row["revision"]),
                validity(row, labels),
                amount(row["derived_hourly"], labels),
                amount(row["derived_cumulative_end"], labels),
            ]
        )
    sections = [
        HistoryTable(
            labels["overview"],
            overview,
            (0.075, 0.24, 0.10, 0.065, 0.13, 0.195, 0.195),
            labels["empty"] if not report["items"] else "",
            split_in_row=False,
        )
    ]
    keys = (
        "id",
        "period_index",
        "revision",
        "status",
        "schedule_revision",
        "start_at",
        "end_at",
        "supplied_hourly",
        "supplied_cumulative",
        "derived_hourly",
        "derived_cumulative_start",
        "derived_cumulative_end",
        "provenance",
        "source_context",
        "event_at",
        "entered_at",
        "actor_id",
        "submitted_at",
        "submitted_by",
        "approved_at",
        "approved_by",
        "amendment_reason",
        "basis_predecessor_record_id",
        "basis_predecessor_revision",
    )
    time_keys = {"start_at", "end_at", "event_at", "entered_at", "submitted_at", "approved_at"}
    for row in report["items"]:
        identity = (
            labels["details"]
            + " · "
            + labels["period_index"]
            + " "
            + str(row["period_index"])
            + " · "
            + labels["revision"]
            + " "
            + str(row["revision"])
        )
        # Keep the period identity inside the repeated table header. A separate
        # heading can be stranded above a table that continues on the next page.
        details = [
            [labels["field"] + "\n" + identity, labels["value"]],
            [labels["validity"], validity(row, labels)],
        ]
        for key in keys:
            value = row[key]
            text = (
                labels["not_recorded"]
                if value is None or value == ""
                else hong_kong_time(value)
                if key in time_keys
                else labels[value]
                if key in ("status", "provenance")
                else str(value)
            )
            details.append([labels[key], text])
        sections.append(HistoryTable("", details, (0.32, 0.68)))
    return sections


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
    writer.writerows(
        [
            [report["title"]],
            *metadata_rows(report),
        ]
    )
    for section in report_tables(report):
        writer.writerows([[], [section.title], *section.rows])
        if section.empty_message:
            writer.writerow([section.empty_message])
    return output.getvalue().encode("utf-8-sig")


def pdf_report(report: dict[str, Any]) -> bytes:
    return history_pdf(
        report["title"],
        metadata_rows(report),
        report_tables(report),
        report["scope"]["station"]["code"] + " · " + report["labels"][report["report_scope"]],
        report["labels"]["page"],
    )


def turnout_reports_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/turnout", tags=["Turnout statements"]
    )
    Database = Annotated[Session, Depends(database)]
    Ready = Annotated[Account, Depends(ready_account)]

    def projection(
        station_id: int,
        db: Session,
        actor: Account,
        locale: ReportLocale,
        *,
        index: int | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        station, constituency, election = station_scope(db, actor, station_id)
        schedule = locked_schedule(db, election.id)
        records = current_records(db, station_id)
        prefix, valid = approved_prefix(records, schedule)
        if index is None:
            rows = [records[key] for key in sorted(records)]
        else:
            row = db.scalar(
                select(TurnoutRecord)
                .where(
                    TurnoutRecord.station_id == station_id,
                    TurnoutRecord.period_index == index,
                    TurnoutRecord.revision == revision,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                period_bounds(schedule, index)
                raise HTTPException(404, detail={"code": "turnout_record_not_found"})
            rows = [row]
        items = []
        for row in rows:
            is_current = records[row.period_index].id == row.id
            items.append(
                {
                    **turnout_record_view(row),
                    "is_current": is_current,
                    "approval_valid": is_current and row.id in valid,
                    "review_required": is_current
                    and row.status == "approved"
                    and row.id not in valid,
                }
            )
        count = period_count(schedule)
        now = timestamp()
        generated_at = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
        report = {
            "scope": {
                "election": {"id": election.id, "name": election.name, "status": election.status},
                "constituency": {
                    "id": constituency.id,
                    "code": constituency.code,
                    "name": constituency.name,
                },
                "station": {"id": station.id, "code": station.code, "name": station.name},
            },
            "schedule": {
                "revision": schedule.revision if index is None else rows[0].schedule_revision,
                **(
                    {
                        "planned_opening_at": as_utc(schedule.planned_opening_at),
                        "planned_closing_at": as_utc(schedule.planned_closing_at),
                        "reporting_interval_minutes": schedule.reporting_interval_minutes,
                    }
                    if index is None
                    else {
                        "period_start_at": as_utc(rows[0].start_at),
                        "period_end_at": as_utc(rows[0].end_at),
                    }
                ),
            },
            "report_scope": "station_current" if index is None else "period_revision",
            "selected_period": index,
            "revision": revision,
            "revision_state": "current"
            if index is None or items[0]["is_current"]
            else "historical",
            "items": items,
            "approved_prefix": prefix if index is None else None,
            "period_count": count if index is None else None,
            "saved_period_count": len(records) if index is None else None,
            "missing_period_count": max(0, count - sum(1 for key in records if 1 <= key <= count))
            if index is None
            else None,
            "title": LABELS[locale]["title"],
            "labels": LABELS[locale],
            "locale": locale,
            "generated_at": generated_at,
            "generation_timezone": "Asia/Hong_Kong",
        }
        report["preview_lines"] = preview_lines(report)
        return report

    @router.get("/statement")
    def station_statement(
        station_id: int, db: Database, actor: Ready, locale: ReportLocale = "tc"
    ) -> dict[str, Any]:
        return projection(station_id, db, actor, locale)

    @router.get("/{period_index}/statement")
    def period_statement(
        station_id: int,
        period_index: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> dict[str, Any]:
        return projection(station_id, db, actor, locale, index=period_index, revision=revision)

    def exported(report: dict[str, Any], format: str, station_id: int) -> Response:
        name = (
            f"turnout-station-{station_id}"
            if report["report_scope"] == "station_current"
            else f"turnout-period-{station_id}-{report['selected_period']}-r{report['revision']}"
        )
        return Response(
            csv_report(report) if format == "csv" else pdf_report(report),
            media_type="text/csv; charset=utf-8" if format == "csv" else "application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{name}-{report["locale"]}.{format}"'
            },
        )

    @router.get("/statement.csv")
    def station_csv(
        station_id: int, db: Database, actor: Ready, locale: ReportLocale = "tc"
    ) -> Response:
        return exported(projection(station_id, db, actor, locale), "csv", station_id)

    @router.get("/statement.pdf")
    def station_pdf(
        station_id: int, db: Database, actor: Ready, locale: ReportLocale = "tc"
    ) -> Response:
        return exported(projection(station_id, db, actor, locale), "pdf", station_id)

    @router.get("/{period_index}/statement.csv")
    def period_csv(
        station_id: int,
        period_index: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> Response:
        return exported(
            projection(station_id, db, actor, locale, index=period_index, revision=revision),
            "csv",
            station_id,
        )

    @router.get("/{period_index}/statement.pdf")
    def period_pdf(
        station_id: int,
        period_index: int,
        db: Database,
        actor: Ready,
        revision: Annotated[int, Query(ge=1)],
        locale: ReportLocale = "tc",
    ) -> Response:
        return exported(
            projection(station_id, db, actor, locale, index=period_index, revision=revision),
            "pdf",
            station_id,
        )

    return router
