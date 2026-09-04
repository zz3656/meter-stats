"""认证 + 后台管理 API handler。
"""
from __future__ import annotations
import datetime
import os
import secrets
import threading
import time
import zipfile
import tempfile
import shutil
from pathlib import Path
from utils import send_json, read_body
from handlers.settings import (
    get_settings, save_settings, init_settings, verify_password,
    add_user, update_user, delete_user, ROLES,
    _needs_migration,
)
from handlers.backup import _get_backup_retention_count, _merge_settings_after_restore
from storage import log, load_json, save_json
from handlers._base import get_data_paths as _get_data_paths
from utils.api import _validate_zip_safely

# ============ 会话管理（带 TTL 自动清理） ============

# 会话超时：30 分钟无活动自动过期
SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 分钟
# 清理间隔：每 5 分钟清理一次过期会话
SESSION_CLEANUP_INTERVAL = 5 * 60  # 5 分钟

# 会话存储: token -> {user_id, username, role, name, created_at, last_access}
_SESSIONS: dict = {}
_SESSIONS_LOCK = threading.Lock()

# 上次清理时间戳（用于懒清理）
_last_cleanup_time: float = 0

# 登录速率限制
_LOGIN_ATTEMPTS: dict = {}  # username -> [{timestamp, success}]
_LOGIN_ATTEMPTS_LOCK = threading.Lock()
_LOGIN_MAX_ATTEMPTS = 10  # 窗口内最大尝试次数
_LOGIN_WINDOW_SECONDS = 5 * 60  # 5 分钟滑动窗口
_LOGIN_COOLDOWN_SECONDS = 2 * 60  # 超限后冷却 2 分钟


def _cleanup_expired_sessions():
    """清理所有过期的会话。"""
    global _last_cleanup_time
    now = time.time()
    if now - _last_cleanup_time < SESSION_CLEANUP_INTERVAL:
        return  # 未到清理时间
    _last_cleanup_time = now

    expired = []
    with _SESSIONS_LOCK:
        for token, sess in _SESSIONS.items():
            last_access = sess.get("_access_time", 0)
            if now - last_access > SESSION_TIMEOUT_SECONDS:
                expired.append(token)
        for token in expired:
            del _SESSIONS[token]

    if expired:
        log(f"  [AUTH] 清理 {len(expired)} 个过期会话")


# ============ 登录速率限制 ============

def _check_login_rate_limit(username: str) -> tuple[bool, str]:
    """检查登录尝试是否超过速率限制。

    使用滑动窗口算法：
    - 5 分钟内最多尝试 10 次
    - 超限后进入 2 分钟冷却期
    - 只记录密码错误的尝试

    返回: (allowed, message)
    """
    now = time.time()
    with _LOGIN_ATTEMPTS_LOCK:
        attempts = _LOGIN_ATTEMPTS.get(username, [])

        # 清理过期记录（只保留窗口内）
        window_start = now - _LOGIN_WINDOW_SECONDS
        attempts = [a for a in attempts if a["timestamp"] > window_start]
        _LOGIN_ATTEMPTS[username] = attempts

        # 检查是否处于冷却期
        failed_attempts = [a for a in attempts if not a["success"]]
        if failed_attempts:
            last_failure = max(failed_attempts, key=lambda a: a["timestamp"])["timestamp"]
            cooldown_remaining = _LOGIN_COOLDOWN_SECONDS - (now - last_failure)
            if cooldown_remaining > 0:
                remaining_min = int(cooldown_remaining / 60) + 1
                return False, f"尝试次数过多，请在 {remaining_min} 分钟后再试"

        # 检查窗口内总尝试次数
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            return False, f"尝试次数过多，请在 {_LOGIN_WINDOW_SECONDS // 60} 分钟后再试"

    return True, ""


def _record_login_attempt(username: str, success: bool) -> None:
    """记录登录尝试（仅记录密码错误的）。"""
    if success:
        # 成功登录，清理该用户的所有历史记录（防止旧失败记录累积）
        with _LOGIN_ATTEMPTS_LOCK:
            _LOGIN_ATTEMPTS[username] = []
        return

    now = time.time()
    with _LOGIN_ATTEMPTS_LOCK:
        attempts = _LOGIN_ATTEMPTS.get(username, [])
        attempts.append({"timestamp": now, "success": success})
        # 只保留窗口内
        attempts = [a for a in attempts if now - a["timestamp"] <= _LOGIN_WINDOW_SECONDS]
        _LOGIN_ATTEMPTS[username] = attempts


def _touch_session(token: str):
    """更新会话的最后访问时间。"""
    with _SESSIONS_LOCK:
        if token in _SESSIONS:
            _SESSIONS[token]["_access_time"] = time.time()


def get_session(token: str) -> dict | None:
    """获取会话（同时检查过期和懒清理）。

    过期检查是立即进行的：即使全局清理间隔（5 分钟）未到，单个过期
    session 也会被返回 None 并从字典中移除。这保证：
    - 用户在 TTL 后访问立即被踢出（不需等清理任务）。
    - 过期会话不在内存中堆积（被读取时立即清理）。
    """
    if not token:
        return None
    _cleanup_expired_sessions()
    now = time.time()
    with _SESSIONS_LOCK:
        sess = _SESSIONS.get(token)
        if sess is None:
            return None
        last_access = sess.get("_access_time", 0)
        if now - last_access > SESSION_TIMEOUT_SECONDS:
            # 过期会话：读完即扔
            del _SESSIONS[token]
            return None
        return sess


def create_session(user: dict) -> str:
    """创建新会话，返回 token。"""
    _cleanup_expired_sessions()
    token = secrets.token_hex(32)
    now = time.time()
    with _SESSIONS_LOCK:
        _SESSIONS[token] = {
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "name": user["name"],
            "created_at": datetime.datetime.fromtimestamp(now).isoformat(),
            "_access_time": now,
        }
    return token


def destroy_session(token: str) -> None:
    """销毁会话。"""
    with _SESSIONS_LOCK:
        _SESSIONS.pop(token, None)


def get_active_session_count() -> int:
    """获取当前活跃会话数（不含已清理的）。"""
    _cleanup_expired_sessions()
    with _SESSIONS_LOCK:
        return len(_SESSIONS)


# 向后兼容: 保留全局 _SESSIONS 引用供 permissions.py 导入
# 但新代码应使用 get_session/destroy_session 函数


def handle_post_login(handler):
    """POST /api/auth/login {username, password} → {ok, token, user}"""
    body = read_body(handler)
    username = (body or {}).get("username", "").strip()
    password = (body or {}).get("password", "")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    # 检查登录速率限制
    allowed, msg = _check_login_rate_limit(username)
    if not allowed:
        send_json(handler, 200, {"ok": False, "error": msg})
        return

    settings = get_settings()
    users = settings.get("users", [])
    user = next((u for u in users if u["username"] == username), None)

    if not user or not user.get("enabled", True):
        _record_login_attempt(username, False)
        send_json(handler, 200, {"ok": False, "error": "用户不存在或已禁用"})
        return

    if not verify_password(password, user["password"]):
        _record_login_attempt(username, False)
        send_json(handler, 200, {"ok": False, "error": "密码错误"})
        return

    # 登录成功，记录并清理旧失败记录
    _record_login_attempt(username, True)

    # 检测到旧版 sha256: 哈希 → 登录成功后静默升级为 pbkdf2
    if _needs_migration(user["password"]):
        users = settings.get("users", [])
        for u in users:
            if u["id"] == user["id"]:
                from handlers.settings import _hash_pass
                u["password"] = _hash_pass(password)
                save_settings(settings)
                log(f"  [AUTH] 用户 {username} 密码已自动升级为 pbkdf2")
                break

    # 创建新会话（含 TTL）
    user_info = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "name": user["name"],
    }
    token = create_session(user_info)

    send_json(handler, 200, {
        "ok": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
        },
    })


def handle_get_logout(handler):
    """GET /api/auth/logout?token=xxx → {ok}"""
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0]
    destroy_session(token)
    send_json(handler, 200, {"ok": True})


def handle_get_me(handler):
    """GET /api/auth/me?token=xxx → {user} or {user: null}"""
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0]

    if token:
        _touch_session(token)  # 延长活跃会话
        sess = get_session(token)
        if sess:
            send_json(handler, 200, {"user": {
                "id": sess["user_id"],
                "username": sess["username"],
                "name": sess["name"],
                "role": sess["role"],
            }})
            return
    send_json(handler, 200, {"user": None})


def handle_get_sessions(handler):
    """GET /api/admin/sessions?token=xxx → {ok, count, timeout_sec, sessions: [...]}

    仅管理员可见，用于查看当前在线用户和会话状态。
    """
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0]
    sess = get_session(token) if token else None
    if not sess or sess.get("role") != "admin":
        send_json(handler, 403, {"error": "仅管理员可访问"})
        return

    # 先清理过期会话再统计
    _cleanup_expired_sessions()
    now = time.time()
    active = []
    with _SESSIONS_LOCK:
        for t, s in _SESSIONS.items():
            age = now - s.get("_access_time", now)
            active.append({
                "token_prefix": t[:8] + "...",
                "user_id": s["user_id"],
                "username": s["username"],
                "name": s["name"],
                "role": s["role"],
                "created_at": s["created_at"],
                "last_access": datetime.datetime.fromtimestamp(
                    s.get("_access_time", 0)
                ).isoformat(),
                "age_seconds": round(age, 0),
                "timeout_minutes": SESSION_TIMEOUT_SECONDS // 60,
            })
    active.sort(key=lambda s: s["last_access"], reverse=True)

    send_json(handler, 200, {
        "ok": True,
        "count": len(active),
        "timeout_sec": SESSION_TIMEOUT_SECONDS,
        "sessions": active,
    })


# ============ 用户管理 CRUD ============

def handle_get_users(handler):
    """GET /api/admin/users → [users]"""
    settings = get_settings()
    # 不返回密码
    users = [{k: v for k, v in u.items() if k != "password"} for u in settings.get("users", [])]
    send_json(handler, 200, users)


def handle_post_users(handler):
    """POST /api/admin/users {username, password, name, role} → {ok, user}"""
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    users = settings.get("users", [])
    username = (body or {}).get("username", "")
    password = (body or {}).get("password", "")
    name = (body or {}).get("name", username)
    role = (body or {}).get("role", "employee")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    result = add_user(users, username, password, name, role)
    if isinstance(result, dict) and "error" in result:
        send_json(handler, 200, {"ok": False, "error": result["error"]})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "user": result})


def handle_put_users(handler, path_clean: str):
    """PUT /api/admin/users/<uid> {fields} → {ok, user}"""
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(handler.path).query)
    uid_str = qs.get("id", [None])[0]
    if not uid_str or not uid_str.isdigit():
        send_json(handler, 200, {"ok": False, "error": "无效的用户ID"})
        return

    uid = int(uid_str)
    settings = get_settings()
    users = settings.get("users", [])
    result = update_user(users, uid, (body := read_body(handler)))
    if result is None:
        send_json(handler, 200, {"ok": False, "error": "用户不存在"})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "user": {k: v for k, v in result.items() if k != "password"}})


def handle_delete_users(handler, path_clean: str):
    """DELETE /api/admin/users/<uid> → {ok}"""
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(handler.path).query)
    uid_str = qs.get("id", [None])[0]
    if not uid_str or not uid_str.isdigit():
        send_json(handler, 200, {"ok": False, "error": "无效的用户ID"})
        return

    uid = int(uid_str)
    settings = get_settings()
    users = settings.get("users", [])
    deleted = delete_user(users, uid)
    if not deleted:
        send_json(handler, 200, {"ok": False, "error": "用户不存在"})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True})


# ============ 电表设置 ============

def handle_get_meter_settings(handler):
    """GET /api/admin/meter → {meter, config}"""
    settings = get_settings()
    send_json(handler, 200, {
        "meter": settings.get("meter", {}),
        "config": settings.get("config", {}),
    })


def handle_get_meters_public(handler):
    """GET /api/meters → {meters, config} （非管理员也可访问）"""
    settings = get_settings()
    send_json(handler, 200, {
        "meters": settings.get("meter", {}),
        "config": settings.get("config", {}),
    })


def handle_put_meter_settings(handler):
    """PUT /api/admin/meter → {meter, config}"""
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    if "meter" in body:
        settings["meter"] = body["meter"]
    if "config" in body:
        settings["config"] = body["config"]
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "meter": settings["meter"], "config": settings["config"]})


# ============ 权限管理 ============

def handle_get_roles(handler):
    """GET /api/admin/roles → [roles]"""
    send_json(handler, 200, [{"key": k, "name": v} for k, v in ROLES.items()])


# ============ 数据管理 ============

def handle_get_backup_status(handler):
    """GET /api/admin/backup-status → {auto_backup, backup_count, backups: [...]}

    列出备份目录下所有的 ZIP 压缩包(手动 meter-backup- + 自动 auto-bak-)，
    每个 ZIP 算一个备份，带 type 字段区分(manual/auto)。
    返回 { name, zip_path, file_count, total_size, created_at, type }
    """
    import zipfile as zf_mod
    from storage import get_data_dir
    from handlers.backup import _resolve_backup_parent

    settings = get_settings()
    auto_backup = settings.get("auto_backup", True)
    data_dir = get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)

    backup_entries = []
    if backup_dir.exists():
        for f in sorted(backup_dir.rglob("*.zip"), reverse=True):
            if not f.is_file():
                continue
            # 手动备份 meter-backup- 前缀,自动备份 auto-bak- 前缀
            if f.name.startswith("meter-backup-"):
                btype = "manual"
                try:
                    ts = f.name.replace("meter-backup-", "").replace(".zip", "")
                except Exception:
                    ts = f.name
            elif f.name.startswith("auto-bak-"):
                btype = "auto"
                try:
                    ts = f.name.replace("auto-bak-", "").replace(".zip", "")
                except Exception:
                    ts = f.name
            else:
                continue

            # 统计 ZIP 内文件数
            file_count = 0
            total_size = 0
            try:
                with zf_mod.ZipFile(f, 'r') as zf:
                    file_count = len(zf.namelist())
                    total_size = sum(info.file_size for info in zf.infolist())
            except Exception:
                total_size = f.stat().st_size

            backup_entries.append({
                "name": ts,
                "zip_path": str(f),
                "zip_name": f.name,
                "file_count": file_count,
                "total_size": total_size,
                "created_at": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "format": "zip",
                "type": btype,
            })

        # 再列出旧格式的备份目录（非 .zip 目录，排除带 _ 的时间戳目录，因为已被 ZIP 覆盖）
        for d in sorted(backup_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if d.is_dir() and not d.name.endswith('.zip'):
                # 只列出没有对应 .zip 的旧目录
                zip_name = f"meter-backup-{d.name}.zip"
                if not (backup_dir / zip_name).exists():
                    # 统计目录内文件
                    file_count = sum(1 for _ in d.rglob('*') if _.is_file())
                    total_size = sum(f.stat().st_size for f in d.rglob('*') if f.is_file())
                    backup_entries.append({
                        "name": d.name,
                        "zip_path": str(d),
                        "zip_name": None,
                        "file_count": file_count,
                        "total_size": total_size,
                        "created_at": datetime.datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "format": "dir",
                        "type": "manual",
                    })

    send_json(handler, 200, {
        "auto_backup": auto_backup,
        "backup_count": len(backup_entries),
        "retention_count": _get_backup_retention_count(),
        "manual_backup_max": 10,
        "data_dir": str(data_dir),
        "backups": backup_entries,
    })


def handle_get_backup_download(handler):
    """GET /api/admin/backup-download?zip_name=xxx → 下载 .zip 文件

    ⚠️ 已弃用: 推荐使用 POST /api/admin/backup-download
    GET 下载可能被浏览器预取/爬虫意外触发。保留 GET 兼容性。
    """
    return handle_post_backup_download(handler, use_get=True)


def handle_post_backup_download(handler):
    """POST /api/admin/backup-download {zip_name} → 下载 .zip 文件

    使用 POST 而非 GET，防止浏览器预取/SEO 爬虫意外下载备份文件。
    请求体: { "zip_name": "meter-backup-20250101_120000.zip" }
    """
    from storage import get_data_dir
    from handlers.backup import _resolve_backup_parent
    from urllib.parse import parse_qs, urlparse

    data_dir = get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)

    # 获取 zip_name（POST body 或 query）
    is_get = False
    try:
        body = read_body(handler)
        zip_name = (body or {}).get("zip_name", "")
    except Exception:
        # GET 兼容路径
        is_get = True
        qs = parse_qs(urlparse(handler.path).query)
        zip_name = qs.get("zip_name", [None])[0]
        if not zip_name:
            dir_name = qs.get("dir", [None])[0]
            if dir_name:
                zip_name = f"meter-backup-{dir_name}.zip"

    if not zip_name:
        send_json(handler, 400, {"error": "缺少 zip_name 参数"})
        return

    zip_path = backup_dir / zip_name
    if not zip_path.is_file():
        send_json(handler, 404, {"error": f"备份文件不存在: {zip_name}"})
        return

    # 安全校验: 防止目录穿越
    real_backup = backup_dir.resolve()
    real_zip = zip_path.resolve()
    if not str(real_zip).startswith(str(real_backup)):
        send_json(handler, 403, {"error": "非法备份文件名"})
        return

    zip_data = zip_path.read_bytes()

    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
    handler.send_header("Content-Length", str(len(zip_data)))
    handler.send_header("Cache-Control", "no-store")
    from utils import CORS
    for k, v in CORS.items():
        handler.send_header(k, v)
    if is_get:
        handler.send_header("X-API-Migration", "已弃用: 请使用 POST /api/admin/backup-download")
    handler.end_headers()
    handler.wfile.write(zip_data)


def handle_get_backup_delete(handler):
    """GET /api/admin/backup-delete?zip_name=xxx → 删除备份

    ⚠️ 已弃用: 推荐使用 POST /api/admin/backup-delete
    GET 删除可被浏览器预取/预连接/SEO 爬虫意外触发删除。保留 GET 兼容性。
    """
    return handle_post_backup_delete(handler, use_get=True)


def handle_post_backup_delete(handler):
    """POST /api/admin/backup-delete {zip_name} → 删除备份

    使用 POST 而非 GET，防止浏览器预取意外删除。
    请求体: { "zip_name": "meter-backup-20250101_120000.zip" }
    Content-Type 必须为 application/json（防止 CSRF）。
    """
    from storage import get_data_dir
    from handlers.backup import _resolve_backup_parent
    from urllib.parse import parse_qs, urlparse

    # 检查 Content-Type 防止 CSRF
    content_type = handler.headers.get("Content-Type", handler.headers.get("content-type", ""))
    is_get = "application/json" not in content_type

    if is_get:
        # GET 兼容路径
        qs = parse_qs(urlparse(handler.path).query)
        zip_name = qs.get("zip_name", [None])[0]
    else:
        body = read_body(handler)
        zip_name = (body or {}).get("zip_name", "")

    if not zip_name:
        send_json(handler, 400, {"ok": False, "error": "缺少 zip_name 参数"})
        return

    data_dir = get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)
    zip_path = backup_dir / zip_name

    if not zip_path.is_file():
        send_json(handler, 404, {"ok": False, "error": f"备份文件不存在: {zip_name}"})
        return

    # 安全校验: 防止目录穿越
    real_backup = backup_dir.resolve()
    real_zip = zip_path.resolve()
    if not str(real_zip).startswith(str(real_backup)):
        send_json(handler, 403, {"ok": False, "error": "非法备份文件名"})
        return

    try:
        zip_path.unlink()
        log(f"[BACKUP] 删除备份: {zip_name}")
        send_json(handler, 200, {"ok": True, "message": "已删除备份"})
    except OSError as e:
        send_json(handler, 500, {"ok": False, "error": f"删除失败: {e}"})


def handle_put_auto_backup(handler):
    """PUT /api/admin/auto-backup {enabled: true/false}"""
    body = read_body(handler)
    settings = get_settings()
    settings["auto_backup"] = bool((body or {}).get("enabled", True))
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "auto_backup": settings["auto_backup"]})


def handle_put_backup_retention(handler):
    """PUT /api/admin/backup-retention {retention_count: 5}

    设置备份文件保留数量。默认 5 个，最小 1。
    """
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return
    count = body.get("retention_count", 5)
    if not isinstance(count, int) or count < 1:
        send_json(handler, 200, {"ok": False, "error": "保留数量必须为 ≥1 的整数"})
        return
    settings = get_settings()
    settings["backup_retention_count"] = count
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "retention_count": count})


# ============ 备份目录配置 ============

def handle_get_backup_config(handler):
    """GET /api/admin/backup-config → {ok: true, backup_dir: path|null, backup_dir_label: str, data_dir: str}

    macOS App 环境: 从 settings.json 读取 backup_dir 字段，用户可自定义备份目录。
    Docker 环境: 备份目录由 METER_BACKUP_DIR 环境变量控制，返回 null + 当前 data_dir 提示前端显示默认路径。
    """
    from storage import get_data_dir
    data_dir = get_data_dir()

    # Docker 环境下备份目录由环境变量控制，不可修改
    if os.environ.get("METER_DOCKER"):
        backup_rel = os.environ.get("METER_BACKUP_DIR", "").strip()
        if backup_rel:
            effective_backup = str(data_dir / backup_rel)
        else:
            effective_backup = str(data_dir / "backup")
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": effective_backup,
            "backup_dir_label": "Docker 备份目录（不可修改）",
            "data_dir": str(data_dir),
            "customizable": False,
        })
        return

    # macOS App 环境: 从 settings.json 读取
    try:
        from handlers.settings import get_settings
        settings = get_settings()
        custom_dir = settings.get("backup_dir")
        if custom_dir:
            label = custom_dir
        else:
            custom_dir = None
            label = "默认备份目录 (data/backup)"
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": custom_dir,  # null 表示使用默认
            "backup_dir_label": label,
            "data_dir": str(data_dir),
            "customizable": True,
        })
    except Exception:
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": None,
            "backup_dir_label": "默认备份目录",
            "data_dir": str(data_dir),
            "customizable": True,
        })


def handle_put_backup_config(handler):
    """PUT /api/admin/backup-config → {ok: bool, backup_dir: path|null, error: str?}

    macOS App 环境: 将用户选择的备份目录保存到 settings.json。
    注意: 已有备份文件不会移动，新备份将保存到新目录。
    """
    # Docker 环境不允许修改
    if os.environ.get("METER_DOCKER"):
        send_json(handler, 200, {
            "ok": False,
            "error": "Docker 环境下备份目录由环境变量 METER_BACKUP_DIR 控制",
            "backup_dir": None,
            "backup_dir_label": None,
        })
        return

    body = read_body(handler)
    new_backup_dir = (body or {}).get("backup_dir")  # null 或绝对路径字符串

    try:
        from handlers.settings import get_settings, save_settings
        settings = get_settings()
        settings["backup_dir"] = new_backup_dir
        save_settings(settings)

        label = new_backup_dir if new_backup_dir else "默认备份目录 (data/backup)"
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": new_backup_dir,
            "backup_dir_label": label,
        })
    except Exception as e:
        send_json(handler, 200, {
            "ok": False,
            "error": f"保存失败: {e}",
            "backup_dir": None,
            "backup_dir_label": None,
        })


def handle_post_restore_upload(handler):
    """POST /api/admin/restore-upload — 上传 ZIP 备份文件并恢复

    接受 multipart/form-data，上传一个 .zip 文件，服务端自动解压并恢复数据。
    恢复前自动备份当前数据（可回滚）。

    返回 { ok: true, restored: [...], message: "..." }
    """
    import zipfile as zf_mod

    from handlers._base import get_data_paths as _get_data_paths

    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    target_dir = data_dir.parent
    from storage import backup_data

    # 解析 multipart 上传
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        send_json(handler, 200, {"ok": False, "error": "请上传 ZIP 文件 (multipart/form-data)"})
        return

    # 读取上传内容
    content_length = int(handler.headers.get("Content-Length", 0))
    body_data = handler.rfile.read(content_length)
    boundary = content_type.split("boundary=", 1)[1] if "boundary=" in content_type else None

    if not boundary:
        send_json(handler, 200, {"ok": False, "error": "无法解析 multipart boundary"})
        return

    # 解析 ZIP 文件
    zip_content = None
    zip_filename = "backup.zip"

    boundary_bytes = b"--" + boundary.encode()
    parts = body_data.split(boundary_bytes)

    for part in parts:
        if part.strip() in (b"", b"--"):
            continue
        # 分离 headers 和 body
        if b"\r\n\r\n" in part:
            headers, file_body = part.split(b"\r\n\r\n", 1)
            header_str = headers.decode("utf-8", errors="replace")
            # 提取文件名
            fname_match = __import__('re').search(r'filename="([^"]+\.zip)"', header_str)
            if fname_match:
                zip_filename = fname_match.group(1)
                # 去掉尾部 \r\n
                zip_content = file_body.rstrip(b"\r\n")
                break

    if not zip_content:
        send_json(handler, 200, {"ok": False, "error": "未找到 ZIP 文件"})
        return

    # 恢复前自动备份当前数据
    pre_backup = backup_data(target_dir, force=True)

    try:
        # 解压到临时目录
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_buffer = __import__('io').BytesIO(zip_content)
            zip_path = Path(tmp_dir) / "restore_upload.zip"
            zip_path.write_bytes(zip_buffer.read())

            # 校验：ZIP Bomb 防护
            safe_dir, error = _validate_zip_safely(zip_path, tmp_dir)
            if error:
                send_json(handler, 200, {"ok": False, "error": f"ZIP 文件不安全: {error}"})
                return

            # 校验：必须是有效的 ZIP 且包含数据文件
            with zipfile.ZipFile(zip_buffer, 'r') as zf:
                namelist = zf.namelist()
                has_readings = any("readings.json" in n for n in namelist)
                if not has_readings:
                    send_json(handler, 200, {"ok": False, "error": "ZIP 文件不包含 readings.json，不是有效的备份文件"})
                    return

            # 找到数据目录（可能是 YYYYMMDD_HHMMSS/ 子目录或根目录）
            extract_dir = Path(tmp_dir)
            children = list(extract_dir.iterdir())
            if len(children) == 1 and children[0].is_dir():
                extract_dir = children[0]

            # 恢复数据文件
            from storage import DATA_FILES
            restored = []
            for name in DATA_FILES.values():
                src_file = extract_dir / name
                if src_file.exists():
                    shutil.copy2(src_file, target_dir / name)
                    restored.append(name)
                    log(f"  恢复 {name} <- {src_file}")

            # 恢复 settings.json:合并业务字段,保留目标环境的部署字段(backup_dir 等)
            settings_src = extract_dir / "settings.json"
            if settings_src.exists():
                try:
                    import json as _json
                    src_settings = _json.loads(settings_src.read_text(encoding="utf-8"))
                    _merge_settings_after_restore(target_dir, src_settings)
                    restored.append("settings.json")
                except Exception as e:
                    log(f"  [WARN] 解析/合并 settings.json 失败: {e}")

        send_json(handler, 200, {
            "ok": True,
            "restored": restored,
            "zip_name": zip_filename,
            "pre_backup": str(pre_backup) if pre_backup else "无",
            "message": f"✅ 已从 {zip_filename} 恢复 {len(restored)} 个文件",
        })
    except zf_mod.BadZipFile:
        send_json(handler, 200, {"ok": False, "error": "ZIP 文件格式错误，请确认是有效的备份文件"})
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"恢复失败: {e}"})


def handle_get_dir_listing(handler):
    """GET /api/admin/dir-listing?path=/data → { ok, path, entries: [...] }

    安全限制:
    - 必须登录（需 token）
    - 仅管理员/主管可见
    - 仅允许浏览 data_dir 和 backup_dir 下的内容（白名单）
    - 防止目录穿越（resolve 后校验）
    """
    from urllib.parse import parse_qs, urlparse
    from handlers.admin import get_session

    # 1. 鉴权
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0] or qs.get("path", [None])[0]  # 兼容两种传参方式

    sess = get_session(token) if token else None
    if not sess:
        send_json(handler, 401, {"error": "未登录，请先登录"})
        return

    # 2. 权限检查（仅 admin/supervisor）
    if sess.get("role") not in (ROLE_ADMIN, ROLE_SUPERVISOR):
        send_json(handler, 403, {"error": "权限不足: 仅管理员和主管可访问"})
        return

    # 3. 获取并校验 path 参数
    qs = parse_qs(urlparse(handler.path).query)
    target_path = qs.get("path", [None])[0]

    if not target_path:
        send_json(handler, 400, {"error": "缺少 path 参数"})
        return

    # 4. 白名单校验：仅允许 data_dir 和 backup_dir
    try:
        from storage import get_data_dir
        from handlers.backup import _resolve_backup_parent
        data_dir = get_data_dir()
        backup_dir = _resolve_backup_parent(data_dir)

        allowed_root = data_dir.resolve()
        # 获取请求路径的解析结果
        p = Path(target_path).resolve()

        # 允许浏览 data_dir 及其子目录
        if not str(p).startswith(str(allowed_root)):
            send_json(handler, 403, {"error": f"不允许浏览该路径（仅允许访问 {data_dir}）"})
            return
    except Exception:
        send_json(handler, 403, {"error": "无法验证路径权限"})
        return

    if not p.exists():
        send_json(handler, 404, {"error": f"路径不存在: {target_path}"})
        return

    if p.is_file():
        send_json(handler, 200, {"path": str(p), "entries": []})
        return

    entries = []
    try:
        for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            stat_info = item.stat()
            entries.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "is_file": item.is_file(),
                "size": stat_info.st_size if item.is_file() else 0,
                "modified": datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    except PermissionError:
        send_json(handler, 403, {"error": f"没有权限读取: {target_path}"})
        return
    except OSError as e:
        send_json(handler, 500, {"error": f"读取失败: {e}"})
        return

    send_json(handler, 200, {"path": target_path, "entries": entries})


def handle_get_audit_log(handler):
    """GET /api/admin/audit?count=100 → {logs: [...]}"""
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    count = int(qs.get("count", ["100"])[0])
    from utils.audit import get_audit_log
    logs = get_audit_log(count)
    send_json(handler, 200, {"logs": logs})


# ============ 水电数据迁移 ============

def handle_get_migrate_status(handler):
    """GET /api/admin/migrate-water-status — 检测旧格式水电数据"""
    from handlers._base import get_data_paths as _get_data_paths

    def _load(path, default=None):
        if default is None: default = []
        return load_json(path, default)

    data_paths = _get_data_paths()
    readings = _load(data_paths.get("readings"), [])
    water_file = data_paths.get("readings_water")
    existing_water = _load(water_file) if water_file else []

    # 查找包含水电字段的记录
    water_records = []
    clean_count = 0
    for r in readings:
        if r.get("main_meter") is not None or r.get("sub_meter") is not None or r.get("water") is not None:
            water_records.append(r)
        else:
            clean_count += 1

    # 检查是否有 null 字段残留
    null_water_records = [r for r in readings if any(k in r for k in ("main_meter", "sub_meter", "water")) and r not in water_records]
    needs_migration = bool(water_records or null_water_records)

    if not needs_migration:
        send_json(handler, 200, {
            "needs_migration": False,
            "readings_total": len(readings),
            "existing_water_count": len(existing_water),
            "water_in_readings": 0,
            "message": "数据已经是最新格式，无需迁移。",
        })
        return

    summary_by_date = {}
    for r in water_records:
        date = r["date"]
        fields = []
        if r.get("main_meter") is not None: fields.append("main_meter")
        if r.get("sub_meter") is not None: fields.append("sub_meter")
        if r.get("water") is not None: fields.append("water")
        summary_by_date[date] = {
            "date": date,
            "fields": fields,
        }

    # 检查是否已有同日期的 water 记录
    water_by_date = {w["date"] for w in existing_water}
    conflicts = sum(1 for d in summary_by_date if d in water_by_date)

    send_json(handler, 200, {
        "needs_migration": True,
        "readings_total": len(readings),
        "existing_water_count": len(existing_water),
        "water_in_readings": len(water_records),
        "water_dates": sorted(summary_by_date.keys()),
        "conflicts_with_existing": conflicts,
        "records_preview": list(summary_by_date.values()),
        "message": f"检测到 {len(water_records)} 条抄表记录包含水电字段，需要迁移到独立的 readings_water.json。",
    })


def handle_post_migrate_water(handler):
    """POST /api/admin/migrate-water — 执行水电数据分离"""
    import json as _json
    import shutil as _shutil
    import datetime as _dt
    from storage import DATA_FILES

    readings_path = _get_data_paths().get("readings")
    water_path = _get_data_paths().get("readings_water")

    readings = load_json(readings_path, [])
    existing_water = load_json(water_path, []) if water_path else []

    # 1. 自动备份
    try:
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = readings_path.parent / f"pre-migrate-{ts}"
        backup_dir.mkdir(exist_ok=True)
        for name in ("readings.json", "readings_water.json"):
            src = readings_path.parent / name
            if src.exists():
                _shutil.copy2(src, backup_dir / name)
        log(f"  [MIGRATE] 备份到 {backup_dir}")
    except Exception as e:
        log(f"  [MIGRATE] 备份失败: {e}")
        send_json(handler, 200, {"ok": False, "error": f"备份失败: {e}", "step": "backup"})
        return

    # 2. 分离数据
    water_records = []
    new_readings = []
    for r in readings:
        has_w = r.get("main_meter") is not None or r.get("sub_meter") is not None or r.get("water") is not None
        if has_w:
            water_records.append(r)
        else:
            new_readings.append(r)

    # 清理 null 字段残留
    for r in new_readings:
        for k in ("main_meter", "sub_meter", "water"):
            if k in r:
                del r[k]

    # 构建新 water 数据
    water_by_date = {w["date"]: w for w in existing_water}
    for r in water_records:
        date = r["date"]
        water_by_date[date] = {
            "date": date,
            "main_meter": r.get("main_meter"),
            "sub_meter": r.get("sub_meter"),
            "water": r.get("water"),
            "note": r.get("note", ""),
        }
    new_water = sorted(water_by_date.values(), key=lambda w: w["date"])

    # 3. 验证完整性
    errors = []
    for r in new_readings:
        for k in ("main_meter", "sub_meter", "water"):
            if k in r:
                errors.append(f"{r['date']} 仍包含 {k}")
    migrated_dates = {r["date"] for r in water_records}
    water_dates = {w["date"] for w in new_water}
    if migrated_dates - water_dates:
        errors.append(f"以下日期未迁移: {migrated_dates - water_dates}")

    if errors:
        send_json(handler, 200, {"ok": False, "error": "验证失败: " + "; ".join(errors), "step": "validation"})
        return

    # 4. 写入
    try:
        with open(readings_path, "w", encoding="utf-8") as f:
            _json.dump(new_readings, f, ensure_ascii=False, indent=2)
        with open(water_path, "w", encoding="utf-8") as f:
            _json.dump(new_water, f, ensure_ascii=False, indent=2)
        log(f"  [MIGRATE] 迁移完成: {len(water_records)} 条水电记录已分离")
    except Exception as e:
        log(f"  [MIGRATE] 写入失败: {e}")
        send_json(handler, 200, {"ok": False, "error": f"写入失败: {e}", "step": "write"})
        return

    send_json(handler, 200, {
        "ok": True,
        "total_readings": len(new_readings),
        "total_water": len(new_water),
        "migrated_count": len(water_records),
        "conflicts_overwritten": sum(1 for r in water_records if r["date"] in {w["date"] for w in existing_water}),
        "message": f"✅ 迁移完成！{len(water_records)} 条水电记录已从抄表记录分离到独立的 readings_water.json。",
    })
