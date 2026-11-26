from __future__ import annotations  # noqa: I001  (import 顺序是刻意的,见下方说明)
import inspect
import traceback
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from utils import send_json

from modules.readings import (
    handle_get_readings, handle_post_readings, handle_put_readings, handle_delete_readings,
)
from modules.utilities.handler import (
    handle_get_readings_water,
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
    handle_get_nas_config, handle_put_nas_config,
)
from modules.system.admin_tools_handler import (
    handle_get_dir_listing, handle_get_audit_log,
    handle_get_migrate_status, handle_post_migrate_water,
)
from modules.stores.handler import (
    handle_get_stores, handle_get_current_store, handle_get_stores_overview,
    handle_post_store, handle_put_store, handle_delete_store,
)

# ⚠️ 上面的 import 顺序是**刻意的**,别让 isort 自动重排:
#    modules.system.admin_handler 必须排在 modules.backup.admin_handler 之前 ——
#    反过来会撞上循环 import(modules.system.admin_handler → modules.backup.admin_handler
#    → modules.system.settings_handler → modules.system.__init__ → modules.system.admin_handler)。
#    这也是本文件带 # noqa: I001 的原因。
#
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

# 仅管理员的接口。
#
# - /api/admin/users:否则任何登录用户都能新建管理员账号自我提权
# - 下面这 5 个是**部署级全局配置**,写的是顶层 settings.json、影响所有门店:
#     备份目录 / NAS 账号密码 / 自动备份开关 / 保留份数 / 图片目录
#   分店主管改了会波及全站(比如关掉自动备份、改错备份目录、读到 NAS 凭据;
#   图片目录还是"全局覆盖项",一设就会让所有门店的照片混进同一目录)。
#   主管仍保留**本店范围**的备份/恢复能力(/api/backup、/api/restore、
#   backup-download、backup-delete、data-files —— 它们各自带门店范围闸)。
ADMIN_ONLY_PREFIXES = (
    "/api/admin/users",
    "/api/admin/backup-config",
    "/api/admin/nas-config",
    "/api/admin/auto-backup",
    "/api/admin/backup-retention",
    "/api/admin/images",
)

# 管理类接口至少主管:审计日志、备份删除/恢复、NAS 同步、电价倍率与图片目录配置
# 这些不该由"只能录入抄表"的员工角色触碰,与前端 ADMIN_MANAGE_ROLES 的意图对齐。
#
# ⚠️ /api/upload、/api/restore、/api/backup、/api/admin/backup-download 也在其中:
#   - upload / restore **能写任意门店的数据**(载荷里带 stores/<id>/ 路径),
#     员工角色不该有「覆盖别人门店数据」的权限;
#   - backup / backup-download 能**导出含全部门店数据的备份包**
#     (Task 7 之前备份包只含顶层 = 单店,现在含全部门店 —— 导出面被放大了)。
# 它们与已有的 /api/admin/data-files 同级:都是「数据文件」级别的操作。
MANAGER_ONLY_PREFIXES = (
    "/api/admin/audit",
    "/api/admin/data-files",
    "/api/admin/dir-listing",
    "/api/admin/migrate-water",
    "/api/admin/restore-upload",
    "/api/admin/sync-from-nas",
    "/api/admin/backup-delete",
    "/api/admin/backup-download",
    "/api/admin/meter",
    "/api/admin/images",
    "/api/admin/auto-backup",
    "/api/admin/backup-retention",
    "/api/admin/backup-config",
    "/api/admin/nas-config",
    "/api/upload",
    "/api/restore",
    "/api/backup",
)
MANAGER_ROLES = frozenset({"admin", "supervisor"})

# 单元测试用 _do_api 直接跑业务逻辑时,可在 fixture 内置 False 跳过鉴权。
# 生产启动路径不读任何环境变量,这个开关在进程内,外部配不出来。
ENFORCE_AUTH = True

# 鉴权关闭时(ENFORCE_AUTH=False)用的合成管理员会话。
# 门店闸要靠它才知道「本次请求属于哪个用户、能看到哪些门店」——
# 返回空会话/None 会让下游拿不到 user_id。
# user_id=0 在 settings.json 里永远不会存在(用户 id 从 1 开始),
# 所以 "_synthetic" 这个标记不会和真实用户混淆:
#   - 合成会话 → 测试模式,按全店放行
#   - 真实会话查不到用户记录 → 403(fail-closed),绝不回退成「全店权限」
_SYNTHETIC_SESSION: Dict[str, Any] = {
    "user_id": 0,
    "username": "test",
    "role": "admin",
    "name": "test",
    "all_stores": True,
    "store_ids": [],
    "_synthetic": True,
}


def _auth_gate(method: str, path_clean: str, handler) -> Optional[Dict[str, Any]]:
    """统一鉴权入口。返回 session dict 表示放行;返回 None 表示已发出 401/403。

    token 由 _get_token 依次尝试 Cookie / ?token= / Authorization 头,
    所以 <img src> 与 <a href> 这类带不了请求头的请求也能用 query 通过校验。

    返回 session 而不是 bool,是为了把「这次请求是谁」交给下游的门店闸 ——
    门店闸要按用户的门店范围放行,不能只看有没有登录。
    """
    if not ENFORCE_AUTH:
        # 业务回归测试关闭了鉴权 —— 合成一个管理员会话,
        # 让下游的门店闸也能拿到可用的 session(而不是空/None)。
        return dict(_SYNTHETIC_SESSION)
    if path_clean in PUBLIC_API_PATHS:
        return {}  # 匿名放行(白名单端点);门店闸会跳过这些路径

    from modules.system.auth_handler import _touch_session, get_session
    from modules.system.permissions_handler import _get_token

    token = _get_token(handler)
    sess = get_session(token) if token else None
    if not sess:
        send_json(handler, 401, {"error": "未登录或会话已过期,请重新登录"})
        return None

    _touch_session(token)  # 有活动就续期,与 check_permission 装饰器行为一致
    role = sess.get("role", "employee")

    if method == "DELETE" and role not in DELETE_ROLES:
        send_json(handler, 403, {"error": "权限不足: 删除需要主管或管理员权限"})
        return None

    if path_clean.startswith(ADMIN_ONLY_PREFIXES) and role != "admin":
        send_json(handler, 403, {"error": "权限不足: 该操作需要管理员权限"})
        return None

    if path_clean.startswith(MANAGER_ONLY_PREFIXES) and role not in MANAGER_ROLES:
        send_json(handler, 403, {"error": "权限不足: 该操作需要主管或管理员权限"})
        return None

    return sess


def _store_gate(sess: Dict[str, Any], handler: Any) -> bool:
    """解析并校验当前门店。返回 False 表示已发出 403/404。

    规则:
    - **单店布局**(没有 stores/ 目录)→ 整体放行,落到默认店。此时只有一家店,
      无从越权;这也保证存量业务回归测试的行为完全不变。
    - **多店布局** → 严格执行:
        - 范围优先取 settings.json 里的用户记录(改权限即时生效,不必重新登录)
        - all_stores=True(总部账号)→ 允许任意**已注册**门店
        - 否则请求的门店必须在该用户的 store_ids 里 → 否则 403
        - 不带 store 参数时:取该用户第一个**仍存在**的 store_ids
          (管理员删店后用户记录里的 store_ids 不会自动清理,直接取 [0] 会 404 锁死);
          有权访问的店全被删了 → 403;总部账号 store_ids 为空 → 取默认店 main
        - 请求的门店没在注册表里 → 404(与「没权限」区分开)

    门店闸是「拦越权」的闸,不是新的 500 来源:判不出布局/权限时一律 403,
    绝不把异常冒给前端。
    """
    from modules.stores import registry
    from modules.stores.context import (
        DEFAULT_STORE_ID,
        multi_store_layout,
        set_current_store,
    )

    # 布局判定:数据目录未初始化时 base_data_dir() 会抛 RuntimeError
    # (Task 1 的 fail-fast 设计 —— 不猜目录,免得静默碰到真实生产数据)。
    # 判不出布局就按单店放行,并记一条日志,绝不把异常冒成 500。
    try:
        multi = multi_store_layout()
    except Exception as e:
        from storage import log
        log(f"[WARN] [store_gate] 数据目录未初始化,按单店布局放行: {e}")
        multi = False

    if not multi:
        set_current_store(DEFAULT_STORE_ID)
        return True

    scope = _user_store_scope(sess)
    if scope is None:
        # 查不到用户记录 → fail-closed:账号可能已被删除,旧会话还在。
        # 绝不回退成「全店权限」—— 那等于「号删了,权限还在」。
        send_json(handler, 403, {"error": "账号不存在或门店权限无法确认,请重新登录"})
        return False

    all_stores, store_ids = scope
    if not all_stores and not store_ids:
        # 受限账号但一个门店都没分配 → 无从谈越权,直接拒绝。
        send_json(handler, 403, {"error": "账号未分配门店,请联系管理员"})
        return False

    requested = _requested_store(handler)
    if not requested:
        # 没指定门店 → 落到「他有权访问的、且仍然存在的」第一个门店。
        #
        # 为什么要跳过已删除的门店:管理员删店只摘掉注册表条目,用户记录里的
        # store_ids 仍留着那个 ID。直接取 store_ids[0] 会撞上 404「门店不存在」
        # → 员工的每个请求都是 404(看不出原因);多店员工连还存在的另一个店
        # 都访问不到 —— 等于被锁死。
        #
        # 显式 ?store= 不走这条路径:用户点名要哪个店,那个店不存在就是不存在
        # (404 仍然正确,见下面的存在性检查)。
        picked = _first_existing_store(store_ids, registry)
        if picked is None:
            if not all_stores:
                # 有权访问的店全被删了 → 403 并说清去找管理员重新分配。
                # 比 404「门店不存在」清楚得多:账号还在,只是没分到有效的店。
                send_json(handler, 403, {"error": "账号未分配有效门店,请联系管理员"})
                return False
            # 总部账号可访问任意**已注册**门店 → 落回默认店
            # (main 不可删,永远存在)。总部账号有 store_ids 时仍落 store_ids[0],
            # 只是跳过已删除的那个 —— 与修复前语义一致。
            picked = DEFAULT_STORE_ID
        requested = picked

    # 权限先判、存在性后判:分店员工探测别的门店 ID 时只能拿到 403,
    # 不会从 403/404 的差别里摸到别家门店存不存在。
    if not all_stores and requested not in store_ids:
        send_json(handler, 403, {"error": f"无权访问门店: {requested}"})
        return False

    if not _store_exists(requested, registry):
        send_json(handler, 404, {"error": f"门店不存在: {requested}"})
        return False

    set_current_store(requested)
    return True


def _user_store_scope(sess: Dict[str, Any]) -> Optional[Tuple[bool, List[str]]]:
    """用户的门店范围。返回 None 表示「查不到用户记录」→ 交给调用方 403。

    优先读 settings.json(改权限即时生效,不必重新登录);
    合成会话(ENFORCE_AUTH=False 的测试模式)按全店放行。
    """
    if sess.get("_synthetic"):
        return (True, [])
    from modules.stores import registry
    user_id = sess.get("user_id")
    if not isinstance(user_id, int):
        # 会话里没有合法的 user_id → 判不出范围 → fail-closed
        return None
    try:
        return registry.user_store_scope(user_id)
    except Exception as e:
        # settings.json 读不到(不存在/损坏)→ 判不出范围 → fail-closed
        from storage import log
        log(f"[WARN] [store_gate] 读用户门店范围失败: {e}")
        return None


def _requested_store(handler: Any) -> str:
    """请求里指定的门店 ID(query 的 ?store=)。没有则返回空串。"""
    qs = parse_qs(urlparse(getattr(handler, "path", "") or "").query)
    values = qs.get("store") or []
    return (values[0] if values else "").strip()


def _store_exists(store_id: str, registry: Any) -> bool:
    """门店是否在注册表里。读不到注册表时按「不存在」处理(fail-closed)。"""
    try:
        return registry.get_store(store_id) is not None
    except Exception as e:
        from storage import log
        log(f"[WARN] [store_gate] 读门店注册表失败: {e}")
        return False


def _first_existing_store(store_ids: List[str], registry: Any) -> Optional[str]:
    """store_ids 里第一个**仍然存在**的门店 ID。都不存在(或列表为空)时返回 None。

    门店被管理员删掉后,用户记录里的 store_ids 不会跟着清理 ——
    这里跳过已删除的,让默认门店落到员工仍有权访问的另一个店。
    """
    for store_id in store_ids:
        if _store_exists(store_id, registry):
            return store_id
    return None


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
    # 门店管理。带路径段的接口必须精确登记在 /api/stores **之前** ——
    # 前缀匹配(/api/stores/xxx 命中 /api/stores)会把它们当成门店列表。
    "/api/stores/current": handle_get_current_store,
    "/api/stores/overview": handle_get_stores_overview,
    "/api/stores": handle_get_stores,
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
    # 门店管理:权限在 handler 内部判(增删改仅 admin)——
    # 放进 ADMIN_ONLY_PREFIXES 会把 GET /api/stores 一起拦掉。
    "/api/stores": handle_post_store,
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
    "/api/admin/nas-config": handle_put_nas_config,
    "/api/duty": handle_put_duty,
    "/api/stores": handle_put_store,
}

_DELETE_PREFIX = {
    "/api/readings": handle_delete_readings,
    "/api/readings-water": handle_delete_readings_water,
    "/api/charges": handle_delete_charges,
    "/api/items": handle_delete_items,
    "/api/purchases": handle_delete_purchases,
    "/api/admin/users": handle_delete_users,
    "/api/duty": handle_delete_duty,
    "/api/stores": handle_delete_store,
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
    "/api/admin/nas-config": handle_get_nas_config,
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
    sess = _auth_gate(method, path_clean, handler)
    if sess is None:
        return True  # 已经发了 401/403,不再往下分发

    # 把「这次请求是谁」交给下游 handler —— handler 不再自己取一次 token。
    # 两次独立取 token 之间会话可能刚好过期,会让「鉴权通过」与
    # 「业务看到的身份」不一致(门店管理 API 就会因此漏判/误判权限)。
    handler._auth_session = sess

    # 门店闸:解析并校验当前门店。挂在 _route() 这个唯一入口上 →
    # 新增接口默认就带门店隔离,不用逐个接口改。
    # 公开端点(health/version/login)与门店无关,必须跳过 ——
    # 否则 /api/health 会被 404,Docker HEALTHCHECK 会把容器判成 unhealthy。
    if path_clean not in PUBLIC_API_PATHS and not _store_gate(sess, handler):
        return True  # 已经发了 403/404,不再往下分发

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
