from __future__ import annotations
import inspect
import traceback
from urllib.parse import parse_qs, urlparse
from utils import send_json

from handlers.readings import (
    handle_get_readings, handle_post_readings, handle_put_readings, handle_delete_readings,
)
from handlers.readings_water import (
    handle_get_readings_water, handle_get_readings_water_monthly,
    handle_post_readings_water, handle_put_readings_water, handle_delete_readings_water,
)
from handlers.charges import (
    handle_get_charges, handle_post_charges, handle_put_charges, handle_delete_charges,
)
from handlers.items import (
    handle_get_items, handle_post_items, handle_put_items, handle_delete_items,
    handle_put_items_lend, handle_put_items_return,
)
from handlers.purchases import (
    handle_get_purchases, handle_post_purchases, handle_put_purchases, handle_put_purchases_stock, handle_delete_purchases,
)
from handlers.duty import (
    handle_get_duty, handle_post_duty, handle_put_duty, handle_delete_duty,
)
from handlers.reports import (
    handle_get_health, handle_get_export, handle_get_monthly_report,
    handle_get_yearly_report, handle_get_monthly_utilities,
    handle_get_snapshot, handle_get_report_cache,
)
from handlers.dataimport import handle_post_import
from handlers.backup import handle_get_data_files, handle_post_backup, handle_post_restore, handle_post_upload
from handlers.admin import (
    # Auth
    handle_post_login, handle_get_logout, handle_get_me, handle_get_sessions,
    # Admin CRUD
    handle_get_users, handle_post_users, handle_put_users, handle_delete_users,
    handle_get_meter_settings, handle_put_meter_settings, handle_get_meters_public,
    handle_get_roles,
    handle_get_backup_status, handle_put_auto_backup,
    handle_put_backup_retention,
    handle_get_backup_config, handle_put_backup_config,
    handle_get_backup_download, handle_get_backup_delete,
    handle_post_backup_download, handle_post_backup_delete,
    handle_post_restore_upload,
    handle_get_dir_listing, handle_get_audit_log,
    handle_get_migrate_status, handle_post_migrate_water,
)

_GET_ROUTES = {
    "/api/health": handle_get_health,
    "/api/snapshot": handle_get_snapshot,
    "/api/export": handle_get_export,
    "/api/monthly-report": handle_get_monthly_report,
    "/api/yearly-report": handle_get_yearly_report,
    "/api/monthly-utilities": handle_get_monthly_utilities,
    "/api/readings": handle_get_readings,
    "/api/readings-water": handle_get_readings_water,
    "/api/charges": handle_get_charges,
    "/api/items": handle_get_items,
    "/api/purchases": handle_get_purchases,
    "/api/meters": handle_get_meters_public,
    "/api/duty": handle_get_duty,
}

_POST_PREFIX = {
    "/api/backup": handle_post_backup,
    "/api/restore": handle_post_restore,
    "/api/upload": handle_post_upload,
    "/api/admin/restore-upload": handle_post_restore_upload,
    "/api/admin/backup-download": handle_post_backup_download,
    "/api/admin/backup-delete": handle_post_backup_delete,
    "/api/admin/migrate-water": handle_post_migrate_water,
    "/api/charges": handle_post_charges,
    "/api/readings": handle_post_readings,
    "/api/readings-water": handle_post_readings_water,
    "/api/auth/login": handle_post_login,
    "/api/admin/users": handle_post_users,
    "/api/items": handle_post_items,
    "/api/purchases": handle_post_purchases,
    "/api/duty": handle_post_duty,
    "/api/import": handle_post_import,
}

_PUT_PREFIX = {
    "/api/items": handle_put_items,
    "/api/purchases": handle_put_purchases,
    "/api/charges": handle_put_charges,
    "/api/readings": handle_put_readings,
    "/api/readings-water": handle_put_readings_water,
    "/api/admin/users": handle_put_users,
    "/api/admin/meter": handle_put_meter_settings,
    "/api/admin/auto-backup": handle_put_auto_backup,
    "/api/admin/backup-retention": handle_put_backup_retention,
    "/api/admin/backup-config": handle_put_backup_config,
    "/api/duty": handle_put_duty,
}

_DELETE_PREFIX = {
    "/api/readings": handle_delete_readings,
    "/api/readings-water": handle_delete_readings_water,
    "/api/charges": handle_delete_charges,
    "/api/items": handle_delete_items,
    "/api/purchases": handle_delete_purchases,
    "/api/admin/users": handle_delete_users,
    "/api/duty": handle_delete_duty,
}

# Admin 路由（精确匹配）
_GET_ADMIN = {
    "/api/auth/logout": handle_get_logout,
    "/api/auth/me": handle_get_me,
    "/api/admin/users": handle_get_users,
    "/api/admin/meter": handle_get_meter_settings,
    "/api/admin/roles": handle_get_roles,
    "/api/admin/backup-status": handle_get_backup_status,
    "/api/admin/backup-download": handle_get_backup_download,
    "/api/admin/backup-delete": handle_get_backup_delete,
    "/api/admin/backup-config": handle_get_backup_config,
    "/api/admin/dir-listing": handle_get_dir_listing,
    "/api/admin/audit": handle_get_audit_log,
    "/api/admin/migrate-water": handle_get_migrate_status,
    "/api/admin/data-files": handle_get_data_files,
    "/api/admin/sessions": handle_get_sessions,
    "/api/admin/report-cache": handle_get_report_cache,
}

def _match_prefix(paths, path_clean):
    for prefix, handler_fn in paths.items():
        if path_clean.startswith(prefix + "/") or path_clean == prefix:
            return handler_fn
    return None

def _call_handler(fn, handler, path_clean):
    sig = inspect.signature(fn)
    if "path_clean" in sig.parameters:
        return fn(handler, path_clean)
    return fn(handler)


def _route(method: str, handler, path: str) -> bool:
    """分发请求到 handler。返回 True 表示已处理，False 表示 404。

    错误处理统一由 _dispatch_fn 包装，消除重复的 try/except。"""

    def _dispatch_fn(fn, label: str, *args, **kwargs):
        """调用 handler 并统一错误处理。"""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            from storage import log
            log(f"[ERROR] {label} {handler.path}: {e}")
            log(traceback.format_exc())
            send_json(handler, 500, {"error": "服务器内部错误"})

    path_clean = path.split("?", 1)[0]

    if method == "OPTIONS":
        handler.send_response(204)
        from utils import CORS
        for k, v in CORS.items():
            handler.send_header(k, v)
        handler.end_headers()
        return True

    # GET: 精确匹配 + 前缀匹配
    if method == "GET":
        # 精确匹配: _GET_ROUTES
        if path_clean in _GET_ROUTES:
            _dispatch_fn(_GET_ROUTES[path_clean], "GET", handler)
            return True
        # 精确匹配: admin 路由
        if path_clean in _GET_ADMIN:
            _dispatch_fn(_GET_ADMIN[path_clean], "GET", handler)
            return True
        # 前缀匹配: _GET_ROUTES (for path like /api/readings/monthly)
        fn = _match_prefix(_GET_ROUTES, path_clean)
        if fn:
            _dispatch_fn(_call_handler, "GET", fn, handler, path_clean)
            return True

    # POST
    if method == "POST":
        handler_fn = _match_prefix(_POST_PREFIX, path_clean)
        if handler_fn:
            _dispatch_fn(handler_fn, "POST", handler)
            return True

    # PUT: 优先匹配特殊路径
    if method == "PUT":
        if path_clean.startswith("/api/purchases/") and path_clean.endswith("/stock"):
            _dispatch_fn(handle_put_purchases_stock, "PUT", handler, path_clean)
            return True
        elif path_clean.startswith("/api/items/") and path_clean.endswith("/lend"):
            _dispatch_fn(handle_put_items_lend, "PUT", handler, path_clean)
            return True
        elif path_clean.startswith("/api/items/") and path_clean.endswith("/return"):
            _dispatch_fn(handle_put_items_return, "PUT", handler, path_clean)
            return True
        else:
            handler_fn = _match_prefix(_PUT_PREFIX, path_clean)
            if handler_fn:
                _dispatch_fn(_call_handler, "PUT", handler_fn, handler, path_clean)
                return True

    # DELETE
    if method == "DELETE":
        handler_fn = _match_prefix(_DELETE_PREFIX, path_clean)
        if handler_fn:
            _dispatch_fn(_call_handler, "DELETE", handler_fn, handler, path_clean)
            return True

    return False

# Public API: tests import `route`, app_handler imports `route`
route = _route
