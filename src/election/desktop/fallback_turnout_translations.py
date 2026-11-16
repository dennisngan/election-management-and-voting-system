"""Source-selection and frozen coverage labels for the Material desktop."""

FALLBACK_TURNOUT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "turnout_title": "時段投票人數",
        "turnout_intro": (
            "選擇正常外部數字、已確認後備庫存來源或恢復核對來源。每個已儲存版本保留來源與"
            "涵蓋時段，再提交主管確認。"
        ),
        "turnout_source_mode": "投票人數來源模式",
        "turnout_mode_normal": "正常外部數字",
        "turnout_mode_fallback": "後備普通庫存推算",
        "turnout_mode_recovery": "恢復外部數字核對",
        "turnout_fallback_source_hint": (
            "選擇已確認的啟用版本及本時段末完整版本。人數由普通發票變化推算；"
            "本時段及累計外部人數須留空。"
        ),
        "turnout_recovery_source_hint": (
            "選擇已確認的恢復版本。恢復在時段末時，人數可留空；若恢復早於時段末，"
            "請提供涵蓋其後正常模式的時段人數或期末累計。"
        ),
        "turnout_activation_id": "已確認啟用記錄編號",
        "turnout_activation_revision": "已確認啟用版本",
        "turnout_snapshot_id": "時段末記錄編號",
        "turnout_snapshot_revision": "時段末版本",
        "turnout_recovery_id": "已確認恢復記錄編號",
        "turnout_recovery_revision": "已確認恢復版本",
        "turnout_frozen_source_basis": "已儲存的來源及涵蓋時段",
        "turnout_activation_reference": "啟用來源",
        "turnout_activation_baseline": "啟用時已確認累計人數",
        "turnout_ordinary_delta": "啟用後普通發票增量",
        "turnout_stock_cumulative": "庫存推算累計人數",
        "turnout_recovered_cumulative": "恢復後外部累計人數",
        "turnout_reconciliation_difference": "外部恢復數字與庫存推算差額",
        "turnout_coverage_hourly": "涵蓋人數",
        "turnout_interval_normal": "正常外部數字",
        "turnout_interval_fallback": "後備普通庫存推算",
        "turnout_interval_reconciled": "已核對恢復數字",
        "fallback_source_required": "此時段涵蓋模式變更，請選擇相符的已確認來源版本。",
    },
    "sc": {
        "turnout_title": "时段投票人数",
        "turnout_intro": (
            "选择正常外部数字、已确认后备库存来源或恢复核对来源。每个已保存版本保留来源与"
            "涵盖时段，再提交主管确认。"
        ),
        "turnout_source_mode": "投票人数来源模式",
        "turnout_mode_normal": "正常外部数字",
        "turnout_mode_fallback": "后备普通库存推算",
        "turnout_mode_recovery": "恢复外部数字核对",
        "turnout_fallback_source_hint": (
            "选择已确认的启用版本及本时段末完整版本。人数由普通发票变化推算；"
            "本时段及累计外部人数须留空。"
        ),
        "turnout_recovery_source_hint": (
            "选择已确认的恢复版本。恢复在时段末时，人数可留空；若恢复早于时段末，"
            "请提供涵盖其后正常模式的时段人数或期末累计。"
        ),
        "turnout_activation_id": "已确认启用记录编号",
        "turnout_activation_revision": "已确认启用版本",
        "turnout_snapshot_id": "时段末记录编号",
        "turnout_snapshot_revision": "时段末版本",
        "turnout_recovery_id": "已确认恢复记录编号",
        "turnout_recovery_revision": "已确认恢复版本",
        "turnout_frozen_source_basis": "已保存的来源及涵盖时段",
        "turnout_activation_reference": "启用来源",
        "turnout_activation_baseline": "启用时已确认累计人数",
        "turnout_ordinary_delta": "启用后普通发票增量",
        "turnout_stock_cumulative": "库存推算累计人数",
        "turnout_recovered_cumulative": "恢复后外部累计人数",
        "turnout_reconciliation_difference": "外部恢复数字与库存推算差额",
        "turnout_coverage_hourly": "涵盖人数",
        "turnout_interval_normal": "正常外部数字",
        "turnout_interval_fallback": "后备普通库存推算",
        "turnout_interval_reconciled": "已核对恢复数字",
        "fallback_source_required": "此时段涵盖模式变更，请选择相符的已确认来源版本。",
    },
    "en": {
        "turnout_title": "Period turnout",
        "turnout_intro": (
            "Select supplied figures, confirmed ordinary-stock fallback sources, or a confirmed "
            "recovery. Saved revisions retain their sources and interval coverage for "
            "Supervisor review."
        ),
        "turnout_source_mode": "Turnout source mode",
        "turnout_mode_normal": "Normal supplied figures",
        "turnout_mode_fallback": "Fallback ordinary stock",
        "turnout_mode_recovery": "Reconciled external recovery",
        "turnout_fallback_source_hint": (
            "Select the confirmed activation revision and complete period-end revision. "
            "Turnout uses ordinary issuance changes; leave supplied period and cumulative "
            "counts blank."
        ),
        "turnout_recovery_source_hint": (
            "Select the confirmed recovery revision. Counts may stay blank for recovery at "
            "period end. For an earlier recovery, supply the period or final cumulative count "
            "covering later normal mode."
        ),
        "turnout_activation_id": "Confirmed activation record ID",
        "turnout_activation_revision": "Confirmed activation revision",
        "turnout_snapshot_id": "Period-end record ID",
        "turnout_snapshot_revision": "Period-end revision",
        "turnout_recovery_id": "Confirmed recovery record ID",
        "turnout_recovery_revision": "Confirmed recovery revision",
        "turnout_frozen_source_basis": "Saved sources and interval coverage",
        "turnout_activation_reference": "Activation source",
        "turnout_activation_baseline": "Confirmed cumulative turnout at activation",
        "turnout_ordinary_delta": "Ordinary issuance since activation",
        "turnout_stock_cumulative": "Stock-derived cumulative turnout",
        "turnout_recovered_cumulative": "Recovered external cumulative turnout",
        "turnout_reconciliation_difference": "Recovered minus stock-derived difference",
        "turnout_coverage_hourly": "Covered turnout",
        "turnout_interval_normal": "Normal supplied figures",
        "turnout_interval_fallback": "Fallback ordinary stock",
        "turnout_interval_reconciled": "Reconciled recovery",
        "fallback_source_required": (
            "This period covers a mode change. Select the matching confirmed source revision."
        ),
    },
}
