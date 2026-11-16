"""Ordinary-stock allocation labels for issuance counters."""

ALLOCATION_TRANSLATIONS = {
    "tc": {
        "allocation_before_return": (
            "此編號範圍是在擬記錄的派發時間之後才退回。請將派發時間設為該次退回時間或之後。"
        ),
        "allocation_title": "櫃台選票派發",
        "allocation_record": "櫃台派發記錄",
        "allocation_records": "已儲存的櫃台派發記錄",
        "allocation_new": "新增櫃台派發",
        "allocation_select": "請選擇派發記錄",
        "allocation_empty": "此投票站尚無已儲存的櫃台派發記錄。",
        "allocation_read_only": (
            "只有獲指派的投票站職員可新增或修正櫃台派發記錄。歷史版本只供查看與匯出。"
        ),
        "allocation_counter": "發票櫃台",
        "allocation_event_at": "原本派發時間（香港時間）",
        "allocation_time_hint": (
            "請以香港時間 YYYY-MM-DD HH:mm 輸入原本派發時間。"
            "可加 :ss 及最多六位小數秒；已記錄的秒數及小數秒會保留。"
        ),
        "allocation_hint": (
            "儲存會直接寫入中央伺服器。只可將本站已接收的普通選票編號範圍派發至發票櫃台；"
            "不包括替換及重複選票儲備。派發至櫃台與向選民發票分開記錄。"
        ),
        "allocation_quantity": "派發數量（包括起始及結束編號）",
        "allocation_save": "儲存櫃台派發",
        "allocation_history": "櫃台派發修訂歷史",
        "allocation_no_history": "尚無可查看的派發記錄版本。",
        "allocation_saved": "櫃台派發記錄已儲存至中央伺服器。",
        "allocation_validation": (
            "請選擇本站發票櫃台，並輸入完全相符的選票系列（1 至 64 個字元）、"
            "1 至 18 位半形數字的編號及有效香港時間。保留編號前的 0；"
            "起始編號不可大於結束編號。修正時須填寫 1 至 1000 個字元的原因。"
        ),
        "allocation_overlap": "此編號範圍與目前已派發的選票重疊，請核對目前派發及可用範圍。",
        "allocation_outside_stock": (
            "此範圍未完全包含在本站同一選票系列目前已接收的普通選票內，請核對系列及編號。"
        ),
        "allocation_not_found": "找不到所選派發記錄或修訂版本，請重新整理後再選擇。",
        "counter_not_found": "找不到本站所選的發票櫃台，請重新整理櫃台清單後再選擇。",
        "allocation_required": "請先選擇已儲存的派發記錄。",
        "allocation_revision_required": "請先選擇已儲存的派發修訂版本。",
        "allocation_newer_revision": (
            "此派發記錄已有較新版本。您審閱的版本及未儲存內容仍保留；請比較後重新載入。"
        ),
        "unsaved_allocation_changes": "有未儲存的櫃台派發變更。捨棄後才會載入所選記錄。",
        "stock_allocations_conflict": (
            "此接收修正會令目前櫃台已獲派發的選票超出已接收普通選票範圍。"
            "請核對相關派發與接收範圍後再儲存。"
        ),
        "allocation_availability": "目前普通選票可派發情況",
        "allocation_received": "已接收普通選票",
        "allocation_allocated": "目前已派發至櫃台",
        "allocation_available": "尚可派發至櫃台",
        "allocation_no_stock": "本站尚無可供派發的普通選票編號範圍。請先核對接收記錄。",
        "allocation_report": "選票派發報表",
        "allocation_report_scope": "報表基準",
        "allocation_report_station": "伺服器目前已儲存的全站庫存及派發",
        "allocation_report_selected": "所選已儲存的派發修訂版本",
        "allocation_report_hint": (
            "目前全站報表列出目前已儲存的接收、派發及可用範圍。"
            "所選版本報表保留該次派發及其接收基礎，不混入目前全站庫存。"
            "兩者均不包含未儲存的表格內容。"
        ),
        "allocation_report_ready": "報表預覽已準備。",
        "allocation_exported": "報表已儲存至所選檔案。",
        "allocation_export_failed": "報表未能匯出。請檢查檔案位置及連線後重試。",
        "allocation_basis": "此派發版本的接收記錄基礎",
    },
    "sc": {
        "allocation_before_return": (
            "此编号范围是在拟记录的派发时间之后才退回。请将派发时间设为该次退回时间或之后。"
        ),
        "allocation_title": "柜台选票派发",
        "allocation_record": "柜台派发记录",
        "allocation_records": "已保存的柜台派发记录",
        "allocation_new": "新增柜台派发",
        "allocation_select": "请选择派发记录",
        "allocation_empty": "此投票站尚无已保存的柜台派发记录。",
        "allocation_read_only": (
            "只有获指派的投票站职员可新增或修正柜台派发记录。历史版本仅供查看与导出。"
        ),
        "allocation_counter": "发票柜台",
        "allocation_event_at": "原本派发时间（香港时间）",
        "allocation_time_hint": (
            "请以香港时间 YYYY-MM-DD HH:mm 输入原本派发时间。"
            "可加 :ss 及最多六位小数秒；已记录的秒数及小数秒会保留。"
        ),
        "allocation_hint": (
            "保存会直接写入中央服务器。只可将本站已接收的普通选票编号范围派发至发票柜台；"
            "不包括替换及重复选票储备。派发至柜台与向选民发票分开记录。"
        ),
        "allocation_quantity": "派发数量（包括起始及结束编号）",
        "allocation_save": "保存柜台派发",
        "allocation_history": "柜台派发修订历史",
        "allocation_no_history": "尚无可查看的派发记录版本。",
        "allocation_saved": "柜台派发记录已保存至中央服务器。",
        "allocation_validation": (
            "请选择本站发票柜台，并输入完全匹配的选票系列（1 至 64 个字符）、"
            "1 至 18 位半角数字的编号及有效香港时间。保留编号前的 0；"
            "起始编号不可大于结束编号。修正时须填写 1 至 1000 个字符的原因。"
        ),
        "allocation_overlap": "此编号范围与当前已派发的选票重叠，请核对当前派发及可用范围。",
        "allocation_outside_stock": (
            "此范围未完全包含在本站同一选票系列当前已接收的普通选票内，请核对系列及编号。"
        ),
        "allocation_not_found": "找不到所选派发记录或修订版本，请刷新后再选择。",
        "counter_not_found": "找不到本站所选的发票柜台，请刷新柜台列表后再选择。",
        "allocation_required": "请先选择已保存的派发记录。",
        "allocation_revision_required": "请先选择已保存的派发修订版本。",
        "allocation_newer_revision": (
            "此派发记录已有较新版本。您审阅的版本及未保存内容仍保留；请比较后重新载入。"
        ),
        "unsaved_allocation_changes": "有未保存的柜台派发变更。舍弃后才会载入所选记录。",
        "stock_allocations_conflict": (
            "此接收修正会令当前柜台已获派发的选票超出已接收普通选票范围。"
            "请核对相关派发与接收范围后再保存。"
        ),
        "allocation_availability": "当前普通选票可派发情况",
        "allocation_received": "已接收普通选票",
        "allocation_allocated": "当前已派发至柜台",
        "allocation_available": "尚可派发至柜台",
        "allocation_no_stock": "本站尚无可供派发的普通选票编号范围。请先核对接收记录。",
        "allocation_report": "选票派发报表",
        "allocation_report_scope": "报表依据",
        "allocation_report_station": "服务器当前已保存的全站库存及派发",
        "allocation_report_selected": "所选已保存的派发修订版本",
        "allocation_report_hint": (
            "当前全站报表列出当前已保存的接收、派发及可用范围。"
            "所选版本报表保留该次派发及其接收依据，不混入当前全站库存。"
            "两者均不包含未保存的表单内容。"
        ),
        "allocation_report_ready": "报表预览已准备。",
        "allocation_exported": "报表已保存至所选文件。",
        "allocation_export_failed": "报表未能导出。请检查文件位置及连接后重试。",
        "allocation_basis": "此派发版本的接收记录依据",
    },
    "en": {
        "allocation_before_return": (
            "These papers were returned aft"
            "er the proposed allocation tim"
            "e. Enter an allocation time at"
            " or after the return that rele"
            "ases this range."
        ),
        "allocation_title": "Counter stock allocations",
        "allocation_record": "Counter allocation",
        "allocation_records": "Saved counter allocations",
        "allocation_new": "New counter allocation",
        "allocation_select": "Select an allocation",
        "allocation_empty": "No counter allocations have been saved for this polling station.",
        "allocation_read_only": (
            "Only assigned Polling Officers can add or correct counter allocations. "
            "Historical revisions are available to view and export."
        ),
        "allocation_counter": "Issuance counter",
        "allocation_event_at": "Original allocation time (Hong Kong time)",
        "allocation_time_hint": (
            "Enter the original allocation time in HKT as YYYY-MM-DD HH:mm. "
            "Optionally add :ss and up to six fractional digits; saved seconds and "
            "fractional seconds are preserved."
        ),
        "allocation_hint": (
            "Saving writes directly to the central server. Allocate only this station's "
            "received ordinary serial ranges to issuance counters; replacement and tendered "
            "reserves are excluded. Allocation to a counter is separate from issuance "
            "to an elector."
        ),
        "allocation_quantity": "Allocation quantity (inclusive serial range)",
        "allocation_save": "Save counter allocation",
        "allocation_history": "Counter allocation revision history",
        "allocation_no_history": "No saved allocation revisions are available.",
        "allocation_saved": "The counter allocation has been saved to the central server.",
        "allocation_validation": (
            "Choose a counter at this station. Enter the exact ballot series (1–64 characters), "
            "serials of 1–18 ASCII digits and a valid HKT time. Preserve leading zeroes; "
            "the start cannot exceed the end. Corrections require a reason of 1–1000 characters."
        ),
        "allocation_overlap": (
            "This serial range overlaps stock already allocated. "
            "Check the current allocations and available ranges."
        ),
        "allocation_outside_stock": (
            "This range is not fully covered by the station's current ordinary received stock "
            "in the same ballot series. Check the exact series and serials."
        ),
        "allocation_not_found": (
            "The selected allocation or revision was not found. Refresh and select it again."
        ),
        "counter_not_found": (
            "The selected station counter was not found. "
            "Refresh the counter list and select it again."
        ),
        "allocation_required": "Select a saved allocation first.",
        "allocation_revision_required": "Select a saved allocation revision first.",
        "allocation_newer_revision": (
            "A newer allocation revision is available. Your reviewed revision and unsaved "
            "input are retained; compare them before reloading."
        ),
        "unsaved_allocation_changes": (
            "There are unsaved counter allocation changes. "
            "Discard them to load the selected record."
        ),
        "stock_allocations_conflict": (
            "This receipt correction would leave a current counter allocation outside "
            "ordinary received stock. Check the related allocations and receipt ranges "
            "before saving."
        ),
        "allocation_availability": "Current ordinary stock availability",
        "allocation_received": "Ordinary stock received",
        "allocation_allocated": "Currently allocated to counters",
        "allocation_available": "Available for counter allocation",
        "allocation_no_stock": (
            "No ordinary serial ranges are available for allocation at this station. "
            "Check the stock receipts first."
        ),
        "allocation_report": "Stock allocation statement",
        "allocation_report_scope": "Report basis",
        "allocation_report_station": "Current saved station stock and allocations",
        "allocation_report_selected": "Selected saved allocation revision",
        "allocation_report_hint": (
            "The current station statement lists current saved receipts, allocations and available "
            "ranges. A selected revision retains that allocation and its receipt basis without "
            "mixing in current station stock. Neither includes unsaved form input."
        ),
        "allocation_report_ready": "The statement preview is ready.",
        "allocation_exported": "The statement has been saved to the selected file.",
        "allocation_export_failed": (
            "The statement could not be exported. "
            "Check the file location and connection, then retry."
        ),
        "allocation_basis": "Receipt basis for this allocation revision",
    },
}
