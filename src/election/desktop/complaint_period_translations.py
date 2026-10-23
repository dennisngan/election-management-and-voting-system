"""P(19) period review and saved report labels, independent of case forms."""

COMPLAINT_PERIOD_TRANSLATIONS = {
    "tc": {
        "complaint_period_title": "P(19) 投訴時段統計",
        "complaint_period_intro": (
            "按已設定時間表準備投訴統計，毋須先記錄實"
            "際開站。收到時間按 [開始, 結束) 分"
            "組，工作狀態以準備統計時為準。"
        ),
        "complaint_period_newer": (
            "目前時段版本或個案基礎已變更；您審閱的統計及未儲存原因仍保留。請比較後重新載入。"
        ),
        "complaint_period_coverage": "目前全站報告涵蓋情況",
        "complaint_period_coverage_hint": (
            "只有個案基礎仍相符的目前主管確認才有效。缺漏不代表零投訴；時間範圍外的案件另外保留。"
        ),
        "complaint_period_required": "已設定時段數",
        "complaint_period_missing": "尚無記錄的時段數",
        "complaint_period_approved_current": "目前有效確認時段數",
        "complaint_period_outside": "時間範圍外的目前案件數",
        "complaint_period_schedule": "已設定報告時間表",
        "complaint_period_total_periods": "時段總數",
        "complaint_period_select_period": "選擇報告時段",
        "complaint_period_period": "時段",
        "complaint_period_visible_periods": "本頁時段數",
        "complaint_period_previous_page": "上一頁時段",
        "complaint_period_next_page": "下一頁時段",
        "complaint_period_goto_period": "輸入時段編號（由 1 起）",
        "complaint_period_goto": "前往時段",
        "complaint_period_reviewed": "您審閱的已儲存統計",
        "complaint_period_frozen_hint": (
            "以下數字、個案及分類名稱取自所選版本準備時的凍結資料；其後案件變更不會改寫此版本。"
        ),
        "complaint_period_missing_hint": ("此時段尚無已儲存統計，不能當作零。請準備並核對統計。"),
        "complaint_period_start": "收到時間範圍開始（香港時間）",
        "complaint_period_end": "收到時間範圍結束，不包括此刻（香港時間）",
        "complaint_period_received": "收到投訴數",
        "complaint_period_completed": "已完成投訴數",
        "complaint_period_in_progress": "處理中投訴數",
        "complaint_period_basis_at": "凍結統計基礎時間（香港時間）",
        "complaint_period_live_basis": "目前版本的個案基礎及確認有效性",
        "complaint_period_live_hint": (
            "這是伺服器目前狀態，與上方保留的已審閱或歷史版本分開顯示。"
        ),
        "complaint_period_needs_review": ("目前版本須重新覆核；原有確認仍保留，暫不納入有效確認。"),
        "complaint_period_valid_approval": "目前版本已獲主管確認，個案基礎仍相符。",
        "complaint_period_basis_matches": "目前個案基礎相符，尚未獲主管有效確認。",
        "complaint_period_basis_changed": ("目前個案基礎已變更，請重新準備統計並核對。"),
        "complaint_period_groups": "凍結分類統計",
        "complaint_period_zero": "此已儲存版本明確記錄零宗投訴。",
        "complaint_period_category_revision": "分類版本",
        "complaint_period_members": "凍結案件明細",
        "complaint_period_case_revision": "案件版本",
        "complaint_period_case_id": "案件編號",
        "complaint_period_case_revision_id": "案件版本記錄編號",
        "complaint_period_actions": "準備、提交及修訂",
        "complaint_period_prepare_hint": (
            "數字由伺服器按目前案件計算，不可手動改寫"
            "。重新準備草稿會建立新版本；提交或確認後"
            "須填寫修訂原因。"
        ),
        "complaint_period_prepare": "按目前案件準備草稿",
        "complaint_period_submit": "提交此統計版本",
        "complaint_period_amend": "準備有原因的新版本",
        "complaint_period_approve": "主管確認此統計版本",
        "complaint_period_approval_hint": (
            "核對所選已提交版本及凍結案件後，輸入您目"
            "前的密碼確認。個案基礎已變更時須先重新準"
            "備及提交。"
        ),
        "complaint_period_history": "統計修訂歷史",
        "complaint_period_no_history": "此時段尚無已儲存版本。",
        "complaint_period_view_revision": "查看此版本",
        "complaint_period_report": "P(19) 報表及匯出",
        "complaint_period_report_hint": (
            "報表使用伺服器已儲存資料，不包含未儲存原因。可選所審閱版本或目前全站統計。"
        ),
        "complaint_period_report_scope": "報表基準",
        "complaint_period_report_selected": "所選已儲存時段版本",
        "complaint_period_report_station": "伺服器目前已儲存的本站 P(19)",
        "complaint_period_report_selected_hint": (
            "保留所選版本的凍結個案、分類及原確認資料；不混入目前全站摘要。"
        ),
        "complaint_period_report_station_hint": (
            "列出目前所有已儲存時段、有效確認與缺漏數，以及時間範圍外案件數；不將缺漏當作零。"
        ),
        "complaint_period_report_missing": (
            "所選時段尚無已儲存版本；可先準備統計，或選擇目前全站報表。"
        ),
        "complaint_report_ready": "P(19) 報表預覽已準備。",
        "complaint_exported": "P(19) 報表已匯出。",
        "complaint_export_failed": (
            "P(19) 報表未能匯出；請核對路徑及連線，已儲存內容及表格仍保留。"
        ),
    },
    "sc": {
        "complaint_period_title": "P(19) 投诉时段统计",
        "complaint_period_intro": (
            "按已设定时间表准备投诉统计，无须先记录实"
            "际开站。收到时间按 [开始, 结束) 分"
            "组，工作状态以准备统计时为准。"
        ),
        "complaint_period_newer": (
            "当前时段版本或个案依据已变更；您审阅的统计及未保存原因仍保留。请比较后重新载入。"
        ),
        "complaint_period_coverage": "当前全站报告覆盖情况",
        "complaint_period_coverage_hint": (
            "只有个案依据仍相符的当前主管确认才有效。缺漏不代表零投诉；时间范围外的案件另行保留。"
        ),
        "complaint_period_required": "已设定时段数",
        "complaint_period_missing": "尚无记录的时段数",
        "complaint_period_approved_current": "当前有效确认时段数",
        "complaint_period_outside": "时间范围外的当前案件数",
        "complaint_period_schedule": "已设定报告时间表",
        "complaint_period_total_periods": "时段总数",
        "complaint_period_select_period": "选择报告时段",
        "complaint_period_period": "时段",
        "complaint_period_visible_periods": "本页时段数",
        "complaint_period_previous_page": "上一页时段",
        "complaint_period_next_page": "下一页时段",
        "complaint_period_goto_period": "输入时段编号（从 1 起）",
        "complaint_period_goto": "前往时段",
        "complaint_period_reviewed": "您审阅的已保存统计",
        "complaint_period_frozen_hint": (
            "以下数字、个案及分类名称取自所选版本准备时的冻结资料；后续案件变更不会改写此版本。"
        ),
        "complaint_period_missing_hint": ("此时段尚无已保存统计，不能当作零。请准备并核对统计。"),
        "complaint_period_start": "收到时间范围开始（香港时间）",
        "complaint_period_end": "收到时间范围结束，不包括此刻（香港时间）",
        "complaint_period_received": "收到投诉数",
        "complaint_period_completed": "已完成投诉数",
        "complaint_period_in_progress": "处理中投诉数",
        "complaint_period_basis_at": "冻结统计依据时间（香港时间）",
        "complaint_period_live_basis": "当前版本的个案依据及确认有效性",
        "complaint_period_live_hint": (
            "这是服务器当前状态，与上方保留的已审阅或历史版本分开显示。"
        ),
        "complaint_period_needs_review": ("当前版本须重新复核；原有确认仍保留，暂不纳入有效确认。"),
        "complaint_period_valid_approval": "当前版本已获主管确认，个案依据仍相符。",
        "complaint_period_basis_matches": "当前个案依据相符，尚未获主管有效确认。",
        "complaint_period_basis_changed": ("当前个案依据已变更，请重新准备统计并核对。"),
        "complaint_period_groups": "冻结分类统计",
        "complaint_period_zero": "此已保存版本明确记录零宗投诉。",
        "complaint_period_category_revision": "分类版本",
        "complaint_period_members": "冻结案件明细",
        "complaint_period_case_revision": "案件版本",
        "complaint_period_case_id": "案件编号",
        "complaint_period_case_revision_id": "案件版本记录编号",
        "complaint_period_actions": "准备、提交及修订",
        "complaint_period_prepare_hint": (
            "数字由服务器按当前案件计算，不可手动改写"
            "。重新准备草稿会建立新版本；提交或确认后"
            "须填写修订原因。"
        ),
        "complaint_period_prepare": "按当前案件准备草稿",
        "complaint_period_submit": "提交此统计版本",
        "complaint_period_amend": "准备有原因的新版本",
        "complaint_period_approve": "主管确认此统计版本",
        "complaint_period_approval_hint": (
            "核对所选已提交版本及冻结案件后，输入您当"
            "前的密码确认。个案依据已变更时须先重新准"
            "备及提交。"
        ),
        "complaint_period_history": "统计修订历史",
        "complaint_period_no_history": "此时段尚无已保存版本。",
        "complaint_period_view_revision": "查看此版本",
        "complaint_period_report": "P(19) 报表及导出",
        "complaint_period_report_hint": (
            "报表使用服务器已保存资料，不包含未保存原因。可选所审阅版本或当前全站统计。"
        ),
        "complaint_period_report_scope": "报表依据",
        "complaint_period_report_selected": "所选已保存时段版本",
        "complaint_period_report_station": "服务器当前已保存的本站 P(19)",
        "complaint_period_report_selected_hint": (
            "保留所选版本的冻结个案、分类及原确认资料；不混入当前全站摘要。"
        ),
        "complaint_period_report_station_hint": (
            "列出当前所有已保存时段、有效确认与缺漏数，以及时间范围外案件数；不将缺漏当作零。"
        ),
        "complaint_period_report_missing": (
            "所选时段尚无已保存版本；可先准备统计，或选择当前全站报表。"
        ),
        "complaint_report_ready": "P(19) 报表预览已准备。",
        "complaint_exported": "P(19) 报表已导出。",
        "complaint_export_failed": (
            "P(19) 报表未能导出；请核对路径及连接，已保存内容及表格仍保留。"
        ),
    },
    "en": {
        "complaint_period_title": ("P(19) complaint period statistics"),
        "complaint_period_intro": (
            "Prepare complaint st"
            "atistics from the co"
            "nfigured schedule wi"
            "thout an actual open"
            "ing prerequisite. Co"
            "horts use received t"
            "ime [start, end); wo"
            "rk status is frozen "
            "at preparation."
        ),
        "complaint_period_newer": (
            "The current period r"
            "evision or case basi"
            "s changed. Your revi"
            "ewed statistics and "
            "unsaved reason are r"
            "etained. Compare bef"
            "ore reloading."
        ),
        "complaint_period_coverage": ("Current station reporting coverage"),
        "complaint_period_coverage_hint": (
            "Only current Supervi"
            "sor approvals whose "
            "case basis still mat"
            "ches remain valid. M"
            "issing does not mean"
            " zero complaints. Ca"
            "ses outside configur"
            "ed coverage remain s"
            "eparate."
        ),
        "complaint_period_required": "Configured periods",
        "complaint_period_missing": ("Periods with no saved record"),
        "complaint_period_approved_current": ("Current valid approved periods"),
        "complaint_period_outside": ("Current cases outside configured coverage"),
        "complaint_period_schedule": ("Configured reporting schedule"),
        "complaint_period_total_periods": "Total periods",
        "complaint_period_select_period": ("Select a reporting period"),
        "complaint_period_period": "Period",
        "complaint_period_visible_periods": "Periods on this page",
        "complaint_period_previous_page": "Previous period page",
        "complaint_period_next_page": "Next period page",
        "complaint_period_goto_period": ("Enter a period number, starting at 1"),
        "complaint_period_goto": "Go to period",
        "complaint_period_reviewed": ("Your reviewed saved statistics"),
        "complaint_period_frozen_hint": (
            "The following figure"
            "s, cases and categor"
            "y labels were frozen"
            " when this revision "
            "was prepared. Later "
            "case changes do not "
            "rewrite this revisio"
            "n."
        ),
        "complaint_period_missing_hint": (
            "This period has no s"
            "aved statistics. It "
            "cannot be treated as"
            " zero. Prepare and r"
            "eview its statistics"
            "."
        ),
        "complaint_period_start": ("Received interval starts (HKT)"),
        "complaint_period_end": ("Received interval ends, exclusive (HKT)"),
        "complaint_period_received": "Received complaints",
        "complaint_period_completed": "Completed complaints",
        "complaint_period_in_progress": ("In-progress complaints"),
        "complaint_period_basis_at": ("Frozen preparation time (HKT)"),
        "complaint_period_live_basis": ("Current revision case basis and approval validity"),
        "complaint_period_live_hint": (
            "This is live server "
            "status, shown separa"
            "tely from the review"
            "ed or historical rev"
            "ision retained above"
            "."
        ),
        "complaint_period_needs_review": (
            "The current revision"
            " requires review. Or"
            "iginal approvals rem"
            "ain preserved but ar"
            "e outside valid appr"
            "oved coverage."
        ),
        "complaint_period_valid_approval": (
            "The current revision has a Supervisor approval and its case basis still matches."
        ),
        "complaint_period_basis_matches": (
            "The current case basis matches; there is no valid Supervisor approval yet."
        ),
        "complaint_period_basis_changed": (
            "The current case basis changed. Prepare and review the statistics again."
        ),
        "complaint_period_groups": ("Frozen category counts"),
        "complaint_period_zero": ("This saved revision explicitly records zero complaints."),
        "complaint_period_category_revision": "Category revision",
        "complaint_period_members": ("Frozen case membership"),
        "complaint_period_case_revision": "Case revision",
        "complaint_period_case_id": "Case ID",
        "complaint_period_case_revision_id": ("Case revision record ID"),
        "complaint_period_actions": ("Prepare, submit and amend"),
        "complaint_period_prepare_hint": (
            "The server derives f"
            "igures from current "
            "cases; counts cannot"
            " be edited manually."
            " Preparing a draft c"
            "reates a new revisio"
            "n. Submitted or appr"
            "oved statistics requ"
            "ire a reasoned amend"
            "ment."
        ),
        "complaint_period_prepare": ("Prepare draft from current cases"),
        "complaint_period_submit": ("Submit this statistics revision"),
        "complaint_period_amend": ("Prepare a reasoned amendment"),
        "complaint_period_approve": ("Supervisor approval of this revision"),
        "complaint_period_approval_hint": (
            "Review this submitte"
            "d revision and its f"
            "rozen cases, then co"
            "nfirm with your curr"
            "ent password. A chan"
            "ged case basis requi"
            "res preparation and "
            "submission again."
        ),
        "complaint_period_history": ("Statistics revision history"),
        "complaint_period_no_history": ("No revision has been saved for this period."),
        "complaint_period_view_revision": "View this revision",
        "complaint_period_report": ("P(19) reports and exports"),
        "complaint_period_report_hint": (
            "Reports use saved se"
            "rver data and exclud"
            "e unsaved reasons. C"
            "hoose the reviewed r"
            "evision or current s"
            "tation statistics."
        ),
        "complaint_period_report_scope": "Report basis",
        "complaint_period_report_selected": ("Selected saved period revision"),
        "complaint_period_report_station": ("Current saved station P(19)"),
        "complaint_period_report_selected_hint": (
            "Retains this revisio"
            "n’s frozen cases, ca"
            "tegories and origina"
            "l approval metadata."
            " Current station sum"
            "maries are excluded."
        ),
        "complaint_period_report_station_hint": (
            "Includes all current"
            " saved periods, vali"
            "d approval and missi"
            "ng counts, and cases"
            " outside coverage. M"
            "issing periods are n"
            "ot zero."
        ),
        "complaint_period_report_missing": (
            "This period has no s"
            "aved revision. Prepa"
            "re statistics first "
            "or select the curren"
            "t station report."
        ),
        "complaint_report_ready": ("P(19) report preview is ready."),
        "complaint_exported": ("P(19) report exported."),
        "complaint_export_failed": (
            "P(19) report export "
            "failed. Check the de"
            "stination and connec"
            "tion. Saved data and"
            " form input are reta"
            "ined."
        ),
    },
}
