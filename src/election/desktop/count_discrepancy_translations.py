"""Reasoned count corrections and exact physical-discrepancy review labels."""

COUNT_DISCREPANCY_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "count_correction_title": "點票紀錄修訂",
        "count_correction_hint": (
            "修訂同一點票輪次的輸入，並保留原有紀錄。儲存後須重新提交、批准及選取結果。"
        ),
        "count_correction_mode": "修訂模式",
        "count_correct_f1": "修訂已提交 F1",
        "count_correct_f2": "修訂已提交 F2",
        "count_refresh_basis": "依最新基準修訂 F1",
        "count_refresh_basis_hint": (
            "請對照最新已接收票箱、帳目及候選人重新核對全部 F1 輸入。此修訂保留舊基準，並"
            "須重新覆核。"
        ),
        "count_cancel_correction": "取消修訂",
        "count_save_correction": "儲存修訂草稿",
        "count_amendment_reason_required": "請填寫修訂原因。",
        "count_explicit_correction_required": "請使用明確的紀錄修訂流程。",
        "count_decisions_changed": "覆核決定已有更新，輸入仍然保留。請核對目前決定及其歷史。",
        "physical_accept": "接納實際票數差額",
        "physical_accept_hint": (
            "接納只記錄對此基準及數字的覆核決定；實際觀察數字及算術驗證不會改變。請填寫原"
            "因並以本人密碼確認。"
        ),
        "physical_difference_accepted": "已記錄實際票數差額的接納決定。",
        "f2_comparison_accepted": "差額已接納",
        "physical_difference_reason_required": "請填寫接納差額的原因（最多 2000 字）。",
        "physical_difference_unavailable": "未有可供覆核的預計或實際票數。",
        "physical_difference_not_pending": "此比較沒有待接納的差額。",
        "physical_decision_revision_conflict": "另一覆核決定已儲存，請重新載入並比較。",
        "count_decision_reason": "覆核原因",
        "count_decision_actor": "覆核人員帳戶 ID",
        "count_decision_history": "實際票數差額決定歷史（目前適用性）",
        "count_decision_current": "適用於目前基準",
        "count_decision_obsolete": "目前不適用，保留作歷史紀錄",
        "count_decision_reviewed_revision": "當時覆核的點票修訂",
        "count_decision_approved_snapshot": "批准當時已審閱的決定（保留快照）",
    },
    "sc": {
        "count_correction_title": "点票记录修订",
        "count_correction_hint": (
            "修订同一点票轮次的输入，并保留原有记录。储存后须重新提交、批准及选取结果。"
        ),
        "count_correction_mode": "修订模式",
        "count_correct_f1": "修订已提交 F1",
        "count_correct_f2": "修订已提交 F2",
        "count_refresh_basis": "依最新基准修订 F1",
        "count_refresh_basis_hint": (
            "请对照最新已接收票箱、账目及候选人重新核对全部 F1 输入。此修订保留旧基准，并"
            "须重新复核。"
        ),
        "count_cancel_correction": "取消修订",
        "count_save_correction": "储存修订草稿",
        "count_amendment_reason_required": "请填写修订原因。",
        "count_explicit_correction_required": "请使用明确的记录修订流程。",
        "count_decisions_changed": "复核决定已有更新，输入仍然保留。请核对目前决定及其历史。",
        "physical_accept": "接纳实际票数差额",
        "physical_accept_hint": (
            "接纳只记录对此基准及数字的复核决定；实际观察数字及算术验证不会改变。请填写原"
            "因并以本人密码确认。"
        ),
        "physical_difference_accepted": "已记录实际票数差额的接纳决定。",
        "f2_comparison_accepted": "差额已接纳",
        "physical_difference_reason_required": "请填写接纳差额的原因（最多 2000 字）。",
        "physical_difference_unavailable": "未有可供复核的预计或实际票数。",
        "physical_difference_not_pending": "此比较没有待接纳的差额。",
        "physical_decision_revision_conflict": "另一复核决定已储存，请重新载入并比较。",
        "count_decision_reason": "复核原因",
        "count_decision_actor": "复核人员账户 ID",
        "count_decision_history": "实际票数差额决定历史（目前适用性）",
        "count_decision_current": "适用于目前基准",
        "count_decision_obsolete": "目前不适用，保留作历史记录",
        "count_decision_reviewed_revision": "当时复核的点票修订",
        "count_decision_approved_snapshot": "批准当时已审阅的决定（保留快照）",
    },
    "en": {
        "count_correction_title": "Correct a count record",
        "count_correction_hint": (
            "Correct an entry within this round and retain the original records. Save, th"
            "en submit, approve and select the result again."
        ),
        "count_correction_mode": "Correction mode",
        "count_correct_f1": "Correct submitted F1",
        "count_correct_f2": "Correct submitted F2",
        "count_refresh_basis": "Correct F1 using the latest basis",
        "count_refresh_basis_hint": (
            "Recheck every F1 entry against the latest received boxes, accounts and candi"
            "dates. This correction retains the old basis and requires renewed review."
        ),
        "count_cancel_correction": "Cancel correction",
        "count_save_correction": "Save corrected draft",
        "count_amendment_reason_required": "Enter a reason for the correction.",
        "count_explicit_correction_required": "Use the explicit record correction action.",
        "count_decisions_changed": (
            "Review decisions changed. Your entries are retained; compare the current dec"
            "isions and history."
        ),
        "physical_accept": "Accept observed physical difference",
        "physical_accept_hint": (
            "Record a review decision for this basis and these figures. Observations and "
            "arithmetic checks remain unchanged. Enter the reason and your own password."
        ),
        "physical_difference_accepted": "The physical-difference decision was recorded.",
        "f2_comparison_accepted": "Difference accepted",
        "physical_difference_reason_required": (
            "Enter a reason for accepting the difference (up to 2000 characters)."
        ),
        "physical_difference_unavailable": (
            "Expected or observed quantities are unavailable for review."
        ),
        "physical_difference_not_pending": "This comparison has no pending difference.",
        "physical_decision_revision_conflict": (
            "Another review decision was saved. Reload and compare."
        ),
        "count_decision_reason": "Review reason",
        "count_decision_actor": "Reviewer account ID",
        "count_decision_history": "Physical-difference history (current applicability)",
        "count_decision_current": "Applies to the current basis",
        "count_decision_obsolete": "Currently inapplicable; retained as history",
        "count_decision_reviewed_revision": "Count revision reviewed",
        "count_decision_approved_snapshot": "Decisions reviewed at approval (preserved snapshot)",
    },
}
