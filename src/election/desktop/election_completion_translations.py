"""Election completion labels for the three supported languages."""

ELECTION_COMPLETION_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
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
