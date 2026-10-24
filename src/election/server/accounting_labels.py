"""P(18) labels extend the existing stock, P(12) and turnout report vocabulary."""

from election.server.special_paper_labels import LABELS as SPECIAL_LABELS
from election.server.stock_reports import ReportLocale
from election.server.stock_snapshot_reports import LABELS as SNAPSHOT_LABELS
from election.server.turnout_reports import LABELS as TURNOUT_LABELS

_ACCOUNTING: dict[ReportLocale, dict[str, str]] = {
    "tc": {
        "title": "P(18) 選票核算及票箱選票估計",
        "scope_note": "保留所選 P(18) 修訂版本的數字及凍結來源；目前有效性另列。",
        "estimate_note": (
            "票箱選票估計數與實際點算數量分開。補發替代已註銷原票，"
            "不再次扣減；已收回未用選票不重複加入接收庫存。"
        ),
        "event_at": "核算原始事件時間（香港時間）",
        "notes": "核算備註",
        "source_current": "凍結來源目前仍有效",
        "approval_valid": "P(18) 目前確認有效",
        "frozen_turnout_approval": "凍結時投票人數確認有效",
        "ordinary_received_quantity": "接收普通選票總數",
        "ordinary_central_unissued_quantity": "主任持有的未發出普通選票",
        "ordinary_at_desks_quantity": "櫃台持有的未發出普通選票",
        "estimated_box_from_stock_quantity": "庫存推算票箱選票數量",
        "estimated_box_from_turnout_quantity": "有效確認投票人數推算票箱選票數量",
        "observed_counted_quantity": "票箱實際點算數量",
        "stock_snapshot": "凍結 P(12) 庫存快照",
        "special_papers": "凍結補發、重複及未用選票觀察",
        "turnout": "凍結 P(15) 投票人數基礎",
        "source_events": "已確認後備啟用及恢復來源",
        "activation_stock_snapshot": "後備啟用 P(12) 快照",
        "endpoint_stock_snapshot": "後備期末 P(12) 快照",
        "stock_snapshot_id": "P(12) 快照記錄編號",
        "stock_snapshot_revision": "P(12) 快照修訂版本",
        "special_paper_id": "特殊選票觀察記錄編號",
        "special_paper_revision": "特殊選票觀察修訂版本",
        "activation": "後備啟用",
        "recovery": "外部恢復及核對",
        "cumulative_quantity": "確認累計人數",
        "recovered": "恢復後核對數字",
        "difference": "恢復外部數字減庫存推算差額",
        "origin_scope": "來源投票站",
    },
    "sc": {
        "title": "P(18) 选票核算及票箱选票估计",
        "scope_note": "保留所选 P(18) 修订版本的数字及冻结来源；当前有效性另列。",
        "estimate_note": (
            "票箱选票估计数与实际点算数量分开。补发替代已注销原票，"
            "不再次扣减；已收回未用选票不重复加入接收库存。"
        ),
        "event_at": "核算原始事件时间（香港时间）",
        "notes": "核算备注",
        "source_current": "冻结来源当前仍有效",
        "approval_valid": "P(18) 当前确认有效",
        "frozen_turnout_approval": "冻结时投票人数确认有效",
        "ordinary_received_quantity": "接收普通选票总数",
        "ordinary_central_unissued_quantity": "主任持有的未发出普通选票",
        "ordinary_at_desks_quantity": "柜台持有的未发出普通选票",
        "estimated_box_from_stock_quantity": "库存推算票箱选票数量",
        "estimated_box_from_turnout_quantity": "有效确认投票人数推算票箱选票数量",
        "observed_counted_quantity": "票箱实际点算数量",
        "stock_snapshot": "冻结 P(12) 库存快照",
        "special_papers": "冻结补发、重复及未用选票观察",
        "turnout": "冻结 P(15) 投票人数依据",
        "source_events": "已确认后备启用及恢复来源",
        "activation_stock_snapshot": "后备启用 P(12) 快照",
        "endpoint_stock_snapshot": "后备期末 P(12) 快照",
        "stock_snapshot_id": "P(12) 快照记录编号",
        "stock_snapshot_revision": "P(12) 快照修订版本",
        "special_paper_id": "特殊选票观察记录编号",
        "special_paper_revision": "特殊选票观察修订版本",
        "activation": "后备启用",
        "recovery": "外部恢复及核对",
        "cumulative_quantity": "确认累计人数",
        "recovered": "恢复后核对数字",
        "difference": "恢复外部数字减库存推算差额",
        "origin_scope": "来源投票站",
    },
    "en": {
        "title": "P(18) stock accounting and box-paper estimates",
        "scope_note": "Figures and frozen sources belong to the selected P(18) revision; "
                      "current validity is shown separately.",
        "estimate_note": (
            "Box-paper estimates remain separate from actual counted papers. Replacements "
            "substitute for cancelled originals and are not deducted again. Retrieved-unused "
            "papers are not added to received stock again."
        ),
        "event_at": "Accounting event time (HKT)",
        "notes": "Accounting notes",
        "source_current": "Frozen sources remain current",
        "approval_valid": "P(18) approval currently valid",
        "frozen_turnout_approval": "Turnout approval valid when frozen",
        "ordinary_received_quantity": "Ordinary papers received",
        "ordinary_central_unissued_quantity": "Unissued ordinary stock with PRO",
        "ordinary_at_desks_quantity": "Unissued ordinary stock at desks",
        "estimated_box_from_stock_quantity": "Estimated box papers from stock",
        "estimated_box_from_turnout_quantity": "Estimated box papers from approved turnout",
        "observed_counted_quantity": "Actual observed counted papers",
        "stock_snapshot": "Frozen P(12) stock snapshot",
        "special_papers": "Frozen special-paper observation",
        "turnout": "Frozen P(15) turnout basis",
        "source_events": "Confirmed fallback activation and recovery sources",
        "activation_stock_snapshot": "Fallback activation P(12) snapshot",
        "endpoint_stock_snapshot": "Fallback endpoint P(12) snapshot",
        "stock_snapshot_id": "P(12) snapshot ID",
        "stock_snapshot_revision": "P(12) snapshot revision",
        "special_paper_id": "Special-paper observation ID",
        "special_paper_revision": "Special-paper observation revision",
        "activation": "Fallback activation",
        "recovery": "External recovery and reconciliation",
        "cumulative_quantity": "Confirmed cumulative turnout",
        "recovered": "Recovered figure",
        "difference": "Recovered external minus stock-derived difference",
        "origin_scope": "Source polling station",
    },
}

LABELS: dict[ReportLocale, dict[str, str]] = {
    locale: {
        **SPECIAL_LABELS[locale], **SNAPSHOT_LABELS[locale],
        **TURNOUT_LABELS[locale], **_ACCOUNTING[locale],
    }
    for locale in _ACCOUNTING
}
