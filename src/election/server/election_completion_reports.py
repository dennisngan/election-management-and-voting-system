"""Localized completion statements rendered exclusively from immutable event values."""

import csv
from dataclasses import asdict
from datetime import datetime
from io import StringIO
from typing import Any

from election.server.constituency_result_labels import LABELS as RESULT_LABELS
from election.server.constituency_result_labels import ReportLocale
from election.server.election_completion_provenance import (
    completion_recount_tables,
    completion_source_tables,
    completion_tie_tables,
)
from election.server.history_pdf import HistoryTable, history_pdf
from election.server.turnout_reports import hong_kong_time

LABELS: dict[ReportLocale, dict[str, str]] = {
    "en": {
        **RESULT_LABELS["en"],
        "title": "Preserved election completion statement",
        "election_id": "Election ID", "event_id": "Event ID", "kind": "Event",
        "revision": "Revision", "basis_digest": "Basis digest", "actor_id": "Actor ID",
        "accepted_at": "Accepted at", "reason": "Reason",
        "previous_finalization_id": "Previous finalization ID", "generated_at": "Generated at",
        "finalization": "Finalization", "reopening": "Reopening",
        "winner": "Elected candidate ID", "complaints": "Recorded complaint status",
        "case_id": "Case ID", "case_reference": "Case reference",
        "completed_at": "Completion time", "in_progress": "In progress", "completed": "Completed",
    },
    "tc": {
        **RESULT_LABELS["tc"],
        "title": "已保留選舉完成確認報表",
        "election_id": "選舉編號", "event_id": "事件編號", "kind": "事件",
        "revision": "修訂", "basis_digest": "基礎摘要", "actor_id": "帳戶編號",
        "accepted_at": "接納時間", "reason": "原因",
        "previous_finalization_id": "先前完成確認編號", "generated_at": "報表產生時間",
        "finalization": "完成確認", "reopening": "重新開放",
        "winner": "當選候選人記錄編號", "complaints": "已記錄投訴狀態",
        "case_id": "個案編號", "case_reference": "個案參考編號",
        "completed_at": "完成時間", "in_progress": "處理中", "completed": "已完成",
    },
    "sc": {
        **RESULT_LABELS["sc"],
        "title": "已保留选举完成确认报表",
        "election_id": "选举编号", "event_id": "事件编号", "kind": "事件",
        "revision": "修订", "basis_digest": "基础摘要", "actor_id": "账户编号",
        "accepted_at": "接纳时间", "reason": "原因",
        "previous_finalization_id": "先前完成确认编号", "generated_at": "报表生成时间",
        "finalization": "完成确认", "reopening": "重新开放",
        "winner": "当选候选人记录编号", "complaints": "已记录投诉状态",
        "case_id": "个案编号", "case_reference": "个案参考编号",
        "completed_at": "完成时间", "in_progress": "处理中", "completed": "已完成",
    },
}


def _value(value: Any, labels: dict[str, str]) -> str:
    if value is None:
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    return str(value)


def _metadata(
    event: dict[str, Any], labels: dict[str, str], generated_at: datetime,
) -> list[list[str]]:
    election = event["outcome"]["election"]
    rows = [
        [labels["election_id"], str(event["election_id"])],
        [labels["election"], election["name"]],
        [labels["event_id"], str(event["id"])],
        [labels["kind"], labels[event["kind"]]],
        [labels["status"], labels[election["status"]]],
        [labels["revision"], str(event["election_revision"])],
        [labels["actor_id"], str(event["actor_id"])],
        [labels["accepted_at"], hong_kong_time(event["accepted_at"])],
        [labels["reason"], event["reason"]],
        [labels["previous_finalization_id"], _value(event["previous_finalization_id"], labels)],
        [labels["basis_digest"], event["basis_digest"]],
        [labels["generated_at"], hong_kong_time(generated_at)],
        [labels["time_basis"], labels["time_hkt"]],
    ]
    return rows


def _tables(
    event: dict[str, Any], labels: dict[str, str], locale: ReportLocale,
) -> list[HistoryTable]:
    outcome = event["outcome"]
    tables = []
    for result in outcome.get("results", []):
        constituency = result["constituency"]
        title = (labels["constituency"] + " #" + str(constituency["id"]) + " · "
                 + constituency["code"] + " · " + constituency["name"])
        tables.append(HistoryTable(title, [
            [labels["field"], labels["value"]],
            [labels["status"], labels[result["status"]]],
            [labels["provisional"], _value(result["provisional"], labels)],
            [labels["winner"], _value(result["winner_candidate_id"], labels)],
            [labels["basis_digest"], result["basis_digest"]],
        ], (0.35, 0.65)))
        votes = [[labels["candidate_id"], labels["name"], labels["quantity"]]]
        votes.extend([
            str(row["candidate_id"]), row["name"], str(row["quantity"]),
        ] for row in result["candidate_totals"])
        tables.append(HistoryTable(labels["candidate_totals"], votes, (0.20, 0.55, 0.25)))
    tables.extend(completion_tie_tables(outcome.get("results", []), locale))
    if event["kind"] == "finalization":
        complaints = [[labels[key] for key in (
            "station_id", "case_id", "case_reference", "revision", "status", "completed_at",
        )]]
        for source in outcome["sources"]["complaints"]:
            for case in source["records"]:
                complaints.append([
                    str(source["station_id"]), str(case["id"]), case["case_reference"],
                    str(case["revision"]), labels[case["work_status"]],
                    hong_kong_time(case["completed_at"]) if case["completed_at"] is not None
                    else labels["not_recorded"],
                ])
        tables.append(HistoryTable(
            labels["complaints"], complaints, (0.12, 0.12, 0.25, 0.10, 0.16, 0.25),
            labels["none"] if len(complaints) == 1 else "",
        ))
        tables.extend(completion_source_tables(outcome["sources"], locale))
        tables.extend(completion_recount_tables(outcome["sources"], locale))
    return tables


def completion_statement(
    event: dict[str, Any], locale: ReportLocale, generated_at: datetime,
) -> dict[str, Any]:
    """Expose the exact saved event and the same localized rows used by downloads."""
    labels = LABELS[locale]
    metadata = _metadata(event, labels, generated_at)
    tables = _tables(event, labels, locale)
    rows = [[labels["title"]], *metadata]
    for table in tables:
        rows.extend([[], [table.title], *table.rows])
        if table.empty_message:
            rows.append([table.empty_message])
    return {
        "locale": locale, "event": event, "title": labels["title"],
        "metadata": metadata, "tables": [asdict(table) for table in tables], "rows": rows,
    }


def completion_csv(event: dict[str, Any], locale: ReportLocale, generated_at: datetime) -> bytes:
    """Keep generation metadata separate from the event's preserved business rows."""
    output = StringIO(newline="")
    csv.writer(output).writerows(completion_statement(event, locale, generated_at)["rows"])
    return output.getvalue().encode("utf-8-sig")


def completion_pdf(event: dict[str, Any], locale: ReportLocale, generated_at: datetime) -> bytes:
    """Render the same preserved business values as the CSV, with the shared CJK layout."""
    labels = LABELS[locale]
    footer = (
        f"{labels['election_id']} {event['election_id']} | {labels['event_id']} {event['id']}"
        f" | {event['basis_digest']}"
    )
    return history_pdf(
        labels["title"], _metadata(event, labels, generated_at), _tables(event, labels, locale),
        footer, labels["page"],
    )
