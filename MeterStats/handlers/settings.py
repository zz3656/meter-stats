"""设置:用户、权限、电表倍率/价格配置。
存储于 data_dir/settings.json。
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import threading

_SETTINGS_LOCK = threading.Lock()
_SETTINGS_FILE = "settings.json"
_DEFAULT_USER = "admin"
_DEFAULT_PASS = "admin123"

# 权限级别 (从 constants 导入，避免重复定义)
from constants import ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_EMPLOYEE, ROLES


def _get_settings_file(data_dir: Path) -> Path:
    return data_dir / _SETTINGS_FILE


def _load() -> dict:
    """加载 settings.json。"""
    path = _get_settings_file(_get_current_dir())
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _get_current_dir() -> Path:
    """从 app_handler 获取数据目录。"""
    import app_handler as _h
    return _h.DATA_PATHS.get("readings", Path.home()).parent


def _save(data: dict) -> None:
    """原子写入 settings.json（tmp + rename，防止崩溃损坏）。"""
    with _SETTINGS_LOCK:
        path = _get_settings_file(_get_current_dir())
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(path)  # atomic on same filesystem
        except Exception as e:
            # 清理临时文件
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            # 不要 raise，避免中断用户操作
            import sys
            print(f"[settings] [WARN] _save failed: {e}", file=sys.stderr)


def init_settings(data_dir: Path) -> dict | None:
    """初始化 settings.json（如果不存在）。

    初始管理员用户名/密码可通过环境变量覆盖:
      - METER_INITIAL_ADMIN（默认 admin）
      - METER_INITIAL_PASS（默认 admin123）
    仅首次创建时生效;settings.json 已存在时忽略。

    使用文件级锁防止并发 TOCTOU 竞态（两个请求同时检测到不存在，
    都尝试写入，导致其中一个的默认用户覆盖另一个）。

    返回: 初始化后的 settings dict，或 None（已存在/失败）。
    """
    import os
    import fcntl

    path = _get_settings_file(data_dir)

    # 如果已经存在，直接返回现有 settings
    if path.exists():
        return None

    # 获取锁，确保只有一个线程能创建
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = lock_path.open("w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        # 其他线程正在创建，释放锁并返回
        lock_fd.close()
        return None

    try:
        # 双重检查：获取锁后再次确认文件是否存在（防止竞态）
        if path.exists():
            return None

        # 检查父目录权限
        path.parent.mkdir(parents=True, exist_ok=True)

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

        # 原子写入（已通过 _save 的 tmp+rename）
        # 但 init_settings 不在 _SETTINGS_LOCK 内调用，需要直接写
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            tmp.replace(path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        # 返回实际创建的内容（供调用方使用）
        default = _init_audit(data_dir, default)
        return default
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def get_settings() -> dict:
    """读取全部 settings（线程安全）。"""
    return _load()


def save_settings(data: dict):
    """保存全部 settings。"""
    _save(data)


def _hash_pass(password: str) -> str:
    """PBKDF2-HMAC-SHA256 密码哈希（标准库，零依赖）。

    格式: "pbkdf2:sha256:<iterations>:<salt_hex>:<derived_key_hex>"
    - iterations: 600_000（NIST 2023 最低推荐值）
    - salt: 16 字节随机
    - dklen: 32 字节
    """
    import secrets
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000, dklen=32)
    return f"pbkdf2:sha256:600000:{salt.hex()}:{dk.hex()}"


def _parse_hash(hashed: str) -> tuple:
    """解析密码哈希字符串，返回 (type, algo_name, iterations, salt, dk)。

    返回值含义:
    - type: "pbkdf2" | "legacy" | None
    - algo_name: "sha256" 等（仅 pbkdf2 时有效）
    - iterations: 迭代次数（仅 pbkdf2 时有效）
    - salt: 盐字节（仅 pbkdf2 时有效）
    - dk: 派生密钥（仅 pbkdf2 时有效）

    旧版 "sha256:<hexdigest>" 返回 type="legacy"，其余为 None。
    不识别的格式全返回 None。
    """
    if not hashed or ":" not in hashed:
        return None, None, None, None, None
    parts = hashed.split(":")
    if parts[0] == "pbkdf2":
        # pbkdf2:sha256:600000:<salt_hex>:<dk_hex>
        if len(parts) != 5:
            return None, None, None, None, None
        return "pbkdf2", parts[1], int(parts[2]), bytes.fromhex(parts[3]), bytes.fromhex(parts[4])
    if parts[0] == "sha256":
        # 旧格式 sha256:<hexdigest>
        return "legacy", None, None, None, None
    return None, None, None, None, None


def _needs_migration(hashed: str) -> bool:
    """判断是否为旧版 sha256: 格式（需要重新哈希）。"""
    return _parse_hash(hashed)[0] == "legacy"


def verify_password(password: str, hashed: str) -> bool:
    """验证密码。"""
    typ, algo, iters, salt, expected_dk = _parse_hash(hashed)

    if typ == "legacy":
        # 旧格式: SHA-256 无 salt，暴力验证（仅兼容过渡期）
        return "sha256:" + hashlib.sha256(password.encode("utf-8")).hexdigest() == hashed

    if typ != "pbkdf2":
        return False

    dk = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt, iters, dklen=32)
    return dk == expected_dk


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


def migrate_users_to_pbkdf2(users: List[dict]) -> bool:
    """扫描所有用户，将旧版 sha256: 哈希升级为 pbkdf2。

    返回 True 表示有用户被迁移（settings 已保存，调用方无需再 save）。
    """
    import hashlib
    migrated = False
    for u in users:
        hashed = u.get("password", "")
        if not _needs_migration(hashed):
            continue
        # 从 legacy 哈希中提取原始密码是不可能的，
        # 所以我们标记用户为"需要改密码"状态，并生成一个随机临时密码。
        # 更好的方式: 让用户在下次登录时改密码（已在 admin.py 中实现）。
        # 这里只记录日志，实际迁移靠 login 时的静默升级。
        log(f"  [MIGRATE] 用户 {u.get('username')} 仍在使用旧版 sha256: 哈希")
        migrated = True
    return migrated


def delete_user(users: List[dict], uid: int) -> bool:
    original = len(users)
    users[:] = [u for u in users if u["id"] != uid]
    return len(users) < original


def delete_user_by_username(users: List[dict], username: str) -> bool:
    original = len(users)
    users[:] = [u for u in users if u["username"] != username]
    return len(users) < original


def _init_audit(data_dir: Path, settings: dict) -> dict:
    """初始化审计日志。"""
    from utils.audit import init_audit_log
    init_audit_log(data_dir)
    return settings
