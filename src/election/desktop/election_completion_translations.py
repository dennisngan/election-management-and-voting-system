"""Read-only election completion labels for the three supported languages."""

ELECTION_COMPLETION_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "election_completion_navigation": "選舉完成確認及歷史記錄",
        "election_completion_title": "選舉完成確認及歷史記錄",
        "election_completion_not_ready": "選舉尚未符合完成確認條件",
        "election_completion_ready": "選舉已符合完成確認條件",
        "election_completion_station": "投票站",
        "polling_completion_missing": "缺少投票服務完成記錄",
        "polling_completion_approval_required": "投票服務完成記錄需要有效批准",
        "full_election_access_required": (
            "主管必須獲指派本次選舉的所有投票站，才能查看完成確認。"
        ),
    },
    "sc": {
        "election_completion_navigation": "选举完成确认及历史记录",
        "election_completion_title": "选举完成确认及历史记录",
        "election_completion_not_ready": "选举尚未符合完成确认条件",
        "election_completion_ready": "选举已符合完成确认条件",
        "election_completion_station": "投票站",
        "polling_completion_missing": "缺少投票服务完成记录",
        "polling_completion_approval_required": "投票服务完成记录需要有效批准",
        "full_election_access_required": (
            "主管必须获指派本次选举的所有投票站，才能查看完成确认。"
        ),
    },
    "en": {
        "election_completion_navigation": "Election completion and history",
        "election_completion_title": "Election completion and history",
        "election_completion_not_ready": "Election cannot be finalized yet",
        "election_completion_ready": "Election is ready for finalization",
        "election_completion_station": "Polling station",
        "polling_completion_missing": "Polling completion is missing",
        "polling_completion_approval_required": "Polling completion requires current approval",
        "full_election_access_required": (
            "Supervisor access to every station in this election is required."
        ),
    },
}
