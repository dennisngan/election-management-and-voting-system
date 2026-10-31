"""Constituency-wide recount instructions and preserved member progress."""

CONSTITUENCY_RECOUNT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "constituency_recount_title": "整個選區重新點票",
        "constituency_recount_intro": (
            "主管可為此選區每個所需點票範圍建立空白新輪次。舊紀錄會保留，工作人員須另行選取各新輪次。"
        ),
        "constituency_recount_time": "指示時間（香港時間）",
        "constituency_recount_time_hint": "YYYY-MM-DD HH:MM，可輸入秒及微秒。",
        "constituency_recount_reason": "整個選區重新點票原因",
        "constituency_recount_reason_hint": "必須填寫，最多 2000 字。",
        "constituency_recount_instruct": "指示整個選區重新點票",
        "constituency_recount_sources": "所有所需點票範圍",
        "constituency_recount_sources_count": "本指示的所需範圍數目",
        "constituency_recount_sources_hint": "此指示包括下列每個範圍，不能省略個別範圍。",
        "constituency_recount_station": "點票站",
        "constituency_recount_scope": "點票範圍",
        "constituency_recount_scope_revision": "點票範圍修訂",
        "constituency_recount_source_round_record": "已選取的來源輪次記錄",
        "constituency_recount_revision": "修訂",
        "constituency_recount_selection_revision": "選取修訂",
        "constituency_recount_refresh": "重新載入指示及進度",
        "constituency_recount_discard": "捨棄指示草稿",
        "constituency_recount_discard_hint": "捨棄尚未儲存的指示時間及原因？已記錄的指示不受影響。",
        "constituency_recount_check": "查核原有指示結果",
        "constituency_recount_request_id": "待確認要求編號",
        "constituency_recount_original_request_id": "原有要求編號",
        "constituency_recount_not_ready": (
            "所需範圍須全部就緒，並有目前已批准及選取的來源輪次，才可發出新指示。"
        ),
        "constituency_recount_unknown_hint": (
            "原有指示結果尚未確認，輸入及要求編號已保留。請先查核結果，再於「要求恢復覆核」重試原有要求。"
        ),
        "constituency_recount_newer_basis": (
            "所需範圍或已選取的來源輪次已有更新。輸入仍保留，請重新載入並核對。"
        ),
        "constituency_recount_confirm_title": "確認整個選區重新點票指示",
        "constituency_recount_confirm_hint": (
            "此指示會保留舊點票紀錄，並為所有所需範圍建立空白新輪次。請以本人主管密碼確認。"
        ),
        "constituency_recount_password": "本人主管密碼",
        "constituency_recount_confirm": "確認重新點票指示",
        "constituency_recount_cancel": "取消",
        "constituency_recount_saved": "已記錄整個選區重新點票指示；請另行選取各範圍的空白新輪次。",
        "constituency_recount_history": "整個選區重新點票指示及進度",
        "constituency_recount_instruction": "重新點票指示",
        "constituency_recount_latest": "最近指示",
        "constituency_recount_historical": "歷史指示",
        "constituency_recount_members_completed": "原有所需範圍已完成數目",
        "constituency_recount_historical_complete": "此指示原有所需的新輪次均曾獲批准及明確選取。",
        "constituency_recount_historical_pending": "此指示原有所需的新輪次尚未全部完成批准及選取。",
        "constituency_recount_history_hint": (
            "此處保留原有指示的完成歷史；目前結果仍按各範圍最新所需的輪次計算。"
        ),
        "constituency_recount_replacement_round": "本指示的新輪次",
        "constituency_recount_record": "輪次記錄",
        "constituency_recount_current_required": "目前所需的輪次記錄",
        "constituency_recount_later_required_hint": (
            "較後的重新點票已指定另一輪次；本指示原有的完成歷史仍會保留。"
        ),
        "constituency_recount_progress_incomplete": "新輪次尚未完成",
        "constituency_recount_progress_submitted": "已提交，等待主管批准",
        "constituency_recount_progress_approved": "已批准，等待明確選取",
        "constituency_recount_progress_completed": "曾以已批准的新輪次完成選取",
        "constituency_recount_completed_at": "原有所需輪次完成時間（香港時間）",
        "constituency_recount_completion_selection": "首次完成時的選取修訂",
        "constituency_recount_entered_at": "伺服器記錄時間（香港時間）",
        "constituency_recount_actor": "發出指示的主管帳戶編號",
        "constituency_recount_not_recorded": "未有記錄",
        "constituency_recount_context_unavailable": "請以獲授權主管登入，並選取此選區內的票站。",
        "constituency_recount_fields_required": "請填寫指示時間及重新點票原因（最多 2000 字）。",
        "constituency_recount_time_invalid": "請輸入有效的香港日期及時間。",
        "constituency_recount_draft_discarded": "已捨棄未儲存的重新點票指示草稿。",
        "constituency_recount_sources_stale": (
            "所需範圍或已選取的來源輪次已有更新，請重新載入並比較。"
        ),
        "constituency_recount_invalid_response": "尚未能確認完整的指示收據，請查核原有要求結果。",
        "constituency_recount_outcome_unconfirmed": "指示結果尚未確認，原有輸入及要求編號已保留。",
        "constituency_recount_changes_pending": (
            "請先完成或捨棄未儲存的選區重新點票草稿，再切換工作資料。"
        ),
        "constituency_result_incomplete": "所需點票來源尚未完整，請核對待處理的點票範圍。",
    },
    "sc": {
        "constituency_recount_title": "整个选区重新点票",
        "constituency_recount_intro": (
            "主管可为此选区每个所需点票范围建立空白新轮次。旧记录会保留，工作人员须另行选取各新轮次。"
        ),
        "constituency_recount_time": "指示时间（香港时间）",
        "constituency_recount_time_hint": "YYYY-MM-DD HH:MM，可输入秒及微秒。",
        "constituency_recount_reason": "整个选区重新点票原因",
        "constituency_recount_reason_hint": "必须填写，最多 2000 字。",
        "constituency_recount_instruct": "指示整个选区重新点票",
        "constituency_recount_sources": "所有所需点票范围",
        "constituency_recount_sources_count": "本指示的所需范围数目",
        "constituency_recount_sources_hint": "此指示包括下列每个范围，不能省略个别范围。",
        "constituency_recount_station": "点票站",
        "constituency_recount_scope": "点票范围",
        "constituency_recount_scope_revision": "点票范围修订",
        "constituency_recount_source_round_record": "已选取的来源轮次记录",
        "constituency_recount_revision": "修订",
        "constituency_recount_selection_revision": "选取修订",
        "constituency_recount_refresh": "重新载入指示及进度",
        "constituency_recount_discard": "舍弃指示草稿",
        "constituency_recount_discard_hint": "舍弃尚未保存的指示时间及原因？已记录的指示不受影响。",
        "constituency_recount_check": "核查原有指示结果",
        "constituency_recount_request_id": "待确认请求编号",
        "constituency_recount_original_request_id": "原有请求编号",
        "constituency_recount_not_ready": (
            "所需范围须全部就绪，并有当前已批准及选取的来源轮次，才可发出新指示。"
        ),
        "constituency_recount_unknown_hint": (
            "原有指示结果尚未确认，输入及请求编号已保留。请先核查结果，再于“请求恢复复核”重试原有请求。"
        ),
        "constituency_recount_newer_basis": (
            "所需范围或已选取的来源轮次已有更新。输入仍保留，请重新载入并核对。"
        ),
        "constituency_recount_confirm_title": "确认整个选区重新点票指示",
        "constituency_recount_confirm_hint": (
            "此指示会保留旧点票记录，并为所有所需范围建立空白新轮次。请以本人主管密码确认。"
        ),
        "constituency_recount_password": "本人主管密码",
        "constituency_recount_confirm": "确认重新点票指示",
        "constituency_recount_cancel": "取消",
        "constituency_recount_saved": "已记录整个选区重新点票指示；请另行选取各范围的空白新轮次。",
        "constituency_recount_history": "整个选区重新点票指示及进度",
        "constituency_recount_instruction": "重新点票指示",
        "constituency_recount_latest": "最近指示",
        "constituency_recount_historical": "历史指示",
        "constituency_recount_members_completed": "原有所需范围已完成数目",
        "constituency_recount_historical_complete": "此指示原有所需的新轮次均曾获批准及明确选取。",
        "constituency_recount_historical_pending": "此指示原有所需的新轮次尚未全部完成批准及选取。",
        "constituency_recount_history_hint": (
            "此处保留原有指示的完成历史；当前结果仍按各范围最新所需的轮次计算。"
        ),
        "constituency_recount_replacement_round": "本指示的新轮次",
        "constituency_recount_record": "轮次记录",
        "constituency_recount_current_required": "当前所需的轮次记录",
        "constituency_recount_later_required_hint": (
            "较后的重新点票已指定另一轮次；本指示原有的完成历史仍会保留。"
        ),
        "constituency_recount_progress_incomplete": "新轮次尚未完成",
        "constituency_recount_progress_submitted": "已提交，等待主管批准",
        "constituency_recount_progress_approved": "已批准，等待明确选取",
        "constituency_recount_progress_completed": "曾以已批准的新轮次完成选取",
        "constituency_recount_completed_at": "原有所需轮次完成时间（香港时间）",
        "constituency_recount_completion_selection": "首次完成时的选取修订",
        "constituency_recount_entered_at": "服务器记录时间（香港时间）",
        "constituency_recount_actor": "发出指示的主管账户编号",
        "constituency_recount_not_recorded": "尚无记录",
        "constituency_recount_context_unavailable": "请以获授权主管登录，并选取此选区内的票站。",
        "constituency_recount_fields_required": "请填写指示时间及重新点票原因（最多 2000 字）。",
        "constituency_recount_time_invalid": "请输入有效的香港日期及时间。",
        "constituency_recount_draft_discarded": "已舍弃未保存的重新点票指示草稿。",
        "constituency_recount_sources_stale": (
            "所需范围或已选取的来源轮次已有更新，请重新载入并比较。"
        ),
        "constituency_recount_invalid_response": "尚未能确认完整的指示收据，请核查原有请求结果。",
        "constituency_recount_outcome_unconfirmed": "指示结果尚未确认，原有输入及请求编号已保留。",
        "constituency_recount_changes_pending": (
            "请先完成或舍弃未保存的选区重新点票草稿，再切换工作资料。"
        ),
        "constituency_result_incomplete": "所需点票来源尚未完整，请核对待处理的点票范围。",
    },
    "en": {
        "constituency_recount_title": "Constituency-wide recount",
        "constituency_recount_intro": (
            "Instruct a blank new round for every required scope in this constituency. "
            "Earlier records remain available; staff select each new round explicitly."
        ),
        "constituency_recount_time": "Instruction time (Hong Kong)",
        "constituency_recount_time_hint": (
            "YYYY-MM-DD HH:MM; seconds and microseconds are supported."
        ),
        "constituency_recount_reason": "Reason for the constituency-wide recount",
        "constituency_recount_reason_hint": "Required, up to 2000 characters.",
        "constituency_recount_instruct": "Instruct constituency-wide recount",
        "constituency_recount_sources": "Every required counting scope",
        "constituency_recount_sources_count": "Required scopes for this instruction",
        "constituency_recount_sources_hint": "This instruction includes every listed scope.",
        "constituency_recount_station": "Counting station",
        "constituency_recount_scope": "Counting scope",
        "constituency_recount_scope_revision": "Scope revision",
        "constituency_recount_source_round_record": "Selected source round record",
        "constituency_recount_revision": "Revision",
        "constituency_recount_selection_revision": "Selection revision",
        "constituency_recount_refresh": "Reload instructions and progress",
        "constituency_recount_discard": "Discard instruction draft",
        "constituency_recount_discard_hint": (
            "Discard the unsaved instruction time and reason? Recorded instructions are retained."
        ),
        "constituency_recount_check": "Check original instruction outcome",
        "constituency_recount_request_id": "Unconfirmed request ID",
        "constituency_recount_original_request_id": "Original request ID",
        "constituency_recount_not_ready": (
            "Every required scope needs a current approved selection before a new instruction."
        ),
        "constituency_recount_unknown_hint": (
            "The original instruction is unconfirmed. Its input and request ID are retained. "
            "Check the outcome before retrying in Request recovery review."
        ),
        "constituency_recount_newer_basis": (
            "The required scopes or selected source rounds changed. "
            "Your input is retained; reload and compare."
        ),
        "constituency_recount_confirm_title": "Confirm constituency-wide recount",
        "constituency_recount_confirm_hint": (
            "Keep the earlier records and create blank rounds for every required scope. "
            "Confirm with your own Supervisor password."
        ),
        "constituency_recount_password": "Your own Supervisor password",
        "constituency_recount_confirm": "Confirm recount instruction",
        "constituency_recount_cancel": "Cancel",
        "constituency_recount_saved": (
            "Constituency-wide recount instructed. Select each blank new round explicitly."
        ),
        "constituency_recount_history": "Constituency recount instructions and progress",
        "constituency_recount_instruction": "Recount instruction",
        "constituency_recount_latest": "Latest instruction",
        "constituency_recount_historical": "Historical instruction",
        "constituency_recount_members_completed": "Original required scopes completed",
        "constituency_recount_historical_complete": (
            "All originally required new rounds were approved and explicitly selected."
        ),
        "constituency_recount_historical_pending": (
            "The originally required new rounds have not all been approved and selected."
        ),
        "constituency_recount_history_hint": (
            "This preserves the original instruction's completion history. "
            "Current results follow each scope's latest required round."
        ),
        "constituency_recount_replacement_round": "This instruction's new round",
        "constituency_recount_record": "Round record",
        "constituency_recount_current_required": "Currently required round record",
        "constituency_recount_later_required_hint": (
            "A later recount requires another round. This instruction's completion history remains."
        ),
        "constituency_recount_progress_incomplete": "New round incomplete",
        "constituency_recount_progress_submitted": "Submitted; awaiting Supervisor approval",
        "constituency_recount_progress_approved": "Approved; awaiting explicit selection",
        "constituency_recount_progress_completed": "Completed by selecting the approved new round",
        "constituency_recount_completed_at": "Original requirement completed at (Hong Kong)",
        "constituency_recount_completion_selection": "First completion selection revision",
        "constituency_recount_entered_at": "Server entry time (Hong Kong)",
        "constituency_recount_actor": "Instructing Supervisor account ID",
        "constituency_recount_not_recorded": "Not recorded",
        "constituency_recount_context_unavailable": (
            "Sign in as an authorized Supervisor and select a station in this constituency."
        ),
        "constituency_recount_fields_required": (
            "Enter the instruction time and recount reason, up to 2000 characters."
        ),
        "constituency_recount_time_invalid": "Enter a valid Hong Kong date and time.",
        "constituency_recount_draft_discarded": "Unsaved recount instruction draft discarded.",
        "constituency_recount_sources_stale": (
            "The required scopes or selected source rounds changed. Reload and compare."
        ),
        "constituency_recount_invalid_response": (
            "The complete instruction receipt is unconfirmed. Check its original outcome."
        ),
        "constituency_recount_outcome_unconfirmed": (
            "The instruction outcome is unknown. Original input and request ID are retained."
        ),
        "constituency_recount_changes_pending": (
            "Finish or discard the unsaved constituency recount draft before changing context."
        ),
        "constituency_result_incomplete": (
            "Required counting sources are incomplete. Review the pending scopes."
        ),
    },
}
