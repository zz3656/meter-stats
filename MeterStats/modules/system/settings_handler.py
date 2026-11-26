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
from constants import ROLE_ADMIN


def _get_settings_file(data_dir: Path) -> Path:
    return data_dir / _SETTINGS_FILE


def _load() -> dict:
    """加载 settings.json。"""
    path = _get_settings_file(_get_current_dir())
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _get_current_dir() -> Path:
    """顶层数据目录 —— settings.json 是全局配置,不随门店变化。

    注意:不要在这里返回门店目录。settings.json 存放用户表、门店注册表和部署配置,
    是所有门店共享的;门店自己的表定义/价格在 stores/<id>/store.json。
    """
    from modules.stores.context import base_data_dir
    return base_data_dir()


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
                "main_mult": 50,   # 总表倍率
                "sub_mult": 40,    # 分表倍率
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


def get_next_user_id(users: List[Dict[str, Any]]) -> int:
    return max((u.get("id", 0) for u in users), default=0) + 1


def add_user(users: List[Dict[str, Any]], username: str, password: str, name: str, role: str,
             store_ids: Optional[List[str]] = None,
             all_stores: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    """新增用户。

    门店归属:
    - all_stores 省略时:admin 默认 True(总部账号,可跨店),其它角色默认 False
    - store_ids 是该用户可访问的门店 ID 列表;非总部账号必须有值才能看到数据
    """
    if any(u["username"] == username for u in users):
        return {"error": "用户名已存在"}
    users.append({
        "id": get_next_user_id(users),
        "username": username,
        "password": _hash_pass(password),
        "role": role,
        "name": name,
        "enabled": True,
        "all_stores": (role == ROLE_ADMIN) if all_stores is None else bool(all_stores),
        "store_ids": list(store_ids) if isinstance(store_ids, list) else [],
        "created_at": datetime.now().isoformat(),
    })
    return users[-1]


def update_user(users: List[Dict[str, Any]], uid: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新用户。门店归属字段:store_ids / all_stores。

    改角色时必须一起重算 all_stores ——
    一个 admin 被降级成 employee 后如果 all_stores 还留着 True,
    他仍然是「总部账号」,能看全部门店(降级形同虚设)。
    """
    for u in users:
        if u["id"] == uid:
            for k in ("username", "name", "role", "enabled"):
                if k in fields:
                    u[k] = fields[k]
            if "all_stores" in fields:
                u["all_stores"] = bool(fields["all_stores"])
            elif "role" in fields:
                # 本次没显式传 all_stores → 按新角色重算:
                # 降级 → False(不再是总部账号);
                # 升级 → 只有旧记录本来就没有这个字段才默认 True
                #         (老 settings.json 里的用户记录没有 all_stores)。
                if u["role"] != ROLE_ADMIN:
                    u["all_stores"] = False
                elif "all_stores" not in u:
                    u["all_stores"] = True
            if "store_ids" in fields:
                v = fields["store_ids"]
                u["store_ids"] = [str(x) for x in v] if isinstance(v, list) else []
            if "password" in fields and fields["password"]:
                u["password"] = _hash_pass(fields["password"])
            return u
    return None


def save_users_verified(settings: Dict[str, Any], user_id: int) -> None:
    """保存 settings,并**回读校验**目标用户的门店归属真的落盘了。

    为什么必须回读:_save() 会吞掉所有异常(只往 stderr 打一行
    `[settings] [WARN] _save failed:`),写失败时调用方会以为成功 ——
    管理员看到「分配成功」,用户实际没落盘。而门店闸
    (registry.user_store_scope 实时读 settings.json)查不到他的 store_ids →
    直接 403,用户被锁在自己门店外面。

    与 registry._persist() 同一套思路:写 → 回读 → 比对 → 不通过就抛错。
    """
    try:
        save_settings(settings)
    except Exception as e:
        raise RuntimeError(f"保存 settings.json 失败: {e}") from e
    _verify_user_persisted(settings, user_id)


def _verify_user_persisted(settings: Dict[str, Any], user_id: int) -> None:
    """回读 settings.json,确认目标用户的门店归属真的落盘了。

    比对:目标用户是否存在 + role / all_stores / store_ids 是否一致。
    不通过就抛 RuntimeError —— 调用方绝不能以为「门店已分配」。
    """
    try:
        on_disk = get_settings()
    except Exception as e:
        raise RuntimeError(f"写入 settings.json 后回读失败: {e}") from e
    expected = _find_user(settings.get("users") or [], user_id)
    actual = _find_user(on_disk.get("users") or [], user_id)
    if expected is None:
        raise RuntimeError(
            f"写入 settings.json 后回读校验不通过: 内存里找不到用户 {user_id}")
    if actual is None:
        raise RuntimeError(
            f"写入 settings.json 后回读校验不通过: 用户 {user_id} 没有落盘")
    for field in ("role", "all_stores"):
        if actual.get(field) != expected.get(field):
            raise RuntimeError(
                f"写入 settings.json 后回读校验不通过: 用户 {user_id} 的 {field} "
                f"落盘值 {actual.get(field)!r} ≠ 预期 {expected.get(field)!r}")
    if _store_ids_signature(actual) != _store_ids_signature(expected):
        raise RuntimeError(
            f"写入 settings.json 后回读校验不通过: 用户 {user_id} 的 store_ids 不一致")


def _find_user(users: List[Dict[str, Any]], user_id: int) -> Optional[Dict[str, Any]]:
    """按 id 找用户记录。找不到返回 None。"""
    for u in users:
        if isinstance(u, dict) and u.get("id") == user_id:
            return u
    return None


def _store_ids_signature(user: Dict[str, Any]) -> List[str]:
    """用户门店归属的可比签名(排序后比较,忽略顺序差异)。"""
    ids = user.get("store_ids")
    if not isinstance(ids, list):
        return []
    return sorted(str(x) for x in ids)


def delete_user(users: List[dict], uid: int) -> bool:
    original = len(users)
    users[:] = [u for u in users if u["id"] != uid]
    return len(users) < original


def _init_audit(data_dir: Path, settings: dict) -> dict:
    """初始化审计日志。"""
    from utils.audit import init_audit_log
    init_audit_log(data_dir)
    return settings
