"""Administrator server-backup page labels in the supported desktop languages."""

SERVER_BACKUP_TRANSLATIONS: dict[str, dict[str, str]] = {
    "tc": {
        "server_backups_navigation": "伺服器備份",
        "server_backups_title": "伺服器備份",
        "server_backups_intro": (
            "只在中央伺服器建立及查看備份。備份含有敏感操作記錄，不會下載到此桌面。"
        ),
        "server_backups_refresh": "重新整理記錄",
        "server_backup_create_section": "建立伺服器備份",
        "server_backup_create_hint": (
            "伺服器會以一致的資料庫快照建立備份，並保留相關記錄與要求收據。"
        ),
        "server_backup_create": "建立伺服器備份",
        "server_backup_creating": "正在提出備份要求…",
        "server_backup_privacy_hint": "SQL 檔案及連線資料只留在伺服器，不會提供下載。",
        "server_backup_outcome_uncertain": "尚未確認要求結果",
        "server_backup_uncertain_hint": (
            "要求可能已在伺服器記錄。請檢查要求結果；如重試，會沿用同一要求編號。"
        ),
        "server_backup_pending": "要求已記錄；備份結果尚未確認。",
        "server_backup_check_outcome": "檢查要求結果",
        "server_backup_retry_request": "以同一要求編號重試",
        "server_backup_running_unconfirmed": "要求已記錄；完成結果尚未確認。",
        "server_backup_status_running": "要求已記錄；結果尚未確認",
        "server_backup_status_succeeded": "已完成",
        "server_backup_status_failed": "失敗",
        "server_backup_succeeded": "備份已完成。",
        "server_backup_failed": "備份失敗；請查看安全錯誤代碼。",
        "server_backup_empty": "尚未有伺服器備份記錄。",
        "server_backup_history": "備份記錄",
        "server_backup_request_id": "要求編號",
        "server_backup_id": "備份識別碼",
        "server_backup_requested_at": "要求時間",
        "server_backup_completed_at": "完成時間",
        "server_backup_cutoff_start": "快照開始時間",
        "server_backup_cutoff_end": "快照結束時間",
        "server_backup_size_bytes": "檔案大小（位元組）",
        "server_backup_sha256": "SHA-256",
        "server_backup_error_code": "安全錯誤代碼",
        "server_backup_not_recorded": "尚未記錄",
        "server_backup_administrator_required": "只有管理員可查看或建立伺服器備份。",
        "backup_list_not_open": "請先開啟備份記錄，再提出要求。",
    },
    "sc": {
        "server_backups_navigation": "服务器备份",
        "server_backups_title": "服务器备份",
        "server_backups_intro": (
            "只在中央服务器创建和查看备份。备份含有敏感操作记录，不会下载到此桌面。"
        ),
        "server_backups_refresh": "刷新记录",
        "server_backup_create_section": "创建服务器备份",
        "server_backup_create_hint": (
            "服务器会以一致的数据库快照创建备份，并保留相关记录与请求回执。"
        ),
        "server_backup_create": "创建服务器备份",
        "server_backup_creating": "正在提交备份请求…",
        "server_backup_privacy_hint": "SQL 文件和连接资料只留在服务器，不会提供下载。",
        "server_backup_outcome_uncertain": "尚未确认请求结果",
        "server_backup_uncertain_hint": (
            "请求可能已在服务器记录。请检查请求结果；如重试，会沿用同一请求编号。"
        ),
        "server_backup_pending": "请求已记录；备份结果尚未确认。",
        "server_backup_check_outcome": "检查请求结果",
        "server_backup_retry_request": "使用同一请求编号重试",
        "server_backup_running_unconfirmed": "请求已记录；完成结果尚未确认。",
        "server_backup_status_running": "请求已记录；结果尚未确认",
        "server_backup_status_succeeded": "已完成",
        "server_backup_status_failed": "失败",
        "server_backup_succeeded": "备份已完成。",
        "server_backup_failed": "备份失败；请查看安全错误代码。",
        "server_backup_empty": "尚无服务器备份记录。",
        "server_backup_history": "备份记录",
        "server_backup_request_id": "请求编号",
        "server_backup_id": "备份标识码",
        "server_backup_requested_at": "请求时间",
        "server_backup_completed_at": "完成时间",
        "server_backup_cutoff_start": "快照开始时间",
        "server_backup_cutoff_end": "快照结束时间",
        "server_backup_size_bytes": "文件大小（字节）",
        "server_backup_sha256": "SHA-256",
        "server_backup_error_code": "安全错误代码",
        "server_backup_not_recorded": "尚未记录",
        "server_backup_administrator_required": "只有管理员可查看或创建服务器备份。",
        "backup_list_not_open": "请先打开备份记录，再提交请求。",
    },
    "en": {
        "server_backups_navigation": "Server backups",
        "server_backups_title": "Server backups",
        "server_backups_intro": (
            "Create and review backups on the central server. Backups contain sensitive "
            "operational records and are not downloaded to this desktop."
        ),
        "server_backups_refresh": "Refresh records",
        "server_backup_create_section": "Create a server backup",
        "server_backup_create_hint": (
            "The server captures a consistent database snapshot and retains related records "
            "and request receipts."
        ),
        "server_backup_create": "Create backup",
        "server_backup_creating": "Requesting backup…",
        "server_backup_privacy_hint": (
            "SQL files and connection details stay on the server and are not downloadable."
        ),
        "server_backup_outcome_uncertain": "Request outcome not confirmed",
        "server_backup_uncertain_hint": (
            "The server may have recorded this request. Check its outcome; a retry reuses "
            "the same request ID."
        ),
        "server_backup_pending": "Request recorded; the backup outcome is not confirmed yet.",
        "server_backup_check_outcome": "Check request outcome",
        "server_backup_retry_request": "Retry the same request ID",
        "server_backup_running_unconfirmed": "Request recorded; completion is not confirmed yet.",
        "server_backup_status_running": "Request recorded; outcome not confirmed",
        "server_backup_status_succeeded": "Completed",
        "server_backup_status_failed": "Failed",
        "server_backup_succeeded": "The backup completed.",
        "server_backup_failed": "The backup failed; see the safe error code.",
        "server_backup_empty": "No server backups have been recorded.",
        "server_backup_history": "Backup records",
        "server_backup_request_id": "Request ID",
        "server_backup_id": "Backup ID",
        "server_backup_requested_at": "Requested at",
        "server_backup_completed_at": "Completed at",
        "server_backup_cutoff_start": "Snapshot start",
        "server_backup_cutoff_end": "Snapshot end",
        "server_backup_size_bytes": "File size (bytes)",
        "server_backup_sha256": "SHA-256",
        "server_backup_error_code": "Safe error code",
        "server_backup_not_recorded": "Not recorded",
        "server_backup_administrator_required": (
            "Only Administrators can view or request server backups."
        ),
        "backup_list_not_open": ("Open the backup records before submitting a request."),
    },
}
