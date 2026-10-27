"""Precise instruction provenance and live contribution labels for count reports."""

from election.server.stock_reports import ReportLocale

_LANGUAGES: tuple[ReportLocale, ...] = ("tc", "sc", "en")
_BASE = {
    "local_recount_pending": (
        "目前重新點票要求尚待完成",
        "当前重新点票要求尚待完成",
        "Current recount requirement pending",
    ),
    "local_recount_contributes_to_result": (
        "所顯示版本計入目前總數",
        "所显示版本计入当前总数",
        "Displayed revision contributes to current totals",
    ),
    "local_recount_associated_instruction": (
        "此輪次所屬的重新點票指示編號",
        "此轮次所属的重新点票指示编号",
        "This round's recount instruction ID",
    ),
    "local_recount_required_instruction": (
        "目前指定的重新點票指示編號",
        "当前指定的重新点票指示编号",
        "Current required recount instruction ID",
    ),
    "local_recount_state_pending": (
        "尚未完成批准及選取",
        "尚未完成批准及选取",
        "Not yet approved and explicitly selected",
    ),
    "local_recount_state_completed": (
        "曾完成批准及選取",
        "曾完成批准及选取",
        "Previously approved and explicitly selected",
    ),
    "local_recount_historical_not_current": (
        "先前指示；目前要求另列",
        "先前指示；当前要求另列",
        "Earlier instruction; current requirement shown separately",
    ),
}
_DETAILS = {
    "request_id": ("原有要求編號", "原有请求编号", "Original request ID"),
    "scope_revision": ("指示所依據的範圍版本", "指示所依据的范围版本", "Instructed scope revision"),
    "scope_revision_id": (
        "指示所依據的範圍版本記錄編號",
        "指示所依据的范围版本记录编号",
        "Instructed scope revision record ID",
    ),
    "source_round_id": ("來源輪次記錄編號", "来源轮次记录编号", "Source round record ID"),
    "source_round_revision": ("來源輪次版本", "来源轮次版本", "Source round revision"),
    "source_round_revision_id": (
        "來源輪次版本記錄編號",
        "来源轮次版本记录编号",
        "Source round revision record ID",
    ),
    "new_round_id": ("新輪次記錄編號", "新轮次记录编号", "New round record ID"),
    "new_round_number": ("新輪次", "新轮次", "New round number"),
    "actor_id": ("指示主管帳戶編號", "指示主管账户编号", "Instructing Supervisor account ID"),
    "reason": ("指示原因", "指示原因", "Instruction reason"),
    "event_at": (
        "指示發生時間（香港）",
        "指示发生时间（香港）",
        "Instruction occurrence time (Hong Kong)",
    ),
    "entered_at": (
        "指示伺服器記錄時間（香港）",
        "指示服务器记录时间（香港）",
        "Instruction server entry time (Hong Kong)",
    ),
    "status": ("曾完成狀態", "曾完成状态", "Historical completion state"),
    "completed_at": (
        "首次合資格完成選取時間（香港）",
        "首次合资格完成选取时间（香港）",
        "First qualifying selection time (Hong Kong)",
    ),
    "completion_selection_revision": (
        "曾完成時的選取版本",
        "曾完成时的选取版本",
        "Historical completion selection revision",
    ),
    "current_satisfied": (
        "目前選取符合此指示",
        "当前选取符合此指示",
        "Current selection satisfies this instruction",
    ),
}
_PREFIXES: dict[ReportLocale, tuple[str, str]] = {
    "tc": ("目前指定指示", "此輪次所屬指示"),
    "sc": ("当前指定指示", "此轮次所属指示"),
    "en": ("Required instruction", "This round's instruction"),
}

LABELS: dict[ReportLocale, dict[str, str]] = {
    locale: {
        **{key: values[index] for key, values in _BASE.items()},
        **{
            f"local_recount_{kind}_{field}": f"{prefix} · {values[index]}"
            for kind, prefix in zip(("required", "associated"), _PREFIXES[locale], strict=True)
            for field, values in _DETAILS.items()
        },
    }
    for index, locale in enumerate(_LANGUAGES)
}


_PARENT_DETAILS = {
    "id": ("全選區重新點票指示編號", "全选区重新点票指示编号", "Constituency-wide instruction ID"),
    "request_id": ("原有全選區要求編號", "原有全选区请求编号", "Original constituency request ID"),
    "constituency_id": ("指示所屬選區編號", "指示所属选区编号", "Instruction constituency ID"),
    "actor_id": ("全選區指示主管帳戶編號", "全选区指示主管账户编号", "Constituency Supervisor account ID"),
    "reason": ("全選區指示原因", "全选区指示原因", "Constituency instruction reason"),
    "event_at": (
        "全選區指示發生時間（香港）",
        "全选区指示发生时间（香港）",
        "Constituency instruction occurrence time (Hong Kong)",
    ),
    "entered_at": (
        "全選區指示記錄時間（香港）",
        "全选区指示记录时间（香港）",
        "Constituency instruction entry time (Hong Kong)",
    ),
    "member_count": ("原有指定範圍數目", "原有指定范围数目", "Original required scope count"),
    "scope_ids": ("原有指定範圍編號", "原有指定范围编号", "Original required scope IDs"),
}
for index, locale in enumerate(_LANGUAGES):
    parent_prefixes = (
        ("Current required instruction", "This round's instruction")
        if locale == "en" else _PREFIXES[locale]
    )
    LABELS[locale].update({
        f"constituency_recount_{kind}_{field}": f"{prefix} · {values[index]}"
        for kind, prefix in zip(("required", "associated"), parent_prefixes, strict=True)
        for field, values in _PARENT_DETAILS.items()
    })
