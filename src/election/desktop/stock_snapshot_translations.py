"""P(12) counter balance labels in the supported desktop languages."""

STOCK_SNAPSHOT_TRANSLATIONS = {
    "tc": {
        "stock_snapshot_validation": (
            "請核對原始香港時間、已申報櫃台及剩餘範圍。系列須完全相符，編"
            "號使用一至十八位半形數字，起始不可大於結束；修訂須填原因。"
        ),
        "event_time_in_future": ("原始事件時間不可晚於伺服器現在時間，請核對香港日期及時間。"),
        "remaining_outside_owned_stock": (
            "此剩餘範圍超出該櫃台於觀察時間持有的普通選票。請核對派發、未發出選票退回、系列及編號。"
        ),
        "snapshot_report": "P(12) 所選結餘版本報表",
        "snapshot_report_hint": (
            "預覽及匯出保留所選已儲存版本的範圍、數量與基礎，包括歷史版本"
            "。未儲存的內容不會納入；報表使用目前所選語言。"
        ),
        "snapshot_records": ("已儲存的結餘觀察"),
        "snapshot_empty": ("本站尚未儲存結餘觀察。"),
        "snapshot_select": ("選擇已儲存的結餘觀察"),
        "snapshot_record": ("結餘觀察"),
        "snapshot_edit": ("建立有原因的修訂"),
        "snapshot_history": ("結餘觀察修訂歷史"),
        "snapshot_historical": ("此為歷史版本，只供查看。請重新載入目前版本後才修訂。"),
        "stock_snapshot_newer_revision": ("伺服器已有較新版本；您審閱的版本及未儲存內容仍保留。"),
        "snapshot_new": "新增結餘觀察",
        "unsaved_stock_snapshot_changes": (
            "結餘表格有未儲存內容。儲存或明確捨棄後，才會切換所審閱的觀察或版本。"
        ),
        "snapshot_title": "P(12) 櫃台結餘與發票",
        "snapshot_intro": (
            "按同一原始時間記錄每個櫃台的普通選票結餘，保留該次接收、派發及退回基礎。"
        ),
        "snapshot_missing": "尚未記錄結餘",
        "snapshot_incomplete": "結餘尚未全部申報",
        "snapshot_complete": "所有櫃台已申報結餘",
        "snapshot_current_issued": "最新有效結餘推算的普通選票發出數量",
        "snapshot_provenance": "此為庫存推算數量，並非已核實的選民身份或正常模式投票人數。",
        "snapshot_basis_stale": (
            "相關接收、派發或退回基礎已有修訂。歷史數字保留；請核對並記錄新的有效結餘。"
        ),
        "snapshot_observation": "櫃台結餘觀察",
        "snapshot_event_time": "原始結餘時間（香港時間 YYYY-MM-DD HH:mm）",
        "snapshot_reporting_hint": (
            "勾選已申報的櫃台，然後輸入尚未發出的普通選票範圍。已申報但沒"
            "有範圍表示零；未勾選表示尚未申報。"
        ),
        "snapshot_reported": "此櫃台已申報結餘",
        "snapshot_explicit_zero": "已申報零張剩餘選票。",
        "snapshot_add_range": "新增剩餘選票範圍",
        "snapshot_save": "儲存結餘觀察",
        "stock_snapshot_saved": "結餘觀察已儲存至中央伺服器。",
        "snapshot_saved_totals": "所選已儲存版本的數量",
        "snapshot_allocated": "派發至櫃台總量",
        "snapshot_returned": "已退回主任的未發出選票",
        "snapshot_net": "櫃台淨派發量",
        "snapshot_remaining": "已申報剩餘選票",
        "snapshot_issued": "庫存推算已發出選票",
    },
    "sc": {
        "stock_snapshot_validation": (
            "请核对原始香港时间、已申报柜台及剩余范围。系列须完全匹配，编"
            "号使用一至十八位半角数字，起始不可大于结束；修订须填原因。"
        ),
        "event_time_in_future": ("原始事件时间不可晚于服务器现在时间，请核对香港日期及时间。"),
        "remaining_outside_owned_stock": (
            "此剩余范围超出该柜台于观察时间持有的普通选票。请核对派发、未发出选票退回、系列及编号。"
        ),
        "snapshot_report": "P(12) 所选结余版本报表",
        "snapshot_report_hint": (
            "预览及导出保留所选已保存版本的范围、数量与依据，包括历史版本"
            "。未保存的内容不会纳入；报表使用当前所选语言。"
        ),
        "snapshot_records": ("已保存的结余观察"),
        "snapshot_empty": ("本站尚未保存结余观察。"),
        "snapshot_select": ("选择已保存的结余观察"),
        "snapshot_record": ("结余观察"),
        "snapshot_edit": ("建立有原因的修订"),
        "snapshot_history": ("结余观察修订历史"),
        "snapshot_historical": ("此为历史版本，仅供查看。请重新载入当前版本后才修订。"),
        "stock_snapshot_newer_revision": ("服务器已有较新版本；您审阅的版本及未保存内容仍保留。"),
        "snapshot_new": "新增结余观察",
        "unsaved_stock_snapshot_changes": (
            "结余表格有未保存内容。保存或明确舍弃后，才会切换所审阅的观察或版本。"
        ),
        "snapshot_title": "P(12) 柜台结余与发票",
        "snapshot_intro": (
            "按同一原始时间记录每个柜台的普通选票结余，保留该次接收、派发及退回依据。"
        ),
        "snapshot_missing": "尚未记录结余",
        "snapshot_incomplete": "结余尚未全部申报",
        "snapshot_complete": "所有柜台已申报结余",
        "snapshot_current_issued": "最新有效结余推算的普通选票发出数量",
        "snapshot_provenance": "此为库存推算数量，并非已核实的选民身份或正常模式投票人数。",
        "snapshot_basis_stale": (
            "相关接收、派发或退回依据已有修订。历史数字保留；请核对并记录新的有效结余。"
        ),
        "snapshot_observation": "柜台结余观察",
        "snapshot_event_time": "原始结余时间（香港时间 YYYY-MM-DD HH:mm）",
        "snapshot_reporting_hint": (
            "勾选已申报的柜台，然后输入尚未发出的普通选票范围。已申报但没"
            "有范围表示零；未勾选表示尚未申报。"
        ),
        "snapshot_reported": "此柜台已申报结余",
        "snapshot_explicit_zero": "已申报零张剩余选票。",
        "snapshot_add_range": "新增剩余选票范围",
        "snapshot_save": "保存结余观察",
        "stock_snapshot_saved": "结余观察已保存至中央服务器。",
        "snapshot_saved_totals": "所选已保存版本的数量",
        "snapshot_allocated": "派发至柜台总量",
        "snapshot_returned": "已退回主任的未发出选票",
        "snapshot_net": "柜台净派发量",
        "snapshot_remaining": "已申报剩余选票",
        "snapshot_issued": "库存推算已发出选票",
    },
    "en": {
        "stock_snapshot_validation": (
            "Check the original HKT time, r"
            "eported counters and remaining"
            " ranges. Use the exact series "
            "and ordered serials of 1–18 AS"
            "CII digits. Amendments require"
            " a reason."
        ),
        "event_time_in_future": (
            "The original event time cannot"
            " be later than server time. Ch"
            "eck the Hong Kong date and tim"
            "e."
        ),
        "remaining_outside_owned_stock": (
            "This remaining range is outsid"
            "e ordinary stock owned by that"
            " counter at the observation ti"
            "me. Check allocations, unissue"
            "d returns, series and serials."
        ),
        "snapshot_report": "P(12) selected balance revision statement",
        "snapshot_report_hint": (
            "Preview and export retain the "
            "selected saved ranges, figures"
            " and basis, including historic"
            "al revisions. Unsaved input is"
            " excluded. Reports use the sel"
            "ected interface language."
        ),
        "snapshot_records": ("Saved balance observations"),
        "snapshot_empty": ("No balance observations have been saved at this station."),
        "snapshot_select": ("Choose a saved balance observation"),
        "snapshot_record": ("Balance observation"),
        "snapshot_edit": ("Prepare a reasoned amendment"),
        "snapshot_history": ("Balance observation revision history"),
        "snapshot_historical": (
            "This historical revision is read-only. Reload the current revision before amending."
        ),
        "stock_snapshot_newer_revision": (
            "A newer server revision is ava"
            "ilable. Your reviewed revision"
            " and unsaved input are retaine"
            "d."
        ),
        "snapshot_new": "New balance observation",
        "unsaved_stock_snapshot_changes": (
            "The balance form has unsaved i"
            "nput. Save it or explicitly di"
            "scard it before changing the r"
            "eviewed observation or revisio"
            "n."
        ),
        "snapshot_title": "P(12) Counter balances",
        "snapshot_intro": (
            "Observe ordinary stock at ever"
            "y counter at one original even"
            "t time. Retain the receipt, al"
            "location and return basis used"
            " for that observation."
        ),
        "snapshot_missing": "No balance observation recorded",
        "snapshot_incomplete": "Some counter balances are unreported",
        "snapshot_complete": "All counter balances reported",
        "snapshot_current_issued": "Ordinary papers issued from the latest valid observation",
        "snapshot_provenance": (
            "This is a stock-derived quanti"
            "ty, not verified elector ident"
            "ity or normal-mode turnout."
        ),
        "snapshot_basis_stale": (
            "The receipt, allocation or ret"
            "urn basis has changed. Histori"
            "cal figures are retained. Chec"
            "k the source records and save "
            "a valid new observation."
        ),
        "snapshot_observation": "Counter balance observation",
        "snapshot_event_time": "Original observation time (HKT YYYY-MM-DD HH:mm)",
        "snapshot_reporting_hint": (
            "Mark each reported counter, th"
            "en enter its remaining ordinar"
            "y serial ranges. Reported with"
            " no ranges means zero. Uncheck"
            "ed means unreported."
        ),
        "snapshot_reported": "This counter has reported its balance",
        "snapshot_explicit_zero": "Explicitly reported zero remaining papers.",
        "snapshot_add_range": "Add remaining serial range",
        "snapshot_save": "Save balance observation",
        "stock_snapshot_saved": "The balance observation was saved to the central server.",
        "snapshot_saved_totals": "Quantities in the selected saved revision",
        "snapshot_allocated": "Gross counter allocations",
        "snapshot_returned": "Unissued stock returned to PRO",
        "snapshot_net": "Net counter allocations",
        "snapshot_remaining": "Reported remaining stock",
        "snapshot_issued": "Stock-derived papers issued",
    },
}
