"""门店注册表 —— settings.json 里的 stores[] 分区。

门店注册表是全局的(所有门店共用一份 settings.json),只存门店的元信息:
ID、名称、编号、地址、是否启用。门店自己的数据在 stores/<id>/ 目录下。

门店 ID 规则:只允许字母、数字、下划线、连字符,长度 1-32。
ID 会拼进文件路径,必须挡住路径穿越("../" 等)。

settings 参数的约定:
    传入了就用传入的那份 dict(调用方自己负责落盘),不传就读写全局
    settings.json。两种用法都支持,便于单元测试直接喂一份内存里的配置。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DEFAULT_STORE_ID = "main"
DEFAULT_STORE_NAME = "总店"

_STORE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def is_valid_store_id(store_id: str) -> bool:
    """门店 ID 是否合法(可安全用作目录名)。"""
    if not isinstance(store_id, str) or not store_id:
        return False
    return bool(_STORE_ID_RE.match(store_id))


def _load_settings(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    """拿到可写的 settings dict。传入了就用传入的,否则读全局 settings.json。"""
    if settings is not None:
        return settings
    from modules.system.settings_handler import get_settings
    return get_settings()


def _persist(settings: dict[str, Any]) -> None:
    """把改动写回 settings.json。"""
    from modules.system.settings_handler import save_settings
    save_settings(settings)


def list_stores(settings: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """全部门店(按创建顺序)。"""
    st = _load_settings(settings)
    stores = st.get("stores")
    if not isinstance(stores, list):
        return []
    return [s for s in stores if isinstance(s, dict)]


def get_store(store_id: str, settings: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """按 ID 查门店;不存在返回 None。"""
    for s in list_stores(settings):
        if s.get("id") == store_id:
            return s
    return None


def ensure_default_store(settings: dict[str, Any]) -> dict[str, Any]:
    """确保注册表里有默认店(总店)。已存在则原样返回。

    顺带把 stores 规整成 list —— settings.json 被人手改坏时也能自愈。
    """
    stores = settings.setdefault("stores", [])
    if not isinstance(stores, list):
        stores = []
        settings["stores"] = stores
    for s in stores:
        if isinstance(s, dict) and s.get("id") == DEFAULT_STORE_ID:
            return s
    store = {
        "id": DEFAULT_STORE_ID,
        "name": DEFAULT_STORE_NAME,
        "code": "",
        "address": "",
        "active": True,
        "created_at": _now(),
    }
    stores.append(store)
    return store


def add_store(store_id: str, name: str, code: str = "", address: str = "",
              settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """新增门店。ID 非法或重复时抛 ValueError。

    同时创建 stores/<id>/ 目录和空的 6 个数据文件 —— 分店建好就能直接用。

    总店(默认店)必须始终在注册表里:挂分店之前先 ensure_default_store(),
    否则注册表里会出现「有分店、没总店」的畸形状态。
    """
    if not is_valid_store_id(store_id):
        raise ValueError(f"门店 ID 非法(只允许字母/数字/下划线/连字符,1-32 位): {store_id}")
    if not name or not str(name).strip():
        raise ValueError("门店名称不能为空")
    st = _load_settings(settings)
    if get_store(store_id, settings=st) is not None:
        raise ValueError(f"门店已存在: {store_id}")
    ensure_default_store(st)
    store: dict[str, Any] = {
        "id": store_id,
        "name": str(name).strip(),
        "code": (code or "").strip(),
        "address": (address or "").strip(),
        "active": True,
        "created_at": _now(),
    }
    # 先把分店建好(目录 + 数据文件 + store.json),再写注册表 ——
    # 建目录失败时注册表里不留半条记录,不会出现「有门店、没数据」的坏状态。
    _create_store_files(store_id, store["name"])
    st["stores"].append(store)
    if settings is None:
        _persist(st)
    return store


def update_store(store_id: str, fields: dict[str, Any],
                 settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """修改门店元信息。可改字段: name / code / address / active。"""
    st = _load_settings(settings)
    store = get_store(store_id, settings=st)
    if store is None:
        raise ValueError(f"门店不存在: {store_id}")
    if "name" in fields and not str(fields["name"] or "").strip():
        raise ValueError("门店名称不能为空")
    for k in ("name", "code", "address", "active"):
        if k in fields:
            store[k] = fields[k]
    if settings is None:
        _persist(st)
    return store


def delete_store(store_id: str, settings: Optional[dict[str, Any]] = None) -> bool:
    """删除门店(默认店不可删)。只删注册表条目,不删数据目录。

    返回 True = 已删除。
    """
    if store_id == DEFAULT_STORE_ID:
        return False
    st = _load_settings(settings)
    stores = st.get("stores") or []
    new_list = [s for s in stores if not (isinstance(s, dict) and s.get("id") == store_id)]
    if len(new_list) == len(stores):
        return False
    st["stores"] = new_list
    if settings is None:
        _persist(st)
    return True


def user_store_scope(user_id: int,
                     settings: Optional[dict[str, Any]] = None) -> Optional[tuple[bool, list[str]]]:
    """查用户的门店范围。

    返回 (all_stores, store_ids);用户不存在返回 None。
    all_stores 为 True 表示总部账号,可访问全部门店。

    没有 all_stores 字段时:admin 默认为 True(总部账号),其它角色默认 False。
    """
    st = _load_settings(settings)
    for u in st.get("users") or []:
        if not isinstance(u, dict):
            continue
        if u.get("id") != user_id:
            continue
        role = u.get("role", "employee")
        all_stores = bool(u.get("all_stores", role == "admin"))
        ids = u.get("store_ids")
        store_ids = [str(x) for x in ids] if isinstance(ids, list) else []
        return (all_stores, store_ids)
    return None


def _now() -> str:
    return datetime.now().isoformat()


def _create_store_files(store_id: str, name: str = "") -> None:
    """创建门店目录 + 空的 6 个数据文件 + 默认 store.json。"""
    from modules.stores import config
    from storage import DATA_FILES, save_json
    d = context_store_dir(store_id)
    d.mkdir(parents=True, exist_ok=True)
    for fname in DATA_FILES.values():
        p = d / fname
        if not p.exists():
            save_json(p, [])
    cfg_path = config.store_config_path(store_id)
    if not cfg_path.exists():
        config.write_store_config(store_id, {
            "id": store_id,
            "name": name,
            "meters": [dict(m) for m in config.DEFAULT_METERS],
            "config": dict(config.DEFAULT_CONFIG),
        })


def context_store_dir(store_id: str) -> Path:
    """薄封装,避免 registry 直接 import context 造成循环依赖。"""
    from modules.stores.context import store_dir
    return store_dir(store_id)
