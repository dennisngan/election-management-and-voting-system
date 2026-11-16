"""Counting-scope editor labels in the three supported desktop languages."""

COUNTING_SCOPE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "counting_scopes_title": "點票範圍",
        "counting_scopes_intro": ("選取此點票站收到的票箱，並保留來源票站帳目版本作為點票依據。"),
        "counting_scope_context": "點票站及選區",
        "counting_scope_list": "已儲存點票範圍",
        "counting_scope_new": "新增點票範圍",
        "counting_scope_no_scopes": "尚未準備點票範圍。",
        "counting_scope_submitted_status": "已提交",
        "counting_scope_reference": "點票範圍編號",
        "counting_scope_event_at": "事件時間（香港時間）",
        "counting_scope_boxes": "目前可用票箱",
        "counting_scope_box_basis": "已選票箱依據",
        "counting_scope_frozen_box_basis": "已保存票箱依據",
        "counting_scope_accounting": "可選的目前來源版本",
        "counting_scope_accounting_basis": "已保存來源帳目依據",
        "counting_scope_p18_reference": "編號及版本",
        "counting_scope_source_received_quantity": "來源收到選票總數",
        "counting_scope_source_replacement_quantity": "來源未用補發儲備",
        "counting_scope_report": "點票範圍預覽及匯出",
        "counting_scope_preview": "預覽此點票範圍版本",
        "counting_scope_report_ready": "已載入所選點票範圍版本的預覽。",
        "counting_scope_exported": "點票範圍報表已匯出。",
        "counting_scope_export_failed": "未能匯出點票範圍報表，請檢查檔案位置並重試。",
        "counting_scope_not_found": "請先載入已保存的點票範圍版本。",
        "counting_scope_notes": "核對備註",
        "counting_scope_reason": "更正原因",
        "counting_scope_save": "儲存點票範圍",
        "counting_scope_submit": "提交點票範圍",
        "counting_scope_refresh": "重新整理點票範圍",
        "counting_scope_reload": "捨棄變更並重新載入已保存版本",
        "counting_scope_discard": "捨棄未儲存變更並載入最新的已保存版本？",
        "counting_scope_status": "狀態",
        "counting_scope_revision": "點票範圍版本",
        "counting_scope_blockers": "待處理項目",
        "counting_scope_no_blockers": "目前沒有阻止點票的項目。",
        "counting_scope_whole_station_warning": (
            "未包括該來源票站所有已知票箱；不會提供來源票站 整體箱內票數估算。"
        ),
        "counting_scope_stock_estimate": "按存量估算箱內票數",
        "counting_scope_turnout_estimate": "按人數估算箱內票數",
        "counting_scope_coverage": "來源票站票箱涵蓋",
        "counting_scope_source": "來源票站",
        "counting_scope_no_accounting": "尚無可供選用的來源帳目。",
        "counting_scope_current_accounting": "使用目前第 %1 版",
        "counting_scope_no_accounting_selected": "不選帳目版本",
        "counting_scope_read_only": "此帳戶可查看點票範圍；只有已指派的點票人員可準備或提交。",
        "counting_scope_historical": "正在查看保留版本，只供閱讀。",
        "counting_scope_stale": "來源依據已變更，請重新載入並核對。",
        "counting_scope_unsaved": "目前點票範圍有未儲存變更。",
        "counting_scope_saved": "點票範圍草稿已儲存。",
        "counting_scope_submitted": "點票範圍已提交。",
        "counting_scope_not_ready": "請先完成所有點票範圍依據及收箱核對。",
        "counting_scope_validation": "請輸入有效編號、香港時間，並核對所選票箱及來源帳目。",
        "counting_scope_box_received": "已收箱",
        "counting_scope_box_pending": "尚未收箱",
        "counting_scope_box_in_scope": "已加入點票範圍",
        "counting_scope_estimate_warning": (
            "不同來源票箱一併點算時，候選人票數不可歸屬至 個別來源票站。"
        ),
        "scope_reason_required": "已提交點票範圍的更正必須說明原因。",
        "scope_state_conflict": "另一位職員已變更此點票範圍的提交狀態；請重新載入後再繼續。",
        "scope_reference_conflict": "此點票站已使用該點票範圍編號。",
        "box_already_in_scope": "所選票箱已加入另一個點票範圍。",
        "scope_membership_conflict": "另一項操作已把所選票箱加入其他點票範圍；請重新整理。",
        "scope_incomplete": "點票範圍仍有未完成項目，請核對收箱及來源帳目。",
        "scope_accounting_origin_mismatch": "所選帳目來源不符合票箱的來源票站。",
        "accounting_receipt_required": "必須先記錄收箱，才可選用來源帳目。",
        "scope_reference_immutable": "已保存的點票範圍編號不可更改。",
        "box_revision_conflict": "所選票箱已有更新版本，請重新整理並核對。",
    },
    "sc": {
        "counting_scopes_title": "点票范围",
        "counting_scopes_intro": ("选择此点票站收到的票箱，并保留来源票站账目版本作为点票依据。"),
        "counting_scope_context": "点票站及选区",
        "counting_scope_list": "已保存点票范围",
        "counting_scope_new": "新增点票范围",
        "counting_scope_no_scopes": "尚未准备点票范围。",
        "counting_scope_submitted_status": "已提交",
        "counting_scope_reference": "点票范围编号",
        "counting_scope_event_at": "事件时间（香港时间）",
        "counting_scope_boxes": "目前可用票箱",
        "counting_scope_box_basis": "已选票箱依据",
        "counting_scope_frozen_box_basis": "已保存票箱依据",
        "counting_scope_accounting": "可选的目前来源版本",
        "counting_scope_accounting_basis": "已保存来源账目依据",
        "counting_scope_p18_reference": "编号及版本",
        "counting_scope_source_received_quantity": "来源收到选票总数",
        "counting_scope_source_replacement_quantity": "来源未用补发储备",
        "counting_scope_report": "点票范围预览及导出",
        "counting_scope_preview": "预览此点票范围版本",
        "counting_scope_report_ready": "已载入所选点票范围版本的预览。",
        "counting_scope_exported": "点票范围报表已导出。",
        "counting_scope_export_failed": "未能导出点票范围报表，请检查文件位置并重试。",
        "counting_scope_not_found": "请先载入已保存的点票范围版本。",
        "counting_scope_notes": "核对备注",
        "counting_scope_reason": "更正原因",
        "counting_scope_save": "保存点票范围",
        "counting_scope_submit": "提交点票范围",
        "counting_scope_refresh": "刷新点票范围",
        "counting_scope_reload": "舍弃变更并重新载入已保存版本",
        "counting_scope_discard": "舍弃未保存变更并载入最新的已保存版本？",
        "counting_scope_status": "状态",
        "counting_scope_revision": "点票范围版本",
        "counting_scope_blockers": "待处理项目",
        "counting_scope_no_blockers": "目前没有阻止点票的项目。",
        "counting_scope_whole_station_warning": (
            "未包括该来源票站所有已知票箱；不会提供来源票站 整体箱内票数估算。"
        ),
        "counting_scope_stock_estimate": "按库存估算箱内票数",
        "counting_scope_turnout_estimate": "按人数估算箱内票数",
        "counting_scope_coverage": "来源票站票箱涵盖",
        "counting_scope_source": "来源票站",
        "counting_scope_no_accounting": "尚无可供选择的来源账目。",
        "counting_scope_current_accounting": "使用目前第 %1 版",
        "counting_scope_no_accounting_selected": "不选账目版本",
        "counting_scope_read_only": "此账户可查看点票范围；只有已指派的点票人员可准备或提交。",
        "counting_scope_historical": "正在查看保留版本，只供阅读。",
        "counting_scope_stale": "来源依据已变更，请重新载入并核对。",
        "counting_scope_unsaved": "目前点票范围有未保存变更。",
        "counting_scope_saved": "点票范围草稿已保存。",
        "counting_scope_submitted": "点票范围已提交。",
        "counting_scope_not_ready": "请先完成所有点票范围依据及收箱核对。",
        "counting_scope_validation": "请输入有效编号、香港时间，并核对所选票箱及来源账目。",
        "counting_scope_box_received": "已收箱",
        "counting_scope_box_pending": "尚未收箱",
        "counting_scope_box_in_scope": "已加入点票范围",
        "counting_scope_estimate_warning": (
            "不同来源票箱一并点算时，候选人票数不可归属至 个别来源票站。"
        ),
        "scope_reason_required": "已提交点票范围的更正必须说明原因。",
        "scope_state_conflict": "另一位职员已更改此点票范围的提交状态；请重新加载后再继续。",
        "scope_reference_conflict": "此点票站已使用该点票范围编号。",
        "box_already_in_scope": "所选票箱已加入另一个点票范围。",
        "scope_membership_conflict": "另一项操作已把所选票箱加入其他点票范围；请刷新。",
        "scope_incomplete": "点票范围仍有未完成项目，请核对收箱及来源账目。",
        "scope_accounting_origin_mismatch": "所选账目来源不符合票箱的来源票站。",
        "accounting_receipt_required": "必须先记录收箱，才可选择来源账目。",
        "scope_reference_immutable": "已保存的点票范围编号不可更改。",
        "box_revision_conflict": "所选票箱已有更新版本，请刷新并核对。",
    },
    "en": {
        "counting_scopes_title": "Counting scopes",
        "counting_scopes_intro": (
            "Choose boxes received at this counting station and retain each source station’s "
            "revision as count provenance."
        ),
        "counting_scope_context": "Counting station and constituency",
        "counting_scope_list": "Saved counting scopes",
        "counting_scope_new": "New counting scope",
        "counting_scope_no_scopes": "No counting scope has been prepared.",
        "counting_scope_submitted_status": "Submitted",
        "counting_scope_reference": "Counting scope reference",
        "counting_scope_event_at": "Event time (Hong Kong time)",
        "counting_scope_boxes": "Current box records",
        "counting_scope_box_basis": "Selected box basis",
        "counting_scope_frozen_box_basis": "Saved box basis",
        "counting_scope_accounting": "Current available source revision",
        "counting_scope_accounting_basis": "Saved source accounting basis",
        "counting_scope_p18_reference": "Record and revision",
        "counting_scope_source_received_quantity": "Source papers received",
        "counting_scope_source_replacement_quantity": "Source unused replacement reserve",
        "counting_scope_report": "Counting scope preview and export",
        "counting_scope_preview": "Preview this counting scope revision",
        "counting_scope_report_ready": "Preview loaded for the selected counting scope revision.",
        "counting_scope_exported": "Counting scope report exported.",
        "counting_scope_export_failed": (
            "Could not export the counting scope report. Check the file location and try again."
        ),
        "counting_scope_not_found": "Load a saved counting scope revision first.",
        "counting_scope_notes": "Review notes",
        "counting_scope_reason": "Amendment reason",
        "counting_scope_save": "Save counting scope",
        "counting_scope_submit": "Submit counting scope",
        "counting_scope_refresh": "Refresh counting scopes",
        "counting_scope_reload": "Discard changes and reload the saved revision",
        "counting_scope_discard": "Discard unsaved changes and load the latest saved revision?",
        "counting_scope_status": "Status",
        "counting_scope_revision": "Counting scope revision",
        "counting_scope_blockers": "Items to resolve",
        "counting_scope_no_blockers": "No current blocker prevents count entry.",
        "counting_scope_whole_station_warning": (
            "Not all known boxes from this source station are included; no whole-station "
            "box-paper estimate is shown."
        ),
        "counting_scope_stock_estimate": "Estimated box papers from stock",
        "counting_scope_turnout_estimate": "Estimated box papers from turnout",
        "counting_scope_coverage": "Source station box coverage",
        "counting_scope_source": "Source station",
        "counting_scope_no_accounting": "No source accounting revision is available.",
        "counting_scope_current_accounting": "Use current revision %1",
        "counting_scope_no_accounting_selected": "No accounting revision",
        "counting_scope_read_only": (
            "This account can view counting scopes; only an assigned Counting Officer can "
            "prepare or submit one."
        ),
        "counting_scope_historical": "Viewing a retained revision. This view is read-only.",
        "counting_scope_stale": (
            "The source basis has changed. Reload and review it before continuing."
        ),
        "counting_scope_unsaved": "This counting scope has unsaved changes.",
        "counting_scope_saved": "Counting scope draft saved.",
        "counting_scope_submitted": "Counting scope submitted.",
        "counting_scope_not_ready": (
            "Resolve the counting scope basis and receipt checks before submitting."
        ),
        "counting_scope_validation": (
            "Enter a valid reference and Hong Kong time, then review the selected boxes and "
            "source accounting."
        ),
        "counting_scope_box_received": "Received",
        "counting_scope_box_pending": "Receipt pending",
        "counting_scope_box_in_scope": "Already assigned to scope",
        "counting_scope_estimate_warning": (
            "When boxes from different source stations are counted together, candidate votes "
            "cannot be attributed to each source station."
        ),
        "scope_reason_required": "A reason is required to amend a submitted counting scope.",
        "scope_state_conflict": (
            "Another staff member changed this scope’s submission state. "
            "Reload it before continuing."
        ),
        "scope_reference_conflict": (
            "This counting scope reference is already used at this station."
        ),
        "box_already_in_scope": "The selected box already belongs to another counting scope.",
        "scope_membership_conflict": (
            "Another operation added this box to a different scope. Refresh and review the box set."
        ),
        "scope_incomplete": (
            "Resolve the box receipt and source accounting blockers before submitting."
        ),
        "scope_accounting_origin_mismatch": (
            "The accounting source does not match a selected box origin."
        ),
        "accounting_receipt_required": (
            "Record the box receipt before selecting its source accounting."
        ),
        "scope_reference_immutable": "A saved counting scope reference cannot be changed.",
        "box_revision_conflict": "The selected box has a newer revision. Refresh and review it.",
    },
}
