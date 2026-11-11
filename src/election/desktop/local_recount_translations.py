"""Labels for the local recount instruction, separate from tally entry."""

LOCAL_RECOUNT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "local_recount_selection_retained": "已保留先前選取的批准輪次；重新點票尚待完成",
        "local_recount_contributes": "此顯示修訂正用於目前總數。",
        "local_recount_not_contributing": "此顯示修訂目前未用於總數。",
        "local_recount_changes_pending": "請先完成或捨棄重新點票指示草稿，再切換點票檢視。",
        "local_recount_required_round": "請選取目前指示所指定的新點票輪次。",
        "local_recount_refresh": "重新整理指示資料",
        "local_recount_discard": "捨棄指示草稿",
        "local_recount_discard_hint": "捨棄尚未儲存的指示時間及原因。",
        "local_recount_check": "查核原有指示結果",
        "local_recount_current_pending": "目前指定的重新點票要求仍待完成。",
        "local_recount_current_satisfied": "目前已批准及選取的輪次符合此指示。",
        "local_recount_title": "本點票範圍重新點票",
        "local_recount_intro": (
            "主管可指示為同一票箱範圍建立全新的空白點票輪次。舊紀錄會保留，並須另行選取新輪次。"
        ),
        "local_recount_scope": "點票範圍",
        "local_recount_source": "已選取及批准的來源輪次",
        "local_recount_revision": "修訂",
        "local_recount_event_at": "指示時間（香港時間）",
        "local_recount_event_hint": "YYYY-MM-DD HH:MM，可輸入秒及微秒。",
        "local_recount_reason": "重新點票原因",
        "local_recount_reason_hint": "必須填寫，最多 2000 字。",
        "local_recount_instruct": "指示重新點票",
        "local_recount_confirm_title": "確認重新點票指示",
        "local_recount_confirm_hint": (
            "此指示會保留舊點票紀錄並建立空白新輪次。請以本人主管密碼確認。"
        ),
        "local_recount_password": "本人主管密碼",
        "local_recount_confirm": "確認指示",
        "local_recount_cancel": "取消",
        "local_recount_latest": "最近的重新點票指示",
        "local_recount_round": "新點票輪次",
        "local_recount_status_pending": "等待新輪次完成、批准及選取",
        "local_recount_status_completed": "新輪次曾完成批准及選取",
        "local_recount_entered_at": "伺服器記錄時間",
        "local_recount_actor": "指示人員帳戶 ID",
        "local_recount_request_id": "待確認要求編號",
        "local_recount_not_ready": "請先選取已準備完成的範圍及目前已批准的輪次。",
        "local_recount_newer_basis": "範圍或已選取輪次已有更新。輸入仍保留，請重新載入並核對。",
        "local_recount_instructed": "已記錄重新點票指示；空白新輪次可供另行選取。",
        "local_recount_reason_required": "請填寫重新點票原因（最多 2000 字）。",
        "local_recount_event_required": "請輸入有效的香港日期及時間。",
        "local_recount_invalid_response": "尚未能確認指示收據，請核對原有要求結果。",
        "local_recount_outcome_unconfirmed": "指示結果尚未確認，原有輸入及要求編號已保留。",
        "local_recount_selection_stale": "已選取的批准輪次已有更新，請重新載入並比較。",
        "local_recount_source_stale": "來源點票修訂已有更新，請重新載入並比較。",
        "local_recount_pending": "目前的重新點票指示仍有待完成。",
    },
    "sc": {
        "local_recount_selection_retained": "已保留先前选取的批准轮次；重新点票尚待完成",
        "local_recount_contributes": "此显示修订正用于当前总数。",
        "local_recount_not_contributing": "此显示修订当前未用于总数。",
        "local_recount_changes_pending": "请先完成或舍弃重新点票指示草稿，再切换点票视图。",
        "local_recount_required_round": "请选择当前指示所指定的新点票轮次。",
        "local_recount_refresh": "重新整理指示资料",
        "local_recount_discard": "舍弃指示草稿",
        "local_recount_discard_hint": "舍弃尚未保存的指示时间及原因。",
        "local_recount_check": "核查原有指示结果",
        "local_recount_current_pending": "当前指定的重新点票要求仍待完成。",
        "local_recount_current_satisfied": "当前已批准及选取的轮次符合此指示。",
        "local_recount_title": "本点票范围重新点票",
        "local_recount_intro": (
            "主管可指示为同一票箱范围建立全新的空白点票轮次。旧记录会保留，并须另行选取新轮次。"
        ),
        "local_recount_scope": "点票范围",
        "local_recount_source": "已选取及批准的来源轮次",
        "local_recount_revision": "修订",
        "local_recount_event_at": "指示时间（香港时间）",
        "local_recount_event_hint": "YYYY-MM-DD HH:MM，可输入秒及微秒。",
        "local_recount_reason": "重新点票原因",
        "local_recount_reason_hint": "必须填写，最多 2000 字。",
        "local_recount_instruct": "指示重新点票",
        "local_recount_confirm_title": "确认重新点票指示",
        "local_recount_confirm_hint": (
            "此指示会保留旧点票记录并建立空白新轮次。请以本人主管密码确认。"
        ),
        "local_recount_password": "本人主管密码",
        "local_recount_confirm": "确认指示",
        "local_recount_cancel": "取消",
        "local_recount_latest": "最近的重新点票指示",
        "local_recount_round": "新点票轮次",
        "local_recount_status_pending": "等待新轮次完成、批准及选取",
        "local_recount_status_completed": "新轮次曾完成批准及选取",
        "local_recount_entered_at": "服务器记录时间",
        "local_recount_actor": "指示人员账户 ID",
        "local_recount_request_id": "待确认请求编号",
        "local_recount_not_ready": "请先选取已准备完成的范围及目前已批准的轮次。",
        "local_recount_newer_basis": "范围或已选取轮次已有更新。输入仍保留，请重新载入并核对。",
        "local_recount_instructed": "已记录重新点票指示；空白新轮次可供另行选取。",
        "local_recount_reason_required": "请填写重新点票原因（最多 2000 字）。",
        "local_recount_event_required": "请输入有效的香港日期及时间。",
        "local_recount_invalid_response": "尚未能确认指示收据，请核对原有请求结果。",
        "local_recount_outcome_unconfirmed": "指示结果尚未确认，原有输入及请求编号已保留。",
        "local_recount_selection_stale": "已选取的批准轮次已有更新，请重新载入并比较。",
        "local_recount_source_stale": "来源点票修订已有更新，请重新载入并比较。",
        "local_recount_pending": "目前的重新点票指示仍有待完成。",
    },
    "en": {
        "local_recount_selection_retained": "Previous approved selection retained; recount pending",
        "local_recount_contributes": "This displayed revision contributes to the current totals.",
        "local_recount_not_contributing": (
            "This displayed revision currently makes no contribution to totals."
        ),
        "local_recount_changes_pending": (
            "Finish or discard the recount instruction draft before changing the counting view."
        ),
        "local_recount_required_round": (
            "Select the new round required by the current recount instruction."
        ),
        "local_recount_refresh": "Refresh instruction context",
        "local_recount_discard": "Discard instruction draft",
        "local_recount_discard_hint": "Discard the unsaved instruction time and reason.",
        "local_recount_check": "Check original instruction outcome",
        "local_recount_current_pending": "The current recount requirement is still pending.",
        "local_recount_current_satisfied": (
            "The current approved selection satisfies this instruction."
        ),
        "local_recount_title": "Local scope recount",
        "local_recount_intro": (
            "A Supervisor can instruct a fresh blank round for these boxes. Earlier records remain "
            "available; select the new round explicitly to enter its tally."
        ),
        "local_recount_scope": "Counting scope",
        "local_recount_source": "Selected approved source round",
        "local_recount_revision": "Revision",
        "local_recount_event_at": "Instruction time (Hong Kong)",
        "local_recount_event_hint": "YYYY-MM-DD HH:MM; seconds and microseconds are supported.",
        "local_recount_reason": "Reason for recount",
        "local_recount_reason_hint": "Required, up to 2000 characters.",
        "local_recount_instruct": "Instruct recount",
        "local_recount_confirm_title": "Confirm local recount instruction",
        "local_recount_confirm_hint": (
            "Keep the earlier tally and create a blank new round. Confirm with your own "
            "Supervisor password."
        ),
        "local_recount_password": "Your own Supervisor password",
        "local_recount_confirm": "Confirm instruction",
        "local_recount_cancel": "Cancel",
        "local_recount_latest": "Latest recount instruction",
        "local_recount_round": "New count round",
        "local_recount_status_pending": (
            "Awaiting completion, approval and selection of the new round"
        ),
        "local_recount_status_completed": "New round was approved and explicitly selected",
        "local_recount_entered_at": "Server entry time",
        "local_recount_actor": "Instructing account ID",
        "local_recount_request_id": "Unconfirmed request ID",
        "local_recount_not_ready": "Choose a count-ready scope with a current approved selection.",
        "local_recount_newer_basis": (
            "The scope or selected round changed. Your input is retained; reload and compare."
        ),
        "local_recount_instructed": (
            "Recount instructed. The blank new round is available to select."
        ),
        "local_recount_reason_required": "Enter a recount reason, up to 2000 characters.",
        "local_recount_event_required": "Enter a valid Hong Kong date and time.",
        "local_recount_invalid_response": (
            "The instruction receipt is unconfirmed. Check its outcome."
        ),
        "local_recount_outcome_unconfirmed": (
            "The instruction outcome is unknown. The original input and request ID are retained."
        ),
        "local_recount_selection_stale": "The approved selection changed. Reload and compare.",
        "local_recount_source_stale": "The source tally revision changed. Reload and compare.",
        "local_recount_pending": "The current recount instruction is still unfinished.",
    },
}
