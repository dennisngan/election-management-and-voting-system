"""P(12) counter balance labels in the supported desktop languages."""

STOCK_SNAPSHOT_TRANSLATIONS = {
    "tc": {
        "snapshot_title": "P(12) 櫃台結餘與發票",
        "snapshot_intro": (
            "按同一原始時間記錄每個櫃台的普通選票結餘，保留該次接收、派發"
            "及退回基礎。"
        ),
        "snapshot_missing": "尚未記錄結餘",
        "snapshot_incomplete": "結餘尚未全部申報",
        "snapshot_complete": "所有櫃台已申報結餘",
        "snapshot_current_issued": "最新有效結餘推算的普通選票發出數量",
        "snapshot_provenance": "此為庫存推算數量，並非已核實的選民身份或正常模式投票人數。",
        "snapshot_basis_stale": (
            "相關接收、派發或退回基礎已有修訂。歷史數字保留；請核對並記錄"
            "新的有效結餘。"
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
        "snapshot_title": "P(12) 柜台结余与发票",
        "snapshot_intro": (
            "按同一原始时间记录每个柜台的普通选票结余，保留该次接收、派发"
            "及退回依据。"
        ),
        "snapshot_missing": "尚未记录结余",
        "snapshot_incomplete": "结余尚未全部申报",
        "snapshot_complete": "所有柜台已申报结余",
        "snapshot_current_issued": "最新有效结余推算的普通选票发出数量",
        "snapshot_provenance": "此为库存推算数量，并非已核实的选民身份或正常模式投票人数。",
        "snapshot_basis_stale": (
            "相关接收、派发或退回依据已有修订。历史数字保留；请核对并记录"
            "新的有效结余。"
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
