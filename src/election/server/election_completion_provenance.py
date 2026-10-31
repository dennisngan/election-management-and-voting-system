"""Render recorded finalization sources without consulting current operational records."""

from typing import Any

from election.server.constituency_result_labels import LABELS as RESULT_LABELS
from election.server.count_report_labels import LABELS as COUNT_LABELS
from election.server.history_pdf import HistoryTable
from election.server.physical_decision_reports import physical_tables
from election.server.stock_reports import ReportLocale
from election.server.turnout_reports import hong_kong_time

_EXTRA: dict[ReportLocale, dict[str, str]] = {
    "en": {
        "kind_tie": "Recorded tie resolution",
        "constituency_id": "Constituency ID",
        "tie_revision": "Revision",
        "tie_winner": "Winner candidate ID",
        "tie_actor": "Authorized by account ID",
        "tie_accepted_at": "Accepted at (HKT)",
        "tie_reason": "Reason",
        "tie_basis": "Resolution basis digest",
        "tie_valid": "Valid at finalization",
        "tie_current": "Current at finalization",
        "counting_station_id": "Counting station ID",
        "accounting_source_station_id": "Accounting source station ID",
        "pinned_source_current": "Source current when scope was frozen",
        "status": "Status",
        "source_snapshot": "Sources recorded at finalization",
        "kind_polling": "Polling completion",
        "kind_accounting": "P(18) accounting",
        "kind_count": "Selected approved count",
        "kind_box": "Frozen box basis",
        "kind_pinned_accounting": "Counting scope accounting basis",
        "kind_comparison": "Physical comparison",
        "station_id": "Station ID",
        "record_id": "Record ID",
        "scope_id": "Counting scope ID",
        "scope_revision": "Scope revision",
        "round_id": "Round ID",
        "revision_id": "Revision record ID",
        "source_current": "Source current at finalization",
        "approval_valid": "Approval valid at finalization",
        "selected": "Selected at finalization",
        "selection_id": "Selection ID",
        "decision_id": "Decision ID",
        "origin_station_id": "Origin station ID",
        "destination_station_id": "Destination station ID",
        "comparison_source": "Comparison source",
        "decision_validity": "Decision validity recorded at approval",
        "decision_is_current": "Latest decision recorded at approval",
        "applies_to_revision": "Applied to the reviewed count revision",
        "schedule_revision": "Polling schedule revision",
        "planned_at": "Planned service time (HKT)",
        "event_at": "Original event time (HKT)",
        "entered_at": "Server entry time (HKT)",
        "actor_id": "Recording account ID",
        "scope_revision_id": "Scope revision record ID",
        "stock_estimate": "Stock-derived box estimate",
        "turnout_estimate": "Turnout-derived box estimate",
        "box_prepared_at": "Box prepared at (HKT)",
        "box_departure_at": "Box departed at (HKT)",
        "box_receipt_at": "Box received at (HKT)",
    },
    "tc": {
        "kind_tie": "已記錄平票決定",
        "constituency_id": "選區編號",
        "tie_revision": "修訂",
        "tie_winner": "當選候選人編號",
        "tie_actor": "授權帳戶編號",
        "tie_accepted_at": "接納時間（香港時間）",
        "tie_reason": "原因",
        "tie_basis": "平票決定基礎摘要",
        "tie_valid": "完成確認時有效",
        "tie_current": "完成確認時為目前決定",
        "counting_station_id": "點票站編號",
        "accounting_source_station_id": "核算來源投票站編號",
        "pinned_source_current": "範圍凍結時來源仍為目前版本",
        "status": "狀態",
        "source_snapshot": "完成確認時記錄的來源",
        "kind_polling": "投票服務完成記錄",
        "kind_accounting": "P(18) 會計",
        "kind_count": "已選核准點票",
        "kind_box": "凍結票箱基礎",
        "kind_pinned_accounting": "點票範圍核算基礎",
        "kind_comparison": "實際數量比較",
        "station_id": "投票站編號",
        "record_id": "記錄編號",
        "scope_id": "點票範圍編號",
        "scope_revision": "點票範圍修訂",
        "round_id": "點票輪次編號",
        "revision_id": "版本記錄編號",
        "source_current": "完成確認時來源仍為目前版本",
        "approval_valid": "完成確認時核准仍然有效",
        "selected": "完成確認時已選用",
        "selection_id": "選定記錄編號",
        "decision_id": "決定編號",
        "origin_station_id": "來源投票站編號",
        "destination_station_id": "接收投票站編號",
        "comparison_source": "比較來源",
        "decision_validity": "核准時記錄的決定有效性",
        "decision_is_current": "核准時記錄的最新決定",
        "applies_to_revision": "適用於已核閱點票修訂",
        "schedule_revision": "投票時間表修訂",
        "planned_at": "計劃服務時間（香港時間）",
        "event_at": "原始事件時間（香港時間）",
        "entered_at": "伺服器記錄時間（香港時間）",
        "actor_id": "記錄帳戶編號",
        "scope_revision_id": "範圍版本記錄編號",
        "stock_estimate": "按存貨推算票箱數量",
        "turnout_estimate": "按投票率推算票箱數量",
        "box_prepared_at": "票箱準備時間（香港時間）",
        "box_departure_at": "票箱離站時間（香港時間）",
        "box_receipt_at": "票箱接收時間（香港時間）",
    },
    "sc": {
        "kind_tie": "已记录平票决定",
        "constituency_id": "选区编号",
        "tie_revision": "修订",
        "tie_winner": "当选候选人编号",
        "tie_actor": "授权账户编号",
        "tie_accepted_at": "接纳时间（香港时间）",
        "tie_reason": "原因",
        "tie_basis": "平票决定基础摘要",
        "tie_valid": "完成确认时有效",
        "tie_current": "完成确认时为当前决定",
        "counting_station_id": "点票站编号",
        "accounting_source_station_id": "核算来源投票站编号",
        "pinned_source_current": "范围冻结时来源仍为当前版本",
        "status": "状态",
        "source_snapshot": "完成确认时记录的来源",
        "kind_polling": "投票服务完成记录",
        "kind_accounting": "P(18) 会计",
        "kind_count": "已选批准点票",
        "kind_box": "冻结票箱基础",
        "kind_pinned_accounting": "点票范围核算基础",
        "kind_comparison": "实际数量比较",
        "station_id": "投票站编号",
        "record_id": "记录编号",
        "scope_id": "点票范围编号",
        "scope_revision": "点票范围修订",
        "round_id": "点票轮次编号",
        "revision_id": "版本记录编号",
        "source_current": "完成确认时来源仍为当前版本",
        "approval_valid": "完成确认时批准仍然有效",
        "selected": "完成确认时已选用",
        "selection_id": "选定记录编号",
        "decision_id": "决定编号",
        "origin_station_id": "来源投票站编号",
        "destination_station_id": "接收投票站编号",
        "comparison_source": "比较来源",
        "decision_validity": "批准时记录的决定有效性",
        "decision_is_current": "批准时记录的最新决定",
        "applies_to_revision": "适用于已审阅点票修订",
        "schedule_revision": "投票时间表修订",
        "planned_at": "计划服务时间（香港时间）",
        "event_at": "原始事件时间（香港时间）",
        "entered_at": "服务器记录时间（香港时间）",
        "actor_id": "记录账户编号",
        "scope_revision_id": "范围版本记录编号",
        "stock_estimate": "按存货推算票箱数量",
        "turnout_estimate": "按投票率推算票箱数量",
        "box_prepared_at": "票箱准备时间（香港时间）",
        "box_departure_at": "票箱离站时间（香港时间）",
        "box_receipt_at": "票箱接收时间（香港时间）",
    },
}


def _value(key: str, value: Any, labels: dict[str, str]) -> str:
    if value is None:
        return labels["not_recorded"]
    if isinstance(value, bool):
        return labels["yes" if value else "no"]
    if key.endswith("_at"):
        return hong_kong_time(value)
    if key in {"status", "p18_status"}:
        return labels.get(str(value), str(value))
    return str(value)


def _pairs(
    data: dict[str, Any],
    fields: tuple[tuple[str, str], ...],
    labels: dict[str, str],
) -> list[list[str]]:
    return [[labels[label], _value(key, data.get(key), labels)] for label, key in fields]


def _table(title: str, pairs: list[list[str]], labels: dict[str, str]) -> HistoryTable:
    # Two label/value pairs per row keep the complete recorded identities together.
    rows = [[labels["field"], labels["value"], labels["field"], labels["value"]]]
    rows.extend(
        pairs[index] + (pairs[index + 1] if index + 1 < len(pairs) else ["", ""])
        for index in range(0, len(pairs), 2)
    )
    return HistoryTable(title, rows, (0.18, 0.32, 0.18, 0.32))


def _accounting_pairs(record: dict[str, Any], labels: dict[str, str]) -> list[list[str]]:
    pairs = _pairs(
        record,
        (
            ("p18_id", "id"),
            ("p18_revision", "revision"),
            ("p18_status", "status"),
            ("source_current", "source_current"),
            ("approval_valid", "approval_valid"),
            ("event_at", "event_at"),
            ("entered_at", "entered_at"),
            ("actor_id", "actor_id"),
            ("submitted_by", "submitted_by"),
            ("submitted_at", "submitted_at"),
            ("approved_by", "approved_by"),
            ("approved_at", "approved_at"),
        ),
        labels,
    )
    pairs.extend(
        _pairs(
            record.get("summary", {}),
            (
                ("stock_estimate", "estimated_box_from_stock_quantity"),
                ("turnout_estimate", "estimated_box_from_turnout_quantity"),
            ),
            labels,
        )
    )
    return pairs


def completion_source_tables(sources: dict[str, Any], locale: ReportLocale) -> list[HistoryTable]:
    """Keep recorded sources and their approval-time comparisons distinct."""
    labels = {**RESULT_LABELS[locale], **COUNT_LABELS[locale], **_EXTRA[locale]}
    tables = []
    for source in sources["polling_completion"]:
        record = source["record"]
        pairs = [
            [labels["source"], labels["kind_polling"]],
            [labels["station_id"], str(source["station_id"])],
        ]
        pairs.extend(
            _pairs(
                record,
                (
                    ("record_id", "id"),
                    ("revision", "revision"),
                    ("status", "status"),
                    ("event_at", "event_at"),
                    ("entered_at", "entered_at"),
                    ("actor_id", "actor_id"),
                    ("submitted_by", "submitted_by"),
                    ("submitted_at", "submitted_at"),
                    ("approved_by", "approved_by"),
                    ("approved_at", "approved_at"),
                    ("schedule_revision", "schedule_revision"),
                    ("planned_at", "planned_at"),
                ),
                labels,
            )
        )
        tables.append(_table(labels["kind_polling"], pairs, labels))
    for source in sources["accounting"]:
        pairs = [
            [labels["source"], labels["kind_accounting"]],
            [labels["station_id"], str(source["station_id"])],
        ]
        pairs.extend(_accounting_pairs(source["record"], labels))
        tables.append(_table(labels["kind_accounting"], pairs, labels))
    for source in sources["selected_counts"]:
        record = source["record"]
        identity = [
            [labels["station_id"], str(source["station_id"])],
            [labels["scope_id"], str(source["scope_id"])],
            [labels["round_id"], str(record["id"])],
        ]
        pairs = [[labels["source"], labels["kind_count"]], *identity]
        pairs.extend(
            _pairs(
                record,
                (
                    ("scope_revision", "scope_revision"),
                    ("round_number", "round_number"),
                    ("revision", "revision"),
                    ("revision_id", "revision_id"),
                    ("status", "status"),
                    ("reviewed_revision", "reviewed_revision"),
                    ("reviewed_revision_id", "reviewed_revision_id"),
                    ("source_current", "source_current"),
                    ("approval_valid", "approval_valid"),
                    ("approved_by", "approved_by"),
                    ("approved_at", "approved_at"),
                    ("selected", "selected"),
                    ("actual_quantity", "actual_counted_quantity"),
                    ("completed_at", "completed_at"),
                ),
                labels,
            )
        )
        pairs.extend(
            _pairs(
                record.get("selection") or {},
                (
                    ("selection_id", "id"),
                    ("selection_revision", "revision"),
                    ("selection_actor_id", "actor_id"),
                    ("selected_at", "selected_at"),
                ),
                labels,
            )
        )
        tables.append(_table(labels["kind_count"], pairs, labels))
        for box in record["scope_basis"]["box_basis"]:
            pairs = [[labels["source"], labels["kind_box"]], *identity]
            pairs.extend(
                _pairs(
                    box,
                    (
                        ("box_id", "id"),
                        ("revision", "revision"),
                        ("box_reference", "box_reference"),
                        ("seal_reference", "seal_reference"),
                        ("status", "status"),
                        ("origin_station_id", "origin_station_id"),
                        ("destination_station_id", "destination_station_id"),
                        ("box_prepared_at", "prepared_at"),
                        ("box_departure_at", "departure_at"),
                        ("box_receipt_at", "receipt_at"),
                    ),
                    labels,
                )
            )
            tables.append(_table(labels["kind_box"], pairs, labels))
        for accounting in record["scope_basis"]["accounting_basis"]:
            pairs = [
                [labels["source"], labels["kind_pinned_accounting"]],
                [labels["counting_station_id"], str(source["station_id"])],
                [labels["scope_id"], str(source["scope_id"])],
                [labels["round_id"], str(record["id"])],
                [labels["accounting_source_station_id"], str(accounting["station_id"])],
            ]
            pinned_labels = {
                **labels,
                "source_current": labels["pinned_source_current"],
                "approval_valid": labels["frozen_p18_approval_valid"],
            }
            pairs.extend(_accounting_pairs(accounting, pinned_labels))
            tables.append(_table(labels["kind_pinned_accounting"], pairs, labels))
        # The existing pure physical-review renderer accepts recorded dictionaries;
        # qualify its validity labels as captured facts rather than live eligibility.
        physical_labels = {**labels, "source": labels["comparison_source"]}
        for decision in record.get("approved_physical_decisions", []):
            rendered = physical_tables(
                {"approved_physical_decisions": [decision]},
                physical_labels,
                include_empty_placeholders=False,
            )
            pairs = [
                [labels["source"], labels["physical_decision_approved"]],
                *identity,
                [labels["decision_id"], str(decision["id"])],
                [labels["comparison_source"], labels["source_" + decision["source"]]],
            ]
            pairs.extend(row for table in rendered for row in table.rows[1:])
            tables.append(_table(labels["physical_decision_approved"], pairs, labels))
        for key, title in (
            ("physical_comparisons", labels["kind_comparison"]),
            ("reviewed_physical_comparisons", labels["physical_comparison_reviewed"]),
        ):
            for comparison in record.get(key, []):
                rendered = physical_tables(
                    {key: [comparison]},
                    physical_labels,
                    include_empty_placeholders=False,
                )
                pairs = [[labels["source"], title], *identity]
                pairs.extend(row for table in rendered for row in table.rows[1:])
                tables.append(_table(title, pairs, labels))
    return tables


def completion_tie_tables(
    results: list[dict[str, Any]], locale: ReportLocale,
) -> list[HistoryTable]:
    """Explain saved winners using the tie authorization retained with that outcome."""
    labels = {**RESULT_LABELS[locale], **COUNT_LABELS[locale], **_EXTRA[locale]}
    tables = []
    for result in results:
        decision = result.get("tie_resolution")
        if not isinstance(decision, dict):
            continue
        pairs = [[labels["constituency_id"], str(result["constituency"]["id"])]]
        pairs.extend(_pairs(decision, (
            ("decision_id", "id"), ("tie_revision", "revision"),
            ("tie_winner", "candidate_id"), ("tie_actor", "actor_id"),
            ("tie_accepted_at", "accepted_at"), ("tie_reason", "reason"),
            ("tie_basis", "basis_digest"), ("tie_valid", "valid"),
            ("tie_current", "is_current"),
        ), labels))
        tables.append(_table(labels["kind_tie"], pairs, labels))
    return tables
