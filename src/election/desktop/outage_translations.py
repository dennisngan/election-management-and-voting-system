"""Connectivity outage and paper reconciliation labels in supported languages."""

OUTAGE_TRANSLATIONS = {
    "tc": {
        "outage_existing_receipt_title": (
            "連結已核實的電子記錄"
        ),
        "outage_existing_receipt_hint": (
            "將紙本參考連結至已儲存的原始電子記錄。此操作不會再次提交該項工作。"
        ),
        "outage_existing_receipt_request": (
            "原始請求編號"
        ),
        "outage_existing_receipt_check": (
            "核查原始記錄"
        ),
        "outage_existing_receipt_checked": (
            "已核實的原始電子記錄"
        ),
        "outage_existing_receipt_reason": (
            "連結原因"
        ),
        "outage_existing_receipt_link": (
            "連結已核實記錄"
        ),
        "outage_existing_receipt_clear": (
            "清除連結草稿"
        ),
        "outage_existing_receipt_retry": (
            "重試連結已核實記錄"
        ),
        "outage_existing_receipt_linked": (
            "紙本參考已連結至原始電子記錄。"
        ),
        "outage_existing_receipt_server_time": (
            "原始記錄的伺服器輸入時間"
        ),
        "outage_existing_link_metadata": (
            "後加的連結記錄"
        ),
        "outage_existing_link_request": (
            "連結請求編號"
        ),
        "outage_existing_request_invalid": (
            "請輸入有效的原始請求編號。"
        ),
        "outage_existing_receipt_check_required": (
            "請先核查原始電子記錄，再進行連結。"
        ),
        "outage_existing_link_reason_required": (
            "請填寫連結此記錄的原因。"
        ),
        "outage_existing_link_clear_first": (
            "請先清除連結草稿，再編輯中斷或紙本記錄。"
        ),
        "paper_receipt_mismatch": (
            "原始電子記錄與此紙本參考、操作或原始時間不符。"
        ),
        "paper_receipt_workflow_unsupported": (
            "無法將所選電子記錄連結至此紙本操作。"
        ),
        "outage_receipt_status_draft": (
            "草稿"
        ),
        "outage_receipt_status_submitted": (
            "已提交"
        ),
        "outage_receipt_status_approved": (
            "已核准"
        ),
        "outage_receipt_status_recorded": (
            "已記錄"
        ),
        "outage_title": "連線中斷及紙本紀錄",
        "outage_report": "中斷及紙本報表",
        "outage_report_preview": "預覽報表",
        "outage_report_export_pdf": "匯出 PDF",
        "outage_report_export_csv": "匯出 CSV",
        "outage_report_ready": "中斷及紙本報表已載入。",
        "outage_report_exported": "中斷及紙本報表已匯出。",
        "outage_report_export_failed": "未能匯出中斷及紙本報表。",
        "outage_intro": "記錄實際中斷時段及紙本參考。原始紙本時間與伺服器記錄時間分開保留。",
        "outage_station": "投票站編號",
        "outage_list": "已記錄的連線中斷",
        "outage_empty": "此投票站尚無連線中斷紀錄。",
        "outage_new": "新增中斷紀錄",
        "outage_load": "載入",
        "outage_refresh": "重新整理清單",
        "outage_reload": "捨棄變更並重新載入",
        "outage_read_only": (
            '此帳戶只可查看。獲指派的投票'
            '站主任或點票主任可記錄中斷及'
            '紙本參考。'
        ),
        "outage_active_required": "只有選舉進行期間可新增或修正紀錄。",
        "outage_details": "中斷詳情",
        "outage_reference": "中斷參考",
        "outage_kind": "中斷類型",
        "outage_network": "網絡",
        "outage_backend": "後端伺服器",
        "outage_database": "資料庫",
        "outage_unknown": "不明",
        "outage_started": "實際開始時間（香港時間 YYYY-MM-DD HH:mm）",
        "outage_ended": "實際結束時間（香港時間 YYYY-MM-DD HH:mm）",
        "outage_time_hint": "可輸入秒及最多六位小數秒；修改未改變的分鐘會保留原有精度。",
        "outage_notes": "中斷備註",
        "outage_reason": "修訂原因",
        "outage_save": "儲存中斷紀錄",
        "outage_amend": "儲存修訂",
        "outage_revision": "中斷修訂",
        "outage_newer_revision": (
            '伺服器已有較新中斷、紙本或核'
            '對修訂；未儲存輸入仍保留。請'
            '核對後明確重新載入。'
        ),
        "outage_server_entered": "伺服器記錄時間（香港時間）",
        "outage_actor": "記錄人員編號",
        "outage_papers": "紙本參考",
        "outage_paper_new": "新增紙本參考",
        "outage_paper_reference": "紙本參考編號",
        "outage_workflow": "後續工作流程",
        "outage_action": "工作流程操作",
        "outage_count": "點票",
        "outage_turnout": "投票率",
        "outage_allocation": "櫃台選票派發",
        "outage_submit": "提交點票",
        "outage_save_turnout": "儲存投票率",
        "outage_create_allocation": "新增派發",
        "outage_amend_allocation": "修正派發",
        "outage_original_time": "紙本原始時間（香港時間 YYYY-MM-DD HH:mm）",
        "outage_original_time_hint": "此時間保留為紙本所載時間；伺服器另行記錄輸入時間。",
        "outage_target_scope": "點票範圍編號",
        "outage_target_round": "點票輪次編號",
        "outage_target_period": "投票率時段編號",
        "outage_target_counter": "發票櫃台編號",
        "outage_target_allocation": "派發紀錄編號",
        "outage_paper_notes": "紙本紀錄備註",
        "outage_paper_reason": "修正紙本紀錄原因",
        "outage_paper_save": "儲存紙本參考",
        "outage_paper_amend": "儲存紙本修正",
        "outage_pending": "待重新輸入",
        "outage_entered": "已重新輸入",
        "outage_paper_revision": "紙本修訂",
        "outage_paper_actor": "輸入人員編號",
        "outage_paper_server_time": "伺服器輸入時間（香港時間）",
        "outage_reentry": "不可變更的輸入收據",
        "outage_receipt_request": "原始請求編號",
        "outage_receipt_record": "原始記錄編號",
        "outage_receipt_revision": "原始記錄修訂",
        "outage_receipt_status": "原始記錄狀態",
        "outage_receipt_event": "原始記錄時間（香港時間）",
        "outage_receipt_target": "核對目標",
        "outage_receipt_actor": "重新輸入人員編號",
        "outage_receipt_reentered_at": "重新輸入時間（香港時間）",
        "outage_receipt_hourly": "每小時數量",
        "outage_receipt_cumulative": "累積數量",
        "outage_receipt_candidate": "候選人觀察票數",
        "outage_receipt_invalid": "明顯無效票分類數量",
        "outage_receipt_questionable_quantity": "待判定問題選票",
        "outage_receipt_actual_counted_quantity": "實際點算張數",
        "outage_receipt_initial_valid_quantity": "初步有效票總數",
        "outage_receipt_clearly_invalid_quantity": "明顯無效票總數",
        "outage_receipt_initial_accounted_quantity": "初步核算票數",
        "outage_receipt_supplied_hourly": "填報每小時數量",
        "outage_receipt_supplied_cumulative": "填報累積數量",
        "outage_receipt_derived_hourly": "計算每小時數量",
        "outage_receipt_derived_cumulative_start": "計算期初累積數量",
        "outage_receipt_derived_cumulative_end": "計算期末累積數量",
        "outage_receipt_serials": "原編號範圍",
        "outage_saved": "中斷紀錄已儲存至中央伺服器。",
        "outage_paper_saved": "紙本參考已儲存至中央伺服器。",
        "outage_reconciled_notice": "紙本核對決定已儲存至中央伺服器。",
        "outage_reconcile": "監督員核對",
        "outage_reconcile_hint": (
            '核對所有紙本參考的不可變更收'
            '據及目前修訂後，由監督員提交'
            '理由並以本人密碼確認。'
        ),
        "outage_reconcile_reason": "核對原因",
        "outage_supervisor_password": "監督員本人密碼",
        "outage_approve": "核准紙本核對",
        "outage_reconciled": "目前紙本核對已核准",
        "outage_not_reconciled": "尚未完成目前紙本核對",
        "outage_reconciliation_history": "核對決定歷史",
        "outage_current_revision": "清單所示伺服器修訂",
        "outage_pending_request": "待核實請求編號",
        "outage_retry_outage": "比較後重試中斷儲存",
        "outage_retry_paper": "比較後重試紙本儲存",
        "outage_retry_approval": "比較後重新確認核對",
        "outage_uncertain_hint": (
            '請重新整理並比較伺服器修訂及'
            '參考，再決定是否以相同請求重'
            '試。程式不會自動重送。'
        ),
        "outage_dirty_hint": "表格有未儲存變更。載入其他紀錄前，請明確選擇捨棄並重新載入。",
        "outage_confirm_discard_title": "捨棄未儲存變更？",
        "outage_confirm_discard": "目前輸入尚未儲存。只有選擇捨棄並繼續後才會載入另一紀錄。",
        "outage_keep_editing": "繼續編輯",
        "outage_discard_continue": "捨棄並繼續",
        "outage_context_unavailable": "請先選擇已指派的投票站。",
        "outage_not_found": "找不到所選中斷紀錄。",
        "outage_not_selected": "請先選擇或新增中斷紀錄。",
        "outage_uncertain_save_pending": (
            '仍有一項結果未核實的請求。請'
            '保留原請求內容並先比較伺服器'
            '清單。'
        ),
        "unsaved_outage_changes": "中斷表格有未儲存變更。",
        "unsaved_outage_paper_changes": "紙本表格有未儲存變更。",
        "outage_validation": "請輸入參考、類型、有效香港時間及不超過 2000 字的備註。",
        "outage_response_invalid": "伺服器回覆未能核實。請保留原請求並比較伺服器紀錄。",
        "outage_interval_invalid": "中斷開始時間不可遲於結束時間。",
        "outage_time_in_future": "時間不可遲於伺服器目前時間。",
        "outage_amendment_reason_required": "修訂中斷紀錄時必須填寫原因。",
        "outage_paper_validation": "請輸入紙本參考及不超過 2000 字的備註。",
        "outage_paper_time_invalid": "請輸入有效的香港日期及時間。",
        "outage_paper_target_required": "請填寫所選工作流程所需的目標編號。",
        "outage_paper_action_invalid": "所選工作流程不支援此操作。",
        "outage_paper_role_required": "此帳戶不可建立所選工作流程的紙本參考。",
        "outage_paper_not_found": "找不到所選紙本參考。",
        "outage_paper_not_editable": "此紙本參考不可修正；已輸入參考會保持不變。",
        "outage_paper_amendment_reason_required": "修正待輸入紙本參考時必須填寫原因。",
        "paper_already_entered": "此紙本參考已輸入並保持不變。",
        "paper_time_in_future": "紙本原始時間不可遲於伺服器目前時間。",
        "paper_reference_conflict": "此紙本參考編號已在此工作流程使用。",
        "paper_target_not_found": "找不到所選目標，或目標不屬於此投票站。",
        "paper_target_invalid": "紙本參考的工作流程、操作或目標不相符。",
        "outage_review_required": "請先載入並核對目前中斷及全部紙本修訂。",
        "outage_papers_pending": "每項紙本參考都必須先完成重新輸入。",
        "outage_paper_records_missing": "伺服器紙本參考清單已有變更，請重新核對。",
        "outage_reconciliation_validation": "請輸入監督員本人密碼及核對原因。",
        "outage_reconciliation_reason_required": "核對決定必須填寫原因。",
        "outage_reconciliation_revision_conflict": "核對已有較新修訂，請重新整理及比較。",
        "outage_paper_revision_conflict": "紙本參考已有較新修訂，請重新整理及比較。",
        "paper_revision_conflict": "紙本參考已有較新修訂，請重新整理及比較。",
        "outage_revision_conflict": "中斷紀錄已有較新修訂，請重新整理及比較。",
        "invalid_credentials": "密碼不正確。結果未改變；請核對後輸入本人密碼重試。",
        "supervisor_required": "只有獲指派的監督員可核准紙本核對。",
        "request_failed": "伺服器回覆無法核實。請檢查連線並比較伺服器紀錄。",
    },
    "sc": {
        "outage_existing_receipt_title": (
            "关联已核实的电子记录"
        ),
        "outage_existing_receipt_hint": (
            "将纸本参考关联至已保存的原始电子记录。此操作不会再次提交该项工作。"
        ),
        "outage_existing_receipt_request": (
            "原始请求编号"
        ),
        "outage_existing_receipt_check": (
            "核查原始记录"
        ),
        "outage_existing_receipt_checked": (
            "已核实的原始电子记录"
        ),
        "outage_existing_receipt_reason": (
            "关联原因"
        ),
        "outage_existing_receipt_link": (
            "关联已核实记录"
        ),
        "outage_existing_receipt_clear": (
            "清除关联草稿"
        ),
        "outage_existing_receipt_retry": (
            "重试关联已核实记录"
        ),
        "outage_existing_receipt_linked": (
            "纸本参考已关联至原始电子记录。"
        ),
        "outage_existing_receipt_server_time": (
            "原始记录的服务器输入时间"
        ),
        "outage_existing_link_metadata": (
            "后加的关联记录"
        ),
        "outage_existing_link_request": (
            "关联请求编号"
        ),
        "outage_existing_request_invalid": (
            "请输入有效的原始请求编号。"
        ),
        "outage_existing_receipt_check_required": (
            "请先核查原始电子记录，再进行关联。"
        ),
        "outage_existing_link_reason_required": (
            "请填写关联此记录的原因。"
        ),
        "outage_existing_link_clear_first": (
            "请先清除关联草稿，再编辑中断或纸本记录。"
        ),
        "paper_receipt_mismatch": (
            "原始电子记录与此纸本参考、操作或原始时间不符。"
        ),
        "paper_receipt_workflow_unsupported": (
            "无法将所选电子记录关联至此纸本操作。"
        ),
        "outage_receipt_status_draft": (
            "草稿"
        ),
        "outage_receipt_status_submitted": (
            "已提交"
        ),
        "outage_receipt_status_approved": (
            "已核准"
        ),
        "outage_receipt_status_recorded": (
            "已记录"
        ),
        "outage_title": "连接中断及纸本记录",
        "outage_report": "中断及纸本报表",
        "outage_report_preview": "预览报表",
        "outage_report_export_pdf": "导出 PDF",
        "outage_report_export_csv": "导出 CSV",
        "outage_report_ready": "中断及纸本报表已载入。",
        "outage_report_exported": "中断及纸本报表已导出。",
        "outage_report_export_failed": "未能导出中断及纸本报表。",
        "outage_intro": "记录实际中断时段及纸本参考。纸本原始时间与服务器记录时间分别保留。",
        "outage_station": "投票站编号",
        "outage_list": "已记录的连接中断",
        "outage_empty": "此投票站尚无连接中断记录。",
        "outage_new": "新增中断记录",
        "outage_load": "载入",
        "outage_refresh": "刷新清单",
        "outage_reload": "舍弃变更并重新载入",
        "outage_read_only": (
            '此账户仅可查看。获指派的投票'
            '站主任或点票主任可记录中断及'
            '纸本参考。'
        ),
        "outage_active_required": "只有选举进行期间可新增或修正记录。",
        "outage_details": "中断详情",
        "outage_reference": "中断参考",
        "outage_kind": "中断类型",
        "outage_network": "网络",
        "outage_backend": "后端服务器",
        "outage_database": "数据库",
        "outage_unknown": "不明",
        "outage_started": "实际开始时间（香港时间 YYYY-MM-DD HH:mm）",
        "outage_ended": "实际结束时间（香港时间 YYYY-MM-DD HH:mm）",
        "outage_time_hint": "可输入秒及最多六位小数秒；修改未改变的分钟会保留原有精度。",
        "outage_notes": "中断备注",
        "outage_reason": "修订原因",
        "outage_save": "保存中断记录",
        "outage_amend": "保存修订",
        "outage_revision": "中断修订",
        "outage_newer_revision": (
            '服务器已有较新中断、纸本或核'
            '对修订；未保存输入仍保留。请'
            '核对后明确重新载入。'
        ),
        "outage_server_entered": "服务器记录时间（香港时间）",
        "outage_actor": "记录人员编号",
        "outage_papers": "纸本参考",
        "outage_paper_new": "新增纸本参考",
        "outage_paper_reference": "纸本参考编号",
        "outage_workflow": "后续工作流程",
        "outage_action": "工作流程操作",
        "outage_count": "点票",
        "outage_turnout": "投票率",
        "outage_allocation": "柜台选票派发",
        "outage_submit": "提交点票",
        "outage_save_turnout": "保存投票率",
        "outage_create_allocation": "新增派发",
        "outage_amend_allocation": "修正派发",
        "outage_original_time": "纸本原始时间（香港时间 YYYY-MM-DD HH:mm）",
        "outage_original_time_hint": "此时间保留为纸本所载时间；服务器另行记录输入时间。",
        "outage_target_scope": "点票范围编号",
        "outage_target_round": "点票轮次编号",
        "outage_target_period": "投票率时段编号",
        "outage_target_counter": "发票柜台编号",
        "outage_target_allocation": "派发记录编号",
        "outage_paper_notes": "纸本记录备注",
        "outage_paper_reason": "修正纸本记录原因",
        "outage_paper_save": "保存纸本参考",
        "outage_paper_amend": "保存纸本修正",
        "outage_pending": "待重新输入",
        "outage_entered": "已重新输入",
        "outage_paper_revision": "纸本修订",
        "outage_paper_actor": "输入人员编号",
        "outage_paper_server_time": "服务器输入时间（香港时间）",
        "outage_reentry": "不可变更的输入收据",
        "outage_receipt_request": "原始请求编号",
        "outage_receipt_record": "原始记录编号",
        "outage_receipt_revision": "原始记录修订",
        "outage_receipt_status": "原始记录状态",
        "outage_receipt_event": "原始记录时间（香港时间）",
        "outage_receipt_target": "核对目标",
        "outage_receipt_actor": "重新输入人员编号",
        "outage_receipt_reentered_at": "重新输入时间（香港时间）",
        "outage_receipt_hourly": "每小时数量",
        "outage_receipt_cumulative": "累计数量",
        "outage_receipt_candidate": "候选人观察票数",
        "outage_receipt_invalid": "明显无效票分类数量",
        "outage_receipt_questionable_quantity": "待判定问题选票",
        "outage_receipt_actual_counted_quantity": "实际点算张数",
        "outage_receipt_initial_valid_quantity": "初步有效票总数",
        "outage_receipt_clearly_invalid_quantity": "明显无效票总数",
        "outage_receipt_initial_accounted_quantity": "初步核算票数",
        "outage_receipt_supplied_hourly": "填报每小时数量",
        "outage_receipt_supplied_cumulative": "填报累计数量",
        "outage_receipt_derived_hourly": "计算每小时数量",
        "outage_receipt_derived_cumulative_start": "计算期初累计数量",
        "outage_receipt_derived_cumulative_end": "计算期末累计数量",
        "outage_receipt_serials": "原编号范围",
        "outage_saved": "中断记录已保存至中央服务器。",
        "outage_paper_saved": "纸本参考已保存至中央服务器。",
        "outage_reconciled_notice": "纸本核对决定已保存至中央服务器。",
        "outage_reconcile": "监督员核对",
        "outage_reconcile_hint": (
            '核对所有纸本参考的不可变更收'
            '据及当前修订后，由监督员提交'
            '原因并以本人密码确认。'
        ),
        "outage_reconcile_reason": "核对原因",
        "outage_supervisor_password": "监督员本人密码",
        "outage_approve": "核准纸本核对",
        "outage_reconciled": "当前纸本核对已核准",
        "outage_not_reconciled": "尚未完成当前纸本核对",
        "outage_reconciliation_history": "核对决定历史",
        "outage_current_revision": "清单所示服务器修订",
        "outage_pending_request": "待核实请求编号",
        "outage_retry_outage": "比较后重试中断保存",
        "outage_retry_paper": "比较后重试纸本保存",
        "outage_retry_approval": "比较后重新确认核对",
        "outage_uncertain_hint": (
            '请刷新并比较服务器修订及参考'
            '，再决定是否以相同请求重试。'
            '程序不会自动重发。'
        ),
        "outage_dirty_hint": "表单有未保存变更。载入其他记录前，请明确选择舍弃并重新载入。",
        "outage_confirm_discard_title": "舍弃未保存变更？",
        "outage_confirm_discard": "当前输入尚未保存。只有选择舍弃并继续后才会载入另一记录。",
        "outage_keep_editing": "继续编辑",
        "outage_discard_continue": "舍弃并继续",
        "outage_context_unavailable": "请先选择已指派的投票站。",
        "outage_not_found": "找不到所选中断记录。",
        "outage_not_selected": "请先选择或新增中断记录。",
        "outage_uncertain_save_pending": (
            '仍有一项结果未核实的请求。请'
            '保留原请求内容并先比较服务器'
            '清单。'
        ),
        "unsaved_outage_changes": "中断表单有未保存变更。",
        "unsaved_outage_paper_changes": "纸本表单有未保存变更。",
        "outage_validation": "请输入参考、类型、有效香港时间及不超过 2000 字的备注。",
        "outage_response_invalid": "服务器回复无法核实。请保留原请求并比较服务器记录。",
        "outage_interval_invalid": "中断开始时间不可迟于结束时间。",
        "outage_time_in_future": "时间不可迟于服务器当前时间。",
        "outage_amendment_reason_required": "修订中断记录时必须填写原因。",
        "outage_paper_validation": "请输入纸本参考及不超过 2000 字的备注。",
        "outage_paper_time_invalid": "请输入有效的香港日期及时间。",
        "outage_paper_target_required": "请填写所选工作流程所需的目标编号。",
        "outage_paper_action_invalid": "所选工作流程不支持此操作。",
        "outage_paper_role_required": "此账户不可创建所选工作流程的纸本参考。",
        "outage_paper_not_found": "找不到所选纸本参考。",
        "outage_paper_not_editable": "此纸本参考不可修正；已输入参考会保持不变。",
        "outage_paper_amendment_reason_required": "修正待输入纸本参考时必须填写原因。",
        "paper_already_entered": "此纸本参考已输入并保持不变。",
        "paper_time_in_future": "纸本原始时间不可迟于服务器当前时间。",
        "paper_reference_conflict": "此纸本参考编号已在此工作流程使用。",
        "paper_target_not_found": "找不到所选目标，或目标不属于此投票站。",
        "paper_target_invalid": "纸本参考的工作流程、操作或目标不相符。",
        "outage_review_required": "请先载入并核对当前中断及全部纸本修订。",
        "outage_papers_pending": "每项纸本参考都必须先完成重新输入。",
        "outage_paper_records_missing": "服务器纸本参考清单已有变更，请重新核对。",
        "outage_reconciliation_validation": "请输入监督员本人密码及核对原因。",
        "outage_reconciliation_reason_required": "核对决定必须填写原因。",
        "outage_reconciliation_revision_conflict": "核对已有较新修订，请刷新及比较。",
        "outage_paper_revision_conflict": "纸本参考已有较新修订，请刷新及比较。",
        "paper_revision_conflict": "纸本参考已有较新修订，请刷新及比较。",
        "outage_revision_conflict": "中断记录已有较新修订，请刷新及比较。",
        "invalid_credentials": "密码不正确。结果未改变；请核对后输入本人密码重试。",
        "supervisor_required": "只有获指派的监督员可核准纸本核对。",
        "request_failed": "服务器回复无法核实。请检查连接并比较服务器记录。",
    },
    "en": {
        "outage_existing_receipt_title": (
            "Link a checked server entry"
        ),
        "outage_existing_receipt_hint": (
            "Match the paper reference to an entry already saved on the server. This does "
            "not submit the operation again."
        ),
        "outage_existing_receipt_request": (
            "Original request ID"
        ),
        "outage_existing_receipt_check": (
            "Check existing entry"
        ),
        "outage_existing_receipt_checked": (
            "Checked server entry"
        ),
        "outage_existing_receipt_reason": (
            "Reason for linking"
        ),
        "outage_existing_receipt_link": (
            "Link checked entry"
        ),
        "outage_existing_receipt_clear": (
            "Clear matching draft"
        ),
        "outage_existing_receipt_retry": (
            "Retry linking the checked entry"
        ),
        "outage_existing_receipt_linked": (
            "Paper reference linked to the original server entry."
        ),
        "outage_existing_receipt_server_time": (
            "Original server entry time"
        ),
        "outage_existing_link_metadata": (
            "Later linkage provenance"
        ),
        "outage_existing_link_request": (
            "Link request ID"
        ),
        "outage_existing_request_invalid": (
            "Enter a valid original request ID."
        ),
        "outage_existing_receipt_check_required": (
            "Check the original server entry before linking."
        ),
        "outage_existing_link_reason_required": (
            "Enter the reason for linking this entry."
        ),
        "outage_existing_link_clear_first": (
            "Clear the matching draft before editing the outage or paper record."
        ),
        "paper_receipt_mismatch": (
            "The server entry does not match this paper reference, action or original time."
        ),
        "paper_receipt_workflow_unsupported": (
            "The selected server entry cannot be linked to this paper action."
        ),
        "outage_receipt_status_draft": (
            "Draft"
        ),
        "outage_receipt_status_submitted": (
            "Submitted"
        ),
        "outage_receipt_status_approved": (
            "Approved"
        ),
        "outage_receipt_status_recorded": (
            "Recorded"
        ),
        "outage_title": "Connectivity outages and paper records",
        "outage_report": "Outage and paper reconciliation report",
        "outage_report_preview": "Preview report",
        "outage_report_export_pdf": "Export PDF",
        "outage_report_export_csv": "Export CSV",
        "outage_report_ready": "The outage and paper reconciliation report is loaded.",
        "outage_report_exported": "The outage and paper reconciliation report was exported.",
        "outage_report_export_failed": (
            "The outage and paper reconciliation report could not be exported."
        ),
        "outage_intro": (
            'Record the actual interruption and paper reference. Original paper '
            'time and server entry time are kept separately.'
        ),
        "outage_station": "Polling station ID",
        "outage_list": "Recorded connectivity outages",
        "outage_empty": "No connectivity outages are recorded for this station.",
        "outage_new": "New outage record",
        "outage_load": "Load",
        "outage_refresh": "Refresh list",
        "outage_reload": "Discard changes and reload",
        "outage_read_only": (
            'This account can view records. Assigned Polling or Counting Officers '
            'can record outages and paper references.'
        ),
        "outage_active_required": (
            'Records can be created or amended only while the election is active.'
        ),
        "outage_details": "Outage details",
        "outage_reference": "Outage reference",
        "outage_kind": "Interruption type",
        "outage_network": "Network",
        "outage_backend": "Backend",
        "outage_database": "Database",
        "outage_unknown": "Unknown",
        "outage_started": "Actual start (Hong Kong time, YYYY-MM-DD HH:mm)",
        "outage_ended": "Actual end (Hong Kong time, YYYY-MM-DD HH:mm)",
        "outage_time_hint": (
            'Seconds and up to six fractional digits are accepted. Unchanged '
            'minutes retain their saved precision.'
        ),
        "outage_notes": "Outage notes",
        "outage_reason": "Amendment reason",
        "outage_save": "Save outage record",
        "outage_amend": "Save amendment",
        "outage_revision": "Outage revision",
        "outage_newer_revision": (
            'A newer outage, paper or reconciliation revision exists. Your unsaved '
            'input is retained; compare before explicitly reloading.'
        ),
        "outage_server_entered": "Server entry time (Hong Kong time)",
        "outage_actor": "Entered by account ID",
        "outage_papers": "Paper references",
        "outage_paper_new": "New paper reference",
        "outage_paper_reference": "Paper reference",
        "outage_workflow": "Follow-up workflow",
        "outage_action": "Workflow action",
        "outage_count": "Count",
        "outage_turnout": "Turnout",
        "outage_allocation": "Counter allocation",
        "outage_submit": "Submit count",
        "outage_save_turnout": "Save turnout",
        "outage_create_allocation": "Create allocation",
        "outage_amend_allocation": "Amend allocation",
        "outage_original_time": "Original paper time (Hong Kong time, YYYY-MM-DD HH:mm)",
        "outage_original_time_hint": (
            'This preserves the time written on paper; the server records entry '
            'time separately.'
        ),
        "outage_target_scope": "Counting scope ID",
        "outage_target_round": "Count round ID",
        "outage_target_period": "Turnout period index",
        "outage_target_counter": "Issuance counter ID",
        "outage_target_allocation": "Allocation ID",
        "outage_paper_notes": "Paper record notes",
        "outage_paper_reason": "Paper correction reason",
        "outage_paper_save": "Save paper reference",
        "outage_paper_amend": "Save paper correction",
        "outage_pending": "Pending re-entry",
        "outage_entered": "Re-entered",
        "outage_paper_revision": "Paper revision",
        "outage_paper_actor": "Entered by account ID",
        "outage_paper_server_time": "Server entry time (Hong Kong time)",
        "outage_reentry": "Immutable re-entry receipt",
        "outage_receipt_request": "Original request ID",
        "outage_receipt_record": "Original record ID",
        "outage_receipt_revision": "Original record revision",
        "outage_receipt_status": "Original record status",
        "outage_receipt_event": "Original record time (Hong Kong time)",
        "outage_receipt_target": "Matched target",
        "outage_receipt_actor": "Re-entry account ID",
        "outage_receipt_reentered_at": "Re-entry time (Hong Kong time)",
        "outage_receipt_hourly": "Hourly quantity",
        "outage_receipt_cumulative": "Cumulative quantity",
        "outage_receipt_candidate": "Candidate observed votes",
        "outage_receipt_invalid": "Clearly invalid by reason",
        "outage_receipt_questionable_quantity": "Questionable papers",
        "outage_receipt_actual_counted_quantity": "Actual counted papers",
        "outage_receipt_initial_valid_quantity": "Initial valid total",
        "outage_receipt_clearly_invalid_quantity": "Clearly invalid total",
        "outage_receipt_initial_accounted_quantity": "Initial accounted total",
        "outage_receipt_supplied_hourly": "Reported hourly quantity",
        "outage_receipt_supplied_cumulative": "Reported cumulative quantity",
        "outage_receipt_derived_hourly": "Derived hourly quantity",
        "outage_receipt_derived_cumulative_start": "Derived cumulative at period start",
        "outage_receipt_derived_cumulative_end": "Derived cumulative at period end",
        "outage_receipt_serials": "Original serial range",
        "outage_saved": "The outage record was saved to the central server.",
        "outage_paper_saved": "The paper reference was saved to the central server.",
        "outage_reconciled_notice": (
            'The paper reconciliation decision was saved to the central server.'
        ),
        "outage_reconcile": "Supervisor reconciliation",
        "outage_reconcile_hint": (
            'After reviewing each immutable paper receipt and current revision, the '
            'Supervisor records a reason and confirms with their own password.'
        ),
        "outage_reconcile_reason": "Reconciliation reason",
        "outage_supervisor_password": "Supervisor's own password",
        "outage_approve": "Approve paper reconciliation",
        "outage_reconciled": "Current paper reconciliation is approved",
        "outage_not_reconciled": "Current paper reconciliation is not complete",
        "outage_reconciliation_history": "Reconciliation decision history",
        "outage_current_revision": "Server revision shown in list",
        "outage_pending_request": "Unconfirmed request ID",
        "outage_retry_outage": "Compare and retry outage save",
        "outage_retry_paper": "Compare and retry paper save",
        "outage_retry_approval": "Compare and confirm reconciliation",
        "outage_uncertain_hint": (
            'Refresh and compare the server revision and references before deciding '
            'whether to retry the same request. The client never resends '
            'automatically.'
        ),
        "outage_dirty_hint": (
            'The form has unsaved changes. Explicitly discard and reload before '
            'selecting another record.'
        ),
        "outage_confirm_discard_title": "Discard unsaved changes?",
        "outage_confirm_discard": (
            'This input is not saved. Another record loads only after you '
            'explicitly discard and continue.'
        ),
        "outage_keep_editing": "Keep editing",
        "outage_discard_continue": "Discard and continue",
        "outage_context_unavailable": "Select an assigned polling station first.",
        "outage_not_found": "The selected outage record was not found.",
        "outage_not_selected": "Select or create an outage record first.",
        "outage_uncertain_save_pending": (
            'A request outcome remains unconfirmed. Keep the original request and '
            'compare the server list first.'
        ),
        "unsaved_outage_changes": "The outage form has unsaved changes.",
        "unsaved_outage_paper_changes": "The paper form has unsaved changes.",
        "outage_validation": (
            'Enter a reference, type, valid Hong Kong times and notes of at most '
            '2,000 characters.'
        ),
        "outage_response_invalid": (
            'The server response could not be confirmed. Keep the original request '
            'and compare server records.'
        ),
        "outage_interval_invalid": "The outage start must not be after its end.",
        "outage_time_in_future": "The time must not be after the current server time.",
        "outage_amendment_reason_required": "An outage amendment requires a reason.",
        "outage_paper_validation": (
            'Enter a paper reference and notes of at most 2,000 characters.'
        ),
        "outage_paper_time_invalid": "Enter a valid Hong Kong date and time.",
        "outage_paper_target_required": (
            'Enter the target ID required by the selected workflow.'
        ),
        "outage_paper_action_invalid": (
            'This action is not supported for the selected workflow.'
        ),
        "outage_paper_role_required": (
            'This account cannot register a paper reference for the selected '
            'workflow.'
        ),
        "outage_paper_not_found": "The selected paper reference was not found.",
        "outage_paper_not_editable": (
            'This paper reference cannot be amended; entered references are '
            'immutable.'
        ),
        "outage_paper_amendment_reason_required": (
            'Correcting a pending paper reference requires a reason.'
        ),
        "paper_already_entered": "This paper reference has been entered and is immutable.",
        "paper_time_in_future": (
            'The original paper time must not be after the current server time.'
        ),
        "paper_reference_conflict": "This paper reference is already used in this workflow.",
        "paper_target_not_found": (
            'The selected target was not found or does not belong to this station.'
        ),
        "paper_target_invalid": (
            'The workflow, action or target does not match this paper reference.'
        ),
        "outage_review_required": (
            'Load and review the current outage and every paper revision first.'
        ),
        "outage_papers_pending": (
            'Every paper reference must be re-entered before reconciliation.'
        ),
        "outage_paper_records_missing": (
            'The server paper-reference list changed. Review it again.'
        ),
        "outage_reconciliation_validation": (
            "Enter the Supervisor's own password and a reconciliation reason."
        ),
        "outage_reconciliation_reason_required": "A reconciliation decision requires a reason.",
        "outage_reconciliation_revision_conflict": (
            'A newer reconciliation exists. Refresh and compare it.'
        ),
        "outage_paper_revision_conflict": (
            'A newer paper revision exists. Refresh and compare it.'
        ),
        "paper_revision_conflict": "A newer paper revision exists. Refresh and compare it.",
        "outage_revision_conflict": "A newer outage revision exists. Refresh and compare it.",
        "invalid_credentials": (
            'The password is incorrect. No result changed; check it and retry with '
            'your own password.'
        ),
        "supervisor_required": (
            'Only an assigned Supervisor can approve the paper reconciliation.'
        ),
        "request_failed": (
            'The server response could not be confirmed. Check the connection and '
            'compare server records.'
        ),
    },
}
