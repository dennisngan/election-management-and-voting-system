"""F1 interface and backend error labels in the three supported languages."""

_LABELS: dict[str, tuple[str, str, str]] = {
    "f1_title": ("F1 初步點票", "F1 初步点票", "F1 initial tally"),
    "f1_entered_at": ("伺服器記錄時間", "服务器记录时间", "Server entry time"),
    "f1_reference_page": ("PDF 頁", "PDF 页", "PDF page"),
    "f1_printed_page": ("印刷頁", "印刷页", "Printed page"),
    "f1_edit_scope_basis": (
        "本表格採用的範圍版本",
        "本表格采用的范围版本",
        "Scope revision for these inputs",
    ),
    "f1_scope_stock_estimate": (
        "來源範圍庫存估算",
        "来源范围库存估算",
        "Scope estimate from stock",
    ),
    "f1_scope_turnout_estimate": (
        "來源範圍核准人數估算",
        "来源范围核准人数估算",
        "Scope estimate from approved turnout",
    ),
    "f1_intro": (
        "按已接收票箱範圍記錄候選人、明顯無效及問題選票；保留原始觀察與版本。",
        "按已接收票箱范围记录候选人、明显无效及问题选票；保留原始观察与版本。",
        "Record candidate votes, clearly invalid and questionable papers for a prepared box scope.",
    ),
    "f1_scope": ("點票範圍", "点票范围", "Counting scope"),
    "f1_choose_scope": ("請選擇點票範圍", "请选择点票范围", "Choose a counting scope"),
    "f1_scope_ready": ("可輸入點票", "可输入点票", "Ready for count entry"),
    "f1_scope_unready": (
        "來源尚未就緒／只供查看",
        "来源尚未就绪／仅供查看",
        "Not ready / view only",
    ),
    "f1_round": ("點票輪次", "点票轮次", "Count round"),
    "f1_initial_round": ("首次點票草稿", "首次点票草稿", "Initial round draft"),
    "f1_history": ("保留的點票版本", "保留的点票版本", "Preserved count revisions"),
    "f1_no_round": (
        "此範圍尚無 F1 草稿。空白數量代表尚未觀察，不代表零。",
        "此范围尚无 F1 草稿。空白数量代表尚未观察，不代表零。",
        "No F1 draft yet. Blank quantities are unobserved, not zero.",
    ),
    "f1_read_only": (
        "此帳戶可查看點票；只有已指派的點票人員可儲存 F1。",
        "此账户可查看点票；只有已指派的点票人员可保存 F1。",
        "This account can view counts. Assigned Counting Officers save F1 drafts.",
    ),
    "f1_historical": (
        "歷史版本只供查看；數字及原因用語保留原版本。",
        "历史版本仅供查看；数字及原因用语保留原版本。",
        "Historical revision: values and reason wording remain frozen and read-only.",
    ),
    "f1_newer": (
        "伺服器已有較新版本或原因目錄。輸入已保留；請核對後重新載入。",
        "服务器已有较新版本或原因目录。输入已保留；请核对后重新载入。",
        "A newer revision or reason catalog is available. Your inputs remain; review and reload.",
    ),
    "f1_event_at": (
        "原始點票觀察時間（香港時間）",
        "原始点票观察时间（香港时间）",
        "Original count observation time (Hong Kong time)",
    ),
    "f1_time_hint": (
        "年-月-日 時:分，可包括秒及微秒。",
        "年-月-日 时:分，可包括秒及微秒。",
        "YYYY-MM-DD HH:MM, optionally seconds and microseconds.",
    ),
    "f1_candidates": ("候選人初步有效票", "候选人初步有效票", "Initial valid votes per candidate"),
    "f1_invalid": ("明顯無效選票分類", "明显无效选票分类", "Clearly invalid papers by reason"),
    "f1_quantity": (
        "已觀察張數（空白為尚未觀察）",
        "已观察张数（空白为尚未观察）",
        "Observed quantity (blank is unobserved)",
    ),
    "f1_questionable": (
        "待判定問題選票",
        "待判定问题选票",
        "Questionable papers awaiting determination",
    ),
    "f1_actual": ("實際點算張數", "实际点算张数", "Actual counted papers"),
    "f1_explanation": (
        "分類說明（Other 有正數時必填）",
        "分类说明（Other 有正数时必填）",
        "Explanation (required for positive Other)",
    ),
    "f1_catalog_hint": (
        "新版本採用目前啟用的原因；已儲存用語在下方及歷史中保留。",
        "新版本采用当前启用的原因；已保存用语在下方及历史中保留。",
        "A new draft uses current enabled reasons; saved wording remains below and in history.",
    ),
    "f1_reference": ("參考來源", "参考来源", "Verified reference"),
    "f1_project_reason": ("專案設定分類", "项目设置分类", "Project-configured reason"),
    "f1_translation_note": (
        "中文為專案翻譯；以下保留參考英文及頁碼。",
        "中文为项目翻译；以下保留参考英文及页码。",
        "Display translations are project-provided; reference English and page are preserved.",
    ),
    "f1_retired_reason": (
        "此已儲存原因不再啟用。請清除或移往目前分類後儲存；歷史仍保留。",
        "此已保存原因不再启用。请清除或移往当前分类后保存；历史仍保留。",
        "This saved reason is no longer enabled. Clear or reclassify its count; history remains.",
    ),
    "f1_notes": ("點票備註", "点票备注", "Count notes"),
    "f1_amendment_reason": (
        "修訂說明（草稿可不填）",
        "修订说明（草稿可不填）",
        "Amendment note (optional for drafts)",
    ),
    "f1_save": ("儲存 F1 草稿", "保存 F1 草稿", "Save F1 draft"),
    "f1_saved": ("F1 草稿已儲存。", "F1 草稿已保存。", "F1 draft saved."),
    "f1_reload": ("重新載入已儲存點票", "重新载入已保存点票", "Reload saved count"),
    "f1_discard": (
        "捨棄未儲存的 F1 輸入並重新載入目前草稿？",
        "丢弃未保存的 F1 输入并重新载入当前草稿？",
        "Discard unsaved F1 inputs and reload the current saved draft?",
    ),
    "f1_saved_summary": ("已儲存 F1 觀察", "已保存 F1 观察", "Saved F1 observations"),
    "f1_initial_valid_quantity": ("初步有效票合計", "初步有效票合计", "Initial valid votes total"),
    "f1_clearly_invalid_quantity": ("明顯無效票合計", "明显无效票合计", "Clearly invalid total"),
    "f1_initial_accounted_quantity": (
        "初步分類張數合計",
        "初步分类张数合计",
        "Initial accounted papers",
    ),
    "f1_questionable_quantity": ("問題選票張數", "问题选票张数", "Questionable papers"),
    "f1_actual_counted_quantity": (
        "已觀察實際點算張數",
        "已观察实际点算张数",
        "Observed actual counted papers",
    ),
    "f1_complete": (
        "F1 所需數字齊全且算術相符。",
        "F1 所需数字齐全且算术相符。",
        "F1 inputs are complete and balanced.",
    ),
    "f1_incomplete": (
        "F1 尚有未觀察數字。請保留空白，待觀察後補錄。",
        "F1 尚有未观察数字。请保留空白，待观察后补录。",
        "F1 has unobserved quantities. Keep them blank until observed.",
    ),
    "f1_scope_basis": (
        "已儲存的票箱及來源核算基礎",
        "已保存的票箱及来源核算依据",
        "Saved box and accounting basis",
    ),
    "f1_estimate_note": (
        "來源估算與實際觀察分開；混合點票不歸於每個來源站。",
        "来源估算与实际观察分开；混合点票不归于每个来源站。",
        "Source estimates are separate from actual observations; mixed votes are not "
        "attributed to each origin.",
    ),
    "f1_saved_reasons": (
        "已儲存原因用語及數字",
        "已保存原因用语及数字",
        "Saved reason wording and quantities",
    ),
    "f1_report": ("F1 預覽及匯出", "F1 预览及导出", "F1 preview and export"),
    "f1_preview": ("預覽已儲存 F1 版本", "预览已保存 F1 版本", "Preview saved F1 revision"),
    "f1_report_ready": (
        "已載入此 F1 版本預覽。",
        "已载入此 F1 版本预览。",
        "F1 revision preview loaded.",
    ),
    "f1_exported": ("F1 報表已匯出。", "F1 报表已导出。", "F1 report exported."),
    "f1_export_failed": (
        "未能匯出 F1；請檢查路徑及連線。",
        "未能导出 F1；请检查路径及连接。",
        "F1 export failed. Check the destination and connection.",
    ),
    "f1_validation": (
        "請核對 F1 輸入及文字長度。",
        "请核对 F1 输入及文字长度。",
        "Check F1 inputs and text lengths.",
    ),
    "f1_time_invalid": (
        "請輸入有效的香港原始觀察時間。",
        "请输入有效的香港原始观察时间。",
        "Enter a valid original Hong Kong observation time.",
    ),
    "f1_quantity_invalid": (
        "張數須為非負整數；尚未觀察請留空。",
        "张数须为非负整数；尚未观察请留空。",
        "Use nonnegative whole quantities; leave unobserved values blank.",
    ),
    "unsaved_f1_changes": (
        "F1 有未儲存內容。請先儲存或明確捨棄後切換／預覽。",
        "F1 有未保存内容。请先保存或明确丢弃后切换／预览。",
        "F1 has unsaved inputs. Save or explicitly discard before switching or previewing.",
    ),
    "count_candidate_invalid": (
        "候選人不屬於此點票範圍，請重新載入。",
        "候选人不属于此点票范围，请重新载入。",
        "The candidate does not belong to this scope. Reload its candidate list.",
    ),
    "count_invalid_reason_invalid": (
        "無效票原因不適用於此 F1，請重新載入。",
        "无效票原因不适用于此 F1，请重新载入。",
        "The invalid-paper reason is not available for this F1. Reload its catalog.",
    ),
    "invalid_reason_revision_conflict": (
        "原因目錄已有變更。輸入已保留，請重新載入並核對分類。",
        "原因目录已有变更。输入已保留，请重新载入并核对分类。",
        "The reason catalog changed. Inputs remain; reload and reconcile the classifications.",
    ),
    "invalid_reason_explanation_required": (
        "有正數的 Other／指定分類必須填寫說明。",
        "有正数的 Other／指定分类必须填写说明。",
        "A positive Other/explanation-required category needs an explanation.",
    ),
    "count_round_not_found": (
        "找不到此點票輪次或版本，請重新載入。",
        "找不到此点票轮次或版本，请重新载入。",
        "The count round/revision was not found. Reload saved data.",
    ),
    "count_scope_revision_conflict": (
        "點票範圍已有新版本。輸入已保留，請重新覆核來源。",
        "点票范围已有新版本。输入已保留，请重新复核来源。",
        "The scope revision changed. Inputs remain; review its sources and reload.",
    ),
    "count_scope_not_ready": (
        "票箱接收及來源核算尚未就緒，不能儲存 F1。",
        "票箱接收及来源核算尚未就绪，不能保存 F1。",
        "Box receipts and accounting are not ready for F1 entry.",
    ),
    "count_round_basis_stale": (
        "此輪次的票箱、核算或候選人來源已有變更，須重新覆核。",
        "此轮次的票箱、核算或候选人来源已有变更，须重新复核。",
        "This round's box/accounting/candidate basis changed and requires renewed review.",
    ),
    "initial_round_exists": (
        "首次點票輪次已存在。輸入已保留，請載入已儲存輪次。",
        "首次点票轮次已存在。输入已保留，请载入已保存轮次。",
        "The initial round already exists. Inputs remain; reload that saved round.",
    ),
    "f1_arithmetic_invalid": (
        "實際張數必須等於候選人票、明顯無效票及問題選票合計。",
        "实际张数必须等于候选人票、明显无效票及问题选票合计。",
        "Actual papers must equal candidate votes plus clearly invalid and questionable papers.",
    ),
    "f1_candidate_missing": (
        "候選人數字尚未觀察",
        "候选人数字尚未观察",
        "Candidate quantity unobserved",
    ),
    "f1_invalid_reason_missing": (
        "無效票分類尚未觀察",
        "无效票分类尚未观察",
        "Invalid-reason quantity unobserved",
    ),
    "f1_questionable_missing": (
        "問題選票數字尚未觀察",
        "问题选票数字尚未观察",
        "Questionable quantity unobserved",
    ),
    "f1_actual_missing": (
        "實際點算張數尚未觀察",
        "实际点算张数尚未观察",
        "Actual counted papers unobserved",
    ),
}

COUNTING_ROUND_TRANSLATIONS: dict[str, dict[str, str]] = {
    locale: {key: values[index] for key, values in _LABELS.items()}
    for index, locale in enumerate(("tc", "sc", "en"))
}
