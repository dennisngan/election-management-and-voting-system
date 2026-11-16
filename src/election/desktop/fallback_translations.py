"""Material EPR fallback activation and review labels in three languages."""

FALLBACK_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "fallback_title": "EPR 後備模式",
        "fallback_mode_normal": "正常外部數字模式",
        "fallback_mode_stock": "後備庫存推算模式",
        "fallback_intro": (
            "使用原始事件時間、已確認的外部累計數字及同時刻完整"
            "結餘。主管確認後才啟用後備推算；此應用程式仍連接中央伺服器。"
        ),
        "fallback_records": "啟用與恢復記錄",
        "fallback_empty": "本站尚無已儲存的後備模式記錄。",
        "fallback_choose_record": "選擇已儲存記錄",
        "fallback_activation": "後備啟用基礎",
        "fallback_event_time": "原始事件時間（香港時間 YYYY-MM-DD HH:mm，可含秒及微秒）",
        "fallback_cumulative": "事件時的外部累計人數",
        "fallback_snapshot_id": "記錄編號",
        "fallback_snapshot_revision": "修訂版本",
        "fallback_snapshot_hint": (
            "選擇與事件時間完全相同、目前有效且所有櫃台已申報的記錄及版本。"
        ),
        "fallback_source": "外部數字來源及涵蓋說明",
        "fallback_save": "儲存啟用草稿",
        "fallback_submit": "提交主管覆核",
        "fallback_frozen_source": "已保留的普通庫存基礎",
        "fallback_remaining": "櫃台普通選票結餘",
        "fallback_ordinary_issued": "庫存推算普通發票數量",
        "fallback_counter": "發票櫃台",
        "fallback_history": "所選記錄的修訂歷史",
        "fallback_approval": "主管確認",
        "fallback_approval_hint": "核對已儲存的來源及櫃台結餘，再以自己的目前密碼確認此版本。",
        "fallback_approval_password": "主管目前密碼",
        "fallback_approve": "確認啟用版本",
        "fallback_kind_activation": "啟用",
        "fallback_kind_recovery": "恢復",
        "fallback_status_draft": "草稿",
        "fallback_status_submitted": "待主管確認",
        "fallback_status_approved": "已確認",
        "fallback_historical": "此為歷史版本，只供查看。",
        "fallback_saved": "後備模式草稿已儲存至中央伺服器。",
        "fallback_submitted": "已提交此版本，等待主管確認。",
        "fallback_approved": "此版本已由主管確認。",
        "fallback_newer_revision": (
            "伺服器來源或記錄已有更新；已保留正在檢視的版本及未儲存內容，請核對後重新載入。"
        ),
        "unsaved_fallback_changes": (
            "後備模式表格有未儲存內容。請儲存，或明確捨棄後才切換記錄、版本或重新載入。"
        ),
        "fallback_validation": "請核對原始香港時間、非負整數累計人數、記錄／版本及來源說明。",
        "fallback_review_required": "所選來源或時間表已有變更，請重新載入目前版本並覆核。",
        "fallback_state_conflict": "此記錄的狀態已改變，請重新載入後再操作。",
        "fallback_record_not_found": "找不到所選後備模式記錄，請重新整理。",
        "fallback_revision_not_found": "找不到所選修訂版本，請重新整理。",
        "fallback_balance_time_required": "觀察時間必須與啟用／恢復事件時間相同。",
        "fallback_source_conflict": "所選後備來源與目前已確認的模式事件不一致，請核對記錄。",
        "fallback_stock_regression": "普通發票數量比啟用基礎更低，請核對所選版本。",
        "fallback_new_activation": "新增後備啟用",
        "fallback_new_recovery": "記錄恢復外部數字",
        "fallback_recovery": "恢復核對基礎",
        "fallback_parent_activation_id": "原啟用記錄編號",
        "fallback_parent_activation_revision": "原啟用確認版本",
        "fallback_reason": "恢復／修正原因",
        "fallback_save_recovery": "儲存恢復草稿",
        "fallback_approve_recovery": "確認恢復版本",
        "fallback_reconciliation": "恢復核對比較",
        "fallback_stock_cumulative": "庫存推算累計人數",
        "fallback_recovered_cumulative": "恢復後外部累計人數",
        "fallback_reconciliation_difference": "外部與庫存推算差額",
        "fallback_reconciliation_hint": (
            "保留伺服器計算的庫存基礎與外部恢復數字。主管確認後返回外部數字模式；相關"
            "投票人數報表仍須重新覆核。"
        ),
        "fallback_begin_amend": "建立有原因的修正",
        "fallback_correction": "有原因的修正",
        "fallback_amend_save": "儲存修正版本",
        "fallback_amended": "修正版本已儲存；請提交並重新由主管確認。",
    },
    "sc": {
        "fallback_title": "EPR 后备模式",
        "fallback_mode_normal": "正常外部数字模式",
        "fallback_mode_stock": "后备库存推算模式",
        "fallback_intro": (
            "使用原始事件时间、已确认的外部累计数字及同时刻完整"
            "结余。主管确认后才启用后备推算；此应用程序仍连接中央服务器。"
        ),
        "fallback_records": "启用与恢复记录",
        "fallback_empty": "本站尚无已保存的后备模式记录。",
        "fallback_choose_record": "选择已保存记录",
        "fallback_activation": "后备启用依据",
        "fallback_event_time": "原始事件时间（香港时间 YYYY-MM-DD HH:mm，可含秒及微秒）",
        "fallback_cumulative": "事件时的外部累计人数",
        "fallback_snapshot_id": "记录编号",
        "fallback_snapshot_revision": "修订版本",
        "fallback_snapshot_hint": (
            "选择与事件时间完全相同、当前有效且所有柜台已申报的记录及版本。"
        ),
        "fallback_source": "外部数字来源及覆盖说明",
        "fallback_save": "保存启用草稿",
        "fallback_submit": "提交主管复核",
        "fallback_frozen_source": "已保留的普通库存依据",
        "fallback_remaining": "柜台普通选票结余",
        "fallback_ordinary_issued": "库存推算普通发票数量",
        "fallback_counter": "发票柜台",
        "fallback_history": "所选记录的修订历史",
        "fallback_approval": "主管确认",
        "fallback_approval_hint": "核对已保存的来源及柜台结余，再以自己的当前密码确认此版本。",
        "fallback_approval_password": "主管当前密码",
        "fallback_approve": "确认启用版本",
        "fallback_kind_activation": "启用",
        "fallback_kind_recovery": "恢复",
        "fallback_status_draft": "草稿",
        "fallback_status_submitted": "待主管确认",
        "fallback_status_approved": "已确认",
        "fallback_historical": "此为历史版本，仅供查看。",
        "fallback_saved": "后备模式草稿已保存至中央服务器。",
        "fallback_submitted": "已提交此版本，等待主管确认。",
        "fallback_approved": "此版本已由主管确认。",
        "fallback_newer_revision": (
            "服务器来源或记录已有更新；已保留正在检视的版本及未保存内容，请核对后重新载入。"
        ),
        "unsaved_fallback_changes": (
            "后备模式表格有未保存内容。请保存，或明确舍弃后才切换记录、版本或重新载入。"
        ),
        "fallback_validation": "请核对原始香港时间、非负整数累计人数、记录／版本及来源说明。",
        "fallback_review_required": "所选来源或时间表已有变更，请重新载入当前版本并复核。",
        "fallback_state_conflict": "此记录的状态已改变，请重新载入后再操作。",
        "fallback_record_not_found": "找不到所选后备模式记录，请重新整理。",
        "fallback_revision_not_found": "找不到所选修订版本，请重新整理。",
        "fallback_balance_time_required": "观察时间必须与启用／恢复事件时间相同。",
        "fallback_source_conflict": "所选后备来源与当前已确认的模式事件不一致，请核对记录。",
        "fallback_stock_regression": "普通发票数量比启用依据更低，请核对所选版本。",
        "fallback_new_activation": "新增后备启用",
        "fallback_new_recovery": "记录恢复外部数字",
        "fallback_recovery": "恢复核对依据",
        "fallback_parent_activation_id": "原启用记录编号",
        "fallback_parent_activation_revision": "原启用确认版本",
        "fallback_reason": "恢复／修正原因",
        "fallback_save_recovery": "保存恢复草稿",
        "fallback_approve_recovery": "确认恢复版本",
        "fallback_reconciliation": "恢复核对比较",
        "fallback_stock_cumulative": "库存推算累计人数",
        "fallback_recovered_cumulative": "恢复后外部累计人数",
        "fallback_reconciliation_difference": "外部与库存推算差额",
        "fallback_reconciliation_hint": (
            "保留服务器计算的库存依据与外部恢复数字。主管确认后返回外部数字模式；相关"
            "投票人数报表仍须重新复核。"
        ),
        "fallback_begin_amend": "建立有原因的修正",
        "fallback_correction": "有原因的修正",
        "fallback_amend_save": "保存修正版本",
        "fallback_amended": "修正版本已保存；请提交并重新由主管确认。",
    },
    "en": {
        "fallback_title": "EPR fallback",
        "fallback_mode_normal": "Normal external-figure mode",
        "fallback_mode_stock": "Stock-derived fallback mode",
        "fallback_intro": (
            "Use the original event time, confirmed supplied cumulative turnout and a "
            "complete balance at that time. Supervisor confirmation activates "
            "fallback derivation while this app stays connected to the central server."
        ),
        "fallback_records": "Activation and recovery records",
        "fallback_empty": "No fallback-mode record is saved at this station.",
        "fallback_choose_record": "Choose a saved record",
        "fallback_activation": "Fallback activation basis",
        "fallback_event_time": (
            "Original event time (HKT YYYY-MM-DD HH:mm; optional seconds/microseconds)"
        ),
        "fallback_cumulative": "Supplied cumulative turnout at the event",
        "fallback_snapshot_id": "Record ID",
        "fallback_snapshot_revision": "Revision",
        "fallback_snapshot_hint": (
            "Use the current complete record/revision at exactly the same time, with "
            "every counter balance reported."
        ),
        "fallback_source": "Supplied figure source and coverage context",
        "fallback_save": "Save activation draft",
        "fallback_submit": "Submit for Supervisor review",
        "fallback_frozen_source": "Retained ordinary-stock basis",
        "fallback_remaining": "Ordinary papers remaining at counters",
        "fallback_ordinary_issued": "Stock-derived ordinary issuance",
        "fallback_counter": "Issuance counter",
        "fallback_history": "Selected record revision history",
        "fallback_approval": "Supervisor confirmation",
        "fallback_approval_hint": (
            "Review the saved source and counter balances, then confirm this revision with "
            "your own current password."
        ),
        "fallback_approval_password": "Supervisor current password",
        "fallback_approve": "Confirm activation revision",
        "fallback_kind_activation": "Activation",
        "fallback_kind_recovery": "Recovery",
        "fallback_status_draft": "Draft",
        "fallback_status_submitted": "Awaiting Supervisor confirmation",
        "fallback_status_approved": "Approved",
        "fallback_historical": "This historical revision is read-only.",
        "fallback_saved": "The fallback draft was saved to the central server.",
        "fallback_submitted": "This revision was submitted for Supervisor confirmation.",
        "fallback_approved": "This revision was confirmed by a Supervisor.",
        "fallback_newer_revision": (
            "A server source or record changed. Your reviewed revision and unsaved input "
            "are retained; compare them before reloading."
        ),
        "unsaved_fallback_changes": (
            "This fallback form has unsaved input. Save it or explicitly discard it before "
            "changing record/revision or reloading."
        ),
        "fallback_validation": (
            "Check the original HKT time, nonnegative whole-number cumulative turnout, "
            "record/revision and source context."
        ),
        "fallback_review_required": (
            "The selected source or schedule changed. Reload the current revision and "
            "review it again."
        ),
        "fallback_state_conflict": "This record's status changed. Reload it before continuing.",
        "fallback_record_not_found": (
            "The selected fallback record was not found. Refresh the list."
        ),
        "fallback_revision_not_found": "The selected revision was not found. Refresh the list.",
        "fallback_balance_time_required": (
            "The balance time must match the activation/recovery event time."
        ),
        "fallback_source_conflict": (
            "The selected fallback source conflicts with confirmed mode events. Review the "
            "saved records."
        ),
        "fallback_stock_regression": (
            "Ordinary issuance is lower than the activation basis. Review the selected revisions."
        ),
        "fallback_new_activation": "New fallback activation",
        "fallback_new_recovery": "Record external recovery",
        "fallback_recovery": "Recovery reconciliation basis",
        "fallback_parent_activation_id": "Original activation ID",
        "fallback_parent_activation_revision": "Original approved activation revision",
        "fallback_reason": "Recovery or correction reason",
        "fallback_save_recovery": "Save recovery draft",
        "fallback_approve_recovery": "Confirm recovery revision",
        "fallback_reconciliation": "Recovery comparison",
        "fallback_stock_cumulative": "Stock-derived cumulative turnout",
        "fallback_recovered_cumulative": "Recovered external cumulative turnout",
        "fallback_reconciliation_difference": "Recovered minus stock-derived difference",
        "fallback_reconciliation_hint": (
            "Retain the server-calculated stock basis and recovered external total. "
            "Supervisor confirmation returns to external-figure mode; affected "
            "periods still require renewed review."
        ),
        "fallback_begin_amend": "Prepare a reasoned correction",
        "fallback_correction": "Reasoned correction",
        "fallback_amend_save": "Save correction revision",
        "fallback_amended": (
            "The correction revision was saved. Submit it for renewed Supervisor confirmation."
        ),
    },
}
