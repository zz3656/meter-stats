"""后台管理 API 门面模块 — 已拆分。

⚠️ 此模块已拆分为:
- modules/system/auth_handler.py         — 登录 / 会话 / 速率限制
- modules/system/users_handler.py        — 用户 CRUD + 电表设置 / 角色查询
- modules/system/settings_handler.py     — 系统设置读写
- modules/system/permissions_handler.py  — 三级权限
- modules/system/admin_tools_handler.py  — 目录浏览 / 审计日志 / 水电数据迁移
- modules/backup/admin_handler.py        — 备份 HTTP API(列表/下载/删除/配置/上传恢复)

为保持向后兼容,本文件 re-export 所有原 handler。
新代码应直接从上述子模块导入。
"""
from __future__ import annotations

# Auth
from modules.system.auth_handler import (
    handle_post_login,
    handle_get_logout,
    handle_get_me,
    handle_get_sessions,
)

# Users / meter settings / roles
from modules.system.users_handler import (
    handle_get_users,
    handle_post_users,
    handle_put_users,
    handle_delete_users,
    handle_get_meter_settings,
    handle_put_meter_settings,
    handle_get_meters_public,
    handle_get_roles,
)

# Backup HTTP API
from modules.backup.admin_handler import (
    handle_get_backup_status,
    handle_put_auto_backup,
    handle_put_backup_retention,
    handle_get_backup_config,
    handle_put_backup_config,
    handle_get_backup_download,
    handle_get_backup_delete,
    handle_post_backup_download,
    handle_post_backup_delete,
    handle_post_restore_upload,
    handle_post_sync_from_nas,
)

# Admin tools
from modules.system.admin_tools_handler import (
    handle_get_dir_listing,
    handle_get_audit_log,
    handle_get_migrate_status,
    handle_post_migrate_water,
)

# Auth 会话 API(供其他模块使用,例如 permissions.py)
from modules.system.auth_handler import (
    get_session,
    create_session,
    destroy_session,
    get_active_session_count,
    _touch_session,
    _SESSIONS,
    _SESSIONS_LOCK,
    SESSION_TIMEOUT_SECONDS,
    _last_cleanup_time,
    _cleanup_expired_sessions,
    _LOGIN_ATTEMPTS,
    _LOGIN_ATTEMPTS_LOCK,
    _LOGIN_MAX_FAILED,
    _LOGIN_WINDOW_SECONDS,
    _LOGIN_COOLDOWN_SECONDS,
    _check_login_rate_limit,
    _record_login_attempt,
)

__all__ = [
    # Auth
    "handle_post_login", "handle_get_logout", "handle_get_me", "handle_get_sessions",
    # Users / meter / roles
    "handle_get_users", "handle_post_users", "handle_put_users", "handle_delete_users",
    "handle_get_meter_settings", "handle_put_meter_settings", "handle_get_meters_public",
    "handle_get_roles",
    # Backup HTTP
    "handle_get_backup_status", "handle_put_auto_backup", "handle_put_backup_retention",
    "handle_get_backup_config", "handle_put_backup_config",
    "handle_get_backup_download", "handle_get_backup_delete",
    "handle_post_backup_download", "handle_post_backup_delete",
    "handle_post_restore_upload",
    "handle_post_sync_from_nas",
    "handle_get_proxy_nas_data",
    # Admin tools
    "handle_get_dir_listing", "handle_get_audit_log",
    "handle_get_migrate_status", "handle_post_migrate_water",
    # Auth helpers
    "get_session", "create_session", "destroy_session", "get_active_session_count",
    "_touch_session",
    # Auth 内部状态(向后兼容,供测试等使用)
    "_SESSIONS", "_SESSIONS_LOCK", "SESSION_TIMEOUT_SECONDS",
    "_last_cleanup_time", "_cleanup_expired_sessions",
    "_LOGIN_ATTEMPTS", "_LOGIN_ATTEMPTS_LOCK",
    "_LOGIN_MAX_FAILED", "_LOGIN_WINDOW_SECONDS", "_LOGIN_COOLDOWN_SECONDS",
    "_check_login_rate_limit", "_record_login_attempt",
]
