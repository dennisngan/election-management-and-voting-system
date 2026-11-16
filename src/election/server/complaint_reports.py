"""Saved received-cohort statements with immutable case membership."""

import csv
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from election.server.complaint_periods import (
    case_cohorts,
    complaint_period_view,
    current_basis,
    current_complaint_cases,
    period_members,
    period_records,
    required_bounds,
)
from election.server.complaints import complaint_read_scope, complaint_schedule
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.models import Account
from election.server.reporting_periods import period_count
from election.server.timestamps import as_utc

type ReportLocale = Literal["tc", "sc", "en"]
HKT = timezone(timedelta(hours=8), "HKT")
LABELS: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        "title": "投訴時段統計報表",
        "election": "選舉",
        "election_status": "選舉狀態",
        "constituency": "選區",
        "station": "投票站",
        "report_scope": "報表基準",
        "basis_note": "報表涵蓋說明",
        "station_current": "伺服器目前已儲存的本站報表",
        "period_revision": "所選已儲存時段版本",
        "revision_state": "版本狀態",
        "current": "目前版本",
        "historical": "歷史版本",
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
        "window": "收到時間範圍（香港時間）",
        "status": "原版本狀態",
        "revision": "修訂版本",
        "basis_current": "目前個案基礎是否相符",
        "validity": "目前確認有效性",
        "valid": "有效確認",
        "needs_review": "須重新覆核",
        "not_approved": "未納入有效確認",
        "historical_not_current": "歷史版本，不屬目前確認範圍",
        "required": "已設定時段總數",
        "saved_period_count": "已儲存時段數",
        "missing": "尚無記錄的時段數",
        "approved_current": "目前有效確認時段數",
        "outside_coverage_case_count": "已設定時間範圍外的目前個案數",
        "coverage_legend": (
            "只列已儲存時段。缺漏不當作零；只有個案基礎仍相符的目前主管確認才有效。"
            "每個時段按收到時間 [開始, 結束) 分組，工作狀態以準備統計時為準。"
        ),
        "period_legend": (
            "保留所選版本準備時的個案、分類名稱、工作狀態及原確認資料；收到時間按 "
            "[開始, 結束) 分組。不包含目前全站摘要或未儲存內容。"
        ),
        "overview": "已儲存時段概覽",
        "details": "時段版本詳情",
        "empty": "尚無已儲存時段；這不代表投訴數為零。",
        "groups": "凍結分類統計",
        "members": "凍結個案明細",
        "empty_groups": "此已儲存版本明確記錄零宗投訴。",
        "schedule_revision": "時間表版本",
        "planned_opening_at": "計劃開站（香港時間）",
        "planned_closing_at": "計劃關站（香港時間）",
        "reporting_interval_minutes": "報告間隔（分鐘）",
        "id": "記錄編號",
        "start_at": "時段開始（香港時間）",
        "end_at": "時段結束（香港時間）",
        "basis_at": "凍結統計基礎時間（香港時間）",
        "total_received": "收到投訴數",
        "total_completed": "已完成投訴數",
        "total_in_progress": "處理中投訴數",
        "entered_at": "伺服器記錄時間（香港時間）",
        "actor_id": "記錄職員編號",
        "submitted_at": "提交時間（香港時間）",
        "submitted_by": "提交職員編號",
        "approved_at": "原確認時間（香港時間）",
        "approved_by": "原確認主管編號",
        "amendment_reason": "修訂原因",
        "category_id": "分類編號",
        "category_revision_id": "分類版本記錄編號",
        "category_revision": "分類修訂版本",
        "code": "分類代碼",
        "label_en": "凍結英文名稱",
        "label_tc": "凍結繁體中文名稱",
        "label_sc": "凍結簡體中文名稱",
        "verified_source": "已核實參考來源",
        "source": "分類來源",
        "verified_reference": "已核實參考分類",
        "project_configured": "項目自訂分類",
        "source_english": "參考來源英文原文",
        "reference_page": "參考頁碼",
        "is_other": "其他分類（須解釋）",
        "translation_provenance": "翻譯來源",
        "project_translation": "項目翻譯",
        "case_id": "個案編號",
        "case_revision_id": "個案版本記錄編號",
        "case_reference": "投訴參考編號",
        "received_at": "收到時間（香港時間）",
        "work_status": "凍結工作狀態",
        "completed_at": "完成時間（香港時間）",
        "in_progress": "處理中",
        "completed": "已完成",
        "category_code": "凍結分類代碼",
        "category_label_en": "凍結分類英文名稱",
        "category_label_tc": "凍結分類繁體中文名稱",
        "category_label_sc": "凍結分類簡體中文名稱",
        "generated_at": "產生時間（香港時間）",
        "time_basis": "時間基準",
        "page": "頁",
    },
    "sc": {
        "title": "投诉时段统计报表",
        "election": "选举",
        "election_status": "选举状态",
        "constituency": "选区",
        "station": "投票站",
        "report_scope": "报表依据",
        "basis_note": "报表覆盖说明",
        "station_current": "服务器当前已保存的本站报表",
        "period_revision": "所选已保存时段版本",
        "revision_state": "版本状态",
        "current": "当前版本",
        "historical": "历史版本",
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
        "window": "收到时间范围（香港时间）",
        "status": "原版本状态",
        "revision": "修订版本",
        "basis_current": "当前个案依据是否相符",
        "validity": "当前确认有效性",
        "valid": "有效确认",
        "needs_review": "须重新复核",
        "not_approved": "未纳入有效确认",
        "historical_not_current": "历史版本，不属于当前确认范围",
        "required": "已设定时段总数",
        "saved_period_count": "已保存时段数",
        "missing": "尚无记录的时段数",
        "approved_current": "当前有效确认时段数",
        "outside_coverage_case_count": "已设定时间范围外的当前个案数",
        "coverage_legend": (
            "只列已保存时段。缺漏不当作零；只有个案依据仍相符的当前主管确认才有效。"
            "每个时段按收到时间 [开始, 结束) 分组，工作状态以准备统计时为准。"
        ),
        "period_legend": (
            "保留所选版本准备时的个案、分类名称、工作状态及原确认资料；收到时间按 "
            "[开始, 结束) 分组。不包含当前全站摘要或未保存内容。"
        ),
        "overview": "已保存时段概览",
        "details": "时段版本详情",
        "empty": "尚无已保存时段；这不代表投诉数为零。",
        "groups": "冻结分类统计",
        "members": "冻结个案明细",
        "empty_groups": "此已保存版本明确记录零宗投诉。",
        "schedule_revision": "时间表版本",
        "planned_opening_at": "计划开站（香港时间）",
        "planned_closing_at": "计划关站（香港时间）",
        "reporting_interval_minutes": "报告间隔（分钟）",
        "id": "记录编号",
        "start_at": "时段开始（香港时间）",
        "end_at": "时段结束（香港时间）",
        "basis_at": "冻结统计依据时间（香港时间）",
        "total_received": "收到投诉数",
        "total_completed": "已完成投诉数",
        "total_in_progress": "处理中投诉数",
        "entered_at": "服务器记录时间（香港时间）",
        "actor_id": "记录职员编号",
        "submitted_at": "提交时间（香港时间）",
        "submitted_by": "提交职员编号",
        "approved_at": "原确认时间（香港时间）",
        "approved_by": "原确认主管编号",
        "amendment_reason": "修订原因",
        "category_id": "分类编号",
        "category_revision_id": "分类版本记录编号",
        "category_revision": "分类修订版本",
        "code": "分类代码",
        "label_en": "冻结英文名称",
        "label_tc": "冻结繁体中文名称",
        "label_sc": "冻结简体中文名称",
        "verified_source": "已核实参考来源",
        "source": "分类来源",
        "verified_reference": "已核实参考分类",
        "project_configured": "项目自定义分类",
        "source_english": "参考来源英文原文",
        "reference_page": "参考页码",
        "is_other": "其他分类（须解释）",
        "translation_provenance": "翻译来源",
        "project_translation": "项目翻译",
        "case_id": "个案编号",
        "case_revision_id": "个案版本记录编号",
        "case_reference": "投诉参考编号",
        "received_at": "收到时间（香港时间）",
        "work_status": "冻结工作状态",
        "completed_at": "完成时间（香港时间）",
        "in_progress": "处理中",
        "completed": "已完成",
        "category_code": "冻结分类代码",
        "category_label_en": "冻结分类英文名称",
        "category_label_tc": "冻结分类繁体中文名称",
        "category_label_sc": "冻结分类简体中文名称",
        "generated_at": "生成时间（香港时间）",
        "time_basis": "时间依据",
        "page": "页",
    },
    "en": {
        "title": "complaint period statistics",
        "election": "Election",
        "election_status": "Election status",
        "constituency": "Constituency",
        "station": "Polling station",
        "report_scope": "Report basis",
        "basis_note": "Coverage and frozen basis",
        "station_current": "Current saved station report",
        "period_revision": "Selected saved period revision",
        "revision_state": "Revision state",
        "current": "Current revision",
        "historical": "Historical revision",
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
        "window": "Received interval (HKT)",
        "status": "Original revision status",
        "revision": "Revision",
        "basis_current": "Matches current case basis",
        "validity": "Current approval validity",
        "valid": "Valid approval",
        "needs_review": "Renewed review required",
        "not_approved": "Outside valid approved coverage",
        "historical_not_current": "Historical, outside current coverage",
        "required": "Configured period count",
        "saved_period_count": "Saved period count",
        "missing": "Periods with no saved record",
        "approved_current": "Current valid approved periods",
        "outside_coverage_case_count": "Current cases outside configured coverage",
        "coverage_legend": (
            "Only saved periods are listed. Missing is not zero. Only current Super"
            "visor approvals whose case basis still matches remain valid. Cohorts u"
            "se received time [start, end); work status is frozen when statistics a"
            "re prepared."
        ),
        "period_legend": (
            "Retains cases, category labels, work status and original approval meta"
            "data frozen at preparation of this revision. Received cohorts use [sta"
            "rt, end). Current station summaries and unsaved input are excluded."
        ),
        "overview": "Saved period overview",
        "details": "Period revision details",
        "empty": "No period has been saved. This does not mean there were zero complaints.",
        "groups": "Frozen category counts",
        "members": "Frozen case membership",
        "empty_groups": "This saved revision explicitly records zero complaints.",
        "schedule_revision": "Schedule revision",
        "planned_opening_at": "Planned opening (HKT)",
        "planned_closing_at": "Planned closing (HKT)",
        "reporting_interval_minutes": "Report interval (minutes)",
        "id": "Record ID",
        "start_at": "Period start (HKT)",
        "end_at": "Period end (HKT)",
        "basis_at": "Frozen preparation time (HKT)",
        "total_received": "Received",
        "total_completed": "Completed",
        "total_in_progress": "In progress",
        "entered_at": "Server entry time (HKT)",
        "actor_id": "Recording account ID",
        "submitted_at": "Submission time (HKT)",
        "submitted_by": "Submitting account ID",
        "approved_at": "Original approval time (HKT)",
        "approved_by": "Original approving account ID",
        "amendment_reason": "Amendment reason",
        "category_id": "Category ID",
        "category_revision_id": "Category revision record ID",
        "category_revision": "Category revision",
        "code": "Category code",
        "label_en": "Frozen English label",
        "label_tc": "Frozen Traditional Chinese label",
        "label_sc": "Frozen Simplified Chinese label",
        "verified_source": "Verified reference source",
        "source": "Category source",
        "verified_reference": "Verified reference category",
        "project_configured": "Project-configured category",
        "source_english": "Original English reference text",
        "reference_page": "Reference page",
        "is_other": "Other category (explanation required)",
        "translation_provenance": "Translation provenance",
        "project_translation": "Project translation",
        "case_id": "Case ID",
        "case_revision_id": "Case revision record ID",
        "case_reference": "Complaint reference",
        "received_at": "Received time (HKT)",
        "work_status": "Frozen work status",
        "completed_at": "Completion time (HKT)",
        "in_progress": "In progress",
        "completed": "Completed",
        "category_code": "Frozen category code",
        "category_label_en": "Frozen category English label",
        "category_label_tc": "Frozen category Traditional Chinese label",
        "category_label_sc": "Frozen category Simplified Chinese label",
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
        return utc.astimezone(HKT).strftime("%Y-%m-%d %H:%M:%S") + fraction + " HKT"
    except OverflowError:
        seconds = utc.hour * 3600 + utc.minute * 60 + utc.second + 8 * 3600 - 86400
        hour, remainder = divmod(seconds, 3600)
        minute, second = divmod(remainder, 60)
        return f"10000-01-01 {hour:02d}:{minute:02d}:{second:02d}{fraction} HKT"


def validity(row: dict[str, Any], labels: dict[str, str]) -> str:
    return labels[
        "historical_not_current"
        if not row["is_latest_revision"]
        else "valid"
        if row["approval_valid"]
        else "needs_review"
        if row["review_required"]
        else "not_approved"
    ]


def metadata_rows(report: dict[str, Any]) -> list[list[str]]:
    labels, scope, schedule = report["labels"], report["scope"], report["schedule"]
    pairs = [
        ("report_scope", labels[report["report_scope"]]),
        ("election", scope["election"]["name"]),
        ("election_status", labels[scope["election"]["status"]]),
        ("constituency", scope["constituency"]["code"] + " · " + scope["constituency"]["name"]),
        ("station", scope["station"]["code"] + " · " + scope["station"]["name"]),
    ]
    if report["report_scope"] == "station_current":
        pairs += [(key, str(value)) for key, value in report["summary"].items()]
        pairs += [
            ("saved_period_count", str(report["saved_period_count"])),
            ("outside_coverage_case_count", str(report["outside_coverage_case_count"])),
        ]
        if schedule:
            pairs += [
                ("schedule_revision", str(schedule["revision"])),
                ("planned_opening_at", hong_kong_time(schedule["planned_opening_at"])),
                ("planned_closing_at", hong_kong_time(schedule["planned_closing_at"])),
                ("reporting_interval_minutes", str(schedule["reporting_interval_minutes"])),
            ]
    else:
        pairs += [
            ("period_index", str(report["selected_period"])),
            ("revision", str(report["revision"])),
            ("revision_state", labels[report["revision_state"]]),
            ("schedule_revision", str(schedule["revision"])),
        ]
    pairs += [
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
    return [[labels[key], value] for key, value in pairs]


def field_text(key: str, value: Any, labels: dict[str, str]) -> str:
    if value is None or value == "":
        return labels["not_recorded"]
    if key.endswith("_at"):
        return hong_kong_time(value)
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if key in ("status", "work_status", "source", "translation_provenance"):
        return labels[value]
    return str(value)


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
                "total_received",
                "total_completed",
                "total_in_progress",
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
                str(row["total_received"]),
                str(row["total_completed"]),
                str(row["total_in_progress"]),
            ]
        )
    tables = [
        HistoryTable(
            labels["overview"],
            overview,
            (0.07, 0.25, 0.10, 0.06, 0.13, 0.13, 0.13, 0.13),
            labels["empty"] if not report["items"] else "",
            split_in_row=False,
        )
    ]
    period_fields = (
        "id",
        "period_index",
        "revision",
        "status",
        "schedule_revision",
        "start_at",
        "end_at",
        "basis_at",
        "basis_current",
        "total_received",
        "total_completed",
        "total_in_progress",
        "entered_at",
        "actor_id",
        "submitted_at",
        "submitted_by",
        "approved_at",
        "approved_by",
        "amendment_reason",
    )
    group_fields = (
        "category_id",
        "category_revision_id",
        "category_revision",
        "code",
        "label_en",
        "label_tc",
        "label_sc",
        "verified_source",
        "source",
        "source_english",
        "reference_page",
        "is_other",
        "translation_provenance",
        "total_received",
        "total_completed",
        "total_in_progress",
    )
    member_fields = (
        "case_id",
        "case_revision_id",
        "revision",
        "case_reference",
        "received_at",
        "work_status",
        "completed_at",
        "entered_at",
        "actor_id",
        "category_id",
        "category_revision",
        "category_code",
        "category_label_en",
        "category_label_tc",
        "category_label_sc",
    )
    for row in report["items"]:
        identity = (
            f"{labels['period_index']} {row['period_index']} · "
            f"{labels['revision']} {row['revision']}"
        )
        details = [
            [labels["field"] + "\n" + labels["details"] + " · " + identity, labels["value"]],
            [labels["validity"], validity(row, labels)],
        ]
        details += [[labels[key], field_text(key, row[key], labels)] for key in period_fields]
        tables.append(HistoryTable("", details, (0.32, 0.68)))
        if not row["group_counts"]:
            tables.append(
                HistoryTable(
                    "",
                    [
                        [labels["groups"] + " · " + identity, labels["value"]],
                        [labels["total_received"], "0"],
                    ],
                    (0.32, 0.68),
                    labels["empty_groups"],
                )
            )
        for group in row["group_counts"]:
            header = labels["groups"] + " · " + identity + " · " + str(group["code"])
            group_rows = [[labels["field"] + "\n" + header, labels["value"]]]
            group_rows += [
                [labels[key], field_text(key, group[key], labels)] for key in group_fields
            ]
            tables.append(HistoryTable("", group_rows, (0.32, 0.68)))
        for member in row["members"]:
            header = labels["members"] + " · " + identity + " · " + member["case_reference"]
            member_rows = [[labels["field"] + "\n" + header, labels["value"]]]
            member_rows += [
                [labels[key], field_text(key, member[key], labels)] for key in member_fields
            ]
            tables.append(HistoryTable("", member_rows, (0.32, 0.68)))
    return tables


def preview_lines(report: dict[str, Any]) -> list[str]:
    lines = [report["title"], *[": ".join(row) for row in metadata_rows(report)]]
    for table in report_tables(report):
        lines += ["", table.title, *[" · ".join(row) for row in table.rows]]
        if table.empty_message:
            lines.append(table.empty_message)
    return lines


def csv_report(report: dict[str, Any]) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerows([[report["title"]], *metadata_rows(report)])
    for table in report_tables(report):
        writer.writerows([[], [table.title], *table.rows])
        if table.empty_message:
            writer.writerow([table.empty_message])
    return output.getvalue().encode("utf-8-sig")


def pdf_report(report: dict[str, Any]) -> bytes:
    return history_pdf(
        report["title"],
        metadata_rows(report),
        report_tables(report),
        report["scope"]["station"]["code"] + " · " + report["labels"][report["report_scope"]],
        report["labels"]["page"],
    )


def complaint_reports_router(
    database: Callable[..., Any],
    ready_account: Callable[..., Any],
    timestamp: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/workspace/stations/{station_id}/complaint-periods",
        tags=["Complaint statements"],
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
        station, constituency, election = complaint_read_scope(db, actor, station_id)
        schedule = complaint_schedule(db, election.id)
        # All case heads and report revisions share the Election/Schedule boundary.
        # Membership is subsequently fetched by immutable case-revision IDs only.
        cases = current_complaint_cases(db, station_id)
        cohorts, outside = case_cohorts(cases, schedule) if schedule else ({}, len(cases))
        records = period_records(db, station_id)
        latest = {row.period_index: row for row in records}
        if index is None:
            rows = [latest[key] for key in sorted(latest)]
        else:
            rows = [
                row for row in records if row.period_index == index and row.revision == revision
            ]
            if not rows:
                if schedule:
                    required_bounds(schedule, index)
                raise HTTPException(404, detail={"code": "complaint_period_record_not_found"})
        members = period_members(db, [row.id for row in rows])
        items = [
            complaint_period_view(
                row,
                members.get(row.id, []),
                basis_current=bool(
                    schedule and current_basis(row, schedule, cohorts.get(row.period_index, []))
                ),
                is_latest_revision=row.id == latest[row.period_index].id,
            )
            for row in rows
        ]
        count = period_count(schedule) if schedule else 0
        summary = (
            {
                "required": count,
                "missing": count - sum(1 <= key <= count for key in latest),
                "approved_current": sum(
                    row["approval_valid"] for row in items if 1 <= row["period_index"] <= count
                ),
            }
            if index is None
            else None
        )
        report: dict[str, Any] = {
            "scope": {
                "election": {"id": election.id, "name": election.name, "status": election.status},
                "constituency": {
                    "id": constituency.id,
                    "code": constituency.code,
                    "name": constituency.name,
                },
                "station": {"id": station.id, "code": station.code, "name": station.name},
            },
            "schedule": (
                {
                    "revision": schedule.revision,
                    "planned_opening_at": as_utc(schedule.planned_opening_at),
                    "planned_closing_at": as_utc(schedule.planned_closing_at),
                    "reporting_interval_minutes": schedule.reporting_interval_minutes,
                }
                if schedule
                else None
            )
            if index is None
            else {
                "revision": rows[0].schedule_revision,
                "period_start_at": as_utc(rows[0].start_at),
                "period_end_at": as_utc(rows[0].end_at),
            },
            "report_scope": "station_current" if index is None else "period_revision",
            "selected_period": index,
            "revision": revision,
            "revision_state": "current"
            if index is None or items[0]["is_latest_revision"]
            else "historical",
            "items": items,
            "summary": summary,
            "period_count": count if index is None else None,
            "saved_period_count": len(latest) if index is None else None,
            "outside_coverage_case_count": outside if index is None else None,
            "title": LABELS[locale]["title"],
            "labels": LABELS[locale],
            "locale": locale,
            "generated_at": as_utc(timestamp()),
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
            f"complaints-station-{station_id}"
            if report["report_scope"] == "station_current"
            else f"complaints-period-{station_id}-{report['selected_period']}-r{report['revision']}"
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
