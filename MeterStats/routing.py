from __future__ import annotations
import inspect
import traceback
from urllib.parse import parse_qs, urlparse
from utils import send_json

from modules.readings import (
    handle_get_readings, handle_post_readings, handle_put_readings, handle_delete_readings,
)
from modules.utilities.handler import (
    handle_get_readings_water, handle_get_readings_water_monthly,
    handle_post_readings_water, handle_put_readings_water, handle_delete_readings_water,
)
from modules.charges import (
    handle_get_charges, handle_post_charges, handle_put_charges, handle_delete_charges,
)
from modules.items import (
    handle_get_items, handle_post_items, handle_put_items, handle_delete_items,
    handle_put_items_lend, handle_put_items_return, handle_delete_items_lend,
)
from modules.purchases import (
    handle_get_purchases, handle_post_purchases, handle_put_purchases, handle_put_purchases_stock, handle_delete_purchases,
)
from modules.duty import (
    handle_get_duty, handle_post_duty, handle_put_duty, handle_delete_duty,
    handle_post_duty_handle, handle_post_duty_image, handle_get_duty_image,
    handle_get_images_config, handle_put_images_config,
)
from modules.reports import (
    handle_get_health, handle_get_export, handle_get_monthly_report,
    handle_get_yearly_report, handle_get_monthly_utilities,
    handle_get_snapshot, handle_get_report_cache,
    handle_get_version,
)
from modules.dataimport import handle_post_import, handle_get_import_template
from modules.backup import handle_get_data_files, handle_post_backup, handle_post_restore, handle_post_upload
from modules.system.auth_handler import (
    handle_post_login, handle_get_logout, handle_get_me, handle_get_sessions,
)
from modules.system.users_handler import (
    handle_get_users, handle_post_users, handle_put_users, handle_delete_users,
)
from modules.system.admin_handler import (
    handle_get_meter_settings, handle_put_meter_settings, handle_get_meters_public,
    handle_get_roles,
)
from modules.backup.admin_handler import (
    handle_get_backup_status, handle_put_auto_backup,
    handle_put_backup_retention,
    handle_get_backup_config, handle_put_backup_config,
    handle_get_backup_download, handle_get_backup_delete,
    handle_post_backup_download, handle_post_backup_delete,
    handle_post_restore_upload,
    handle_post_sync_from_nas,
    handle_get_proxy_nas_data,
)
from modules.system.admin_tools_handler import (
    handle_get_dir_listing, handle_get_audit_log,
    handle_get_migrate_status, handle_post_migrate_water,
)

# 注：admin 模块已拆分,本表保留为兼容层。新代码推荐直接从子模块导入:
#   - modules.system.auth_handler         — 登录/会话
#   - modules.system.users_handler        — 用户 CRUD + 电表设置
#   - modules.backup.admin_handler — 备份 HTTP API
#   - modules.system.admin_tools_handler  — 辅助工具(目录/审计/迁移)

# ============ 接口级鉴权(全局强制) ============
# 仅以下三个端点允许匿名访问,其余 /api/* 一律要求有效会话:
#   /api/health     — Docker HEALTHCHECK / run.sh 启动探测 / 登录页前置健康检查
#   /api/version    — 登录页需要未登录也能显示版本号
#   /api/auth/login — 取 token 的入口本身
PUBLIC_API_PATHS = frozenset({"/api/health", "/api/version", "/api/auth/login"})

# 删除类操作允许的角色,与前端 ADMIN_DELETE_ROLES 保持一致
DELETE_ROLES = frozenset({"admin", "supervisor"})

# 用户管理仅管理员:否则任何登录用户都能新建管理员账号自我提权
ADMIN_ONLY_PREFIXES = ("/api/admin/users",)

# 管理类接口至少主管:审计日志、备份删除/恢复、NAS 同步、电价倍率与图片目录配置
# 这些不该由"只能录入抄表"的员工角色触碰,与前端 ADMIN_MANAGE_ROLES 的意图对齐。
MANAGER_ONLY_PREFIXES = (
    "/api/admin/audit",
    "/api/admin/data-files",
    "/api/admin/dir-listing",
    "/api/admin/migrate-water",
    "/api/admin/restore-upload",
    "/api/admin/sync-from-nas",
    "/api/admin/backup-delete",
    "/api/admin/meter",
    "/api/admin/images",
    "/api/admin/auto-backup",
    "/api/admin/backup-retention",
    "/api/admin/backup-config",
)
MANAGER_ROLES = frozenset({"admin", "supervisor"})

# 单元测试用 _do_api 直接跑业务逻辑时,可在 fixture 内置 False 跳过鉴权。
# 生产启动路径不读任何环境变量,这个开关在进程内,外部配不出来。
ENFORCE_AUTH = True


def _auth_gate(method: str, path_clean: str, handler) -> bool:
    """统一鉴权入口。放行返回 True;已发出 401/403 响应则返回 False。

    token 由 _get_token 依次尝试 Cookie / ?token= / Authorization 头,
    所以 <img src> 与 <a href> 这类带不了请求头的请求也能用 query 通过校验。
    """
    if not ENFORCE_AUTH or path_clean in PUBLIC_API_PATHS:
        return True

    from modules.system.permissions_handler import _get_token
    from modules.system.auth_handler import get_session, _touch_session

    token = _get_token(handler)
    sess = get_session(token) if token else None
    if not sess:
        send_json(handler, 401, {"error": "未登录或会话已过期,请重新登录"})
        return False

    _touch_session(token)  # 有活动就续期,与 check_permission 装饰器行为一致
    role = sess.get("role", "employee")

    if method == "DELETE" and role not in DELETE_ROLES:
        send_json(handler, 403, {"error": "权限不足: 删除需要主管或管理员权限"})
        return False

    if path_clean.startswith(ADMIN_ONLY_PREFIXES) and role != "admin":
        send_json(handler, 403, {"error": "权限不足: 用户管理需要管理员权限"})
        return False

    if path_clean.startswith(MANAGER_ONLY_PREFIXES) and role not in MANAGER_ROLES:
        send_json(handler, 403, {"error": "权限不足: 该操作需要主管或管理员权限"})
        return False

    return True


_GET_ROUTES = {
    "/api/health": handle_get_health,
    "/api/version": handle_get_version,
    "/api/snapshot": handle_get_snapshot,
    "/api/export": handle_get_export,
    "/api/monthly-report": handle_get_monthly_report,
    "/api/yearly-report": handle_get_yearly_report,
    "/api/monthly-utilities": handle_get_monthly_utilities,
    "/api/import/template": handle_get_import_template,
    "/api/readings": handle_get_readings,
    "/api/readings-water": handle_get_readings_water,
    "/api/charges": handle_get_charges,
    "/api/items": handle_get_items,
    "/api/purchases": handle_get_purchases,
    "/api/meters": handle_get_meters_public,
    "/api/duty": handle_get_duty,
    "/api/proxy/nas-data": handle_get_proxy_nas_data,
}

_POST_PREFIX = {
    "/api/backup": handle_post_backup,
    "/api/restore": handle_post_restore,
    "/api/upload": handle_post_upload,
    "/api/admin/restore-upload": handle_post_restore_upload,
    "/api/admin/sync-from-nas": handle_post_sync_from_nas,
    "/api/proxy/nas-data": handle_get_proxy_nas_data,
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
    "/api/admin/migrate-water-status": handle_get_migrate_status,
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
        from utils import CORS, _add_cors
        for k, v in CORS.items():
            handler.send_header(k, v)
        _add_cors(handler)
        handler.end_headers()
        return True

    # GET: 精确匹配 + 前缀匹配
    if not _auth_gate(method, path_clean, handler):
        return True  # 已经发了 401/403,不再往下分发

    if method == "GET":
        # 特殊路径: /api/duty/image/{filename}
        if path_clean.startswith("/api/duty/image/"):
            filename = path_clean[len("/api/duty/image/"):]
            _dispatch_fn(handle_get_duty_image, "GET", handler, filename)
            return True
        # 特殊路径: /api/admin/images
        if path_clean == "/api/admin/images":
            _dispatch_fn(handle_get_images_config, "GET", handler)
            return True
        # 精确匹配: _GET_ROUTES
        if path_clean in _GET_ROUTES:
            _dispatch_fn(_call_handler, "GET", _GET_ROUTES[path_clean], handler, path_clean)
            return True
        # 精确匹配: admin 路由
        if path_clean in _GET_ADMIN:
            _dispatch_fn(_call_handler, "GET", _GET_ADMIN[path_clean], handler, path_clean)
            return True
        # 前缀匹配: _GET_ROUTES (for path like /api/readings/monthly)
        fn = _match_prefix(_GET_ROUTES, path_clean)
        if fn:
            _dispatch_fn(_call_handler, "GET", fn, handler, path_clean)
            return True

    # POST
    if method == "POST":
        # 特殊路径: /api/duty/{id}/handle
        if path_clean.startswith("/api/duty/") and path_clean.endswith("/handle"):
            _dispatch_fn(handle_post_duty_handle, "POST", handler, path_clean)
            return True
        # 特殊路径: /api/duty/image
        if path_clean == "/api/duty/image":
            _dispatch_fn(handle_post_duty_image, "POST", handler, path_clean)
            return True
        handler_fn = _match_prefix(_POST_PREFIX, path_clean)
        if handler_fn:
            _dispatch_fn(handler_fn, "POST", handler)
            return True

    # PUT: 优先匹配特殊路径
    if method == "PUT":
        if path_clean == "/api/admin/images":
            _dispatch_fn(handle_put_images_config, "PUT", handler)
            return True
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
        # 特殊路径: /api/items/{id}/lend/{record_id} 删除借出记录
        if path_clean.startswith("/api/items/") and "/lend/" in path_clean:
            _dispatch_fn(handle_delete_items_lend, "DELETE", handler, path_clean)
            return True
        handler_fn = _match_prefix(_DELETE_PREFIX, path_clean)
        if handler_fn:
            _dispatch_fn(_call_handler, "DELETE", handler_fn, handler, path_clean)
            return True

    return False

# Public API: tests import `route`, app_handler imports `route`
route = _route
