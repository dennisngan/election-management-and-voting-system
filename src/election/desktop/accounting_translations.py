"""Labels keep estimates, observed papers and source approvals distinct."""

ACCOUNTING_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "accounting_title": "選票帳目",
        "accounting_provenance_external_manual": "人工提供的外部數字",
        "accounting_provenance_fallback_stock": "後備普通庫存推算",
        "accounting_provenance_mixed": "正常及後備涵蓋時段",
        "accounting_provenance_external_reconciled": "已核對恢復外部數字",
        "accounting_not_found": "此票站尚未儲存帳目。",
        "accounting_reason_required": "請填寫更正已提交或核准帳目的原因。",
        "accounting_balance_invalid": "來源帳目數量不平衡，請核對存量及各類選票。",
        "accounting_turnout_time_invalid": "投票人數時段晚於選票觀察，請選擇相符的來源。",
        "accounting_intro": "按來源票站準備選票帳目；儲存所選來源版本，供其後點票使用。",
        "accounting_sources": "帳目來源",
        "accounting_special_source": "特別及未用選票觀察版本",
        "accounting_choose_special": "請選擇來源觀察",
        "accounting_turnout_source": "投票人數來源（可不選）",
        "accounting_no_turnout": "未選投票人數來源",
        "accounting_source_hint": "來源觀察包含櫃台存量、收到選票及各類選票的版本。",
        "accounting_turnout_hint": (
            "保留已提供人數及核准狀態。只有有效核准的累計人數用作人數基礎估算。"
        ),
        "accounting_notes": "核對備註",
        "accounting_reason": "更正原因（已提交或核准的帳目必填）",
        "accounting_save": "儲存帳目草稿",
        "accounting_correct": "保留原版並更正",
        "accounting_submit": "提交帳目審核",
        "accounting_approve": "核准此帳目版本",
        "accounting_summary": "帳目及箱內選票估算",
        "accounting_estimate_hint": (
            "估算已扣除領取後收回的未用選票。補發選票替代損壞原票，不再扣減一次。"
        ),
        "accounting_observed_hint": (
            "實際點算張數尚未觀察；「—」不代表零。帳目不會代填實際點算張數。"
        ),
        "accounting_provenance": "已儲存來源版本",
        "accounting_stock_basis": "櫃台存量來源",
        "accounting_special_basis": "特別及未用選票來源",
        "accounting_turnout_basis": "投票人數及其來源",
        "accounting_supplied_total": "提供的累計投票人數",
        "accounting_approved_total": "核准衍生累計投票人數",
        "accounting_source_current": "來源版本仍有效",
        "accounting_source_stale": "來源已變更，請重新核對及儲存更正版本。",
        "accounting_approval_valid": "此版本核准仍有效",
        "accounting_unapproved_turnout": "此投票人數尚未有效核准；不會用作箱內選票估算。",
        "accounting_newer_revision": "伺服器資料已更新。保留目前輸入；請重新載入並核對後繼續。",
        "accounting_read_only": "此帳戶可查看帳目；只有已指派的點票人員可準備及提交。",
        "accounting_historical": "正在查看保留的歷史版本，只供閱讀及匯出。",
        "accounting_no_record": "尚未儲存帳目。請選擇來源並準備草稿。",
        "accounting_reload": "重新載入目前版本",
        "accounting_history": "保留版本",
        "accounting_report": "帳目預覽及匯出",
        "accounting_preview": "預覽此帳目版本",
        "accounting_discard": "捨棄未儲存的帳目變更並載入所選版本？",
        "accounting_validation": "請選擇有效來源版本，檢查備註及必填更正原因。",
        "accounting_state_conflict": "帳目狀態已變更，請重新載入並核對。",
        "accounting_record_not_found": "請先儲存或載入帳目版本。",
        "unsaved_accounting_changes": "帳目有未儲存的變更，請先儲存或明確捨棄。",
        "accounting_saved": "帳目草稿已儲存。",
        "accounting_submitted": "帳目已提交審核。",
        "accounting_approved": "此帳目版本已核准。",
        "accounting_report_ready": "已載入所選帳目版本的報表。",
        "accounting_exported": "帳目報表已匯出。",
        "accounting_export_failed": "未能匯出帳目，請檢查檔案位置並重試。",
        "accounting_received_quantity": "收到選票總數",
        "accounting_ordinary_received_quantity": "收到普通選票",
        "accounting_ordinary_central_unissued_quantity": "中央未發普通選票",
        "accounting_ordinary_at_desks_quantity": "櫃台剩餘普通選票",
        "accounting_replacement_unissued_quantity": "未用補發儲備",
        "accounting_tendered_unissued_quantity": "未用重複選票儲備",
        "accounting_ordinary_issued_quantity": "存量衍生普通發票",
        "accounting_replacement_issued_quantity": "已發補發選票",
        "accounting_spoilt_original_quantity": "交回損壞原票",
        "accounting_tendered_issued_quantity": "已發重複選票",
        "accounting_retrieved_refused_quantity": "拒絕接收而收回",
        "accounting_retrieved_found_quantity": "站內尋回未用選票",
        "accounting_retrieved_held_quantity": "暫存待領未用選票",
        "accounting_retrieved_unused_quantity": "收回未用選票合計",
        "accounting_never_issued_quantity": "從未發出票數合計",
        "accounting_estimated_box_from_stock_quantity": "按存量估算箱內票數",
        "accounting_estimated_box_from_turnout_quantity": "按核准人數估算箱內票數",
        "accounting_observed_counted_quantity": "實際點算張數（尚未觀察）",
    },
    "sc": {
        "accounting_title": "选票账目",
        "accounting_provenance_external_manual": "人工提供的外部数字",
        "accounting_provenance_fallback_stock": "后备普通库存推算",
        "accounting_provenance_mixed": "正常及后备涵盖时段",
        "accounting_provenance_external_reconciled": "已核对恢复外部数字",
        "accounting_not_found": "此票站尚未保存账目。",
        "accounting_reason_required": "请填写更正已提交或核准账目的原因。",
        "accounting_balance_invalid": "来源账目数量不平衡，请核对存量及各类选票。",
        "accounting_turnout_time_invalid": "投票人数时段晚于选票观察，请选择相符的来源。",
        "accounting_intro": "按来源票站准备选票账目；保存所选来源版本，供其后点票使用。",
        "accounting_sources": "账目来源",
        "accounting_special_source": "特别及未用选票观察版本",
        "accounting_choose_special": "请选择来源观察",
        "accounting_turnout_source": "投票人数来源（可不选）",
        "accounting_no_turnout": "未选投票人数来源",
        "accounting_source_hint": "来源观察包含柜台存量、收到选票及各类选票的版本。",
        "accounting_turnout_hint": (
            "保留已提供人数及核准状态。只有有效核准的累计人数用作人数基础估算。"
        ),
        "accounting_notes": "核对备注",
        "accounting_reason": "更正原因（已提交或核准的账目必填）",
        "accounting_save": "保存账目草稿",
        "accounting_correct": "保留原版并更正",
        "accounting_submit": "提交账目审核",
        "accounting_approve": "核准此账目版本",
        "accounting_summary": "账目及箱内选票估算",
        "accounting_estimate_hint": (
            "估算已扣除领取后收回的未用选票。补发选票替代损坏原票，不再扣减一次。"
        ),
        "accounting_observed_hint": (
            "实际点算张数尚未观察；「—」不代表零。账目不会代填实际点算张数。"
        ),
        "accounting_provenance": "已保存来源版本",
        "accounting_stock_basis": "柜台存量来源",
        "accounting_special_basis": "特别及未用选票来源",
        "accounting_turnout_basis": "投票人数及其来源",
        "accounting_supplied_total": "提供的累计投票人数",
        "accounting_approved_total": "核准衍生累计投票人数",
        "accounting_source_current": "来源版本仍有效",
        "accounting_source_stale": "来源已变更，请重新核对及保存更正版本。",
        "accounting_approval_valid": "此版本核准仍有效",
        "accounting_unapproved_turnout": "此投票人数尚未有效核准；不会用作箱内选票估算。",
        "accounting_newer_revision": "服务器数据已更新。保留目前输入；请重新载入并核对后继续。",
        "accounting_read_only": "此账户可查看账目；只有已指派的点票人员可准备及提交。",
        "accounting_historical": "正在查看保留的历史版本，只供阅读及导出。",
        "accounting_no_record": "尚未保存账目。请选择来源并准备草稿。",
        "accounting_reload": "重新载入目前版本",
        "accounting_history": "保留版本",
        "accounting_report": "账目预览及导出",
        "accounting_preview": "预览此账目版本",
        "accounting_discard": "舍弃未保存的账目变更并载入所选版本？",
        "accounting_validation": "请选择有效来源版本，检查备注及必填更正原因。",
        "accounting_state_conflict": "账目状态已变更，请重新载入并核对。",
        "accounting_record_not_found": "请先保存或载入账目版本。",
        "unsaved_accounting_changes": "账目有未保存的变更，请先保存或明确舍弃。",
        "accounting_saved": "账目草稿已保存。",
        "accounting_submitted": "账目已提交审核。",
        "accounting_approved": "此账目版本已核准。",
        "accounting_report_ready": "已载入所选账目版本的报表。",
        "accounting_exported": "账目报表已导出。",
        "accounting_export_failed": "未能导出账目，请检查文件位置并重试。",
        "accounting_received_quantity": "收到选票总数",
        "accounting_ordinary_received_quantity": "收到普通选票",
        "accounting_ordinary_central_unissued_quantity": "中央未发普通选票",
        "accounting_ordinary_at_desks_quantity": "柜台剩余普通选票",
        "accounting_replacement_unissued_quantity": "未用补发储备",
        "accounting_tendered_unissued_quantity": "未用重复选票储备",
        "accounting_ordinary_issued_quantity": "存量衍生普通发票",
        "accounting_replacement_issued_quantity": "已发补发选票",
        "accounting_spoilt_original_quantity": "交回损坏原票",
        "accounting_tendered_issued_quantity": "已发重复选票",
        "accounting_retrieved_refused_quantity": "拒绝接收而收回",
        "accounting_retrieved_found_quantity": "站内寻回未用选票",
        "accounting_retrieved_held_quantity": "暂存待领未用选票",
        "accounting_retrieved_unused_quantity": "收回未用选票合计",
        "accounting_never_issued_quantity": "从未发出票数合计",
        "accounting_estimated_box_from_stock_quantity": "按存量估算箱内票数",
        "accounting_estimated_box_from_turnout_quantity": "按核准人数估算箱内票数",
        "accounting_observed_counted_quantity": "实际点算张数（尚未观察）",
    },
    "en": {
        "accounting_title": "Stock accounting",
        "accounting_provenance_external_manual": "Manually supplied external figures",
        "accounting_provenance_fallback_stock": "Fallback ordinary stock",
        "accounting_provenance_mixed": "Normal and fallback intervals",
        "accounting_provenance_external_reconciled": "Reconciled external recovery",
        "accounting_not_found": "No accounting has been saved for this station.",
        "accounting_reason_required": (
            "Give a reason for correcting submitted or approved accounting."
        ),
        "accounting_balance_invalid": (
            "Source quantities do not balance. Check stock and paper categories."
        ),
        "accounting_turnout_time_invalid": (
            "The turnout period ends after the paper observation. Choose compatible sources."
        ),
        "accounting_intro": (
            "Prepare source-station accounting and preserve selected revisions for later counting."
        ),
        "accounting_sources": "Accounting sources",
        "accounting_special_source": "Special and retrieved-paper observation revision",
        "accounting_choose_special": "Choose a source observation",
        "accounting_turnout_source": "Turnout source (optional)",
        "accounting_no_turnout": "No turnout source selected",
        "accounting_source_hint": (
            "The observation preserves desk balances, received stock and paper-category revisions."
        ),
        "accounting_turnout_hint": (
            "Supplied figures and approval remain separate. Only a "
            "valid approved cumulative figure produces the turnout estimate."
        ),
        "accounting_notes": "Reconciliation notes",
        "accounting_reason": "Correction reason (required after submission or approval)",
        "accounting_save": "Save accounting draft",
        "accounting_correct": "Preserve and correct revision",
        "accounting_submit": "Submit accounting for review",
        "accounting_approve": "Approve this accounting revision",
        "accounting_summary": "Accounting and box-paper estimates",
        "accounting_estimate_hint": (
            "Estimates subtract retrieved-unused papers. Replacements "
            "substitute for surrendered originals without a second deduction."
        ),
        "accounting_observed_hint": (
            "Actual counted papers have not been observed. "
            "An em dash means missing, and does not mean zero."
        ),
        "accounting_provenance": "Saved source revisions",
        "accounting_stock_basis": "Desk-stock basis",
        "accounting_special_basis": "Special and retrieved-paper basis",
        "accounting_turnout_basis": "Turnout and its provenance",
        "accounting_supplied_total": "Supplied cumulative turnout",
        "accounting_approved_total": "Approved derived cumulative turnout",
        "accounting_source_current": "Source revisions remain current",
        "accounting_source_stale": (
            "Sources changed. Review them and save a corrected accounting revision."
        ),
        "accounting_approval_valid": "Approval of this revision remains valid",
        "accounting_unapproved_turnout": (
            "This turnout source has no valid approval and does not produce a box-paper estimate."
        ),
        "accounting_newer_revision": (
            "Server data changed. Your input is retained; reload and review before continuing."
        ),
        "accounting_read_only": (
            "This account can view accounting. Assigned Counting Officers prepare and submit it."
        ),
        "accounting_historical": (
            "Viewing a preserved historical revision for reading and export."
        ),
        "accounting_no_record": ("No accounting is saved yet. Select sources to prepare a draft."),
        "accounting_reload": "Reload current revision",
        "accounting_history": "Preserved revisions",
        "accounting_report": "Accounting preview and export",
        "accounting_preview": "Preview this accounting revision",
        "accounting_discard": (
            "Discard unsaved accounting changes and load the selected revision?"
        ),
        "accounting_validation": (
            "Choose valid source revisions and check notes and the required correction reason."
        ),
        "accounting_state_conflict": "Accounting status changed. Reload and review it.",
        "accounting_record_not_found": "Save or load an accounting revision first.",
        "unsaved_accounting_changes": (
            "Accounting has unsaved changes. Save or explicitly discard them first."
        ),
        "accounting_saved": "Accounting draft saved.",
        "accounting_submitted": "Accounting submitted for review.",
        "accounting_approved": "This accounting revision is approved.",
        "accounting_report_ready": "Report loaded for the selected accounting revision.",
        "accounting_exported": "Accounting report exported.",
        "accounting_export_failed": (
            "Accounting export failed. Check the file location and retry."
        ),
        "accounting_received_quantity": "Total received papers",
        "accounting_ordinary_received_quantity": "Ordinary papers received",
        "accounting_ordinary_central_unissued_quantity": "Central unissued ordinary stock",
        "accounting_ordinary_at_desks_quantity": "Ordinary stock remaining at desks",
        "accounting_replacement_unissued_quantity": "Unused replacement reserve",
        "accounting_tendered_unissued_quantity": "Unused tendered reserve",
        "accounting_ordinary_issued_quantity": "Stock-derived ordinary issues",
        "accounting_replacement_issued_quantity": "Replacement papers issued",
        "accounting_spoilt_original_quantity": "Surrendered spoilt originals",
        "accounting_tendered_issued_quantity": "Tendered papers issued",
        "accounting_retrieved_refused_quantity": "Retrieved after refusal",
        "accounting_retrieved_found_quantity": "Retrieved after being found",
        "accounting_retrieved_held_quantity": "Held pending return",
        "accounting_retrieved_unused_quantity": "Total retrieved-unused papers",
        "accounting_never_issued_quantity": "Total never-issued stock",
        "accounting_estimated_box_from_stock_quantity": "Box-paper estimate from stock",
        "accounting_estimated_box_from_turnout_quantity": (
            "Box-paper estimate from approved turnout"
        ),
        "accounting_observed_counted_quantity": "Actual counted papers (not yet observed)",
    },
}
