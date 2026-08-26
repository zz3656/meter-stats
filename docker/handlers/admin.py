"""认证 + 后台管理 API handler。
"""
from __future__ import annotations
import datetime
import os
import secrets
from pathlib import Path
from utils import send_json, read_body
from handlers.settings import (
    get_settings, save_settings, init_settings, verify_password,
    add_user, update_user, delete_user, ROLES,
)


def _get_data_paths():
    import app_handler as _h
    return _h.DATA_PATHS


# 会话存储: session_id -> {user_id, username, role, name}
_SESSIONS: dict = {}
SESSION_SECRET = secrets.token_hex(32)


def handle_post_login(handler):
    """POST /api/auth/login {username, password} → {ok, token, user}"""
    body = read_body(handler)
    username = (body or {}).get("username", "").strip()
    password = (body or {}).get("password", "")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    settings = get_settings()
    users = settings.get("users", [])
    user = next((u for u in users if u["username"] == username), None)

    if not user or not user.get("enabled", True):
        send_json(handler, 200, {"ok": False, "error": "用户不存在或已禁用"})
        return

    if not verify_password(password, user["password"]):
        send_json(handler, 200, {"ok": False, "error": "密码错误"})
        return

    token = secrets.token_hex(32)
    _SESSIONS[token] = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "name": user["name"],
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }

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
    if token and token in _SESSIONS:
        del _SESSIONS[token]
    send_json(handler, 200, {"ok": True})


def handle_get_me(handler):
    """GET /api/auth/me?token=xxx → {user} or {user: null}"""
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0]

    if token and token in _SESSIONS:
        sess = _SESSIONS[token]
        send_json(handler, 200, {"user": {
            "id": sess["user_id"],
            "username": sess["username"],
            "name": sess["name"],
            "role": sess["role"],
        }})
    else:
        send_json(handler, 200, {"user": None})


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
    """GET /api/admin/backup-status → {auto_backup, backup_count, backups: [...]}"""
    import zipfile
    import io
    from storage import get_data_dir
    settings = get_settings()
    auto_backup = settings.get("auto_backup", True)
    data_dir = get_data_dir()
    backup_dir = data_dir / "backup"
    
    # 列出所有备份目录（只返回 count 给旧前端兼容）
    backup_entries = []
    if backup_dir.exists():
        for d in sorted(backup_dir.iterdir(), reverse=True):
            if d.is_dir():
                # 统计备份中的文件数量和总大小
                file_count = 0
                total_size = 0
                try:
                    for f in d.iterdir():
                        if f.is_file():
                            file_count += 1
                            total_size += f.stat().st_size
                except OSError:
                    pass
                backup_entries.append({
                    "name": d.name,
                    "file_count": file_count,
                    "total_size": total_size,
                    "created_at": datetime.utcfromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
    
    send_json(handler, 200, {
        "auto_backup": auto_backup,
        "backup_count": len(backup_entries),
        "data_dir": str(data_dir),
        "backups": backup_entries,
    })


def handle_get_backup_download(handler):
    """GET /api/admin/backup-download?dir=YYYYMMDD_HHMMSS → 下载 .zip 文件"""
    import zipfile
    import io
    from storage import get_data_dir
    from urllib.parse import parse_qs, urlparse
    
    data_dir = get_data_dir()
    backup_dir = data_dir / "backup"
    
    qs = parse_qs(urlparse(handler.path).query)
    dir_name = qs.get("dir", [None])[0]
    
    if not dir_name:
        send_json(handler, 400, {"error": "缺少 dir 参数"})
        return
    
    src = backup_dir / dir_name
    if not src.is_dir():
        send_json(handler, 404, {"error": f"备份目录不存在: {dir_name}"})
        return
    
    # 创建 zip 内存流
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in src.rglob('*'):
            if f.is_file():
                zf.write(f, f.name)
    
    zip_buffer.seek(0)
    zip_data = zip_buffer.read()
    
    # 设置响应头
    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Disposition", f'attachment; filename="linclub-backup-{dir_name}.zip"')
    handler.send_header("Content-Length", str(len(zip_data)))
    from utils import CORS
    for k, v in CORS.items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(zip_data)


def handle_put_auto_backup(handler):
    """PUT /api/admin/auto-backup {enabled: true/false}"""
    body = read_body(handler)
    settings = get_settings()
    settings["auto_backup"] = bool((body or {}).get("enabled", True))
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "auto_backup": settings["auto_backup"]})


# ============ 备份目录配置 ============

def handle_get_backup_config(handler):
    """GET /api/admin/backup-config → {backup_dir: "/path" | null, backup_dir_label: "..."}"""
    from storage import get_data_dir
    data_dir = get_data_dir()

    settings = get_settings()
    backup_dir = settings.get("backup_dir")
    backup_dir_label = settings.get("backup_dir_label")
    send_json(handler, 200, {
        "ok": True,
        "backup_dir": backup_dir,
        "backup_dir_label": backup_dir_label,
        "data_dir": str(data_dir),
    })


def handle_put_backup_config(handler):
    """PUT /api/admin/backup-config → {backup_dir: "/path" | null}

    - {backup_dir: "/path", backup_dir_label: "My Backups"} → 设置备份目录
    - {backup_dir: null} → 清除备份目录（恢复默认行为）
    """
    body = read_body(handler)
    settings = get_settings()

    new_dir = (body or {}).get("backup_dir")
    if new_dir is None:
        # 清除备份目录设置
        settings.pop("backup_dir", None)
        settings.pop("backup_dir_label", None)
    elif new_dir:
        # 设置备份目录
        label = (body or {}).get("backup_dir_label", "")
        settings["backup_dir"] = str(new_dir)
        settings["backup_dir_label"] = label
    # 如果 new_dir is None 但被显式传递（某些情况），不做任何事

    save_settings(settings)
    # 计算当前数据目录
    from storage import get_data_dir
    data_dir = str(get_data_dir())
    send_json(handler, 200, {
        "ok": True,
        "backup_dir": settings.get("backup_dir"),
        "backup_dir_label": settings.get("backup_dir_label"),
        "data_dir": data_dir,
    })
