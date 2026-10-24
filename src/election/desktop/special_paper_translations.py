"""Special-paper observations and frozen stock accounting in three desktop languages."""

SPECIAL_PAPER_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "special_sources_changed": (
            "接收庫存已在您編輯期間改變。已保留您的數量及所選基礎。"
            "請核對來源變更；如需載入目前系列，請選擇新增觀察並明確捨棄此草稿。"
        ),
        "special_title": "補發、重複及未用選票核算",
        "special_intro": (
            "按每個已接收的選票系列記錄累計數量。補發選票與已收回並註銷的損壞原票配對，"
            "不重複扣減；重複選票不增加普通投票人數。已收回未用選票與從未發出庫存分開核算。"
            "儲存本記錄不會改動已提供的投票人數。"
        ),
        "special_records": "已儲存的特殊選票觀察",
        "special_empty": "本站尚未儲存特殊選票觀察；尚未記錄並不表示零。",
        "special_select": "選擇已儲存的特殊選票觀察",
        "special_new": "新增特殊選票觀察",
        "special_observation": "特殊選票數量觀察",
        "special_event_time": "原始觀察時間（香港時間 YYYY-MM-DD HH:mm，可輸入秒及微秒）",
        "special_basis": "P(12) 結餘觀察基礎",
        "special_basis_hint": (
            "選擇不晚於本次觀察時間、目前有效且所有櫃台已申報的 P(12) 版本。"
            "核算會保留該版本及本次適用的接收／儲備基礎。"
        ),
        "special_choose_basis": "選擇目前完整的 P(12) 版本",
        "special_series": "已接收的選票系列",
        "special_count_hint": (
            "為每個已接收系列填寫截至原始觀察時間的六項累計數量。空白表示尚未填報；"
            "零須明確輸入。可用「全部填入零」記錄已確認的零數量。"
        ),
        "special_zero_all": "全部填入零",
        "special_save": "儲存特殊選票觀察",
        "special_edit": "建立有原因的修訂",
        "special_history": "特殊選票觀察修訂歷史",
        "special_saved_totals": "所選已儲存版本的數量",
        "special_historical": "此為歷史版本，只供查看。請重新載入目前版本後才修訂。",
        "special_basis_stale": (
            "所選版本的原有數字及來源基礎仍保留。相關庫存或 P(12) 基礎已有修訂；"
            "請核對目前有效的結餘後，再儲存新的觀察或修訂。"
        ),
        "special_report": "所選特殊選票核算版本報表",
        "special_report_hint": (
            "預覽及匯出保留所選已儲存版本的數量、接收及 P(12) 來源基礎，包括歷史版本。"
            "未儲存內容不會納入；報表標籤使用目前所選語言。票箱選票數量屬庫存估計。"
        ),
        "special_paper_validation": (
            "請核對原始香港時間、目前完整的 P(12) 版本及所有已接收系列。"
            "每項數量須填非負整數；修訂須填寫原因。"
        ),
        "special_paper_saved": "特殊選票觀察已儲存至中央伺服器。",
        "unsaved_special_paper_changes": (
            "特殊選票表格有未儲存內容。儲存或明確捨棄後，才會切換所審閱的觀察、版本或來源基礎。"
        ),
        "special_paper_newer_revision": (
            "伺服器已有較新版本；您審閱的版本及未儲存數量仍保留。請比較後再重新載入。"
        ),
        "special_paper_bounds": (
            "填報數量超出適用的已接收儲備或普通已發出選票基礎。"
            "請核對所選 P(12) 版本、系列及各項累計數量。"
        ),
        "replacement_spoilt_mismatch": (
            "補發選票數量須與已收回並註銷的損壞原票數量配對一致。請核對兩項數量。"
        ),
        "special_paper_series_incomplete": (
            "請按完全相符的名稱填報所有已接收選票系列，每個系列只填一次。"
        ),
        "special_paper_issuance_regression": (
            "補發或重複選票的累計發出數量與其他已儲存觀察不一致。"
            "請按原始時間核對較早、同時及較後的觀察；累計發出數量不可隨時間倒退。"
        ),
        "special_paper_stock_conflict": (
            "此變更與已儲存特殊選票觀察所核算的庫存有衝突。請核對相關接收記錄、儲備及觀察版本。"
        ),
        "special_paper_not_found": "找不到所選特殊選票觀察或修訂版本，請重新整理後再選擇。",
        "stock_snapshot_incomplete": (
            "請選擇所有櫃台均已申報結餘的 P(12) 版本。尚未申報的結餘不可當作零。"
        ),
        "stock_snapshot_basis_stale": (
            "所選 P(12) 基礎已有變更，或其時間晚於本次觀察。請核對接收、派發及退回記錄，"
            "儲存目前有效且完整的 P(12) 結餘，再選擇不晚於本次觀察時間的版本。"
        ),
        "special_received_quantity": "接收選票總數",
        "special_ordinary_issued_quantity": "庫存推算普通發票數量",
        "special_replacement_issued_quantity": "補發選票數量",
        "special_spoilt_original_quantity": "已收回並註銷的損壞原票（與補發配對，不重複扣減）",
        "special_tendered_issued_quantity": "重複選票發出數量",
        "special_retrieved_refused_quantity": "已收回未用選票：選民拒絕接受",
        "special_retrieved_found_quantity": "已收回未用選票：在站內發現",
        "special_retrieved_held_quantity": "已收回未用選票：保留待選民返回",
        "special_retrieved_unused_quantity": "已收回未用選票合計",
        "special_ordinary_unissued_quantity": "從未發出普通選票餘量",
        "special_replacement_unissued_quantity": "未使用補發選票儲備",
        "special_tendered_unissued_quantity": "未使用重複選票儲備",
        "special_never_issued_quantity": "從未發出選票合計",
        "special_estimated_box_papers_quantity": "庫存推算票箱選票數量",
    },
    "sc": {
        "special_sources_changed": (
            "接收库存已在您编辑期间改变。已保留您的数量及所选依据。"
            "请核对来源变更；如需载入当前系列，请选择新增观察并明确舍弃此草稿。"
        ),
        "special_title": "补发、重复及未用选票核算",
        "special_intro": (
            "按每个已接收的选票系列记录累计数量。补发选票与已收回并注销的损坏原票配对，"
            "不重复扣减；重复选票不增加普通投票人数。已收回未用选票与从未发出库存分开核算。"
            "保存本记录不会改动已提供的投票人数。"
        ),
        "special_records": "已保存的特殊选票观察",
        "special_empty": "本站尚未保存特殊选票观察；尚未记录并不表示零。",
        "special_select": "选择已保存的特殊选票观察",
        "special_new": "新增特殊选票观察",
        "special_observation": "特殊选票数量观察",
        "special_event_time": "原始观察时间（香港时间 YYYY-MM-DD HH:mm，可输入秒及微秒）",
        "special_basis": "P(12) 结余观察依据",
        "special_basis_hint": (
            "选择不晚于本次观察时间、当前有效且所有柜台已申报的 P(12) 版本。"
            "核算会保留该版本及本次适用的接收／储备依据。"
        ),
        "special_choose_basis": "选择当前完整的 P(12) 版本",
        "special_series": "已接收的选票系列",
        "special_count_hint": (
            "为每个已接收系列填写截至原始观察时间的六项累计数量。空白表示尚未填报；"
            "零须明确输入。可用“全部填入零”记录已确认的零数量。"
        ),
        "special_zero_all": "全部填入零",
        "special_save": "保存特殊选票观察",
        "special_edit": "建立有原因的修订",
        "special_history": "特殊选票观察修订历史",
        "special_saved_totals": "所选已保存版本的数量",
        "special_historical": "此为历史版本，仅供查看。请重新载入当前版本后才修订。",
        "special_basis_stale": (
            "所选版本的原有数字及来源依据仍保留。相关库存或 P(12) 依据已有修订；"
            "请核对当前有效的结余后，再保存新的观察或修订。"
        ),
        "special_report": "所选特殊选票核算版本报表",
        "special_report_hint": (
            "预览及导出保留所选已保存版本的数量、接收及 P(12) 来源依据，包括历史版本。"
            "未保存内容不会纳入；报表标签使用当前所选语言。票箱选票数量属于库存估计。"
        ),
        "special_paper_validation": (
            "请核对原始香港时间、当前完整的 P(12) 版本及所有已接收系列。"
            "每项数量须填非负整数；修订须填写原因。"
        ),
        "special_paper_saved": "特殊选票观察已保存至中央服务器。",
        "unsaved_special_paper_changes": (
            "特殊选票表格有未保存内容。保存或明确舍弃后，才会切换所审阅的观察、版本或来源依据。"
        ),
        "special_paper_newer_revision": (
            "服务器已有较新版本；您审阅的版本及未保存数量仍保留。请比较后再重新载入。"
        ),
        "special_paper_bounds": (
            "填报数量超出适用的已接收储备或普通已发出选票依据。"
            "请核对所选 P(12) 版本、系列及各项累计数量。"
        ),
        "replacement_spoilt_mismatch": (
            "补发选票数量须与已收回并注销的损坏原票数量配对一致。请核对两项数量。"
        ),
        "special_paper_series_incomplete": (
            "请按完全匹配的名称填报所有已接收选票系列，每个系列只填一次。"
        ),
        "special_paper_issuance_regression": (
            "补发或重复选票的累计发出数量与其他已保存观察不一致。"
            "请按原始时间核对较早、同时及较后的观察；累计发出数量不可随时间倒退。"
        ),
        "special_paper_stock_conflict": (
            "此变更与已保存特殊选票观察所核算的库存有冲突。请核对相关接收记录、储备及观察版本。"
        ),
        "special_paper_not_found": "找不到所选特殊选票观察或修订版本，请刷新后再选择。",
        "stock_snapshot_incomplete": (
            "请选择所有柜台均已申报结余的 P(12) 版本。尚未申报的结余不可当作零。"
        ),
        "stock_snapshot_basis_stale": (
            "所选 P(12) 依据已有变更，或其时间晚于本次观察。请核对接收、派发及退回记录，"
            "保存当前有效且完整的 P(12) 结余，再选择不晚于本次观察时间的版本。"
        ),
        "special_received_quantity": "接收选票总数",
        "special_ordinary_issued_quantity": "库存推算普通发票数量",
        "special_replacement_issued_quantity": "补发选票数量",
        "special_spoilt_original_quantity": "已收回并注销的损坏原票（与补发配对，不重复扣减）",
        "special_tendered_issued_quantity": "重复选票发出数量",
        "special_retrieved_refused_quantity": "已收回未用选票：选民拒绝接受",
        "special_retrieved_found_quantity": "已收回未用选票：在站内发现",
        "special_retrieved_held_quantity": "已收回未用选票：保留待选民返回",
        "special_retrieved_unused_quantity": "已收回未用选票合计",
        "special_ordinary_unissued_quantity": "从未发出普通选票余量",
        "special_replacement_unissued_quantity": "未使用补发选票储备",
        "special_tendered_unissued_quantity": "未使用重复选票储备",
        "special_never_issued_quantity": "从未发出选票合计",
        "special_estimated_box_papers_quantity": "库存推算票箱选票数量",
    },
    "en": {
        "special_sources_changed": (
            "Received stock changed while you were editing. Your counts and selected basis "
            "are retained. Compare the source changes; to reload current series, choose New "
            "observation and explicitly discard this draft."
        ),
        "special_title": "Special ballot stock accounting",
        "special_intro": (
            "Record cumulative special-paper quantities for each received ballot series. "
            "Replacements pair with cancelled spoilt originals and are not deducted twice. "
            "Tendered papers do not add ordinary voters. Retrieved-unused papers remain separate "
            "from never-issued stock. Saving does not change supplied turnout."
        ),
        "special_records": "Saved special-paper observations",
        "special_empty": (
            "No special-paper observation is saved at this station. Missing is not zero."
        ),
        "special_select": "Choose a saved special-paper observation",
        "special_new": "New special-paper observation",
        "special_observation": "Special-paper count observation",
        "special_event_time": (
            "Original observation time (HKT YYYY-MM-DD HH:mm; optional seconds and microseconds)"
        ),
        "special_basis": "P(12) balance observation basis",
        "special_basis_hint": (
            "Choose a current, complete P(12) revision at or before this observation time. "
            "The accounting retains that revision and the applicable receipt/reserve basis."
        ),
        "special_choose_basis": "Choose a current, complete P(12) revision",
        "special_series": "Received ballot series",
        "special_count_hint": (
            "Enter all six cumulative category counts for every received series as of the "
            "original observation time. Blank means unreported; enter zero explicitly. "
            "Use Set all counts to zero to record confirmed zeroes."
        ),
        "special_zero_all": "Set all counts to zero",
        "special_save": "Save special-paper observation",
        "special_edit": "Prepare a reasoned amendment",
        "special_history": "Special-paper observation revision history",
        "special_saved_totals": "Quantities in the selected saved revision",
        "special_historical": (
            "This historical revision is read-only. Reload the current revision before amending."
        ),
        "special_basis_stale": (
            "Saved figures and their original basis are retained. Related stock or P(12) "
            "sources have changed. Review a current valid balance before saving another "
            "observation or amendment."
        ),
        "special_report": "Selected special-paper accounting statement",
        "special_report_hint": (
            "Preview and export retain the selected saved quantities and original receipt/P(12) "
            "basis, including historical revisions. Unsaved input is excluded. Report labels "
            "use the selected language. Box-paper quantities are stock-derived estimates."
        ),
        "special_paper_validation": (
            "Check the original HKT time, a current complete P(12) revision and all received "
            "series. Enter every quantity as a nonnegative whole number. "
            "Amendments require a reason."
        ),
        "special_paper_saved": "The special-paper observation was saved to the central server.",
        "unsaved_special_paper_changes": (
            "This special-paper form has unsaved input. Save it or explicitly discard it "
            "before changing the reviewed observation, revision or source basis."
        ),
        "special_paper_newer_revision": (
            "A newer server revision is available. Your reviewed revision and unsaved counts "
            "are retained. Compare them before reloading."
        ),
        "special_paper_bounds": (
            "Reported quantities exceed the applicable received reserves or ordinary "
            "issued-paper basis. Check the selected P(12) revision, series and cumulative counts."
        ),
        "replacement_spoilt_mismatch": (
            "Replacement issues must match the surrendered/cancelled spoilt originals "
            "paired with them. Check both quantities."
        ),
        "special_paper_series_incomplete": (
            "Report every received ballot series once, using its exact name."
        ),
        "special_paper_issuance_regression": (
            "Cumulative replacement or tendered issues conflict with another saved observation. "
            "Compare the original times and counts in earlier, same-time and later observations; "
            "cumulative issues cannot decrease over time."
        ),
        "special_paper_stock_conflict": (
            "This change conflicts with stock already accounted for in saved special-paper "
            "observations. Check the affected receipt, reserve and observation revisions."
        ),
        "special_paper_not_found": (
            "The selected special-paper observation or revision was not found. "
            "Refresh and select it again."
        ),
        "stock_snapshot_incomplete": (
            "Choose a P(12) revision with every counter balance reported. "
            "An unreported balance cannot be treated as zero."
        ),
        "stock_snapshot_basis_stale": (
            "The selected P(12) basis changed or is later than this observation. Review receipts, "
            "allocations and returns, save a current complete P(12) balance, then choose a "
            "revision at or before this observation time."
        ),
        "special_received_quantity": "Total papers received",
        "special_ordinary_issued_quantity": "Stock-derived ordinary issuance",
        "special_replacement_issued_quantity": "Replacement papers issued",
        "special_spoilt_original_quantity": (
            "Surrendered/cancelled spoilt originals (paired with replacements; not deducted twice)"
        ),
        "special_tendered_issued_quantity": "Tendered papers issued",
        "special_retrieved_refused_quantity": "Retrieved unused papers refused by electors",
        "special_retrieved_found_quantity": "Retrieved unused papers found within station",
        "special_retrieved_held_quantity": "Retrieved unused papers held pending elector's return",
        "special_retrieved_unused_quantity": "Retrieved-unused papers total",
        "special_ordinary_unissued_quantity": "Never-issued ordinary papers remaining",
        "special_replacement_unissued_quantity": "Unused replacement reserve",
        "special_tendered_unissued_quantity": "Unused tendered reserve",
        "special_never_issued_quantity": "Never-issued stock total",
        "special_estimated_box_papers_quantity": "Estimated box papers from stock",
    },
}
