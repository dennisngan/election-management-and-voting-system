"""Election completion labels for the three supported languages."""

ELECTION_COMPLETION_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "election_completion_export_changed": (
            "所選歷史記錄已變更。請重新開啟匯出。"
        ),
        "election_completion_reopen": "重新開放選舉",
        "election_completion_reopen_reason": "重新開放原因",
        "election_completion_reopen_hint": "先重新載入歷史記錄，然後記錄重新開放的原因。",
        "election_completion_reopen_confirm": "確認重新開放",
        "election_completion_reopen_password_hint": (
            "請輸入你自己的密碼，以重新開放已檢視的選舉版本。"
        ),
        "election_reopening_not_ready": "請重新載入目前已定案的選舉歷史記錄後，再重新開放。",
        "election_completion_export_failed": "無法匯出已保留報表",
        "election_completion_exported": "已匯出已保留報表",
        "election_completion_history": "已保留完成確認記錄",
        "election_completion_event": "選擇歷史記錄",
        "election_completion_finalization": "完成確認",
        "election_completion_reopening": "重新開放",
        "election_completion_current": "目前選舉狀態",
        "election_completion_revision": "版本",
        "election_completion_preview": "預覽報表",
        "election_completion_review_changed": (
            "選舉資料已更新。請取消並重新檢視後再確認。"
        ),
        "election_completion_finalize": "確認選舉完成",
        "election_completion_finalized": "選舉已完成確認；已保留結果。",
        "election_completion_confirm_title": "確認選舉完成",
        "election_completion_password_hint": "請輸入你自己的密碼，以確認已檢視的選舉結果。",
        "election_completion_password": "你的密碼",
        "election_completion_cancel": "取消",
        "election_completion_navigation": "選舉完成確認及歷史記錄",
        "election_completion_title": "選舉完成確認及歷史記錄",
        "election_completion_not_ready": "選舉尚未符合完成確認條件",
        "election_completion_ready": "選舉已符合完成確認條件",
        "election_completion_station": "投票站",
        "polling_completion_missing": "缺少投票服務完成記錄",
        "station_boxes_missing": "缺少所需票箱",
        "result_tie_resolution_required": "影響結果的平票需要授權決定",
        "polling_completion_approval_required": "投票服務完成記錄需要有效批准",
        "full_election_access_required": (
            "主管必須獲指派本次選舉的所有投票站，才能查看完成確認。"
        ),
    },
    "sc": {
        "election_completion_export_changed": (
            "所选历史记录已变更。请重新打开导出。"
        ),
        "election_completion_reopen": "重新开放选举",
        "election_completion_reopen_reason": "重新开放原因",
        "election_completion_reopen_hint": "先重新载入历史记录，然后记录重新开放的原因。",
        "election_completion_reopen_confirm": "确认重新开放",
        "election_completion_reopen_password_hint": (
            "请输入你自己的密码，以重新开放已检视的选举版本。"
        ),
        "election_reopening_not_ready": "请重新载入目前已定案的选举历史记录后，再重新开放。",
        "election_completion_export_failed": "无法导出已保留报表",
        "election_completion_exported": "已导出已保留报表",
        "election_completion_history": "已保留完成确认记录",
        "election_completion_event": "选择历史记录",
        "election_completion_finalization": "完成确认",
        "election_completion_reopening": "重新开放",
        "election_completion_current": "目前选举状态",
        "election_completion_revision": "版本",
        "election_completion_preview": "预览报表",
        "election_completion_review_changed": (
            "选举资料已更新。请取消并重新检视后再确认。"
        ),
        "election_completion_finalize": "确认选举完成",
        "election_completion_finalized": "选举已完成确认；已保留结果。",
        "election_completion_confirm_title": "确认选举完成",
        "election_completion_password_hint": "请输入你自己的密码，以确认已检视的选举结果。",
        "election_completion_password": "你的密码",
        "election_completion_cancel": "取消",
        "election_completion_navigation": "选举完成确认及历史记录",
        "election_completion_title": "选举完成确认及历史记录",
        "election_completion_not_ready": "选举尚未符合完成确认条件",
        "election_completion_ready": "选举已符合完成确认条件",
        "election_completion_station": "投票站",
        "polling_completion_missing": "缺少投票服务完成记录",
        "station_boxes_missing": "缺少所需票箱",
        "result_tie_resolution_required": "影响结果的平票需要授权决定",
        "polling_completion_approval_required": "投票服务完成记录需要有效批准",
        "full_election_access_required": (
            "主管必须获指派本次选举的所有投票站，才能查看完成确认。"
        ),
    },
    "en": {
        "election_completion_export_changed": (
            "The selected history event changed. Open the export again."
        ),
        "election_completion_reopen": "Reopen election",
        "election_completion_reopen_reason": "Reason for reopening",
        "election_completion_reopen_hint": "Refresh history, then record the reason for reopening.",
        "election_completion_reopen_confirm": "Confirm reopening",
        "election_completion_reopen_password_hint": (
            "Enter your own password to reopen the reviewed election revision."
        ),
        "election_reopening_not_ready": (
            "Refresh the current finalized election history before reopening."
        ),
        "election_completion_export_failed": "Could not export the preserved statement",
        "election_completion_exported": "Preserved statement exported",
        "election_completion_history": "Preserved completion history",
        "election_completion_event": "Select history event",
        "election_completion_finalization": "Finalization",
        "election_completion_reopening": "Reopening",
        "election_completion_current": "Current election state",
        "election_completion_revision": "Revision",
        "election_completion_preview": "Preview statement",
        "election_completion_review_changed": (
            "Election data changed. Cancel and review the current facts before confirming."
        ),
        "election_completion_finalize": "Finalize election",
        "election_completion_finalized": "Election finalized. Preserved outcome available.",
        "election_completion_confirm_title": "Confirm election finalization",
        "election_completion_password_hint": (
            "Enter your own password to confirm the reviewed election outcome."
        ),
        "election_completion_password": "Your password",
        "election_completion_cancel": "Cancel",
        "election_completion_navigation": "Election completion and history",
        "election_completion_title": "Election completion and history",
        "election_completion_not_ready": "Election cannot be finalized yet",
        "election_completion_ready": "Election is ready for finalization",
        "election_completion_station": "Polling station",
        "polling_completion_missing": "Polling completion is missing",
        "station_boxes_missing": "Required ballot boxes are missing",
        "result_tie_resolution_required": "Result-affecting tie requires an authorized resolution",
        "polling_completion_approval_required": "Polling completion requires current approval",
        "full_election_access_required": (
            "Supervisor access to every station in this election is required."
        ),
    },
}
