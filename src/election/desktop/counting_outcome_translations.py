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
}

COUNT_OUTCOME_TRANSLATIONS: dict[str, dict[str, str]] = {
    locale: {key: values[index] for key, values in _LABELS.items()}
    for index, locale in enumerate(("tc", "sc", "en"))
}
