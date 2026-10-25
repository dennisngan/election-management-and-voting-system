"""Questionable-paper and count-workflow messages in the supported languages."""

_LABELS: dict[str, tuple[str, str, str]] = {
    "f2_saved": ("已儲存 F2 判定草稿", "已保存 F2 判定草稿", "F2 determination draft saved"),
    "f2_time_invalid": (
        "請輸入有效的香港觀察時間及判定開始時間。",
        "请输入有效的香港观察时间及判定开始时间。",
        "Enter valid Hong Kong observation and determination times.",
    ),
    "f2_quantity_invalid": (
        "請輸入非負整數；未觀察的項目請留空。",
        "请输入非负整数；未观察的项目请留空。",
        "Enter a nonnegative whole number or leave an unobserved item blank.",
    ),
    "f2_validation": (
        "請檢查 F2 輸入及文字長度。",
        "请检查 F2 输入及文字长度。",
        "Check F2 inputs and text lengths.",
    ),
    "f2_outcomes_exceed_questionable": (
        "已知判定張數超過原問題選票張數。",
        "已知判定张数超过原问题选票张数。",
        "Known outcomes exceed the original questionable-paper count.",
    ),
    "f2_outcomes_unbalanced": (
        "接納與拒納的合計須等於原問題選票張數。",
        "接纳与拒纳的合计须等于原问题选票张数。",
        "Accepted and rejected outcomes must equal the original questionable-paper count.",
    ),
    "determination_reason_required": (
        "更改已儲存的判定開始時間須填寫修訂原因。",
        "更改已保存的判定开始时间须填写修订原因。",
        "Give a reason for changing the saved determination start.",
    ),
    "determination_time_invalid": (
        "判定開始時間不可晚於 F2 觀察時間。",
        "判定开始时间不可晚于 F2 观察时间。",
        "Determination cannot start after the F2 observation time.",
    ),
    "f1_incomplete": (
        "請先完成並儲存 F1 觀察。",
        "请先完成并保存 F1 观察。",
        "Complete and save the F1 observations first.",
    ),
    "f2_discard_required": (
        "修改 F1 前須明確確認清除目前 F2；歷史記錄會保留。",
        "修改 F1 前须明确确认清除当前 F2；历史记录会保留。",
        "Confirm replacement of the current F2 before changing F1. Its history is retained.",
    ),
    "count_round_read_only": (
        "此點票版本只供檢視。",
        "此点票版本仅供查看。",
        "This count revision is read-only.",
    ),
    "count_round_state_conflict": (
        "點票狀態已變更，請重新載入並檢查。",
        "点票状态已变更，请重新加载并检查。",
        "The count state changed. Reload and review it.",
    ),
    "count_inputs_incomplete": (
        "請完成所有必要觀察及平衡核對後再提交。",
        "请完成所有必要观察及平衡核对后再提交。",
        "Complete the required observations and balance the count before submission.",
    ),
    "count_physical_difference_unaccepted": (
        "實際張數與已知估算有差異，須經主管處理後才可核准。",
        "实际张数与已知估算有差异，须经主管处理后才可批准。",
        "A known physical difference requires Supervisor disposition before approval.",
    ),
    "count_approval_invalid": (
        "此確切版本沒有目前有效的核准。",
        "此确切版本没有当前有效的批准。",
        "This exact revision has no current valid approval.",
    ),
    "selection_revision_conflict": (
        "所選核准輪次已由其他用戶變更，請重新載入。",
        "所选批准轮次已由其他用户变更，请重新加载。",
        "Another user changed the selected approved round. Reload it.",
    ),
    "count_submitted": (
        "已提交點票並記錄完成時間",
        "已提交点票并记录完成时间",
        "Count submitted and completion recorded",
    ),
    "count_approved": (
        "已核准此確切點票版本",
        "已批准此确切点票版本",
        "This exact count revision is approved",
    ),
    "count_selected": (
        "已明確選定核准輪次",
        "已明确选定批准轮次",
        "Approved round explicitly selected",
    ),
    "unsaved_count_changes": (
        "請先儲存或捨棄未儲存的點票變更。",
        "请先保存或放弃未保存的点票变更。",
        "Save or discard the unsaved count changes first.",
    ),
    "f2_candidate_missing": (
        "候選人接納張數尚未觀察",
        "候选人接纳张数尚未观察",
        "Accepted quantity for a candidate is unobserved",
    ),
    "f2_invalid_reason_missing": (
        "拒納原因張數尚未觀察",
        "拒纳原因张数尚未观察",
        "Rejected quantity for a reason is unobserved",
    ),
    "determination_start_missing": (
        "尚未記錄問題選票判定開始時間",
        "尚未记录问题选票判定开始时间",
        "Questionable-paper determination start is unrecorded",
    ),
    "final_arithmetic_invalid": (
        "最終票數與實際張數不平衡",
        "最终票数与实际张数不平衡",
        "Final totals do not balance with actual counted papers",
    ),
    "f2_title": ("F2 判定", "F2 判定", "F2 determination"),
    "f2_hint": (
        "只輸入已觀察的判定結果；未觀察的數量請留空，明確的零請輸入 0。",
        "只输入已观察的判定结果；未观察的数量请留空，明确的零请输入 0。",
        "Enter observed outcomes only. Leave unobserved quantities blank; "
        "enter 0 for observed zero.",
    ),
    "f2_observation_time": (
        "F2 觀察時間（香港時間）",
        "F2 观察时间（香港时间）",
        "F2 observed at (Hong Kong time)",
    ),
    "f2_determination_start": (
        "問題選票判定開始時間（香港時間）",
        "问题选票判定开始时间（香港时间）",
        "Questionable-paper determination started at (Hong Kong time)",
    ),
    "f2_time_hint": (
        "判定開始時間不可晚於 F2 觀察時間。",
        "判定开始时间不可晚于 F2 观察时间。",
        "Determination start cannot be later than the F2 observation.",
    ),
    "f2_accepted_outcomes": ("接納為候選人票", "接纳为候选人票", "Accept as candidate votes"),
    "f2_accepted_quantity": ("接納張數", "接纳张数", "Accepted quantity"),
    "f2_rejected_outcomes": ("拒納原因", "拒纳原因", "Rejected-paper reasons"),
    "f2_reason_source_note": (
        "保留來源英文、來源字母、頁碼及項目翻譯資料。",
        "保留来源英文、来源字母、页码及项目翻译资料。",
        "Preserved source English, letter, page references, and project translation.",
    ),
    "f2_source_english": (
        "保存的英文來源文字",
        "保存的英文来源文字",
        "Preserved English source wording",
    ),
    "f2_source_letter": ("來源字母", "来源字母", "Source letter"),
    "f2_reference_pages": ("電子／印刷頁碼", "电子／印刷页码", "PDF / printed pages"),
    "f2_translation_provenance": ("翻譯來源", "翻译来源", "Translation provenance"),
    "f2_project_translation": ("項目翻譯", "项目翻译", "Project translation"),
    "f2_project_reason": (
        "項目設定原因；不代表官方來源文字或代號。",
        "项目设置原因；不代表官方来源文字或代号。",
        "Project-configured reason; no official source wording or code is claimed.",
    ),
    "f2_rejected_quantity": ("拒納張數", "拒纳张数", "Rejected quantity"),
    "f2_explanation_required": (
        "正數張數必須補充說明。",
        "正数张数必须补充说明。",
        "An explanation is required for a positive quantity.",
    ),
    "f2_explanation": ("判定說明", "判定说明", "Determination explanation"),
    "f2_notes": ("F2 備註", "F2 备注", "F2 notes"),
    "f2_amendment_reason": ("修訂原因", "修订原因", "Amendment reason"),
    "f2_save": ("儲存 F2 草稿", "保存 F2 草稿", "Save F2 draft"),
    "f2_historical": (
        "正在檢視保存的歷史版本；只供閱讀。",
        "正在查看保存的历史版本；仅供阅读。",
        "Viewing a preserved historical revision; read-only.",
    ),
    "f2_results_title": (
        "已儲存的最終點票結果",
        "已保存的最终点票结果",
        "Saved final count results",
    ),
    "f2_inputs_complete": (
        "已觀察並平衡所有必要數量。",
        "已观察并平衡所有必要数量。",
        "Required inputs are observed and balanced.",
    ),
    "f2_inputs_incomplete": (
        "必要數量仍未完成觀察或平衡。",
        "必要数量仍未完成观察或平衡。",
        "Required inputs are still missing or unbalanced.",
    ),
    "f2_workflow_complete": (
        "點票已提交並記錄完成。",
        "点票已提交并记录完成。",
        "Count was submitted and completion recorded.",
    ),
    "f2_workflow_incomplete": (
        "此版本尚未提交；輸入完整不代表工作流程已完成。",
        "此版本尚未提交；输入完整不代表工作流程已完成。",
        "This revision has not been submitted; complete inputs are not workflow completion.",
    ),
    "f2_workflow_status": ("工作流程狀態", "工作流程状态", "Workflow status"),
    "f2_accepted_questionable_quantity": (
        "已接納問題選票",
        "已接纳问题选票",
        "Accepted questionable papers",
    ),
    "f2_rejected_questionable_quantity": (
        "已拒納問題選票",
        "已拒纳问题选票",
        "Rejected questionable papers",
    ),
    "f2_final_valid_quantity": ("最終有效票", "最终有效票", "Final valid votes"),
    "f2_final_invalid_quantity": ("最終無效票", "最终无效票", "Final invalid papers"),
    "f2_final_accounted_quantity": ("最終合計", "最终合计", "Final accounted papers"),
    "f2_actual_counted_quantity": ("實際點算張數", "实际点算张数", "Actual counted papers"),
    "f2_final_candidates": ("最終候選人票數", "最终候选人票数", "Final candidate votes"),
    "f2_physical_comparisons": (
        "實際張數與已知估算比較",
        "实际张数与已知估算比较",
        "Actual count and known estimate comparisons",
    ),
    "f2_source_stock": ("庫存估算", "库存估算", "Stock estimate"),
    "f2_source_turnout": ("投票人數估算", "投票人数估算", "Turnout estimate"),
    "f2_comparison_unavailable": (
        "不可用；來源未能提供估算",
        "不可用；来源未能提供估算",
        "Unavailable; no estimate from this source",
    ),
    "f2_comparison_matching": ("相符", "相符", "Matching"),
    "f2_comparison_pending": (
        "有差異，待主管處理",
        "有差异，待主管处理",
        "Difference pending Supervisor disposition",
    ),
    "f2_expected": ("估算", "估算", "Expected"),
    "f2_actual": ("實際", "实际", "Actual"),
    "f2_difference": ("差異（實際－估算）", "差异（实际－估算）", "Difference (actual − expected)"),
    "f2_approval_blockers": ("核准條件", "批准条件", "Approval conditions"),
    "f2_submitted_at": ("提交時間", "提交时间", "Submitted at"),
    "f2_submitted_by": ("提交職員編號", "提交职员编号", "Submitted by account"),
    "f2_approved_at": ("核准時間", "批准时间", "Approved at"),
    "f2_approved_by": ("核准主管編號", "批准主管编号", "Approved by account"),
    "f2_approval_valid": (
        "此確切版本目前核准有效",
        "此确切版本当前批准有效",
        "This exact revision has a current valid approval",
    ),
    "f2_approval_invalid": (
        "此核准版本已不再是目前有效版本",
        "此批准版本已不再是当前有效版本",
        "This approval is no longer current and valid",
    ),
    "f2_selected": ("已選定為目前結果", "已选定为当前结果", "Selected as the current result"),
    "f2_selection_historical": (
        "選擇指向的版本已成為歷史版本",
        "选择指向的版本已成为历史版本",
        "The selected pointer now refers to a historical revision",
    ),
    "f2_selected_at": ("選定時間", "选定时间", "Selected at"),
    "f2_selected_by": ("選定主管編號", "选定主管编号", "Selected by account"),
    "f2_submit": ("提交點票並記錄完成", "提交点票并记录完成", "Submit count and record completion"),
    "f2_approve": ("核准此確切版本", "批准此确切版本", "Approve this exact revision"),
    "f2_select": ("選定為目前結果", "选定为当前结果", "Select as current result"),
    "f2_approve_dialog": (
        "輸入主管密碼以核准點票",
        "输入主管密码以批准点票",
        "Enter Supervisor password to approve this count",
    ),
    "f2_select_dialog": (
        "輸入主管密碼以選定結果",
        "输入主管密码以选定结果",
        "Enter Supervisor password to select this result",
    ),
    "f2_dialog_revision": (
        "將處理此確切版本",
        "将处理此确切版本",
        "Action applies to this exact revision",
    ),
    "f2_confirm": ("確認", "确认", "Confirm"),
    "f2_cancel": ("取消", "取消", "Cancel"),
    "f1_discard_f2_title": (
        "以新 F1 草稿取代目前 F2？",
        "以新 F1 草稿替代当前 F2？",
        "Replace current F2 with a new F1 draft?",
    ),
    "f1_discard_f2_message": (
        "儲存 F1 會清除目前 F2；現有 F2 版本仍會保留在歷史記錄。",
        "保存 F1 会清除当前 F2；现有 F2 版本仍会保留在历史记录。",
        "Saving F1 clears the current F2. Its saved revision remains in history.",
    ),
    "f1_discard_f2_confirm": (
        "清除 F2 並儲存 F1",
        "清除 F2 并保存 F1",
        "Discard current F2 and save F1",
    ),
}

COUNT_OUTCOME_TRANSLATIONS: dict[str, dict[str, str]] = {
    locale: {key: values[index] for key, values in _LABELS.items()}
    for index, locale in enumerate(("tc", "sc", "en"))
}
