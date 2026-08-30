"""设置:用户、权限、电表倍率/价格配置。
存储于 data_dir/settings.json。
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import threading

_SETTINGS_LOCK = threading.Lock()
_SETTINGS_FILE = "settings.json"
_DEFAULT_USER = "admin"
_DEFAULT_PASS = "admin123"

# 权限级别
ROLE_ADMIN = "admin"       # 管理员:全部权限
ROLE_SUPERVISOR = "supervisor"  # 主管:录入+编辑+删除+管理
ROLE_EMPLOYEE = "employee"      # 员工:仅录入+编辑

ROLES = {ROLE_ADMIN: "管理员", ROLE_SUPERVISOR: "主管", ROLE_EMPLOYEE: "员工"}


def _get_settings_file(data_dir: Path) -> Path:
    return data_dir / _SETTINGS_FILE


def _load() -> dict:
    """加载 settings.json。"""
    return json.load(open(_get_settings_file(_get_current_dir()), "r", encoding="utf-8"))


def _get_current_dir() -> Path:
    """从 app_handler 获取数据目录。"""
    import app_handler as _h
    return _h.DATA_PATHS.get("readings", Path.home()).parent


def _save(data: dict):
    with _SETTINGS_LOCK:
        path = _get_settings_file(_get_current_dir())
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def init_settings(data_dir: Path):
    """初始化 settings.json（如果不存在）。

    初始管理员用户名/密码可通过环境变量覆盖:
      - METER_INITIAL_ADMIN（默认 admin）
      - METER_INITIAL_PASS（默认 admin123）
    仅首次创建时生效;settings.json 已存在时忽略。
    """
    import os
    path = _get_settings_file(data_dir)
    if path.exists():
        return
    username = os.environ.get("METER_INITIAL_ADMIN", "").strip() or _DEFAULT_USER
    password = os.environ.get("METER_INITIAL_PASS", "").strip() or _DEFAULT_PASS
    default = {
        "users": [
            {
                "id": 1,
                "username": username,
                "password": _hash_pass(password),
                "role": ROLE_ADMIN,
                "name": "管理员",
                "enabled": True,
                "created_at": datetime.now().isoformat(),
            }
        ],
        "meter": {
            "hall": {"label": "大厅", "icon": "🎤", "multiplier": 160, "color": "#2563eb"},
            "fire": {"label": "消防", "icon": "🧯", "multiplier": 1, "color": "#dc2626"},
            "private_room": {"label": "包厢", "icon": "🛋️", "multiplier": 160, "color": "#059669"},
            "ac": {"label": "空调", "icon": "❄️", "multiplier": 160, "color": "#d97706"},
        },
        "config": {
            "electricity_price": 0.9,
            "water_price": 4.5,
        },
    }
    _save(default)


def get_settings() -> dict:
    """读取全部 settings（线程安全）。"""
    return _load()


def save_settings(data: dict):
    """保存全部 settings。"""
    _save(data)


def _hash_pass(password: str) -> str:
    """简单哈希:实际部署可换 hashlib.sha256。"""
    import hashlib
    return "sha256:" + hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """验证密码。"""
    return _hash_pass(password) == hashed


def get_next_user_id(users: List[dict]) -> int:
    return max((u.get("id", 0) for u in users), default=0) + 1


def add_user(users: List[dict], username: str, password: str, name: str, role: str) -> Optional[dict]:
    if any(u["username"] == username for u in users):
        return {"error": "用户名已存在"}
    users.append({
        "id": get_next_user_id(users),
        "username": username,
        "password": _hash_pass(password),
        "role": role,
        "name": name,
        "enabled": True,
        "created_at": datetime.now().isoformat(),
    })
    return users[-1]


def update_user(users: List[dict], uid: int, fields: dict) -> Optional[dict]:
    for u in users:
        if u["id"] == uid:
            for k in ("username", "name", "role", "enabled"):
                if k in fields:
                    u[k] = fields[k]
            if "password" in fields and fields["password"]:
                u["password"] = _hash_pass(fields["password"])
            return u
    return None


def delete_user(users: List[dict], uid: int) -> bool:
    original = len(users)
    users[:] = [u for u in users if u["id"] != uid]
    return len(users) < original


def delete_user_by_username(users: List[dict], username: str) -> bool:
    original = len(users)
    users[:] = [u for u in users if u["username"] != username]
    return len(users) < original
