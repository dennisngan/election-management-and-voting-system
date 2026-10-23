"""Complaint forms, category provenance and review feedback in supported languages."""

COMPLAINT_TRANSLATIONS = {
    "tc": {
        "complaint_cases": "投訴案件",
        "complaint_case_intro": (
            "記錄實際接收的投訴及處理進度；毋須先記錄票站實際開站。時段按已設定時間表計算。"
        ),
        "complaint_case_list": "已儲存案件",
        "complaint_case_select": "選擇已儲存案件",
        "complaint_case_new": "新增投訴案件",
        "complaint_case_none": "尚未記錄投訴案件。",
        "complaint_case_reference": "案件編號",
        "complaint_received_time": "實際接收時間（香港時間）",
        "complaint_case_description": "投訴性質及說明",
        "complaint_work_status": "處理狀態",
        "complaint_in_progress": "處理中",
        "complaint_completed": "已完成",
        "complaint_completed_time": "實際完成時間（香港時間）",
        "complaint_case_reason": "修訂或補錄原因",
        "complaint_case_reason_hint": (
            "修訂已影響提交統計的案件，或補錄至已提交時段，必須填寫原因。新案件亦可保留補充背景。"
        ),
        "complaint_case_create": "儲存新案件",
        "complaint_case_edit": "儲存案件更正",
        "complaint_case_amend": "儲存有原因的修訂",
        "complaint_case_read_only": "此角色或選舉狀態只可查看案件及歷史版本。",
        "complaint_frozen_category": (
            "此案件保留原有分類標籤及版本；即使分類其後改名或停用，仍可保留原分類。"
        ),
        "complaint_received_period": "已儲存接收時段",
        "complaint_outside_coverage": (
            "接收時間不在已設定的報告時段內；案件仍保留原有實際時間，未歸入任何時段。"
        ),
        "complaint_case_newer": (
            "案件已有較新版本或提交狀態已變更；您審閱的版本及未儲存內容仍保留。重新載入前請先比較。"
        ),
        "complaint_case_history": "案件修訂歷史",
        "complaint_case_no_history": "選擇已儲存案件以查看修訂歷史。",
        "complaint_case_view_revision": "查看此版本",
        "complaint_amendment_reason_required": "請填寫有原因修訂的原因。",
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
        "complaint_category_disabled_label": "已停用",
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
        "complaint_period_validation": "請選擇有效投訴時段及已審閱版本，並核對修訂原因。",
        "unsaved_complaint_period_changes": "投訴統計有未儲存內容，請先儲存或確認捨棄。",
        "complaint_period_prepared": "已按目前案件準備統計草稿，請核對後提交。",
        "complaint_period_submitted": "此投訴統計版本已提交，待主管確認。",
        "complaint_period_amended": "已準備有原因的新統計版本；原版本及確認仍保留。",
        "complaint_period_approved": "主管已確認此投訴統計版本。",
    },
    "sc": {
        "complaint_cases": "投诉案件",
        "complaint_case_intro": (
            "记录实际接收的投诉及处理进度；无需先记录票站实际开站。时段按已设置时间表计算。"
        ),
        "complaint_case_list": "已保存案件",
        "complaint_case_select": "选择已保存案件",
        "complaint_case_new": "新增投诉案件",
        "complaint_case_none": "尚未记录投诉案件。",
        "complaint_case_reference": "案件编号",
        "complaint_received_time": "实际接收时间（香港时间）",
        "complaint_case_description": "投诉性质及说明",
        "complaint_work_status": "处理状态",
        "complaint_in_progress": "处理中",
        "complaint_completed": "已完成",
        "complaint_completed_time": "实际完成时间（香港时间）",
        "complaint_case_reason": "修订或补录原因",
        "complaint_case_reason_hint": (
            "修订已影响提交统计的案件，或补录至已提交时段，必须填写原因。新案件也可保留补充背景。"
        ),
        "complaint_case_create": "保存新案件",
        "complaint_case_edit": "保存案件更正",
        "complaint_case_amend": "保存有原因的修订",
        "complaint_case_read_only": "此角色或选举状态只可查看案件及历史版本。",
        "complaint_frozen_category": (
            "此案件保留原有分类标签及版本；即使分类之后改名或停用，仍可保留原分类。"
        ),
        "complaint_received_period": "已保存接收时段",
        "complaint_outside_coverage": (
            "接收时间不在已设置的报告时段内；案件仍保留原有实际时间，未归入任何时段。"
        ),
        "complaint_case_newer": (
            "案件已有较新版本或提交状态已变更；您审阅的版本及未保存内容仍保留。重新载入前请先比较。"
        ),
        "complaint_case_history": "案件修订历史",
        "complaint_case_no_history": "选择已保存案件以查看修订历史。",
        "complaint_case_view_revision": "查看此版本",
        "complaint_amendment_reason_required": "请填写有原因修订的原因。",
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
        "complaint_category_disabled_label": "已停用",
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
        "complaint_period_validation": "请选择有效投诉时段及已审阅版本，并核对修订原因。",
        "unsaved_complaint_period_changes": "投诉统计有未保存内容，请先保存或确认舍弃。",
        "complaint_period_prepared": "已按当前案件准备统计草稿，请核对后提交。",
        "complaint_period_submitted": "此投诉统计版本已提交，待主管确认。",
        "complaint_period_amended": "已准备有原因的新统计版本；原版本及确认仍保留。",
        "complaint_period_approved": "主管已确认此投诉统计版本。",
    },
    "en": {
        "complaint_cases": "Complaint cases",
        "complaint_case_intro": (
            "Record received complaints and their progress without waiting for an a"
            "ctual opening record. Reporting periods follow the configured schedule"
            "."
        ),
        "complaint_case_list": "Saved cases",
        "complaint_case_select": "Select a saved case",
        "complaint_case_new": "New complaint case",
        "complaint_case_none": "No complaint cases have been recorded.",
        "complaint_case_reference": "Case reference",
        "complaint_received_time": "Actual received time (Hong Kong time)",
        "complaint_case_description": "Complaint nature and description",
        "complaint_work_status": "Work status",
        "complaint_in_progress": "In progress",
        "complaint_completed": "Completed",
        "complaint_completed_time": "Actual completion time (Hong Kong time)",
        "complaint_case_reason": "Amendment or late-entry reason",
        "complaint_case_reason_hint": (
            "Give a reason for an amendment or a late case in a submitted period. A"
            " new case may also retain this context."
        ),
        "complaint_case_create": "Save new case",
        "complaint_case_edit": "Save case correction",
        "complaint_case_amend": "Save reasoned amendment",
        "complaint_case_read_only": (
            "This role or election status permits reading cases and their history."
        ),
        "complaint_frozen_category": (
            "This case retains its original category label and revision, including "
            "after a rename or disablement."
        ),
        "complaint_received_period": "Saved received period",
        "complaint_outside_coverage": (
            "The received time is outside configured reporting periods. Its actual "
            "time is retained without assigning a period."
        ),
        "complaint_case_newer": (
            "A newer case revision or submission state is available. Your reviewed "
            "revision and unsaved input remain. Compare before reloading."
        ),
        "complaint_case_history": "Case revision history",
        "complaint_case_no_history": "Select a saved case to view its revision history.",
        "complaint_case_view_revision": "Review this revision",
        "complaint_amendment_reason_required": "Enter a reason for the amendment.",
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
        "complaint_category_disabled_label": "Disabled",
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
        "complaint_period_validation": (
            "Select a valid reviewed period and check the amendment reason."
        ),
        "unsaved_complaint_period_changes": (
            "Save or explicitly discard the complaint report's changes."
        ),
        "complaint_period_prepared": (
            "Statistics draft prepared from current cases. Review and submit."
        ),
        "complaint_period_submitted": (
            "This complaint report revision awaits Supervisor approval."
        ),
        "complaint_period_amended": (
            "New reasoned statistics revision prepared; earlier records remain."
        ),
        "complaint_period_approved": "The Supervisor approved this complaint report revision.",
    },
}
