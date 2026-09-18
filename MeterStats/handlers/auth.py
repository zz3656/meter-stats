"""认证与会话管理 — 登录、登出、查询当前用户、会话列表。
从原 handlers.admin.py 拆分而来,保持 API 行为完全一致。
"""
from __future__ import annotations
import datetime
import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from handlers.settings import (
    get_settings, save_settings, verify_password, _needs_migration, _hash_pass,
)
from storage import log


# ============ 会话管理(带 TTL 自动清理) ============

# 会话超时:30 分钟无活动自动过期
SESSION_TIMEOUT_SECONDS = 30 * 60
# 清理间隔:每 5 分钟清理一次过期会话
SESSION_CLEANUP_INTERVAL = 5 * 60

# 会话存储: token -> {user_id, username, role, name, created_at, last_access}
_SESSIONS: dict = {}
_SESSIONS_LOCK = threading.Lock()

# 上次清理时间戳(用于懒清理)
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

    使用滑动窗口算法:
    - 5 分钟内最多尝试 10 次
    - 超限后进入 2 分钟冷却期
    - 只记录密码错误的尝试

    返回: (allowed, message)
    """
    now = time.time()
    with _LOGIN_ATTEMPTS_LOCK:
        attempts = _LOGIN_ATTEMPTS.get(username, [])

        # 清理过期记录(只保留窗口内)
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
                return False, f"尝试次数过多,请在 {remaining_min} 分钟后再试"

        # 检查窗口内总尝试次数
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            return False, f"尝试次数过多,请在 {_LOGIN_WINDOW_SECONDS // 60} 分钟后再试"

    return True, ""


def _record_login_attempt(username: str, success: bool) -> None:
    """记录登录尝试(仅记录密码错误的)。"""
    if success:
        # 成功登录,清理该用户的所有历史记录(防止旧失败记录累积)
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
    """获取会话(同时检查过期和懒清理)。"""
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
            # 过期会话:读完即扔
            del _SESSIONS[token]
            return None
        return sess


def create_session(user: dict) -> str:
    """创建新会话,返回 token。"""
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
    """获取当前活跃会话数(不含已清理的)。"""
    _cleanup_expired_sessions()
    with _SESSIONS_LOCK:
        return len(_SESSIONS)


# ============ HTTP Handlers ============

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

    # 登录成功,记录并清理旧失败记录
    _record_login_attempt(username, True)

    # 检测到旧版 sha256: 哈希 → 登录成功后静默升级为 pbkdf2
    if _needs_migration(user["password"]):
        users = settings.get("users", [])
        for u in users:
            if u["id"] == user["id"]:
                u["password"] = _hash_pass(password)
                save_settings(settings)
                log(f"  [AUTH] 用户 {username} 密码已自动升级为 pbkdf2")
                break

    # 创建新会话(含 TTL)
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
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0]
    destroy_session(token)
    send_json(handler, 200, {"ok": True})


def handle_get_me(handler):
    """GET /api/auth/me?token=xxx → {user} or {user: null}"""
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

    仅管理员可见,用于查看当前在线用户和会话状态。
    """
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
