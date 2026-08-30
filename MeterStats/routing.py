from __future__ import annotations
import inspect
import traceback
from urllib.parse import parse_qs, urlparse
from utils import send_json

from handlers.readings import (
    handle_get_readings, handle_post_readings, handle_put_readings, handle_delete_readings,
)
from handlers.charges import (
    handle_get_charges, handle_post_charges, handle_put_charges, handle_delete_charges,
)
from handlers.items import (
    handle_get_items, handle_post_items, handle_put_items, handle_delete_items,
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
)
from handlers.backup import handle_get_data_files, handle_post_backup, handle_post_restore, handle_post_upload
from handlers.admin import (
    # Auth
    handle_post_login, handle_get_logout, handle_get_me,
    # Admin CRUD
    handle_get_users, handle_post_users, handle_put_users, handle_delete_users,
    handle_get_meter_settings, handle_put_meter_settings,
    handle_get_roles,
    handle_get_backup_status, handle_put_auto_backup,
    handle_put_backup_retention,
    handle_get_backup_config, handle_put_backup_config,
    handle_get_backup_download, handle_get_backup_delete,
    handle_post_restore_upload,
    handle_get_dir_listing,
)

_GET_ROUTES = {
    "/api/health": handle_get_health,
    "/api/export": handle_get_export,
    "/api/monthly-report": handle_get_monthly_report,
    "/api/yearly-report": handle_get_yearly_report,
    "/api/monthly-utilities": handle_get_monthly_utilities,
    "/api/readings": handle_get_readings,
    "/api/charges": handle_get_charges,
    "/api/items": handle_get_items,
    "/api/purchases": handle_get_purchases,
    "/api/duty": handle_get_duty,
}

_POST_PREFIX = {
    "/api/backup": handle_post_backup,
    "/api/restore": handle_post_restore,
    "/api/upload": handle_post_upload,
    "/api/admin/restore-upload": handle_post_restore_upload,
    "/api/charges": handle_post_charges,
    "/api/readings": handle_post_readings,
    "/api/auth/login": handle_post_login,
    "/api/admin/users": handle_post_users,
    "/api/items": handle_post_items,
    "/api/purchases": handle_post_purchases,
    "/api/duty": handle_post_duty,
}

_PUT_PREFIX = {
    "/api/items": handle_put_items,
    "/api/purchases": handle_put_purchases,
    "/api/charges": handle_put_charges,
    "/api/readings": handle_put_readings,
    "/api/admin/users": handle_put_users,
    "/api/admin/meter": handle_put_meter_settings,
    "/api/admin/auto-backup": handle_put_auto_backup,
    "/api/admin/backup-retention": handle_put_backup_retention,
    "/api/admin/backup-config": handle_put_backup_config,
    "/api/duty": handle_put_duty,
}

_DELETE_PREFIX = {
    "/api/readings": handle_delete_readings,
    "/api/charges": handle_delete_charges,
    "/api/items": handle_delete_items,
    "/api/purchases": handle_delete_purchases,
    "/api/admin/users": handle_delete_users,
    "/api/duty": handle_delete_duty,
}

# 新增 admin 路由
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
    "/api/admin/data-files": handle_get_data_files,
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

def route(method: str, handler, path: str):
    path_clean = path.split("?", 1)[0]

    if method == "OPTIONS":
        handler.send_response(204)
        from utils import CORS
        for k, v in CORS.items():
            handler.send_header(k, v)
        handler.end_headers()
        return

    if method == "GET":
        # 精确匹配: _GET_ROUTES
        if path_clean in _GET_ROUTES:
            try:
                _GET_ROUTES[path_clean](handler)
            except Exception as e:
                from storage import log
                log(f"[ERROR] GET {path_clean}: {e}")
                log(traceback.format_exc())
                send_json(handler, 500, {"error": "服务器内部错误"})
            return
        # 精确匹配: admin 路由
        if path_clean in _GET_ADMIN:
            try:
                _GET_ADMIN[path_clean](handler)
            except Exception as e:
                from storage import log
                log(f"[ERROR] GET {path_clean}: {e}")
                log(traceback.format_exc())
                send_json(handler, 500, {"error": "服务器内部错误"})
            return
        # 前缀匹配: _GET_ROUTES (for path like /api/readings/monthly)
        fn = _match_prefix(_GET_ROUTES, path_clean)
        if fn:
            try:
                _call_handler(fn, handler, path_clean)
            except Exception as e:
                from storage import log
                log(f"[ERROR] GET {path_clean}: {e}")
                log(traceback.format_exc())
                send_json(handler, 500, {"error": "服务器内部错误"})
            return

    if method == "POST":
        handler_fn = _match_prefix(_POST_PREFIX, path_clean)
        if handler_fn:
            try:
                handler_fn(handler)
            except Exception as e:
                from storage import log
                log(f"[ERROR] POST {path_clean}: {e}")
                log(traceback.format_exc())
                send_json(handler, 500, {"error": "服务器内部错误"})
            return

    if method == "PUT":
        handler_fn = _match_prefix(_PUT_PREFIX, path_clean)
        if not handler_fn:
            handler_fn = handle_put_purchases_stock if (
                path_clean.startswith("/api/purchases/") and path_clean.endswith("/stock")
            ) else None
        if handler_fn:
            try:
                _call_handler(handler_fn, handler, path_clean)
            except Exception as e:
                from storage import log
                log(f"[ERROR] PUT {path_clean}: {e}")
                log(traceback.format_exc())
                send_json(handler, 500, {"error": "服务器内部错误"})
            return

    if method == "DELETE":
        handler_fn = _match_prefix(_DELETE_PREFIX, path_clean)
        if handler_fn:
            try:
                _call_handler(handler_fn, handler, path_clean)
            except Exception as e:
                from storage import log
                log(f"[ERROR] DELETE {path_clean}: {e}")
                log(traceback.format_exc())
                send_json(handler, 500, {"error": "服务器内部错误"})
            return

    send_json(handler, 404, {"error": "未知 API 路径"})
