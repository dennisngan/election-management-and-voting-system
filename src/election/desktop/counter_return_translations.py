"""Unissued ordinary-stock return labels for issuance counters."""

COUNTER_RETURN_TRANSLATIONS = {
    "tc": {
        "counter_return_title": "櫃台未發出選票退回",
        "counter_return_hint": (
            "將發票櫃台從未向選民發出的普通選票退回投票站主任（PRO）。"
            "這與先前已發出後取回的未用選票分開記錄；不得將已發出的選票退回未發出庫存。"
        ),
        "counter_return_records": "已儲存的櫃台退回記錄",
        "counter_return_empty": "此投票站尚無已儲存的櫃台退回記錄。",
        "counter_return_select": "請選擇退回記錄",
        "counter_return_record": "櫃台退回記錄",
        "counter_return_new": "新增櫃台退回",
        "counter_return_edit": "修正櫃台退回",
        "counter_return_history": "櫃台退回修訂歷史",
        "counter_return_historical": "歷史退回版本（只供查看）",
        "counter_return_read_only": (
            "只有獲指派的投票站職員可新增或修正櫃台退回記錄。歷史版本只供查看。"
        ),
        "counter_return_newer_revision": (
            "此退回記錄已有較新版本。您審閱的版本及未儲存內容仍保留；請比較後重新載入。"
        ),
        "counter_return_event_time": "原本退回時間（香港時間 YYYY-MM-DD HH:mm）",
        "counter_return_save": "儲存櫃台退回",
        "counter_return_saved": "櫃台退回記錄已儲存至中央伺服器。",
        "counter_return_validation": (
            "請選擇本站發票櫃台，並輸入完全相符的選票系列（1 至 64 個字元）、"
            "1 至 18 位半形數字的編號及有效香港時間。保留編號前的 0；"
            "起始編號不可大於結束編號。修正時須填寫 1 至 1000 個字元的原因。"
        ),
        "unsaved_counter_return_changes": "櫃台退回表格有未儲存內容。確認捨棄後才會繼續所選操作。",
        "stock_return_not_found": "找不到所選退回記錄或修訂版本，請重新整理後再選擇。",
        "return_outside_owned_stock": (
            "此範圍未完全包含在退回時間該櫃台持有的同一系列未發出普通選票內。"
            "請核對櫃台、系列、編號及退回時間。"
        ),
        "stock_returns_conflict": (
            "此變更與已記錄的選票退回或其後派發有衝突。請核對相關櫃台、系列、編號範圍及事件時間。"
        ),
        "stock_already_issued": (
            "此範圍包含已記錄為發出的選票。已發出的選票不可退回或重新記作未發出庫存。"
        ),
        "stock_observations_conflict": (
            "此變更與已儲存的餘額快照所記錄的已發出或剩餘選票有衝突。"
            "請核對相關快照、選票範圍及事件時間。"
        ),
    },
    "sc": {
        "counter_return_title": "柜台未发出选票退回",
        "counter_return_hint": (
            "将发票柜台从未向选民发出的普通选票退回投票站主任（PRO）。"
            "这与先前已发出后取回的未用选票分开记录；不得将已发出的选票退回未发出库存。"
        ),
        "counter_return_records": "已保存的柜台退回记录",
        "counter_return_empty": "此投票站尚无已保存的柜台退回记录。",
        "counter_return_select": "请选择退回记录",
        "counter_return_record": "柜台退回记录",
        "counter_return_new": "新增柜台退回",
        "counter_return_edit": "修正柜台退回",
        "counter_return_history": "柜台退回修订历史",
        "counter_return_historical": "历史退回版本（仅供查看）",
        "counter_return_read_only": (
            "只有获指派的投票站职员可新增或修正柜台退回记录。历史版本仅供查看。"
        ),
        "counter_return_newer_revision": (
            "此退回记录已有较新版本。您审阅的版本及未保存内容仍保留；请比较后重新载入。"
        ),
        "counter_return_event_time": "原本退回时间（香港时间 YYYY-MM-DD HH:mm）",
        "counter_return_save": "保存柜台退回",
        "counter_return_saved": "柜台退回记录已保存至中央服务器。",
        "counter_return_validation": (
            "请选择本站发票柜台，并输入完全匹配的选票系列（1 至 64 个字符）、"
            "1 至 18 位半角数字的编号及有效香港时间。保留编号前的 0；"
            "起始编号不可大于结束编号。修正时须填写 1 至 1000 个字符的原因。"
        ),
        "unsaved_counter_return_changes": "柜台退回表格有未保存内容。确认舍弃后才会继续所选操作。",
        "stock_return_not_found": "找不到所选退回记录或修订版本，请刷新后再选择。",
        "return_outside_owned_stock": (
            "此范围未完全包含在退回时间该柜台持有的同一系列未发出普通选票内。"
            "请核对柜台、系列、编号及退回时间。"
        ),
        "stock_returns_conflict": (
            "此变更与已记录的选票退回或其后派发有冲突。请核对相关柜台、系列、编号范围及事件时间。"
        ),
        "stock_already_issued": (
            "此范围包含已记录为发出的选票。已发出的选票不可退回或重新记作未发出库存。"
        ),
        "stock_observations_conflict": (
            "此变更与已保存的余额快照所记录的已发出或剩余选票有冲突。"
            "请核对相关快照、选票范围及事件时间。"
        ),
    },
    "en": {
        "counter_return_title": "Unissued counter stock returns",
        "counter_return_hint": (
            "Return never-issued ordinary stock from an issuance counter to the Presiding "
            "Officer (PRO). Record these returns separately from previously issued "
            "retrieved-unused ballots; issued papers cannot become unissued stock."
        ),
        "counter_return_records": "Saved counter stock returns",
        "counter_return_empty": (
            "No counter stock returns have been saved for this polling station."
        ),
        "counter_return_select": "Select a stock return",
        "counter_return_record": "Counter stock return",
        "counter_return_new": "New counter stock return",
        "counter_return_edit": "Correct counter stock return",
        "counter_return_history": "Counter stock return revision history",
        "counter_return_historical": "Historical return revision (read-only)",
        "counter_return_read_only": (
            "Only assigned Polling Officers can add or correct counter stock returns. "
            "Historical revisions are read-only."
        ),
        "counter_return_newer_revision": (
            "A newer stock return revision is available. Your reviewed revision and unsaved "
            "input are retained; compare them before reloading."
        ),
        "counter_return_event_time": "Original return time (HKT, YYYY-MM-DD HH:mm)",
        "counter_return_save": "Save counter stock return",
        "counter_return_saved": "The counter stock return has been saved to the central server.",
        "counter_return_validation": (
            "Choose a counter at this station. Enter the exact ballot series (1–64 characters), "
            "serials of 1–18 ASCII digits and a valid HKT time. Preserve leading zeroes; "
            "the start cannot exceed the end. Corrections require a reason of 1–1000 characters."
        ),
        "unsaved_counter_return_changes": (
            "This stock return form has unsaved input. "
            "Confirm discard to continue with the selected action."
        ),
        "stock_return_not_found": (
            "The selected stock return or revision was not found. Refresh and select it again."
        ),
        "return_outside_owned_stock": (
            "This range is not fully covered by unissued ordinary stock owned by the counter "
            "in the same ballot series at the return time. Check the counter, series, serials "
            "and return time."
        ),
        "stock_returns_conflict": (
            "This change conflicts with recorded stock returns or later allocations. "
            "Check their counters, series, serial ranges and event times."
        ),
        "stock_already_issued": (
            "This range contains papers already recorded as issued. "
            "Issued papers cannot be returned or recorded again as unissued stock."
        ),
        "stock_observations_conflict": (
            "This change conflicts with issued or remaining papers recorded in saved stock "
            "snapshots. Check the related snapshots, serial ranges and event times."
        ),
    },
}
