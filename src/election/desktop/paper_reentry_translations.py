"""Labels shared by the three paper re-entry selectors."""

PAPER_REENTRY_TRANSLATIONS = {
    "tc": {
        "workspace_uncertain_request": "請先查核不確定請求的結果，再切換票站。",
        "paper_reentry_title": "重新輸入紙本記錄",
        "paper_reentry_reference": "紙本參考編號（選填）",
        "paper_reentry_none": "一般電子輸入",
        "paper_reentry_hint": (
            "請選取與此操作相符的待輸入紙本參考。紙本原始時間會與伺服器輸入時間分開保留。"
        ),
        "paper_reentry_refresh": "重新載入紙本參考",
        "paper_reentry_clear": "清除紙本參考",
        "paper_reentry_original_at": "紙本原始事件時間（香港時間）",
        "paper_reentry_uncertain": "請先查核不確定請求的結果，再更改紙本參考。",
        "paper_reentry_invalid": "請選取與此操作及目標相符的紙本參考。",
        "paper_reentry_load_failed": "無法載入紙本參考。請檢查連線並重試。",
    },
    "sc": {
        "workspace_uncertain_request": "请先核查不确定请求的结果，再切换票站。",
        "paper_reentry_title": "重新输入纸本记录",
        "paper_reentry_reference": "纸本参考编号（选填）",
        "paper_reentry_none": "一般电子输入",
        "paper_reentry_hint": (
            "请选择与此操作相符的待输入纸本参考。纸本原始时间会与服务器输入时间分开保留。"
        ),
        "paper_reentry_refresh": "重新载入纸本参考",
        "paper_reentry_clear": "清除纸本参考",
        "paper_reentry_original_at": "纸本原始事件时间（香港时间）",
        "paper_reentry_uncertain": "请先核查不确定请求的结果，再更改纸本参考。",
        "paper_reentry_invalid": "请选择与此操作及目标相符的纸本参考。",
        "paper_reentry_load_failed": "无法载入纸本参考。请检查连接并重试。",
    },
    "en": {
        "workspace_uncertain_request": "Check the uncertain request before switching polling stations.",
        "paper_reentry_title": "Re-enter a paper record",
        "paper_reentry_reference": "Paper reference (optional)",
        "paper_reentry_none": "Ordinary electronic entry",
        "paper_reentry_hint": (
            "Select the pending reference for this operation. "
            "The original paper time is preserved separately from server entry time."
        ),
        "paper_reentry_refresh": "Reload paper references",
        "paper_reentry_clear": "Clear paper reference",
        "paper_reentry_original_at": "Original paper event time (HKT)",
        "paper_reentry_uncertain": (
            "Check the uncertain request before changing its paper reference."
        ),
        "paper_reentry_invalid": "Select a paper reference matching this operation and target.",
        "paper_reentry_load_failed": (
            "Could not load paper references. Check the connection and retry."
        ),
    },
}
