"""Staff-facing interface labels for the three supported desktop languages."""

from election.desktop.accounting_translations import ACCOUNTING_TRANSLATIONS
from election.desktop.allocation_translations import ALLOCATION_TRANSLATIONS
from election.desktop.box_translations import BOX_EVENT_WORDS
from election.desktop.complaint_period_translations import COMPLAINT_PERIOD_TRANSLATIONS
from election.desktop.complaint_translations import COMPLAINT_TRANSLATIONS
from election.desktop.counter_return_translations import COUNTER_RETURN_TRANSLATIONS
from election.desktop.counting_outcome_translations import COUNT_OUTCOME_TRANSLATIONS
from election.desktop.counting_round_translations import COUNTING_ROUND_TRANSLATIONS
from election.desktop.counting_scope_translations import COUNTING_SCOPE_TRANSLATIONS
from election.desktop.fallback_translations import FALLBACK_TRANSLATIONS
from election.desktop.fallback_turnout_translations import FALLBACK_TURNOUT_TRANSLATIONS
from election.desktop.invalid_reason_translations import INVALID_REASON_TRANSLATIONS
from election.desktop.outage_translations import OUTAGE_TRANSLATIONS
from election.desktop.paper_reentry_translations import PAPER_REENTRY_TRANSLATIONS
from election.desktop.recovery_translations import RECOVERY_TRANSLATIONS
from election.desktop.special_paper_translations import SPECIAL_PAPER_TRANSLATIONS
from election.desktop.stock_snapshot_translations import STOCK_SNAPSHOT_TRANSLATIONS

TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "app_name": "選舉管理及投票系統",
        "election_management": "選舉管理",
        "tagline": "清楚記錄每項票站工作。",
        "sign_in": "登入",
        "signing_in": "正在登入…",
        "staff_access": "職員登入",
        "welcome": "歡迎使用",
        "server_address": "伺服器位址",
        "username": "帳戶名稱",
        "password": "密碼",
        "change_password": "更改密碼",
        "current_password": "目前密碼",
        "new_password": "新密碼",
        "confirm_password": "確認新密碼",
        "password_hint": "請使用 12 至 128 個字元，並與目前密碼不同。",
        "first_login": "首次登入：請先更改臨時密碼。",
        "save_password": "儲存新密碼",
        "saving_password": "正在儲存…",
        "account": "帳戶",
        "workspace": "工作區",
        "polling": "投票站工作",
        "counting": "點票工作",
        "records": "記錄與報表",
        "settings": "設定",
        "no_election": "尚未設定選舉",
        "no_election_detail": "請由管理員設定選舉及票站資料後，再進行相關工作。",
        "authenticated": "身分驗證成功",
        "signed_in_as": "目前登入帳戶",
        "role": "職務",
        "administrator": "管理員",
        "polling_officer": "投票站職員",
        "counting_officer": "點票人員",
        "supervisor": "主管",
        "session_expires": "登入時段到期時間",
        "no_idle_lock": "閒置不會自動登出；每次登入時段最長為 24 小時。",
        "logout": "登出",
        "refresh": "重新整理",
        "server": "伺服器",
        "connecting": "正在連線",
        "connected": "已連線",
        "disconnected": "未能連線",
        "certificate_error": "無法驗證伺服器憑證。請檢查伺服器位址及信任憑證設定。",
        "invalid_server": "請輸入有效的 HTTPS 伺服器位址。",
        "invalid_credentials": "帳戶名稱或密碼不正確。",
        "session_expired": "登入時段已到期或失效，請重新登入。",
        "database_unavailable": "伺服器目前無法連接資料庫，請稍後重試。",
        "request_failed": "未能完成要求。請檢查連線後重試。",
        "validation_error": "請檢查輸入資料後重試。",
        "password_mismatch": "兩次輸入的新密碼不相同。",
        "password_changed": "密碼已在其他地方更改，請重新登入。",
        "password_unchanged": "新密碼必須與目前密碼不同。",
        "password_change_required": "請先更改臨時密碼，才能繼續。",
        "password_change_success": "新密碼已儲存。",
        "retry": "重試",
        "last_refresh": "最後更新",
        "hong_kong_time": "香港時間",
        "language": "語言",
        "connection_detail": "此桌面程式連接至所設定的中央伺服器。",
        "not_configured": "尚未設定",
        "signed_out": "已登出",
        "pending": "待處理",
        "ready": "已就緒",
        "user_profile": "帳戶資料",
        "session": "登入時段",
        "health_check": "連線檢查",
        "saved": "已儲存",
        "min_password": "密碼長度必須為 12 至 128 個字元。",
        "role_scope": "可用功能及資料取決於您的職務與票站指派。",
        "linked_server": "已設定的伺服器",
        "election_setup": "選舉設定",
        "saved_elections": "已儲存的選舉",
        "new_election": "新增選舉",
        "election_name": "選舉名稱",
        "save_election": "儲存選舉",
        "constituencies": "選區",
        "new_constituency": "新增選區",
        "constituency_name": "選區名稱",
        "constituency_code": "選區代號",
        "save_constituency": "儲存選區",
        "candidates": "候選人",
        "new_candidate": "新增候選人",
        "candidate_name": "候選人姓名",
        "ballot_number": "候選人編號",
        "save_candidate": "儲存候選人",
        "one_seat_rule": "每個選區選出 1 人；每張有效選票只可選擇 1 名候選人。",
        "select_election": "請選擇選舉",
        "select_constituency": "請選擇選區",
        "no_constituencies": "此選舉尚未新增選區。",
        "no_candidates": "此選區尚未新增候選人。",
        "draft": "草稿",
        "revision": "修訂版本",
        "unsaved_changes": "目前表格有未儲存的內容。切換選擇會捨棄這些內容。",
        "discard_changes": "捨棄變更",
        "keep_editing": "繼續編輯",
        "reload_saved": "重新載入已儲存資料",
        "configuration_saved": "設定已儲存。",
        "configuration_validation": (
            "名稱須為 1 至 160 個字元，選區代號須為 1 至 32 個字元，"
            "候選人編號須為正整數。請勿只輸入空白。"
        ),
        "revision_conflict": (
            "其他職員已儲存較新的版本。您的未儲存內容已保留；請重新載入已儲存資料後核對。"
        ),
        "duplicate_configuration": (
            "此代號或候選人編號已在目前的選舉、選區或投票站內使用，請改用其他值。"
        ),
        "request_conflict": (
            "此儲存要求已用於不同內容。您的輸入已保留；請重新載入已儲存資料後核對。"
        ),
        "configuration_not_found": "找不到所選資料，請重新整理後再選擇。",
        "draft_required": "只有選舉草稿可在此編輯。",
        "administrator_required": "只有管理員可設定選舉資料。",
        "saving": "正在儲存…",
        "loading": "正在載入…",
        "editing_new": "新增資料",
        "no_saved_elections": "尚未儲存選舉。請新增選舉草稿。",
        "station_setup": "票站設定",
        "station_setup_hint": "請先在「選舉設定」新增選舉及選區，再設定投票站與發票櫃台。",
        "stations": "投票站",
        "new_station": "新增投票站",
        "station_name": "投票站名稱",
        "station_code": "投票站代號",
        "save_station": "儲存投票站",
        "no_stations": "此選區尚未新增投票站。",
        "select_station": "請選擇投票站",
        "counters": "發票櫃台",
        "new_counter": "新增發票櫃台",
        "counter_name": "發票櫃台名稱",
        "counter_code": "發票櫃台代號",
        "save_counter": "儲存發票櫃台",
        "no_counters": "此投票站尚未新增發票櫃台。",
        "counting_mode": "點票安排",
        "local_counting": "本站點票",
        "send_to_destination": "送往指定點票站",
        "counting_destination": "接收票箱的點票站",
        "select_destination": "請選擇接收站",
        "counting_arrangement_note": "接收站必須屬於同一選區，並採用本站點票。",
        "receiving_from": "指定送往此站的來源投票站",
        "invalid_counting_destination": "請選擇同一選舉及選區內採用本站點票的其他投票站。",
        "receiver_in_use": (
            "其他投票站已指定送往此站。請先更改這些來源站的點票目的地，才可將此站改為送往其他站。"
        ),
        "station_configuration_validation": (
            "名稱須為 1 至 160 個字元，代號須為 1 至 32 個字元，且不可只有空白。"
            "送往其他站時，必須選擇接收站。"
        ),
        "schedule_not_configured": "尚未設定選舉時間表。",
        "schedule_required": "請先儲存完整的選舉時間表，才可啟用選舉。",
        "active_election_conflict": "請先完成目前進行中的選舉，才可啟用另一選舉。",
        "election_configuration_incomplete": "啟用前請補齊選區、候選人、投票站及發票櫃台資料。",
        "schedule_validation": (
            "請以香港時間 YYYY-MM-DD HH:mm 輸入有效日期及時間。結束時間須晚於開始時間，"
            "報告間隔須為 1 至 1440 分鐘。"
        ),
        "schedule_saved": "選舉時間表已儲存。",
        "election_activated": "選舉已啟用。",
        "unsaved_schedule": "時間表有未儲存的內容。請先儲存後再啟用選舉。",
        "staff_accounts": "職員帳戶",
        "unsaved_staff_changes": "請先儲存或重新載入帳戶變更，再重設密碼。",
        "no_audit_events": "尚無帳戶變更記錄。",
        "election_status": "選舉狀態",
        "read_only_election": "此選舉已啟用或完成，只可在此檢視。",
        "newer_saved_version": "已有較新的儲存版本。您的輸入已保留；請重新載入後核對。",
        "wrong_active_election": "此票站不屬於目前進行中的選舉，請重新整理並選擇可用票站。",
        "new_account": "新增帳戶",
        "select_account": "請選擇帳戶",
        "no_accounts": "尚未新增職員帳戶。",
        "display_name": "顯示名稱",
        "account_enabled": "啟用帳戶",
        "station_assignments": "票站指派",
        "no_station_options": "尚無可指派的投票站。請先完成票站設定。",
        "no_assigned_stations": "目前沒有可用的指派投票站。請聯絡管理員。",
        "save_account": "儲存帳戶",
        "temporary_password": "臨時密碼",
        "confirm_temporary_password": "確認臨時密碼",
        "reset_password": "重設密碼",
        "reset_password_hint": (
            "重設後所有登入時段將失效。職員須使用新臨時密碼登入，並先更改密碼。"
        ),
        "staff_changes_hint": "儲存變更後，此職員須重新登入。",
        "staff_saved": "職員帳戶已儲存。",
        "password_reset_success": "臨時密碼已重設。職員須重新登入並更改密碼。",
        "access_changed": "您的權限或票站指派已更改，請重新登入。",
        "staff_validation": (
            "帳戶名稱須為 1 至 64 個字元，顯示名稱須為 1 至 120 個字元，且不可只有空白。"
            "臨時密碼須為 12 至 128 個字元。"
        ),
        "username_exists": "此帳戶名稱已被使用，請改用其他名稱。",
        "account_not_found": "找不到所選帳戶，請重新整理。",
        "invalid_station_assignment": ("請指派現有投票站，且不可重複。管理員帳戶不可指派票站。"),
        "last_administrator_required": "最少須保留一個已啟用的管理員帳戶。",
        "operational_role_required": "此功能只供投票站職員、點票人員或主管使用。",
        "station_access_denied": "您未獲指派此投票站，無法存取其工作內容。",
        "audit_history": "帳戶變更記錄",
        "staff_created": "已建立職員帳戶",
        "staff_updated": "已更新職員帳戶",
        "staff_password_reset": "已重設職員密碼",
        "station_context": "票站工作區",
        "active_election": "進行中的選舉",
        "activation_guidance": "請由管理員在「選舉時間表」檢查設定並啟用選舉。",
        "no_active_election": "目前沒有進行中的選舉。",
        "selected_election": "所選選舉",
        "election_schedule": "選舉時間表",
        "election_date": "選舉日期",
        "planned_opening": "預定投票開始時間",
        "planned_closing": "預定投票結束時間",
        "reporting_interval": "報告間隔（分鐘）",
        "schedule_time_hint": (
            "香港時間 YYYY-MM-DD HH:mm；結束時間須晚於開始時間；"
            "報告間隔為 1 至 1440 分鐘。跨日結束時，請輸入結束當日日期。"
        ),
        "save_schedule": "儲存時間表",
        "activate_election": "啟用選舉",
        "activation_confirmation": "啟用所選選舉供所有票站使用？同一時間只可進行一場選舉。",
        "active": "進行中",
        "finalized": "已完成",
        "polling_events": "開站及關站記錄",
        "polling_schedule_summary": "時間表與最新記錄",
        "schedule_is_not_actual": "預定時間不代表票站已開放、已停止接納新到達者或已服務完畢。",
        "opening": "實際開站",
        "admission_closure": "停止接納新到達者",
        "queue_clear_estimate": "預計隊伍清理時間",
        "service_completion": "完成服務排隊選民",
        "not_recorded": "尚未記錄",
        "submitted": "已提交，待主管確認",
        "approved": "已確認",
        "missing": "尚未記錄",
        "on_time": "準時",
        "delayed": "延遲",
        "select_polling_event": "選擇開站或關站事項",
        "actual_opening_at": "實際開站時間",
        "admission_closed_at": "停止接納新到達者的時間",
        "queue_observed_at": "作出隊伍估算的時間",
        "actual_service_completed_at": "實際完成服務排隊選民的時間",
        "estimated_queue_clear_at": "預計完成服務排隊選民的時間",
        "opening_status": "開站情況",
        "opening_delay_reason": "延遲開站原因（延遲時必填）",
        "event_reason": "事項說明（如適用）",
        "amendment_reason": "修訂原因",
        "polling_time_hint": (
            "請輸入香港時間 YYYY-MM-DD HH:mm。未發生的實際事項可留空儲存草稿；提交前須填妥。"
        ),
        "queue_estimate_is_forecast": (
            "這是預測，並不代表隊伍已清理或投票工作已完成。請另行記錄實際完成服務時間。"
        ),
        "polling_read_only": "只有投票站職員可填寫事項；主管使用自己的帳戶確認已提交的修訂版本。",
        "save_polling_draft": "儲存事項草稿",
        "submit_polling": "提交此修訂版本",
        "amend_polling": "建立修訂草稿",
        "approve_polling": "主管確認",
        "approval_password": "您目前的主管帳戶密碼",
        "polling_approval_hint": (
            "請核對此事項及修訂版本，使用目前登入的主管帳戶密碼確認。密碼不會儲存在記錄內。"
        ),
        "polling_amendment_hint": (
            "輸入更正內容及修訂原因，再建立新草稿。較早版本及其確認會保留；新草稿須重新提交及確認。"
        ),
        "polling_history": "事項修訂及確認記錄",
        "no_polling_history": "此事項尚無已儲存的記錄。",
        "server_entry": "伺服器記錄時間",
        "entered_by": "記錄職員編號",
        "submission": "提交資料",
        "submitted_by": "提交職員編號",
        "approval": "主管確認資料",
        "approved_by": "確認主管編號",
        "planned_time_basis": "所依據的預定時間",
        "polling_validation": (
            "請檢查實際時間、預計時間及原因。實際事項不可在未來發生，事項先後"
            "須一致，延遲開站須說明原因。"
        ),
        "active_election_required": "只可記錄進行中選舉的票站事項。請先由管理員啟用選舉。",
        "polling_officer_required": "只有獲指派的投票站職員可填寫及提交此事項。",
        "supervisor_required": "只有獲指派的主管可確認此事項。",
        "polling_state_conflict": (
            "事項狀態已改變，無法完成此操作。您的輸入已保留，請重新載入後核對。"
        ),
        "unsaved_polling_changes": "表格有未儲存的內容。請先儲存，或捨棄變更後繼續。",
        "polling_saved": "事項草稿已儲存，尚未提交。",
        "polling_submitted": "此修訂版本已提交，待主管確認。",
        "polling_approved": "主管已確認此修訂版本。",
        "polling_amended": "已建立修訂草稿。較早版本及確認已保留；請核對後重新提交。",
        "polling_newer_revision": (
            "已有較新的事項版本。您檢視的版本及輸入已保留；請重新載入後核對。"
        ),
        "turnout_validation": "請檢查投票人數、累計數字、報告時段、香港時間及原因。",
        "turnout_period_not_found": "找不到此報告時段，請重新載入並核對選舉時間表。",
        "turnout_record_not_found": "找不到所選的投票人數記錄或版本，請重新載入。",
        "turnout_schedule_conflict": "報告所依據的時間表已變更，請重新載入並比較後再繼續。",
        "turnout_state_conflict": "報告狀態已變更，請重新載入已儲存的版本並核對。",
        "turnout_review_required": "請先審閱目前已儲存的投票人數及來源，再提交或確認。",
        "turnout_previous_period_required": "請先完成所需的較早報告時段，再繼續此時段。",
        "unsaved_turnout_changes": "投票人數表格有未儲存內容，請先儲存或確認捨棄。",
        "turnout_saved": "投票人數草稿已儲存，尚未提交。",
        "turnout_submitted": "此投票人數版本已提交，待主管確認。",
        "turnout_approved": "主管已確認此投票人數版本。",
        "turnout_amended": "已建立修訂草稿；原有版本及確認已保留，請核對後重新提交。",
        "turnout_newer_revision": (
            "伺服器資料或確認狀態已有變更。您審閱的版本及未儲存內容已保留，請重新載入並比較。"
        ),
        "external_manual": "人工提供的外部數字",
        "turnout_title": "正常模式投票人數",
        "turnout_intro": (
            "人工填寫外部提供的時段及累計投票人數，無須 EPR 連線、P(12) 快照或已確認的開站記錄。"
        ),
        "turnout_approved_coverage": "連續有效的主管確認範圍",
        "turnout_coverage_hint": (
            "只計入從首時段開始連續且仍有效的主管確認。缺漏、草稿、待確認或須重新覆核的時段，"
            "不會當作零人加入；沒有有效確認的人數顯示為「—」。"
        ),
        "turnout_approved_total": "有效確認範圍的累計投票人數",
        "turnout_approved_periods": "連續有效確認的時段數",
        "turnout_covered_until": "有效確認至",
        "turnout_baseline_hint": (
            "首時段以零為起始累計基礎；較後時段須以前一時段仍有效的主管確認為基礎。"
            "即使開站確認尚待處理，也可記錄已完結時段的明確零人報表。"
        ),
        "turnout_configured_schedule": "依選舉時間表設定的報告時段",
        "turnout_total_periods": "已設定的時段總數",
        "turnout_period": "報告時段",
        "turnout_select_period": "選擇報告時段",
        "turnout_visible_periods": "本頁時段數／全部時段數",
        "turnout_previous_page": "上一頁報告時段",
        "turnout_next_page": "下一頁報告時段",
        "turnout_goto_period": "輸入報告時段編號（由 1 開始）",
        "turnout_goto_action": "前往指定報告時段",
        "turnout_reviewed_period": "審閱的時段及版本",
        "turnout_historical": "歷史版本，只供檢視；繼續填寫前請重新載入目前版本。",
        "turnout_live_state": "伺服器目前狀態（與審閱版本分開）",
        "turnout_approval_valid": "此時段仍屬連續有效的主管確認範圍。",
        "turnout_review_invalid": (
            "原確認已保留，但其來源或前一時段基礎已變更，現須重新覆核。請建立有原因的修訂草稿並重新提交。"
        ),
        "turnout_not_approved": "此時段目前未納入有效確認範圍。",
        "turnout_supplied_hourly": "外部提供的本時段投票人數",
        "turnout_supplied_cumulative": "外部提供的截至本時段末累計投票人數",
        "turnout_optional_counts_hint": (
            "可填本時段人數、累計人數，或同時填兩者。只用非負整數；輸入 0 表示明確零人，"
            "留空表示尚未提供。主管確認時會核對相鄰累計及涵蓋時段。"
        ),
        "turnout_event_time": "外部報表的原始事件時間",
        "turnout_time_hint": (
            "香港時間：YYYY-MM-DD HH:mm。草稿可暫存未完整資料；提交須為已完結時段，"
            "原始事件時間不得早於時段結束或晚於現在。"
        ),
        "turnout_source_context": "外部數字來源及涵蓋範圍",
        "turnout_read_only": "此職務可檢視時段及歷史；只有獲指派的投票站職員可準備報表。",
        "turnout_save": "儲存投票人數草稿",
        "turnout_submit": "提交此版本供主管確認",
        "turnout_amend": "建立有原因的修訂草稿",
        "turnout_amendment_hint": (
            "已提交或已確認的數字須以修訂草稿更正，並填寫原因。較早版本及確認會保留；"
            "受影響的較後時段須重新覆核。"
        ),
        "turnout_approve": "主管確認此投票人數版本",
        "turnout_approval_hint": (
            "請核對目前審閱的時段、版本及來源，再輸入您目前登入主管帳戶的現有密碼。"
            "確認只適用於此版本，並須具備有效的前一時段基礎。"
        ),
        "turnout_history": "時段修訂及確認歷史",
        "turnout_no_history": "此時段尚無已儲存的版本。",
        "turnout_view_revision": "檢視此版本",
        "turnout_derived_hourly": "此版本確認時計算的本時段人數",
        "turnout_derived_start": "此版本確認時採用的起始累計",
        "turnout_derived_end": "此版本確認時計算的結束累計",
        "turnout_basis_revision": "所依據的前一時段確認版本",
        "turnout_basis_record": "記錄編號",
        "turnout_first_baseline": "首時段起始累計基礎：0",
        "turnout_report": "P(15) 時段及累計投票人數報表",
        "turnout_report_hint": (
            "請選擇審閱版本或本站目前報表；兩者均使用已儲存資料，不包含未儲存內容。"
        ),
        "turnout_report_scope": "選擇報表基準",
        "turnout_report_selected": "目前審閱的時段版本",
        "turnout_report_station": "本站目前 P(15) 總覽",
        "turnout_report_selected_hint": "保留您審閱的確切版本，包括歷史數字、來源及原確認資料。",
        "turnout_report_station_hint": "使用伺服器目前已儲存的全部時段及連續有效確認範圍。",
        "turnout_report_missing": "此時段尚無已儲存版本；可改選本站目前總覽。",
        "turnout_report_ready": "P(15) 投票人數報表預覽已準備好。",
        "turnout_exported": "P(15) 投票人數報表已儲存至所選檔案。",
        "turnout_export_failed": "未能儲存 P(15) 投票人數報表，請檢查位置及連線後重試。",
        "boxes": "票箱交收與點票事項",
        "box_list": "已儲存的票箱記錄",
        "box_new": "新增票箱",
        "box_select": "選擇票箱記錄",
        "box_none": "尚無已儲存的票箱記錄；這不代表現場沒有票箱。",
        "box_read_only": "此處僅供檢視；交收及點票事項須由具相應票站權限的職員記錄。",
        "box_newer_revision": (
            "伺服器已有較新記錄。您審閱的版本及未儲存內容已保留，請重新載入並比較。"
        ),
        "box_details": "票箱資料",
        "box_ref": "票箱識別資料",
        "box_seal": "封條識別資料",
        "box_origin": "來源投票站",
        "box_destination": "接收點票站",
        "box_status": "交收狀態",
        "box_prepared": "已記錄準備完成",
        "box_departed_status": "已記錄離站",
        "box_received_status": "已記錄接收",
        "box_prepared_time": "實際準備完成時間（香港時間）",
        "box_departure_time": "實際離站時間（香港時間）",
        "box_receipt_time": "實際接收時間（香港時間）",
        "box_time_hint": "請輸入實際發生的香港時間，格式為 YYYY-MM-DD HH:mm；不可填寫未來時間。",
        "box_create": "儲存票箱準備記錄",
        "box_handover": "記錄交收",
        "box_event_time": "實際事項時間（香港時間）",
        "box_reason": "說明／修正原因",
        "box_depart": "記錄離站",
        "box_receive": "記錄接收",
        "box_correct_departure": "修正離站記錄",
        "box_correct_receipt": "修正接收記錄",
        "box_history": "票箱交收歷史",
        "box_no_history": "此票箱尚無已儲存的交收歷史。",
        "box_entered_at": "伺服器記錄時間",
        "box_actor": "記錄職員編號",
        "box_event_prepared": "票箱準備完成",
        "box_event_departure": "票箱離站",
        "box_event_receipt": "接收票箱",
        "box_event_departure_correction": "離站記錄修正",
        "box_event_receipt_correction": "接收記錄修正",
        "box_milestones": "點票工作事項",
        "box_milestone_kind": "事項類別",
        "box_conversion_complete": "投票站轉為點票站完成",
        "box_first_box_opening": "首次開啟票箱",
        "box_questionable_determination_start": "開始審定問題選票",
        "box_milestone_box": "首次開啟的票箱",
        "box_milestone_time": "實際事項時間（香港時間）",
        "box_milestone_reason": "事項說明／修訂原因",
        "box_save_milestone": "儲存點票事項",
        "box_milestone_history": "點票事項修訂歷史",
        "box_no_milestones": "尚無已儲存的點票事項。",
        "box_count_completion": "點票完成時間",
        "box_count_unrecorded": "尚未記錄；完成時間會由後續的點票完成流程產生。",
        "box_milestones_not_applicable": "此投票站將票箱送往指定點票站，本地點票事項不適用。",
        "box_report": "票箱交收與點票事項報表",
        "box_report_hint": (
            "報表使用產生當刻伺服器已儲存的整個票站記錄，不包含未儲存內容；"
            "產生報表不會更改您目前審閱的記錄。"
        ),
        "box_milestone_correction_hint": "修訂已儲存的點票事項須填寫原因；原有版本會保留。",
        "box_validation": (
            "請檢查票箱、封條、實際時間及相關事項。時間不能在未來，並須符合已記錄的交收次序。"
        ),
        "box_departure_required": "尚未記錄票箱離站，不能確認接收送抵的票箱。",
        "box_receipt_required": "請先記錄接收此票箱，再記錄開箱時間。",
        "box_reference_exists": "來源票站已有相同識別資料的票箱，請核對現有記錄。",
        "box_state_conflict": "所選的交收事項已記錄或狀態已變更，請重新載入並比較。",
        "box_not_found": "在獲准的票站範圍內找不到此票箱，請重新載入。",
        "box_correction_reason_required": "修正已記錄的事項時，必須填寫原因。",
        "counting_station_required": "此事項只適用於進行本地點票的站點。",
        "counting_officer_required": "此事項須由獲指派的點票人員記錄。",
        "unsaved_box_changes": "票箱或點票事項表格有未儲存內容，請先儲存或確認捨棄。",
        "box_saved": "票箱準備記錄已儲存。",
        "box_departed": "票箱離站記錄已儲存。",
        "box_received": "票箱接收記錄已儲存。",
        "box_corrected": "交收修正已儲存，原有記錄已保留。",
        "box_milestone_saved": "點票工作事項已儲存。",
        "box_report_ready": "伺服器目前的交收及事項報表已載入。",
        "box_exported": "票箱交收報表已儲存至所選檔案。",
        "box_export_failed": "未能完成匯出，請檢查檔案位置及連線後重試。",
        "queue": "輪候時間",
        "queue_latest": "最新輪候觀察",
        "queue_missing": "尚無輪候觀察，不能視為沒有隊伍。",
        "queue_due": "已到更新時間，請觀察並記錄輪候情況，或確認情況不變。",
        "queue_fresh": "觀察仍在 30 分鐘更新時段內。",
        "queue_under_30": "少於 30 分鐘",
        "queue_30_59": "30 至 59 分鐘",
        "queue_60_90": "60 至 90 分鐘",
        "queue_over_90": "超過 90 分鐘",
        "queue_band": "輪候時間範圍",
        "queue_observation": "輪候觀察",
        "queue_unchanged_confirmation": "確認輪候情況不變",
        "queue_event_time": "觀察／確認時間（香港時間）",
        "queue_entered_at": "伺服器記錄時間",
        "queue_actor": "記錄職員編號",
        "queue_due_at": "下次更新時間",
        "queue_overdue_periods": "已到期的 30 分鐘時段數",
        "queue_form": "記錄輪候情況",
        "queue_form_hint": (
            "請輸入實際觀察時間，格式為 YYYY-MM-DD HH:mm。確認情況不變也會新增一項有時間的記錄。"
        ),
        "queue_reason": "觀察說明（選填）",
        "queue_save": "儲存新觀察",
        "queue_confirm": "確認範圍不變",
        "queue_confirm_hint": "確認不變時，請保留已審閱的範圍、清空觀察說明，並輸入新的確認時間。",
        "queue_reviewed": "目前審閱的記錄版本",
        "queue_read_only": "只有獲指派的投票站職員可在進行中的選舉記錄輪候情況。",
        "queue_history": "輪候觀察與確認歷史",
        "queue_no_history": "尚無已儲存的輪候觀察或確認。",
        "queue_confirms": "所確認的記錄編號",
        "queue_current_marker": "最新觀察",
        "queue_newer_revision": (
            "伺服器有較新的記錄。已保留目前審閱的版本及輸入內容；請重新載入並比較後再記錄。"
        ),
        "queue_validation": "請檢查輪候範圍、香港時間及說明。實際觀察／確認時間不能在未來。",
        "queue_confirmation_requires_current": (
            "確認不變前，請保留已審閱的輪候範圍並清空觀察說明；如情況有變，請儲存新觀察。"
        ),
        "queue_observation_conflict": "所確認的觀察已變更或尚未存在。請重新載入記錄並比較。",
        "queue_revision_not_found": "找不到所選的輪候歷史版本，請重新載入。",
        "unsaved_queue_changes": "輪候表格有未儲存的內容。請先儲存，或捨棄並重新載入。",
        "queue_saved": "輪候觀察已儲存。",
        "queue_confirmed": "輪候情況不變的確認已儲存。",
        "queue_report": "輪候情況歷史報表",
        "queue_report_hint": "報表使用目前審閱版本的已儲存歷史，不包含未儲存的表格內容。",
        "queue_report_ready": "輪候歷史報表預覽已載入。",
        "queue_exported": "輪候歷史報表已儲存至所選檔案。",
        "queue_export_failed": "未能完成匯出。請檢查檔案位置及連線後重試。",
        "received_stock": "選票接收與儲備",
        "stock_receipt": "接收記錄",
        "stock_receipts": "已儲存的接收記錄",
        "new_stock_receipt": "新增接收記錄",
        "select_stock_receipt": "請選擇接收記錄",
        "no_stock_receipts": "此投票站尚未記錄收到的選票。",
        "stock_read_only": "只有獲指派的投票站職員可新增或修正接收記錄。歷史版本只供查看與匯出。",
        "stock_recorded": "已記錄",
        "stock_current": "目前版本",
        "stock_historical": "歷史版本（唯讀）",
        "stock_return_current": "載入目前版本",
        "stock_series": "選票系列",
        "stock_event_at": "接收時間（香港時間）",
        "stock_time_hint": "請以香港時間 YYYY-MM-DD HH:mm 輸入原本接收選票的時間。",
        "stock_pool_hint": (
            "普通選票、替換選票儲備及重複選票儲備分開記錄。請填寫各類起始數量；沒有儲備時請填寫 0。"
        ),
        "stock_pool_ordinary": "普通選票",
        "stock_pool_replacement": "替換選票儲備",
        "stock_pool_tendered": "重複選票儲備",
        "stock_calculated_total": "按編號範圍計算的接收總數",
        "stock_total_received": "已記錄接收總數",
        "stock_add_range": "新增編號範圍",
        "stock_remove_range": "移除此範圍",
        "stock_serial_hint": (
            "請輸入 1 至 18 位半形數字，並保留編號前的 0。"
            "起始編號不可大於結束編號，各類範圍不可重疊。"
        ),
        "no_stock_ranges": "尚未新增編號範圍。請新增普通選票或儲備範圍。",
        "stock_range": "編號範圍",
        "stock_pool": "選票類別",
        "stock_serial_from": "起始編號",
        "stock_serial_to": "結束編號",
        "stock_range_quantity": "計算所得數量",
        "stock_correction_hint": "儲存修正會建立新版本並保留原記錄。請填寫修正原因。",
        "stock_reason": "修正原因",
        "stock_save_correction": "儲存修正版本",
        "stock_save": "儲存接收記錄",
        "stock_history": "接收記錄修訂歷史",
        "no_stock_history": "尚無可查看的接收記錄版本。",
        "stock_report": "選票接收及儲備報表",
        "stock_report_hint": (
            "預覽及匯出以所選記錄及修訂版本為準。請先儲存變更，或重新載入已儲存版本。"
        ),
        "stock_report_language": "匯出報表語言",
        "stock_preview": "預覽報表",
        "stock_export_pdf": "匯出 PDF",
        "stock_export_csv": "匯出 UTF-8 CSV",
        "stock_preview_language": "目前預覽的語言",
        "stock_export_location": "已儲存的報表檔案",
        "stock_validation": (
            "請檢查選票系列、香港時間及有效編號範圍。"
            "三類起始數量須為非負整數，並與各類編號範圍合計相符。"
            "最少須接收 1 張選票。"
        ),
        "stock_overlap": "此選區及選票系列的編號已由其他接收記錄或類別使用，請核對範圍。",
        "stock_receipt_not_found": "找不到所選接收記錄或修訂版本，請重新整理後再選擇。",
        "election_read_only": "已完成選舉的記錄只供查看與匯出，不能直接更改。",
        "stock_saved": "選票接收記錄已儲存。",
        "stock_report_ready": "所選版本的報表預覽已載入。",
        "stock_exported": "報表已儲存至所選檔案。",
        "stock_export_failed": "匯出未完成。請檢查所選檔案位址及連線，然後重試。",
        "stock_newer_revision": (
            "伺服器有較新的版本。您正在查看的版本及未儲存內容已保留；請重新載入並核對。"
        ),
        "unsaved_stock_changes": (
            "此表格有未儲存內容。請先儲存變更，或捨棄變更並重新載入已儲存版本，再繼續。"
        ),
        "report_glyph_unavailable": (
            "PDF 字型不支援報表中的部分文字。請保留原文，改用 CSV 或請管理員更新報表字型。"
        ),
        "unsaved_station_changes": "表格有未儲存的內容。請先儲存，或捨棄變更後繼續。",
    },
    "sc": {
        "app_name": "选举管理及投票系统",
        "election_management": "选举管理",
        "tagline": "清楚记录每项票站工作。",
        "sign_in": "登录",
        "signing_in": "正在登录…",
        "staff_access": "职员登录",
        "welcome": "欢迎使用",
        "server_address": "服务器地址",
        "username": "账户名称",
        "password": "密码",
        "change_password": "更改密码",
        "current_password": "当前密码",
        "new_password": "新密码",
        "confirm_password": "确认新密码",
        "password_hint": "请使用 12 至 128 个字符，并与当前密码不同。",
        "first_login": "首次登录：请先更改临时密码。",
        "save_password": "保存新密码",
        "saving_password": "正在保存…",
        "account": "账户",
        "workspace": "工作区",
        "polling": "投票站工作",
        "counting": "点票工作",
        "records": "记录与报表",
        "settings": "设置",
        "no_election": "尚未设置选举",
        "no_election_detail": "请由管理员设置选举及票站资料后，再进行相关工作。",
        "authenticated": "身份验证成功",
        "signed_in_as": "当前登录账户",
        "role": "职务",
        "administrator": "管理员",
        "polling_officer": "投票站职员",
        "counting_officer": "点票人员",
        "supervisor": "主管",
        "session_expires": "登录会话到期时间",
        "no_idle_lock": "闲置不会自动退出；每次登录会话最长为 24 小时。",
        "logout": "退出登录",
        "refresh": "刷新",
        "server": "服务器",
        "connecting": "正在连接",
        "connected": "已连接",
        "disconnected": "无法连接",
        "certificate_error": "无法验证服务器证书。请检查服务器地址及信任证书设置。",
        "invalid_server": "请输入有效的 HTTPS 服务器地址。",
        "invalid_credentials": "账户名称或密码不正确。",
        "session_expired": "登录会话已到期或失效，请重新登录。",
        "database_unavailable": "服务器当前无法连接数据库，请稍后重试。",
        "request_failed": "无法完成请求。请检查连接后重试。",
        "validation_error": "请检查输入资料后重试。",
        "password_mismatch": "两次输入的新密码不相同。",
        "password_changed": "密码已在其他地方更改，请重新登录。",
        "password_unchanged": "新密码必须与当前密码不同。",
        "password_change_required": "请先更改临时密码，才能继续。",
        "password_change_success": "新密码已保存。",
        "retry": "重试",
        "last_refresh": "最后更新",
        "hong_kong_time": "香港时间",
        "language": "语言",
        "connection_detail": "此桌面程序连接至所设置的中央服务器。",
        "not_configured": "尚未设置",
        "signed_out": "已退出登录",
        "pending": "待处理",
        "ready": "已就绪",
        "user_profile": "账户资料",
        "session": "登录会话",
        "health_check": "连接检查",
        "saved": "已保存",
        "min_password": "密码长度必须为 12 至 128 个字符。",
        "role_scope": "可用功能及资料取决于您的职务与票站分配。",
        "linked_server": "已设置的服务器",
        "election_setup": "选举设置",
        "saved_elections": "已保存的选举",
        "new_election": "新增选举",
        "election_name": "选举名称",
        "save_election": "保存选举",
        "constituencies": "选区",
        "new_constituency": "新增选区",
        "constituency_name": "选区名称",
        "constituency_code": "选区代号",
        "save_constituency": "保存选区",
        "candidates": "候选人",
        "new_candidate": "新增候选人",
        "candidate_name": "候选人姓名",
        "ballot_number": "候选人编号",
        "save_candidate": "保存候选人",
        "one_seat_rule": "每个选区选出 1 人；每张有效选票只可选择 1 名候选人。",
        "select_election": "请选择选举",
        "select_constituency": "请选择选区",
        "no_constituencies": "此选举尚未新增选区。",
        "no_candidates": "此选区尚未新增候选人。",
        "draft": "草稿",
        "revision": "修订版本",
        "unsaved_changes": "当前表格有未保存的内容。切换选择会舍弃这些内容。",
        "discard_changes": "舍弃更改",
        "keep_editing": "继续编辑",
        "reload_saved": "重新载入已保存资料",
        "configuration_saved": "设置已保存。",
        "configuration_validation": (
            "名称须为 1 至 160 个字符，选区代号须为 1 至 32 个字符，"
            "候选人编号须为正整数。请勿只输入空白。"
        ),
        "revision_conflict": (
            "其他职员已保存较新的版本。您的未保存内容已保留；请重新载入已保存资料后核对。"
        ),
        "duplicate_configuration": (
            "此代号或候选人编号已在当前的选举、选区或投票站内使用，请改用其他值。"
        ),
        "request_conflict": (
            "此保存请求已用于不同内容。您的输入已保留；请重新载入已保存资料后核对。"
        ),
        "configuration_not_found": "找不到所选资料，请刷新后再选择。",
        "draft_required": "只有选举草稿可在此编辑。",
        "administrator_required": "只有管理员可设置选举资料。",
        "saving": "正在保存…",
        "loading": "正在载入…",
        "editing_new": "新增资料",
        "no_saved_elections": "尚未保存选举。请新增选举草稿。",
        "station_setup": "票站设置",
        "station_setup_hint": "请先在“选举设置”新增选举及选区，再设置投票站与发票柜台。",
        "stations": "投票站",
        "new_station": "新增投票站",
        "station_name": "投票站名称",
        "station_code": "投票站代号",
        "save_station": "保存投票站",
        "no_stations": "此选区尚未新增投票站。",
        "select_station": "请选择投票站",
        "counters": "发票柜台",
        "new_counter": "新增发票柜台",
        "counter_name": "发票柜台名称",
        "counter_code": "发票柜台代号",
        "save_counter": "保存发票柜台",
        "no_counters": "此投票站尚未新增发票柜台。",
        "counting_mode": "点票安排",
        "local_counting": "本站点票",
        "send_to_destination": "送往指定点票站",
        "counting_destination": "接收票箱的点票站",
        "select_destination": "请选择接收站",
        "counting_arrangement_note": "接收站必须属于同一选区，并采用本站点票。",
        "receiving_from": "指定送往此站的来源投票站",
        "invalid_counting_destination": "请选择同一选举及选区内采用本站点票的其他投票站。",
        "receiver_in_use": (
            "其他投票站已指定送往此站。请先更改这些来源站的点票目的地，才可将此站改为送往其他站。"
        ),
        "station_configuration_validation": (
            "名称须为 1 至 160 个字符，代号须为 1 至 32 个字符，且不可只有空白。"
            "送往其他站时，必须选择接收站。"
        ),
        "schedule_not_configured": "尚未设置选举时间表。",
        "schedule_required": "请先保存完整的选举时间表，才可启用选举。",
        "active_election_conflict": "请先完成当前进行中的选举，才可启用另一选举。",
        "election_configuration_incomplete": "启用前请补齐选区、候选人、投票站及发票柜台资料。",
        "schedule_validation": (
            "请以香港时间 YYYY-MM-DD HH:mm 输入有效日期及时间。结束时间须晚于开始时间，"
            "报告间隔须为 1 至 1440 分钟。"
        ),
        "schedule_saved": "选举时间表已保存。",
        "election_activated": "选举已启用。",
        "unsaved_schedule": "时间表有未保存的内容。请先保存后再启用选举。",
        "staff_accounts": "职员账户",
        "unsaved_staff_changes": "请先保存或重新载入账户更改，再重设密码。",
        "no_audit_events": "尚无账户更改记录。",
        "election_status": "选举状态",
        "read_only_election": "此选举已启用或完成，只可在此查看。",
        "newer_saved_version": "已有较新的保存版本。您的输入已保留；请重新载入后核对。",
        "wrong_active_election": "此票站不属于当前进行中的选举，请刷新并选择可用票站。",
        "new_account": "新增账户",
        "select_account": "请选择账户",
        "no_accounts": "尚未新增职员账户。",
        "display_name": "显示名称",
        "account_enabled": "启用账户",
        "station_assignments": "票站指派",
        "no_station_options": "尚无可指派的投票站。请先完成票站设置。",
        "no_assigned_stations": "当前没有可用的指派投票站。请联系管理员。",
        "save_account": "保存账户",
        "temporary_password": "临时密码",
        "confirm_temporary_password": "确认临时密码",
        "reset_password": "重设密码",
        "reset_password_hint": (
            "重设后所有登录会话将失效。职员须使用新临时密码登录，并先更改密码。"
        ),
        "staff_changes_hint": "保存更改后，此职员须重新登录。",
        "staff_saved": "职员账户已保存。",
        "password_reset_success": "临时密码已重设。职员须重新登录并更改密码。",
        "access_changed": "您的权限或票站指派已更改，请重新登录。",
        "staff_validation": (
            "账户名称须为 1 至 64 个字符，显示名称须为 1 至 120 个字符，且不可只有空白。"
            "临时密码须为 12 至 128 个字符。"
        ),
        "username_exists": "此账户名称已被使用，请改用其他名称。",
        "account_not_found": "找不到所选账户，请刷新。",
        "invalid_station_assignment": ("请指派现有投票站，且不可重复。管理员账户不可指派票站。"),
        "last_administrator_required": "最少须保留一个已启用的管理员账户。",
        "operational_role_required": "此功能只供投票站职员、点票人员或主管使用。",
        "station_access_denied": "您未获指派此投票站，无法访问其工作内容。",
        "audit_history": "账户更改记录",
        "staff_created": "已建立职员账户",
        "staff_updated": "已更新职员账户",
        "staff_password_reset": "已重设职员密码",
        "station_context": "票站工作区",
        "active_election": "进行中的选举",
        "activation_guidance": "请由管理员在“选举时间表”检查设置并启用选举。",
        "no_active_election": "当前没有进行中的选举。",
        "selected_election": "所选选举",
        "election_schedule": "选举时间表",
        "election_date": "选举日期",
        "planned_opening": "预定投票开始时间",
        "planned_closing": "预定投票结束时间",
        "reporting_interval": "报告间隔（分钟）",
        "schedule_time_hint": (
            "香港时间 YYYY-MM-DD HH:mm；结束时间须晚于开始时间；"
            "报告间隔为 1 至 1440 分钟。跨日结束时，请输入结束当日日期。"
        ),
        "save_schedule": "保存时间表",
        "activate_election": "启用选举",
        "activation_confirmation": "启用所选选举供所有票站使用？同一时间只可进行一场选举。",
        "active": "进行中",
        "finalized": "已完成",
        "polling_events": "开站及关站记录",
        "polling_schedule_summary": "时间表与最新记录",
        "schedule_is_not_actual": "预定时间不代表票站已开放、已停止接纳新到达者或已服务完毕。",
        "opening": "实际开站",
        "admission_closure": "停止接纳新到达者",
        "queue_clear_estimate": "预计队伍清理时间",
        "service_completion": "完成服务排队选民",
        "not_recorded": "尚未记录",
        "submitted": "已提交，待主管确认",
        "approved": "已确认",
        "missing": "尚未记录",
        "on_time": "准时",
        "delayed": "延迟",
        "select_polling_event": "选择开站或关站事项",
        "actual_opening_at": "实际开站时间",
        "admission_closed_at": "停止接纳新到达者的时间",
        "queue_observed_at": "作出队伍估算的时间",
        "actual_service_completed_at": "实际完成服务排队选民的时间",
        "estimated_queue_clear_at": "预计完成服务排队选民的时间",
        "opening_status": "开站情况",
        "opening_delay_reason": "延迟开站原因（延迟时必填）",
        "event_reason": "事项说明（如适用）",
        "amendment_reason": "修订原因",
        "polling_time_hint": (
            "请输入香港时间 YYYY-MM-DD HH:mm。未发生的实际事项可留空保存草稿；提交前须填妥。"
        ),
        "queue_estimate_is_forecast": (
            "这是预测，并不代表队伍已清理或投票工作已完成。请另行记录实际完成服务时间。"
        ),
        "polling_read_only": "只有投票站职员可填写事项；主管使用自己的账户确认已提交的修订版本。",
        "save_polling_draft": "保存事项草稿",
        "submit_polling": "提交此修订版本",
        "amend_polling": "建立修订草稿",
        "approve_polling": "主管确认",
        "approval_password": "您当前的主管账户密码",
        "polling_approval_hint": (
            "请核对此事项及修订版本，使用当前登录的主管账户密码确认。密码不会保存在记录内。"
        ),
        "polling_amendment_hint": (
            "输入更正内容及修订原因，再建立新草稿。较早版本及其确认会保留；新草稿须重新提交及确认。"
        ),
        "polling_history": "事项修订及确认记录",
        "no_polling_history": "此事项尚无已保存的记录。",
        "server_entry": "服务器记录时间",
        "entered_by": "记录职员编号",
        "submission": "提交资料",
        "submitted_by": "提交职员编号",
        "approval": "主管确认资料",
        "approved_by": "确认主管编号",
        "planned_time_basis": "所依据的预定时间",
        "polling_validation": (
            "请检查实际时间、预计时间及原因。实际事项不可在未来发生，事项先后"
            "须一致，延迟开站须说明原因。"
        ),
        "active_election_required": "只可记录进行中选举的票站事项。请先由管理员启用选举。",
        "polling_officer_required": "只有获指派的投票站职员可填写及提交此事项。",
        "supervisor_required": "只有获指派的主管可确认此事项。",
        "polling_state_conflict": (
            "事项状态已改变，无法完成此操作。您的输入已保留，请重新载入后核对。"
        ),
        "unsaved_polling_changes": "表格有未保存的内容。请先保存，或放弃更改后继续。",
        "polling_saved": "事项草稿已保存，尚未提交。",
        "polling_submitted": "此修订版本已提交，待主管确认。",
        "polling_approved": "主管已确认此修订版本。",
        "polling_amended": "已建立修订草稿。较早版本及确认已保留；请核对后重新提交。",
        "polling_newer_revision": (
            "已有较新的事项版本。您查看的版本及输入已保留；请重新载入后核对。"
        ),
        "turnout_validation": "请检查投票人数、累计数字、报告时段、香港时间及原因。",
        "turnout_period_not_found": "找不到此报告时段，请重新载入并核对选举时间表。",
        "turnout_record_not_found": "找不到所选的投票人数记录或版本，请重新载入。",
        "turnout_schedule_conflict": "报告所依据的时间表已更改，请重新载入并比较后再继续。",
        "turnout_state_conflict": "报告状态已更改，请重新载入已保存的版本并核对。",
        "turnout_review_required": "请先审阅当前已保存的投票人数及来源，再提交或确认。",
        "turnout_previous_period_required": "请先完成所需的较早报告时段，再继续此时段。",
        "unsaved_turnout_changes": "投票人数表格有未保存内容，请先保存或确认舍弃。",
        "turnout_saved": "投票人数草稿已保存，尚未提交。",
        "turnout_submitted": "此投票人数版本已提交，待主管确认。",
        "turnout_approved": "主管已确认此投票人数版本。",
        "turnout_amended": "已建立修订草稿；原有版本及确认已保留，请核对后重新提交。",
        "turnout_newer_revision": (
            "服务器资料或确认状态已有变更。您审阅的版本及未保存内容已保留，请重新载入并比较。"
        ),
        "external_manual": "人工提供的外部数字",
        "turnout_title": "正常模式投票人数",
        "turnout_intro": (
            "人工填写外部提供的时段及累计投票人数，无须 EPR 连接、P(12) 快照或已确认的开站记录。"
        ),
        "turnout_approved_coverage": "连续有效的主管确认范围",
        "turnout_coverage_hint": (
            "只计入从首时段开始连续且仍有效的主管确认。缺漏、草稿、待确认或须重新复核的时段，"
            "不会当作零人加入；没有有效确认的人数显示为“—”。"
        ),
        "turnout_approved_total": "有效确认范围的累计投票人数",
        "turnout_approved_periods": "连续有效确认的时段数",
        "turnout_covered_until": "有效确认至",
        "turnout_baseline_hint": (
            "首时段以零为起始累计基础；较后时段须以前一时段仍有效的主管确认为基础。"
            "即使开站确认尚待处理，也可记录已结束时段的明确零人报表。"
        ),
        "turnout_configured_schedule": "依选举时间表设定的报告时段",
        "turnout_total_periods": "已设定的时段总数",
        "turnout_period": "报告时段",
        "turnout_select_period": "选择报告时段",
        "turnout_visible_periods": "本页时段数／全部时段数",
        "turnout_previous_page": "上一页报告时段",
        "turnout_next_page": "下一页报告时段",
        "turnout_goto_period": "输入报告时段编号（从 1 开始）",
        "turnout_goto_action": "前往指定报告时段",
        "turnout_reviewed_period": "审阅的时段及版本",
        "turnout_historical": "历史版本，仅供查看；继续填写前请重新载入当前版本。",
        "turnout_live_state": "服务器当前状态（与审阅版本分开）",
        "turnout_approval_valid": "此时段仍属于连续有效的主管确认范围。",
        "turnout_review_invalid": (
            "原确认已保留，但其来源或前一时段基础已变更，现须重新复核。请建立有原因的修订草稿并重新提交。"
        ),
        "turnout_not_approved": "此时段当前未纳入有效确认范围。",
        "turnout_supplied_hourly": "外部提供的本时段投票人数",
        "turnout_supplied_cumulative": "外部提供的截至本时段末累计投票人数",
        "turnout_optional_counts_hint": (
            "可填本时段人数、累计人数，或同时填两者。只用非负整数；输入 0 表示明确零人，"
            "留空表示尚未提供。主管确认时会核对相邻累计及覆盖时段。"
        ),
        "turnout_event_time": "外部报表的原始事件时间",
        "turnout_time_hint": (
            "香港时间：YYYY-MM-DD HH:mm。草稿可暂存未完整资料；提交须为已结束时段，"
            "原始事件时间不得早于时段结束或晚于当前时间。"
        ),
        "turnout_source_context": "外部数字来源及覆盖范围",
        "turnout_read_only": "此职务可查看时段及历史；只有获指派的投票站职员可准备报表。",
        "turnout_save": "保存投票人数草稿",
        "turnout_submit": "提交此版本供主管确认",
        "turnout_amend": "建立有原因的修订草稿",
        "turnout_amendment_hint": (
            "已提交或已确认的数字须以修订草稿更正，并填写原因。较早版本及确认会保留；"
            "受影响的较后时段须重新复核。"
        ),
        "turnout_approve": "主管确认此投票人数版本",
        "turnout_approval_hint": (
            "请核对当前审阅的时段、版本及来源，再输入您当前登录主管账户的现有密码。"
            "确认只适用于此版本，并须具备有效的前一时段基础。"
        ),
        "turnout_history": "时段修订及确认历史",
        "turnout_no_history": "此时段尚无已保存的版本。",
        "turnout_view_revision": "查看此版本",
        "turnout_derived_hourly": "此版本确认时计算的本时段人数",
        "turnout_derived_start": "此版本确认时采用的起始累计",
        "turnout_derived_end": "此版本确认时计算的结束累计",
        "turnout_basis_revision": "所依据的前一时段确认版本",
        "turnout_basis_record": "记录编号",
        "turnout_first_baseline": "首时段起始累计基础：0",
        "turnout_report": "P(15) 时段及累计投票人数报表",
        "turnout_report_hint": (
            "请选择审阅版本或本站当前报表；两者均使用已保存数据，不包含未保存内容。"
        ),
        "turnout_report_scope": "选择报表基准",
        "turnout_report_selected": "当前审阅的时段版本",
        "turnout_report_station": "本站当前 P(15) 总览",
        "turnout_report_selected_hint": "保留您审阅的确切版本，包括历史数字、来源及原确认数据。",
        "turnout_report_station_hint": "使用服务器当前已保存的全部时段及连续有效确认范围。",
        "turnout_report_missing": "此时段尚无已保存版本；可改选本站当前总览。",
        "turnout_report_ready": "P(15) 投票人数报表预览已准备好。",
        "turnout_exported": "P(15) 投票人数报表已保存至所选文件。",
        "turnout_export_failed": "未能保存 P(15) 投票人数报表，请检查位置及连接后重试。",
        "boxes": "票箱交收与点票事项",
        "box_list": "已保存的票箱记录",
        "box_new": "新增票箱",
        "box_select": "选择票箱记录",
        "box_none": "尚无已保存的票箱记录；这不代表现场没有票箱。",
        "box_read_only": "此处仅供查看；交收及点票事项须由具相应票站权限的职员记录。",
        "box_newer_revision": (
            "服务器已有较新记录。您审阅的版本及未保存内容已保留，请重新载入并比较。"
        ),
        "box_details": "票箱资料",
        "box_ref": "票箱识别资料",
        "box_seal": "封条识别资料",
        "box_origin": "来源投票站",
        "box_destination": "接收点票站",
        "box_status": "交收状态",
        "box_prepared": "已记录准备完成",
        "box_departed_status": "已记录离站",
        "box_received_status": "已记录接收",
        "box_prepared_time": "实际准备完成时间（香港时间）",
        "box_departure_time": "实际离站时间（香港时间）",
        "box_receipt_time": "实际接收时间（香港时间）",
        "box_time_hint": "请输入实际发生的香港时间，格式为 YYYY-MM-DD HH:mm；不可填写未来时间。",
        "box_create": "保存票箱准备记录",
        "box_handover": "记录交收",
        "box_event_time": "实际事项时间（香港时间）",
        "box_reason": "说明／修正原因",
        "box_depart": "记录离站",
        "box_receive": "记录接收",
        "box_correct_departure": "修正离站记录",
        "box_correct_receipt": "修正接收记录",
        "box_history": "票箱交收历史",
        "box_no_history": "此票箱尚无已保存的交收历史。",
        "box_entered_at": "服务器记录时间",
        "box_actor": "记录职员编号",
        "box_event_prepared": "票箱准备完成",
        "box_event_departure": "票箱离站",
        "box_event_receipt": "接收票箱",
        "box_event_departure_correction": "离站记录修正",
        "box_event_receipt_correction": "接收记录修正",
        "box_milestones": "点票工作事项",
        "box_milestone_kind": "事项类别",
        "box_conversion_complete": "投票站转为点票站完成",
        "box_first_box_opening": "首次开启票箱",
        "box_questionable_determination_start": "开始审定问题选票",
        "box_milestone_box": "首次开启的票箱",
        "box_milestone_time": "实际事项时间（香港时间）",
        "box_milestone_reason": "事项说明／修订原因",
        "box_save_milestone": "保存点票事项",
        "box_milestone_history": "点票事项修订历史",
        "box_no_milestones": "尚无已保存的点票事项。",
        "box_count_completion": "点票完成时间",
        "box_count_unrecorded": "尚未记录；完成时间会由后续的点票完成流程产生。",
        "box_milestones_not_applicable": "此投票站将票箱送往指定点票站，本地点票事项不适用。",
        "box_report": "票箱交收与点票事项报表",
        "box_report_hint": (
            "报表使用生成当刻服务器已保存的整个票站记录，不包含未保存内容；"
            "生成报表不会更改您当前审阅的记录。"
        ),
        "box_milestone_correction_hint": "修订已保存的点票事项须填写原因；原有版本会保留。",
        "box_validation": (
            "请检查票箱、封条、实际时间及相关事项。时间不能在未来，并须符合已记录的交收次序。"
        ),
        "box_departure_required": "尚未记录票箱离站，不能确认接收送抵的票箱。",
        "box_receipt_required": "请先记录接收此票箱，再记录开箱时间。",
        "box_reference_exists": "来源票站已有相同识别资料的票箱，请核对现有记录。",
        "box_state_conflict": "所选的交收事项已记录或状态已更改，请重新载入并比较。",
        "box_not_found": "在获准的票站范围内找不到此票箱，请重新载入。",
        "box_correction_reason_required": "修正已记录的事项时，必须填写原因。",
        "counting_station_required": "此事项只适用于进行本地点票的站点。",
        "counting_officer_required": "此事项须由获指派的点票人员记录。",
        "unsaved_box_changes": "票箱或点票事项表格有未保存内容，请先保存或确认舍弃。",
        "box_saved": "票箱准备记录已保存。",
        "box_departed": "票箱离站记录已保存。",
        "box_received": "票箱接收记录已保存。",
        "box_corrected": "交收修正已保存，原有记录已保留。",
        "box_milestone_saved": "点票工作事项已保存。",
        "box_report_ready": "服务器当前的交收及事项报表已载入。",
        "box_exported": "票箱交收报表已保存至所选文件。",
        "box_export_failed": "未能完成导出，请检查文件位置及连接后重试。",
        "queue": "轮候时间",
        "queue_latest": "最新轮候观察",
        "queue_missing": "尚无轮候观察，不能视为没有队伍。",
        "queue_due": "已到更新时间，请观察并记录轮候情况，或确认情况不变。",
        "queue_fresh": "观察仍在 30 分钟更新时段内。",
        "queue_under_30": "少于 30 分钟",
        "queue_30_59": "30 至 59 分钟",
        "queue_60_90": "60 至 90 分钟",
        "queue_over_90": "超过 90 分钟",
        "queue_band": "轮候时间范围",
        "queue_observation": "轮候观察",
        "queue_unchanged_confirmation": "确认轮候情况不变",
        "queue_event_time": "观察／确认时间（香港时间）",
        "queue_entered_at": "服务器记录时间",
        "queue_actor": "记录职员编号",
        "queue_due_at": "下次更新时间",
        "queue_overdue_periods": "已到期的 30 分钟时段数",
        "queue_form": "记录轮候情况",
        "queue_form_hint": (
            "请输入实际观察时间，格式为 YYYY-MM-DD HH:mm。确认情况不变也会新增一项有时间的记录。"
        ),
        "queue_reason": "观察说明（选填）",
        "queue_save": "保存新观察",
        "queue_confirm": "确认范围不变",
        "queue_confirm_hint": "确认不变时，请保留已审阅的范围、清空观察说明，并输入新的确认时间。",
        "queue_reviewed": "当前审阅的记录版本",
        "queue_read_only": "只有获指派的投票站职员可在进行中的选举记录轮候情况。",
        "queue_history": "轮候观察与确认历史",
        "queue_no_history": "尚无已保存的轮候观察或确认。",
        "queue_confirms": "所确认的记录编号",
        "queue_current_marker": "最新观察",
        "queue_newer_revision": (
            "服务器有较新的记录。已保留当前审阅的版本及输入内容；请重新载入并比较后再记录。"
        ),
        "queue_validation": "请检查轮候范围、香港时间及说明。实际观察／确认时间不能在未来。",
        "queue_confirmation_requires_current": (
            "确认不变前，请保留已审阅的轮候范围并清空观察说明；如情况有变，请保存新观察。"
        ),
        "queue_observation_conflict": "所确认的观察已更改或尚未存在。请重新载入记录并比较。",
        "queue_revision_not_found": "找不到所选的轮候历史版本，请重新载入。",
        "unsaved_queue_changes": "轮候表格有未保存的内容。请先保存，或舍弃并重新载入。",
        "queue_saved": "轮候观察已保存。",
        "queue_confirmed": "轮候情况不变的确认已保存。",
        "queue_report": "轮候情况历史报表",
        "queue_report_hint": "报表使用当前审阅版本的已保存历史，不包含未保存的表格内容。",
        "queue_report_ready": "轮候历史报表预览已载入。",
        "queue_exported": "轮候历史报表已保存至所选文件。",
        "queue_export_failed": "未能完成导出。请检查文件位置及连接后重试。",
        "received_stock": "选票接收与储备",
        "stock_receipt": "接收记录",
        "stock_receipts": "已保存的接收记录",
        "new_stock_receipt": "新增接收记录",
        "select_stock_receipt": "请选择接收记录",
        "no_stock_receipts": "此投票站尚未记录收到的选票。",
        "stock_read_only": "只有获指派的投票站职员可新增或修正接收记录。历史版本只供查看与导出。",
        "stock_recorded": "已记录",
        "stock_current": "当前版本",
        "stock_historical": "历史版本（只读）",
        "stock_return_current": "载入当前版本",
        "stock_series": "选票系列",
        "stock_event_at": "接收时间（香港时间）",
        "stock_time_hint": "请以香港时间 YYYY-MM-DD HH:mm 输入原本接收选票的时间。",
        "stock_pool_hint": (
            "普通选票、替换选票储备及重复选票储备分开记录。请填写各类起始数量；没有储备时请填写 0。"
        ),
        "stock_pool_ordinary": "普通选票",
        "stock_pool_replacement": "替换选票储备",
        "stock_pool_tendered": "重复选票储备",
        "stock_calculated_total": "按编号范围计算的接收总数",
        "stock_total_received": "已记录接收总数",
        "stock_add_range": "新增编号范围",
        "stock_remove_range": "移除此范围",
        "stock_serial_hint": (
            "请输入 1 至 18 位半角数字，并保留编号前的 0。"
            "起始编号不可大于结束编号，各类范围不可重叠。"
        ),
        "no_stock_ranges": "尚未新增编号范围。请新增普通选票或储备范围。",
        "stock_range": "编号范围",
        "stock_pool": "选票类别",
        "stock_serial_from": "起始编号",
        "stock_serial_to": "结束编号",
        "stock_range_quantity": "计算所得数量",
        "stock_correction_hint": "保存修正会建立新版本并保留原记录。请填写修正原因。",
        "stock_reason": "修正原因",
        "stock_save_correction": "保存修正版本",
        "stock_save": "保存接收记录",
        "stock_history": "接收记录修订历史",
        "no_stock_history": "尚无可查看的接收记录版本。",
        "stock_report": "选票接收及储备报表",
        "stock_report_hint": (
            "预览及导出以所选记录及修订版本为准。请先保存更改，或重新载入已保存版本。"
        ),
        "stock_report_language": "导出报表语言",
        "stock_preview": "预览报表",
        "stock_export_pdf": "导出 PDF",
        "stock_export_csv": "导出 UTF-8 CSV",
        "stock_preview_language": "当前预览的语言",
        "stock_export_location": "已保存的报表文件",
        "stock_validation": (
            "请检查选票系列、香港时间及有效编号范围。"
            "三类起始数量须为非负整数，并与各类编号范围合计相符。"
            "最少须接收 1 张选票。"
        ),
        "stock_overlap": "此选区及选票系列的编号已由其他接收记录或类别使用，请核对范围。",
        "stock_receipt_not_found": "找不到所选接收记录或修订版本，请刷新后再选择。",
        "election_read_only": "已完成选举的记录只供查看与导出，不能直接更改。",
        "stock_saved": "选票接收记录已保存。",
        "stock_report_ready": "所选版本的报表预览已载入。",
        "stock_exported": "报表已保存至所选文件。",
        "stock_export_failed": "导出未完成。请检查所选文件位置及连接，然后重试。",
        "stock_newer_revision": (
            "服务器有较新的版本。您正在查看的版本及未保存内容已保留；请重新载入并核对。"
        ),
        "unsaved_stock_changes": (
            "此表格有未保存内容。请先保存更改，或舍弃更改并重新载入已保存版本，再继续。"
        ),
        "report_glyph_unavailable": (
            "PDF 字体不支持报表中的部分文字。请保留原文，改用 CSV 或请管理员更新报表字体。"
        ),
        "unsaved_station_changes": "表格有未保存的内容。请先保存，或放弃更改后继续。",
    },
    "en": {
        "app_name": "Election Management and Voting System",
        "election_management": "Election management",
        "tagline": "A clear record of station work.",
        "sign_in": "Sign in",
        "signing_in": "Signing in…",
        "staff_access": "Staff sign-in",
        "welcome": "Welcome",
        "server_address": "Server address",
        "username": "Username",
        "password": "Password",
        "change_password": "Change password",
        "current_password": "Current password",
        "new_password": "New password",
        "confirm_password": "Confirm new password",
        "password_hint": "Use 12–128 characters, different from your current password.",
        "first_login": "First sign-in: change your temporary password to continue.",
        "save_password": "Save new password",
        "saving_password": "Saving…",
        "account": "Account",
        "workspace": "Workspace",
        "polling": "Polling operations",
        "counting": "Counting",
        "records": "Records and reports",
        "settings": "Settings",
        "no_election": "No election configured",
        "no_election_detail": "An Administrator must configure election and station details first.",
        "authenticated": "Authenticated",
        "signed_in_as": "Signed in as",
        "role": "Role",
        "administrator": "Administrator",
        "polling_officer": "Polling Officer",
        "counting_officer": "Counting Officer",
        "supervisor": "Supervisor",
        "session_expires": "Session expires",
        "no_idle_lock": "No inactivity logout. Each session lasts up to 24 hours.",
        "logout": "Sign out",
        "refresh": "Refresh",
        "server": "Server",
        "connecting": "Connecting",
        "connected": "Connected",
        "disconnected": "Unable to connect",
        "certificate_error": "Cannot verify server certificate. Check the address and trusted CA.",
        "invalid_server": "Enter a valid HTTPS server address.",
        "invalid_credentials": "The username or password is incorrect.",
        "session_expired": "Your session has expired or is no longer valid. Sign in again.",
        "database_unavailable": "The server cannot reach the database. Try again later.",
        "request_failed": "The request could not be completed. Check the connection and try again.",
        "validation_error": "Check your entries and try again.",
        "password_mismatch": "The new passwords do not match.",
        "password_changed": "Password changed elsewhere; sign in again.",
        "password_unchanged": "Choose a password different from your current one.",
        "password_change_required": "Change your temporary password before continuing.",
        "password_change_success": "Your new password has been saved.",
        "retry": "Retry",
        "last_refresh": "Last updated",
        "hong_kong_time": "Hong Kong time",
        "language": "Language",
        "connection_detail": "This desktop client connects to the configured central server.",
        "not_configured": "Not configured",
        "signed_out": "Signed out",
        "pending": "Pending",
        "ready": "Ready",
        "user_profile": "Account details",
        "session": "Session",
        "health_check": "Connection check",
        "saved": "Saved",
        "min_password": "The password must contain 12–128 characters.",
        "role_scope": "Available features and records follow your role and station assignments.",
        "linked_server": "Configured server",
        "election_setup": "Election setup",
        "saved_elections": "Saved elections",
        "new_election": "New election",
        "election_name": "Election name",
        "save_election": "Save election",
        "constituencies": "Constituencies",
        "new_constituency": "New constituency",
        "constituency_name": "Constituency name",
        "constituency_code": "Constituency code",
        "save_constituency": "Save constituency",
        "candidates": "Candidates",
        "new_candidate": "New candidate",
        "candidate_name": "Candidate name",
        "ballot_number": "Candidate number",
        "save_candidate": "Save candidate",
        "one_seat_rule": "Each constituency elects 1 candidate; each valid ballot allows 1 choice.",
        "select_election": "Select an election",
        "select_constituency": "Select a constituency",
        "no_constituencies": "No constituencies have been added to this election.",
        "no_candidates": "No candidates have been added to this constituency.",
        "draft": "Draft",
        "revision": "Revision",
        "unsaved_changes": "This form has unsaved entries. Changing your selection discards them.",
        "discard_changes": "Discard changes",
        "keep_editing": "Keep editing",
        "reload_saved": "Reload saved data",
        "configuration_saved": "Configuration saved.",
        "configuration_validation": (
            "Names need 1–160 characters, constituency codes 1–32 characters, "
            "and candidate numbers a positive integer. Entries cannot contain only spaces."
        ),
        "revision_conflict": (
            "Another staff member saved a newer revision. Your unsaved entries are kept. "
            "Reload saved data to compare."
        ),
        "duplicate_configuration": (
            "That code or candidate number is already used in this election, "
            "constituency or station. Choose a different value."
        ),
        "request_conflict": (
            "This save request was already used for different entries. Your entries are kept. "
            "Reload saved data to compare."
        ),
        "configuration_not_found": "Selected record not found. Refresh and select it again.",
        "draft_required": "Only draft elections can be edited here.",
        "administrator_required": "Only an Administrator can configure election records.",
        "saving": "Saving…",
        "loading": "Loading…",
        "editing_new": "New record",
        "no_saved_elections": "No elections saved yet. Create a draft election to begin.",
        "station_setup": "Station setup",
        "station_setup_hint": (
            "First define the election and constituencies in Election setup, "
            "then configure polling stations and issuance counters here."
        ),
        "stations": "Polling stations",
        "new_station": "New polling station",
        "station_name": "Polling station name",
        "station_code": "Polling station code",
        "save_station": "Save polling station",
        "no_stations": "No polling stations have been added to this constituency.",
        "select_station": "Select a polling station",
        "counters": "Issuance counters",
        "new_counter": "New issuance counter",
        "counter_name": "Issuance counter name",
        "counter_code": "Issuance counter code",
        "save_counter": "Save issuance counter",
        "no_counters": "No issuance counters have been added to this polling station.",
        "counting_mode": "Counting arrangement",
        "local_counting": "Count locally",
        "send_to_destination": "Send to a counting station",
        "counting_destination": "Receiving counting station",
        "select_destination": "Select a receiving station",
        "counting_arrangement_note": (
            "The receiving station must count locally within the same constituency."
        ),
        "receiving_from": "Polling stations assigned to send here",
        "invalid_counting_destination": (
            "Select another polling station that counts locally "
            "within the same election and constituency."
        ),
        "receiver_in_use": (
            "Other polling stations are assigned to send here. Reassign their destinations "
            "before changing this station to sending."
        ),
        "station_configuration_validation": (
            "Names need 1–160 characters and codes 1–32 characters; neither can be blank. "
            "Sending requires a receiving station."
        ),
        "schedule_not_configured": "No election schedule configured.",
        "schedule_required": "Save a complete election schedule before activating the election.",
        "active_election_conflict": "Finish the current active election before activating another.",
        "election_configuration_incomplete": (
            "Complete constituency, candidate, polling station and issuance counter setup "
            "before activation."
        ),
        "schedule_validation": (
            "Enter valid dates and times in HKT as YYYY-MM-DD HH:mm. The end must be later "
            "than the start, with a reporting interval of 1–1440 minutes."
        ),
        "schedule_saved": "Election schedule saved.",
        "election_activated": "Election activated.",
        "unsaved_schedule": "This schedule has unsaved changes. Save it before activation.",
        "staff_accounts": "Staff accounts",
        "unsaved_staff_changes": "Save or reload account changes before resetting the password.",
        "no_audit_events": "No account changes recorded yet.",
        "election_status": "Election status",
        "read_only_election": "This election is active or finalized and can only be viewed here.",
        "newer_saved_version": (
            "A newer saved revision is available. Your entries are kept; reload to review."
        ),
        "wrong_active_election": (
            "This station is outside the active election. Refresh and select an available station."
        ),
        "new_account": "New account",
        "select_account": "Select an account",
        "no_accounts": "No staff accounts have been added.",
        "display_name": "Display name",
        "account_enabled": "Account enabled",
        "station_assignments": "Station assignments",
        "no_station_options": (
            "No polling stations available to assign. Complete Station setup first."
        ),
        "no_assigned_stations": (
            "No assigned polling stations are available. Contact an Administrator."
        ),
        "save_account": "Save account",
        "temporary_password": "Temporary password",
        "confirm_temporary_password": "Confirm temporary password",
        "reset_password": "Reset password",
        "reset_password_hint": (
            "Resetting revokes all sessions. Staff must sign in with the new temporary password "
            "and change it before continuing."
        ),
        "staff_changes_hint": "Saving changes requires this staff member to sign in again.",
        "staff_saved": "Staff account saved.",
        "password_reset_success": (
            "Temporary password reset. Staff must sign in again and change it."
        ),
        "access_changed": "Your access or station assignments changed. Sign in again.",
        "staff_validation": (
            "Usernames need 1–64 characters and display names 1–120 characters; "
            "neither can be blank. "
            "Temporary passwords need 12–128 characters."
        ),
        "username_exists": "That username is already in use. Choose another.",
        "account_not_found": "Selected account not found. Refresh the list.",
        "invalid_station_assignment": (
            "Assign existing polling stations without duplicates. "
            "Administrator accounts cannot have station assignments."
        ),
        "last_administrator_required": "At least one enabled Administrator account must remain.",
        "operational_role_required": (
            "This function requires a Polling Officer, Counting Officer or Supervisor role."
        ),
        "station_access_denied": "You are not assigned to this polling station's workspace.",
        "audit_history": "Account change history",
        "staff_created": "Staff account created",
        "staff_updated": "Staff account updated",
        "staff_password_reset": "Staff password reset",
        "station_context": "Station workspace",
        "active_election": "Active election",
        "activation_guidance": (
            "An Administrator can review and activate an election in Election schedule."
        ),
        "no_active_election": "No active election.",
        "selected_election": "Selected election",
        "election_schedule": "Election schedule",
        "election_date": "Election date",
        "planned_opening": "Scheduled opening",
        "planned_closing": "Scheduled closing",
        "reporting_interval": "Reporting interval (minutes)",
        "schedule_time_hint": (
            "HKT, YYYY-MM-DD HH:mm. The end must be later than the start. "
            "Reporting interval: 1–1440 minutes. For next-day closing, enter the closing date."
        ),
        "save_schedule": "Save schedule",
        "activate_election": "Activate election",
        "activation_confirmation": (
            "Activate the selected election for all polling stations? "
            "Only one election can be active at a time."
        ),
        "active": "Active",
        "finalized": "Finalized",
        "polling_events": "Opening and closing records",
        "polling_schedule_summary": "Schedule and latest records",
        "schedule_is_not_actual": (
            "Planned times do not confirm opening, closure to new arrivals, or "
            "completion of service."
        ),
        "opening": "Actual opening",
        "admission_closure": "Closure to new arrivals",
        "queue_clear_estimate": "Queue-clear estimate",
        "service_completion": "Completion of service to queued electors",
        "not_recorded": "Not recorded",
        "submitted": "Submitted for review",
        "approved": "Approved",
        "missing": "Not recorded",
        "on_time": "On time",
        "delayed": "Delayed",
        "select_polling_event": "Select an opening or closing event",
        "actual_opening_at": "Actual opening time",
        "admission_closed_at": "Time admission to new arrivals closed",
        "queue_observed_at": "Time the queue estimate was made",
        "actual_service_completed_at": "Actual completion of service to queued electors",
        "estimated_queue_clear_at": "Estimated completion of service to queued electors",
        "opening_status": "Opening status",
        "opening_delay_reason": "Opening delay reason (required when delayed)",
        "event_reason": "Event explanation (if applicable)",
        "amendment_reason": "Reason for amendment",
        "polling_time_hint": (
            "Enter Hong Kong time as YYYY-MM-DD HH:mm. An event that has not "
            "occurred may remain blank in a saved draft; complete it before "
            "submission."
        ),
        "queue_estimate_is_forecast": (
            "This is a forecast. Record actual completion of service separately; "
            "an estimate does not confirm a cleared queue or a completed poll."
        ),
        "polling_read_only": (
            "Polling Officers prepare records. Supervisors use their own account "
            "to approve a submitted revision."
        ),
        "save_polling_draft": "Save event draft",
        "submit_polling": "Submit this revision",
        "amend_polling": "Create amendment draft",
        "approve_polling": "Supervisor approval",
        "approval_password": "Your current Supervisor account password",
        "polling_approval_hint": (
            "Review this event and revision, then confirm with the password of "
            "your signed-in Supervisor account. The password is not stored in the "
            "record."
        ),
        "polling_amendment_hint": (
            "Enter the corrected details and amendment reason, then create a new "
            "draft. Earlier revisions and approvals remain in history; submit the "
            "new draft for fresh approval."
        ),
        "polling_history": "Event revision and approval history",
        "no_polling_history": "No saved records for this event.",
        "server_entry": "Server entry time",
        "entered_by": "Entered by account ID",
        "submission": "Submission",
        "submitted_by": "Submitted by account ID",
        "approval": "Approval",
        "approved_by": "Approved by account ID",
        "planned_time_basis": "Planned time used for this revision",
        "polling_validation": (
            "Check event times, the forecast and reasons. Actual events cannot be "
            "in the future, recorded events must be in order, and a delayed "
            "opening requires a reason."
        ),
        "active_election_required": (
            "Records can be changed only for an active election. An Administrator "
            "must activate the election first."
        ),
        "polling_officer_required": (
            "Only an assigned Polling Officer can prepare and submit this event."
        ),
        "supervisor_required": "Only an assigned Supervisor can approve this event.",
        "polling_state_conflict": (
            "The event status has changed. Your input is retained; reload the "
            "saved record and review it before continuing."
        ),
        "unsaved_polling_changes": (
            "The form has unsaved changes. Save it, or discard the changes before continuing."
        ),
        "polling_saved": "Event draft saved; it has not been submitted.",
        "polling_submitted": "This revision was submitted for Supervisor approval.",
        "polling_approved": "The Supervisor approved this revision.",
        "polling_amended": (
            "Amendment draft created. Earlier revisions and approvals are "
            "retained; review and submit the new draft."
        ),
        "polling_newer_revision": (
            "A newer event revision is available. Your reviewed version and input "
            "are retained; reload and compare before continuing."
        ),
        "turnout_validation": (
            "Check the turnout quantities, cumulative figures, report period, HKT time and reason."
        ),
        "turnout_period_not_found": (
            "This report period was not found. Reload and check the schedule."
        ),
        "turnout_record_not_found": (
            "The selected turnout record or revision was not found. Reload."
        ),
        "turnout_schedule_conflict": (
            "The report's schedule has changed. Reload and compare before continuing."
        ),
        "turnout_state_conflict": (
            "The report status has changed. Reload and review the saved revision."
        ),
        "turnout_review_required": (
            "Review the current saved turnout figures and their source before "
            "submitting or approving."
        ),
        "turnout_previous_period_required": "Complete the required earlier report periods first.",
        "unsaved_turnout_changes": (
            "The turnout form has unsaved input. Save it or explicitly discard it."
        ),
        "turnout_saved": "Turnout draft saved; it has not been submitted.",
        "turnout_submitted": "This turnout revision was submitted for Supervisor approval.",
        "turnout_approved": "The Supervisor approved this turnout revision.",
        "turnout_amended": (
            "Amendment draft created. Earlier revisions and approvals are retained; "
            "review and submit the new draft."
        ),
        "turnout_newer_revision": (
            "Server data or approval status has changed. Your reviewed version and unsaved input "
            "are retained. Reload and compare before continuing."
        ),
        "external_manual": "Manually supplied external figures",
        "turnout_title": "Normal-mode turnout",
        "turnout_intro": (
            "Enter externally supplied period and cumulative turnout. An EPR connection, "
            "P(12) snapshot or approved opening record is not required."
        ),
        "turnout_approved_coverage": "Continuous valid approved coverage",
        "turnout_coverage_hint": (
            "Only consecutive periods with still-valid Supervisor approvals are included, "
            "starting from the first period. Missing, draft, pending or invalidated periods "
            "are not added as zero. Turnout without valid approved coverage is shown as —."
        ),
        "turnout_approved_total": "Cumulative turnout within valid approved coverage",
        "turnout_approved_periods": "Consecutive valid approved periods",
        "turnout_covered_until": "Approved coverage ends at",
        "turnout_baseline_hint": (
            "The first period starts from a zero cumulative baseline. Each later approval "
            "uses the preceding period's still-valid approval. Explicit zero reports for "
            "completed periods remain possible while opening approval is pending."
        ),
        "turnout_configured_schedule": "Reporting periods from the election schedule",
        "turnout_total_periods": "Configured period count",
        "turnout_period": "Reporting period",
        "turnout_select_period": "Select a reporting period",
        "turnout_visible_periods": "Periods on this page / all periods",
        "turnout_previous_page": "Previous page of periods",
        "turnout_next_page": "Next page of periods",
        "turnout_goto_period": "Reporting period number, starting at 1",
        "turnout_goto_action": "Go to the specified period",
        "turnout_reviewed_period": "Reviewed period and revision",
        "turnout_historical": (
            "Historical revision, read-only. Reload the current revision to continue entry."
        ),
        "turnout_live_state": "Current server status, separate from the reviewed revision",
        "turnout_approval_valid": "This period remains within continuous valid approved coverage.",
        "turnout_review_invalid": (
            "The earlier approval is retained, but its source or preceding-period basis has "
            "changed. Create a reasoned amendment and submit it for renewed review."
        ),
        "turnout_not_approved": "This period is not currently within valid approved coverage.",
        "turnout_supplied_hourly": "Externally supplied turnout for this period",
        "turnout_supplied_cumulative": "Externally supplied cumulative turnout at period end",
        "turnout_optional_counts_hint": (
            "Enter period turnout, cumulative turnout, or both. Use nonnegative integers. "
            "Enter 0 for an explicit zero; leave blank when no figure was supplied. "
            "Supervisor approval checks adjacent cumulative figures and interval coverage."
        ),
        "turnout_event_time": "Original event time of the external report",
        "turnout_time_hint": (
            "HKT: YYYY-MM-DD HH:mm. Drafts may be incomplete. Submission requires a completed "
            "period and an original event time no earlier than period end and no later than now."
        ),
        "turnout_source_context": "External source and coverage context",
        "turnout_read_only": (
            "This role can view periods and history. "
            "Only an assigned Polling Officer prepares reports."
        ),
        "turnout_save": "Save turnout draft",
        "turnout_submit": "Submit this revision for Supervisor approval",
        "turnout_amend": "Create a reasoned amendment draft",
        "turnout_amendment_hint": (
            "Correct submitted or approved figures through an amendment draft with a reason. "
            "Earlier revisions and approvals are retained; "
            "affected later periods need renewed review."
        ),
        "turnout_approve": "Approve this turnout revision",
        "turnout_approval_hint": (
            "Check the reviewed period, revision and source, then re-enter the existing password "
            "of your signed-in Supervisor account. Approval applies to this exact revision and "
            "requires a valid preceding-period basis."
        ),
        "turnout_history": "Period revision and approval history",
        "turnout_no_history": "No revision has been saved for this period.",
        "turnout_view_revision": "View this revision",
        "turnout_derived_hourly": "Period turnout derived at this revision's approval",
        "turnout_derived_start": "Starting cumulative basis used at approval",
        "turnout_derived_end": "Ending cumulative turnout derived at approval",
        "turnout_basis_revision": "Preceding approved revision used as the basis",
        "turnout_basis_record": "Record ID",
        "turnout_first_baseline": "First-period starting cumulative baseline: 0",
        "turnout_report": "P(15) period and cumulative turnout report",
        "turnout_report_hint": (
            "Choose the reviewed revision or the current station report. Both use saved "
            "records and exclude unsaved input."
        ),
        "turnout_report_scope": "Choose the report basis",
        "turnout_report_selected": "Currently reviewed period revision",
        "turnout_report_station": "Current station P(15) overview",
        "turnout_report_selected_hint": (
            "Keep the exact revision you reviewed, including its historical figures, "
            "source and original approval details."
        ),
        "turnout_report_station_hint": (
            "Use all currently saved server periods and the continuous valid approval coverage."
        ),
        "turnout_report_missing": (
            "This period has no saved revision. Choose the current station overview instead."
        ),
        "turnout_report_ready": "The P(15) turnout report preview is ready.",
        "turnout_exported": "The P(15) turnout report was saved to the selected file.",
        "turnout_export_failed": (
            "Could not save the P(15) turnout report. "
            "Check the location and connection, then retry."
        ),
        "boxes": "Box handover and milestones",
        "box_list": "Saved box records",
        "box_new": "New box",
        "box_select": "Select a box record",
        "box_none": "No box records have been saved. This does not mean no boxes are present.",
        "box_read_only": (
            "Read-only view. Staff with the corresponding station permission record "
            "handovers and counting milestones."
        ),
        "box_newer_revision": (
            "Newer server records are available. Your reviewed records and unsaved input "
            "are retained. Reload and compare before continuing."
        ),
        "box_details": "Box details",
        "box_ref": "Box reference",
        "box_seal": "Seal reference",
        "box_origin": "Origin polling station",
        "box_destination": "Receiving counting station",
        "box_status": "Handover status",
        "box_prepared": "Preparation recorded",
        "box_departed_status": "Departure recorded",
        "box_received_status": "Receipt recorded",
        "box_prepared_time": "Actual preparation time (Hong Kong time)",
        "box_departure_time": "Actual departure time (Hong Kong time)",
        "box_receipt_time": "Actual receipt time (Hong Kong time)",
        "box_time_hint": (
            "Enter the actual Hong Kong time as YYYY-MM-DD HH:mm. Future times are not allowed."
        ),
        "box_create": "Save box preparation",
        "box_handover": "Record handover",
        "box_event_time": "Actual event time (Hong Kong time)",
        "box_reason": "Details / correction reason",
        "box_depart": "Record departure",
        "box_receive": "Record receipt",
        "box_correct_departure": "Correct departure",
        "box_correct_receipt": "Correct receipt",
        "box_history": "Box handover history",
        "box_no_history": "No handover history has been saved for this box.",
        "box_entered_at": "Server entry time",
        "box_actor": "Recorded by account ID",
        "box_event_prepared": "Box prepared",
        "box_event_departure": "Box departed",
        "box_event_receipt": "Box received",
        "box_event_departure_correction": "Departure correction",
        "box_event_receipt_correction": "Receipt correction",
        "box_milestones": "Counting milestones",
        "box_milestone_kind": "Milestone type",
        "box_conversion_complete": "Conversion to counting station complete",
        "box_first_box_opening": "First box opening",
        "box_questionable_determination_start": "Questionable-ballot determination started",
        "box_milestone_box": "First box opened",
        "box_milestone_time": "Actual milestone time (Hong Kong time)",
        "box_milestone_reason": "Milestone details / amendment reason",
        "box_save_milestone": "Save counting milestone",
        "box_milestone_history": "Counting milestone revision history",
        "box_no_milestones": "No counting milestones have been saved.",
        "box_count_completion": "Count completion time",
        "box_count_unrecorded": (
            "Not recorded; the later count-completion workflow will produce this time."
        ),
        "box_milestones_not_applicable": (
            "This polling station sends boxes to its designated counting station. "
            "Local counting milestones do not apply."
        ),
        "box_report": "Box handover and counting timeline report",
        "box_report_hint": (
            "The report uses the whole station's saved server records at generation time. "
            "Unsaved input is excluded. Generating it does not change your reviewed records."
        ),
        "box_milestone_correction_hint": (
            "Amending a saved milestone requires a reason. Earlier revisions are retained."
        ),
        "box_validation": (
            "Check the box, seal, actual time and event. Times cannot be in the future "
            "or conflict with the recorded handover sequence."
        ),
        "box_departure_required": "Record departure before acknowledging a transferred box.",
        "box_receipt_required": "Record receipt of this box before its opening time.",
        "box_reference_exists": (
            "This origin station already has that box reference. Check its records."
        ),
        "box_state_conflict": (
            "This event is already recorded or its state changed. Reload and compare."
        ),
        "box_not_found": (
            "This box was not found in the authorized station context. Reload the records."
        ),
        "box_correction_reason_required": "Enter a reason when correcting a recorded event.",
        "counting_station_required": "This event applies to stations that count locally.",
        "counting_officer_required": "An assigned Counting Officer must record this event.",
        "unsaved_box_changes": (
            "The box or milestone form has unsaved input. Save or explicitly discard it."
        ),
        "box_saved": "Box preparation saved.",
        "box_departed": "Box departure saved.",
        "box_received": "Box receipt saved.",
        "box_corrected": "Handover correction saved; the original event is retained.",
        "box_milestone_saved": "Counting milestone saved.",
        "box_report_ready": "The server's current handover and timeline report is ready.",
        "box_exported": "Box handover report saved to the selected file.",
        "box_export_failed": (
            "Export did not complete. Check the file location and connection, then retry."
        ),
        "queue": "Queue waiting times",
        "queue_latest": "Latest queue observation",
        "queue_missing": (
            "No queue observation has been recorded. This does not mean there is no queue."
        ),
        "queue_due": (
            "An update is due. Observe the queue and record its band, or confirm it is unchanged."
        ),
        "queue_fresh": "The observation is within its 30-minute update interval.",
        "queue_under_30": "Under 30 minutes",
        "queue_30_59": "30–59 minutes",
        "queue_60_90": "60–90 minutes",
        "queue_over_90": "Over 90 minutes",
        "queue_band": "Waiting-time band",
        "queue_observation": "Queue observation",
        "queue_unchanged_confirmation": "Unchanged-band confirmation",
        "queue_event_time": "Observed / confirmed at (Hong Kong time)",
        "queue_entered_at": "Server entry time",
        "queue_actor": "Recorded by account ID",
        "queue_due_at": "Next update due",
        "queue_overdue_periods": "30-minute intervals elapsed",
        "queue_form": "Record the queue",
        "queue_form_hint": (
            "Enter the actual observation time as YYYY-MM-DD HH:mm in HKT. "
            "Confirming an unchanged band also creates a new timed record."
        ),
        "queue_reason": "Observation note (optional)",
        "queue_save": "Save new observation",
        "queue_confirm": "Confirm band unchanged",
        "queue_confirm_hint": (
            "To confirm an unchanged band, retain the reviewed band, clear the observation "
            "note and enter a new confirmation time."
        ),
        "queue_reviewed": "Reviewed history revision",
        "queue_read_only": (
            "Assigned Polling Officers can record queue observations while the election is active."
        ),
        "queue_history": "Observation and confirmation history",
        "queue_no_history": "No queue observations or confirmations have been saved.",
        "queue_confirms": "Confirmed record ID",
        "queue_current_marker": "Latest observation",
        "queue_newer_revision": (
            "Newer server history is available. Your reviewed revision and input are retained. "
            "Reload and compare before recording."
        ),
        "queue_validation": (
            "Check the waiting-time band, HKT time and note. Actual observation or "
            "confirmation times cannot be in the future."
        ),
        "queue_confirmation_requires_current": (
            "Retain the reviewed band and clear the observation note to confirm it is "
            "unchanged. Save a new observation when it has changed."
        ),
        "queue_observation_conflict": (
            "The observation being confirmed changed or does not yet exist. "
            "Reload the history and compare."
        ),
        "queue_revision_not_found": (
            "The selected queue history revision was not found. Reload the history."
        ),
        "unsaved_queue_changes": (
            "The queue form has unsaved input. Save it, or discard it and reload."
        ),
        "queue_saved": "Queue observation saved.",
        "queue_confirmed": "Unchanged-band confirmation saved.",
        "queue_report": "Queue observation history",
        "queue_report_hint": (
            "Reports use saved history through the reviewed revision. "
            "Unsaved form input is excluded."
        ),
        "queue_report_ready": "The queue history preview is ready.",
        "queue_exported": "Queue history report saved to the selected file.",
        "queue_export_failed": (
            "Export did not complete. Check the file location and connection, then retry."
        ),
        "received_stock": "Received stock and reserves",
        "stock_receipt": "Receipt",
        "stock_receipts": "Saved stock receipts",
        "new_stock_receipt": "New stock receipt",
        "select_stock_receipt": "Select a stock receipt",
        "no_stock_receipts": "No received ballot stock has been recorded for this polling station.",
        "stock_read_only": (
            "Only assigned Polling Officers can add or correct stock receipts. Historical "
            "revisions are available to view and export."
        ),
        "stock_recorded": "Recorded",
        "stock_current": "Current revision",
        "stock_historical": "Historical revision (read-only)",
        "stock_return_current": "Load current revision",
        "stock_series": "Ballot series",
        "stock_event_at": "Received at (Hong Kong time)",
        "stock_time_hint": "Enter the original receipt time in HKT as YYYY-MM-DD HH:mm.",
        "stock_pool_hint": (
            "Record ordinary papers, replacement reserves and tendered reserves separately."
            " Enter each starting quantity; enter 0 when a reserve is empty."
        ),
        "stock_pool_ordinary": "Ordinary papers",
        "stock_pool_replacement": "Replacement reserve",
        "stock_pool_tendered": "Tendered reserve",
        "stock_calculated_total": "Total calculated from serial ranges",
        "stock_total_received": "Recorded total received",
        "stock_add_range": "Add serial range",
        "stock_remove_range": "Remove this range",
        "stock_serial_hint": (
            "Use 1–18 ASCII digits and preserve leading zeroes. The start cannot exceed the"
            " end, and ranges cannot overlap across pools."
        ),
        "no_stock_ranges": "No serial ranges added. Add an ordinary or reserve range.",
        "stock_range": "Serial range",
        "stock_pool": "Pool",
        "stock_serial_from": "Serial from",
        "stock_serial_to": "Serial to",
        "stock_range_quantity": "Calculated quantity",
        "stock_correction_hint": (
            "Saving a correction creates a new revision and retains the original. Enter a "
            "correction reason."
        ),
        "stock_reason": "Correction reason",
        "stock_save_correction": "Save correction revision",
        "stock_save": "Save stock receipt",
        "stock_history": "Stock receipt revision history",
        "no_stock_history": "No saved receipt revisions are available.",
        "stock_report": "Ballot stock receipt and reserves",
        "stock_report_hint": (
            "Preview and export use the selected receipt and revision. Save changes or "
            "reload the saved revision first."
        ),
        "stock_report_language": "Export language",
        "stock_preview": "Preview statement",
        "stock_export_pdf": "Export PDF",
        "stock_export_csv": "Export UTF-8 CSV",
        "stock_preview_language": "Current preview language",
        "stock_export_location": "Saved report file",
        "stock_validation": (
            "Check the ballot series, HKT receipt time and valid serial ranges. Starting "
            "pool quantities must be nonnegative integers matching their inclusive ranges. "
            "Receive at least 1 paper."
        ),
        "stock_overlap": (
            "Those serials are already used by another receipt or pool in this constituency"
            " and ballot series. Check the ranges."
        ),
        "stock_receipt_not_found": (
            "The selected receipt or revision was not found. Refresh and select it again."
        ),
        "election_read_only": (
            "Finalized election records can be viewed and exported but cannot be changed directly."
        ),
        "stock_saved": "Stock receipt saved.",
        "stock_report_ready": "The selected revision is ready to preview.",
        "stock_exported": "Report saved to the selected file.",
        "stock_export_failed": (
            "Export did not complete. Check the selected file location and connection, then retry."
        ),
        "stock_newer_revision": (
            "A newer server revision is available. Your reviewed revision and unsaved input"
            " are retained. Reload and compare before continuing."
        ),
        "unsaved_stock_changes": (
            "This form has unsaved changes. Save them, or discard and reload the saved "
            "revision before continuing."
        ),
        "report_glyph_unavailable": (
            "Some report characters are unavailable in the PDF font. Preserve the original "
            "text and use CSV, or ask an Administrator to update the report font."
        ),
        "unsaved_station_changes": (
            "The form has unsaved changes. Save it, or discard the changes before continuing."
        ),
    },
}

for language, complaint_labels in COMPLAINT_TRANSLATIONS.items():
    TRANSLATIONS[language].update(complaint_labels)

for language, period_labels in COMPLAINT_PERIOD_TRANSLATIONS.items():
    TRANSLATIONS[language].update(period_labels)

for language, allocation_labels in ALLOCATION_TRANSLATIONS.items():
    TRANSLATIONS[language].update(allocation_labels)

for language, snapshot_labels in STOCK_SNAPSHOT_TRANSLATIONS.items():
    TRANSLATIONS[language].update(snapshot_labels)

for language, return_labels in COUNTER_RETURN_TRANSLATIONS.items():
    TRANSLATIONS[language].update(return_labels)

for language, special_labels in SPECIAL_PAPER_TRANSLATIONS.items():
    TRANSLATIONS[language].update(special_labels)

for language, fallback_labels in FALLBACK_TRANSLATIONS.items():
    TRANSLATIONS[language].update(fallback_labels)

for language, fallback_turnout_labels in FALLBACK_TURNOUT_TRANSLATIONS.items():
    TRANSLATIONS[language].update(fallback_turnout_labels)

for language, accounting_labels in ACCOUNTING_TRANSLATIONS.items():
    TRANSLATIONS[language].update(accounting_labels)

for language, counting_scope_labels in COUNTING_SCOPE_TRANSLATIONS.items():
    TRANSLATIONS[language].update(counting_scope_labels)

for language, invalid_reason_labels in INVALID_REASON_TRANSLATIONS.items():
    TRANSLATIONS[language].update(invalid_reason_labels)

for language, counting_round_labels in COUNTING_ROUND_TRANSLATIONS.items():
    TRANSLATIONS[language].update(counting_round_labels)

for language, outcome_labels in COUNT_OUTCOME_TRANSLATIONS.items():
    TRANSLATIONS[language].update(outcome_labels)

for language, event_labels in BOX_EVENT_WORDS.items():
    TRANSLATIONS[language].update(event_labels)

for language, labels in RECOVERY_TRANSLATIONS.items():
    TRANSLATIONS[language].update(labels)

for language, labels in OUTAGE_TRANSLATIONS.items():
    TRANSLATIONS[language].update(labels)

for language, labels in PAPER_REENTRY_TRANSLATIONS.items():
    TRANSLATIONS[language].update(labels)
