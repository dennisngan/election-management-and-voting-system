"""F1 invalid-ballot reason catalogue labels in supported desktop languages."""

INVALID_REASON_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "invalid_reasons_title": "無效選票原因",
        "invalid_reasons_hint": "管理 F1 初步點票使用的無效選票原因及顯示文字。",
        "invalid_reason_select": "選擇原因",
        "invalid_reason_new": "新增項目原因",
        "invalid_reason_save": "儲存原因版本",
        "invalid_reason_code": "項目代號",
        "invalid_reason_stage": "適用點票階段",
        "invalid_reason_f1": "F1 初步點票",
        "invalid_reason_label_tc": "繁體中文顯示文字",
        "invalid_reason_label_sc": "簡體中文顯示文字",
        "invalid_reason_label_en": "英文顯示文字",
        "invalid_reason_enabled": "可供選用",
        "invalid_reason_explanation_required": "選用時必須解釋",
        "invalid_reason_revision": "原因版本",
        "invalid_reason_history": "原因歷史版本",
        "invalid_reason_current": "目前版本",
        "invalid_reason_historical": "正在查看保留版本，只供閱讀。",
        "invalid_reason_source": "來源資料及翻譯",
        "invalid_reason_source_verified": "已核對英文來源文字",
        "invalid_reason_source_project": "項目設定原因；不代表官方原因代號或來源文字",
        "invalid_reason_source_english": "保存的英文來源文字",
        "invalid_reason_source_letter": "來源字母",
        "invalid_reason_reference_page": "電子版頁碼",
        "invalid_reason_printed_page": "印刷頁碼",
        "invalid_reason_translation_provenance": "顯示翻譯來源",
        "invalid_reason_project_translation": "項目翻譯",
        "invalid_reason_source_note": (
            "來源核對只確認所列英文原文；繁體、簡體及可編輯英文顯示文字屬項目翻譯。"
            "「其他」是項目選項，不代表官方代號。"
        ),
        "invalid_reason_other_note": "「其他」不可停用，並必須要求說明。",
        "invalid_reason_other_label": "其他（請註明原因）",
        "invalid_reason_disabled": "已停用",
        "invalid_reason_verified": "來源英文已核對",
        "invalid_reason_project": "項目設定",
        "invalid_reason_saved": "無效選票原因已儲存。",
        "invalid_reason_validation": "請輸入項目代號及三種語言的顯示文字，且不可只輸入空白。",
        "invalid_reason_code_exists": "此選舉已使用該項目代號。",
        "invalid_reason_not_found": "找不到此無效選票原因。請重新載入選舉目錄。",
        "invalid_reason_other_required": "「其他」必須保持啟用並要求說明。",
        "invalid_reason_election_read_only": "已完成的選舉目錄只供閱讀。",
        "unsaved_invalid_reason_changes": "原因表格有未儲存內容。請先儲存或捨棄變更。",
        "invalid_reason_create_help": (
            "新增原因屬於項目設定，須使用項目代號；不會加入官方來源代號。"
        ),
    },
    "sc": {
        "invalid_reasons_title": "无效选票原因",
        "invalid_reasons_hint": "管理 F1 初步点票使用的无效选票原因及显示文字。",
        "invalid_reason_select": "选择原因",
        "invalid_reason_new": "新增项目原因",
        "invalid_reason_save": "保存原因版本",
        "invalid_reason_code": "项目代号",
        "invalid_reason_stage": "适用点票阶段",
        "invalid_reason_f1": "F1 初步点票",
        "invalid_reason_label_tc": "繁体中文显示文字",
        "invalid_reason_label_sc": "简体中文显示文字",
        "invalid_reason_label_en": "英文显示文字",
        "invalid_reason_enabled": "可供选择",
        "invalid_reason_explanation_required": "选择时必须解释",
        "invalid_reason_revision": "原因版本",
        "invalid_reason_history": "原因历史版本",
        "invalid_reason_current": "当前版本",
        "invalid_reason_historical": "正在查看保留版本，只供阅读。",
        "invalid_reason_source": "来源资料及翻译",
        "invalid_reason_source_verified": "已核对英文来源文字",
        "invalid_reason_source_project": "项目设置原因；不代表官方原因代号或来源文字",
        "invalid_reason_source_english": "保存的英文来源文字",
        "invalid_reason_source_letter": "来源字母",
        "invalid_reason_reference_page": "电子版页码",
        "invalid_reason_printed_page": "印刷页码",
        "invalid_reason_translation_provenance": "显示翻译来源",
        "invalid_reason_project_translation": "项目翻译",
        "invalid_reason_source_note": (
            "来源核对只确认所列英文原文；繁体、简体及可编辑英文显示文字属于项目翻译。"
            "“其他”是项目选项，不代表官方代号。"
        ),
        "invalid_reason_other_note": "“其他”不可停用，并必须要求说明。",
        "invalid_reason_other_label": "其他（请注明原因）",
        "invalid_reason_disabled": "已停用",
        "invalid_reason_verified": "来源英文已核对",
        "invalid_reason_project": "项目设置",
        "invalid_reason_saved": "无效选票原因已保存。",
        "invalid_reason_validation": "请输入项目代号及三种语言的显示文字，且不可只输入空白。",
        "invalid_reason_code_exists": "此选举已使用该项目代号。",
        "invalid_reason_not_found": "找不到此无效选票原因。请重新载入选举目录。",
        "invalid_reason_other_required": "“其他”必须保持启用并要求说明。",
        "invalid_reason_election_read_only": "已完成的选举目录只供阅读。",
        "unsaved_invalid_reason_changes": "原因表格有未保存内容。请先保存或舍弃更改。",
        "invalid_reason_create_help": (
            "新增原因属于项目设置，须使用项目代号；不会加入官方来源代号。"
        ),
    },
    "en": {
        "invalid_reasons_title": "Invalid ballot reasons",
        "invalid_reasons_hint": (
            "Manage invalid-paper reasons and display wording used during the F1 initial tally."
        ),
        "invalid_reason_select": "Select a reason",
        "invalid_reason_new": "New project reason",
        "invalid_reason_save": "Save reason revision",
        "invalid_reason_code": "Project code",
        "invalid_reason_stage": "Counting stage",
        "invalid_reason_f1": "F1 initial tally",
        "invalid_reason_label_tc": "Traditional Chinese display label",
        "invalid_reason_label_sc": "Simplified Chinese display label",
        "invalid_reason_label_en": "English display label",
        "invalid_reason_enabled": "Available for selection",
        "invalid_reason_explanation_required": "Require an explanation when used",
        "invalid_reason_revision": "Reason revision",
        "invalid_reason_history": "Reason history",
        "invalid_reason_current": "Current revision",
        "invalid_reason_historical": "Viewing a retained revision. This view is read-only.",
        "invalid_reason_source": "Source details and translation",
        "invalid_reason_source_verified": "English source wording verified",
        "invalid_reason_source_project": (
            "Project-configured reason; no official reason code or source wording is claimed"
        ),
        "invalid_reason_source_english": "Preserved English source wording",
        "invalid_reason_source_letter": "Source letter",
        "invalid_reason_reference_page": "PDF page",
        "invalid_reason_printed_page": "Printed page",
        "invalid_reason_translation_provenance": "Display translation provenance",
        "invalid_reason_project_translation": "Project translation",
        "invalid_reason_source_note": (
            "Verification applies only to the displayed original English source wording. "
            "Traditional, Simplified and editable English display labels are project translations. "
            "Other is a project option and does not claim an official code."
        ),
        "invalid_reason_other_note": "Other must remain enabled and require an explanation.",
        "invalid_reason_other_label": "Other (specify reason)",
        "invalid_reason_disabled": "Disabled",
        "invalid_reason_verified": "Verified English source",
        "invalid_reason_project": "Project configured",
        "invalid_reason_saved": "Invalid ballot reason saved.",
        "invalid_reason_validation": (
            "Enter a project code and nonblank display labels in all three languages."
        ),
        "invalid_reason_code_exists": "This project code is already used in this election.",
        "invalid_reason_not_found": (
            "This invalid-ballot reason could not be found. Reload the catalogue."
        ),
        "invalid_reason_other_required": "Other must remain enabled and require an explanation.",
        "invalid_reason_election_read_only": "A finalized election catalogue is read-only.",
        "unsaved_invalid_reason_changes": (
            "This reason has unsaved changes. Save them or discard them before continuing."
        ),
        "invalid_reason_create_help": (
            "New reasons are project configured and use a project code; "
            "they do not add official source codes."
        ),
    },
}
