"""Complaint forms, category provenance and review feedback in supported languages."""

COMPLAINT_TRANSLATIONS = {
    "tc": {
        "complaint_categories": "投訴分類設定",
        "complaint_categories_hint": (
            "管理本選舉的顯示標籤及可用分類；已記錄案件保留當時的分類版本。"
        ),
        "complaint_category_select": "選擇投訴分類",
        "complaint_category_new": "新增本項目分類",
        "complaint_category_code": "分類編號",
        "complaint_category_tc": "繁體中文顯示標籤",
        "complaint_category_sc": "簡體中文顯示標籤",
        "complaint_category_en": "英文顯示標籤",
        "complaint_category_enabled": "可供新案件選用",
        "complaint_description_rule": "案件必須填寫說明",
        "complaint_category_save": "儲存分類",
        "complaint_category_source": "分類來源及原標籤",
        "complaint_verified_reference": "已核對的參考文件分類",
        "complaint_project_configured": "本項目自行設定的分類",
        "complaint_translation_note": "中文顯示標籤為本項目翻譯；原參考英文標籤另行保留。",
        "complaint_reference_page": "參考文件印刷頁碼",
        "complaint_other_note": "「其他」分類必須保留為可用，並要求說明投訴性質。",
        "complaint_category_saved": "投訴分類已儲存。",
        "complaint_category_validation": "請填寫分類編號及三種語言標籤，並核對長度。",
        "complaint_category_newer": "分類已有較新版本；您審閱的版本及未儲存標籤已保留。",
        "unsaved_complaint_category_changes": "分類表格有未儲存內容，請先儲存或確認捨棄。",
        "unsaved_complaint_changes": "投訴案件有未儲存內容，請先儲存或確認捨棄。",
        "complaint_validation": "請核對投訴資料、實際時間及完成狀態。",
        "complaint_saved": "投訴案件已儲存。",
        "complaint_amended": "已儲存有原因的案件修訂；原有版本仍保留。",
        "complaint_historical_readonly": "此為歷史版本，只供檢視；請重新載入目前版本後編輯。",
        "complaint_amendment_required": "此案件已影響提交的統計，須填寫原因並使用修訂功能。",
        "complaint_category_code_exists": "此選舉已有相同分類編號，請核對。",
        "complaint_category_disabled": "此分類已停用，請選擇目前可用分類。",
        "complaint_category_not_found": "找不到此投訴分類，請重新載入。",
        "complaint_description_required": "此分類必須填寫投訴性質或說明。",
        "complaint_late_reason_required": "此接收時段已有已提交統計，新增遲錄案件須填寫原因。",
        "complaint_not_found": "找不到此投訴案件，請重新載入。",
        "complaint_other_required": "「其他」分類必須保持可用並要求說明。",
        "complaint_period_not_ended": "此報告時段尚未完結，暫不可提交統計。",
        "complaint_period_not_found": "找不到此投訴報告時段，請核對時間表。",
        "complaint_period_record_not_found": "此投訴報告時段或版本尚無已儲存記錄。",
        "complaint_period_review_required": "案件基礎已變更，請重新準備並審閱統計後再提交或確認。",
        "complaint_period_state_conflict": "投訴統計狀態已變更，請重新載入並核對。",
        "complaint_reference_exists": "此案件編號已由另一投訴案件使用或保留。",
        "complaint_revision_not_found": "找不到此投訴案件版本，請重新載入。",
        "complaint_schedule_conflict": "投訴統計所依據的時間表已變更，請重新載入並比較。",
    },
    "sc": {
        "complaint_categories": "投诉分类设置",
        "complaint_categories_hint": (
            "管理本选举的显示标签及可用分类；已记录案件保留当时的分类版本。"
        ),
        "complaint_category_select": "选择投诉分类",
        "complaint_category_new": "新增本项目分类",
        "complaint_category_code": "分类编号",
        "complaint_category_tc": "繁体中文显示标签",
        "complaint_category_sc": "简体中文显示标签",
        "complaint_category_en": "英文显示标签",
        "complaint_category_enabled": "可供新案件选用",
        "complaint_description_rule": "案件必须填写说明",
        "complaint_category_save": "保存分类",
        "complaint_category_source": "分类来源及原标签",
        "complaint_verified_reference": "已核对的参考文件分类",
        "complaint_project_configured": "本项目自行设置的分类",
        "complaint_translation_note": "中文显示标签为本项目翻译；原参考英文标签另行保留。",
        "complaint_reference_page": "参考文件印刷页码",
        "complaint_other_note": "“其他”分类必须保留为可用，并要求说明投诉性质。",
        "complaint_category_saved": "投诉分类已保存。",
        "complaint_category_validation": "请填写分类编号及三种语言标签，并核对长度。",
        "complaint_category_newer": "分类已有较新版本；您审阅的版本及未保存标签已保留。",
        "unsaved_complaint_category_changes": "分类表格有未保存内容，请先保存或确认舍弃。",
        "unsaved_complaint_changes": "投诉案件有未保存内容，请先保存或确认舍弃。",
        "complaint_validation": "请核对投诉数据、实际时间及完成状态。",
        "complaint_saved": "投诉案件已保存。",
        "complaint_amended": "已保存有原因的案件修订；原有版本仍保留。",
        "complaint_historical_readonly": "此为历史版本，只供查看；请重新载入当前版本后编辑。",
        "complaint_amendment_required": "此案件已影响提交的统计，须填写原因并使用修订功能。",
        "complaint_category_code_exists": "此选举已有相同分类编号，请核对。",
        "complaint_category_disabled": "此分类已停用，请选择当前可用分类。",
        "complaint_category_not_found": "找不到此投诉分类，请重新载入。",
        "complaint_description_required": "此分类必须填写投诉性质或说明。",
        "complaint_late_reason_required": "此接收时段已有已提交统计，新增迟录案件须填写原因。",
        "complaint_not_found": "找不到此投诉案件，请重新载入。",
        "complaint_other_required": "“其他”分类必须保持可用并要求说明。",
        "complaint_period_not_ended": "此报告时段尚未结束，暂不可提交统计。",
        "complaint_period_not_found": "找不到此投诉报告时段，请核对时间表。",
        "complaint_period_record_not_found": "此投诉报告时段或版本尚无已保存记录。",
        "complaint_period_review_required": "案件基础已变更，请重新准备并审阅统计后再提交或确认。",
        "complaint_period_state_conflict": "投诉统计状态已变更，请重新载入并核对。",
        "complaint_reference_exists": "此案件编号已由另一投诉案件使用或保留。",
        "complaint_revision_not_found": "找不到此投诉案件版本，请重新载入。",
        "complaint_schedule_conflict": "投诉统计所依据的时间表已变更，请重新载入并比较。",
    },
    "en": {
        "complaint_categories": "Complaint categories",
        "complaint_categories_hint": (
            "Configure this election's display labels and available categories. "
            "Recorded cases retain the category revision they used."
        ),
        "complaint_category_select": "Select a complaint category",
        "complaint_category_new": "New project category",
        "complaint_category_code": "Category code",
        "complaint_category_tc": "Traditional Chinese display label",
        "complaint_category_sc": "Simplified Chinese display label",
        "complaint_category_en": "English display label",
        "complaint_category_enabled": "Available for new cases",
        "complaint_description_rule": "Case description is required",
        "complaint_category_save": "Save category",
        "complaint_category_source": "Category source and original label",
        "complaint_verified_reference": "Verified reference category",
        "complaint_project_configured": "Project-configured category",
        "complaint_translation_note": (
            "Chinese display labels are project translations. "
            "The original reference English label is retained separately."
        ),
        "complaint_reference_page": "Printed reference page",
        "complaint_other_note": "Other must remain available and require the complaint's nature.",
        "complaint_category_saved": "Complaint category saved.",
        "complaint_category_validation": (
            "Enter a category code and all three labels within the limits."
        ),
        "complaint_category_newer": (
            "A newer category revision is available. "
            "Your reviewed revision and unsaved labels remain."
        ),
        "unsaved_complaint_category_changes": (
            "Save or explicitly discard the category form's changes."
        ),
        "unsaved_complaint_changes": "Save or explicitly discard this complaint's unsaved changes.",
        "complaint_validation": "Check the complaint details, actual times and completion status.",
        "complaint_saved": "Complaint case saved.",
        "complaint_amended": "Reasoned case amendment saved; earlier revisions remain available.",
        "complaint_historical_readonly": (
            "Historical revision. Reload the current revision to edit."
        ),
        "complaint_amendment_required": (
            "This case affects submitted statistics. Enter a reason and use the amendment action."
        ),
        "complaint_category_code_exists": "This election already has that category code.",
        "complaint_category_disabled": "This category is disabled. Select an available category.",
        "complaint_category_not_found": "Complaint category not found. Reload the catalog.",
        "complaint_description_required": "Describe the complaint's nature for this category.",
        "complaint_late_reason_required": (
            "Statistics were submitted for this receipt period. Enter a reason for this late case."
        ),
        "complaint_not_found": "Complaint case not found. Reload the saved records.",
        "complaint_other_required": "Other must stay available and require a description.",
        "complaint_period_not_ended": (
            "This reporting period has not ended; submission is unavailable."
        ),
        "complaint_period_not_found": "Complaint reporting period not found. Check the schedule.",
        "complaint_period_record_not_found": (
            "No saved complaint period record or revision was found."
        ),
        "complaint_period_review_required": (
            "The case basis changed. Prepare and review the statistics again before submission "
            "or approval."
        ),
        "complaint_period_state_conflict": "Complaint report status changed. Reload and compare.",
        "complaint_reference_exists": "Another complaint uses or reserves this case reference.",
        "complaint_revision_not_found": "Complaint case revision not found. Reload the records.",
        "complaint_schedule_conflict": (
            "The complaint reporting schedule changed. Reload and compare."
        ),
    },
}
