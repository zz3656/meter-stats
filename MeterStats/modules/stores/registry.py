"""门店注册表 —— settings.json 里的 stores[] 分区。

门店注册表是全局的(所有门店共用一份 settings.json),只存门店的元信息:
ID、名称、编号、地址、是否启用。门店自己的数据在 stores/<id>/ 目录下。

门店 ID 规则:只允许字母、数字、下划线、连字符,长度 1-32。
ID 会拼进文件路径,必须挡住路径穿越("../" 等)。

大小写:macOS(本项目 .app 的主力平台)与 Windows 的文件系统大小写不敏感,
stores/MAIN 与 stores/main 是**同一个目录**。所以注册表除了拒绝完全相同的 ID,
还拒绝大小写不相同的 ID —— 否则新建的"分店"会静默读写总店的数据。
不做"统一转小写":已有门店的 ID 可能已经被用户看到、用过了,
静默改写 ID 比拒绝新增更糟。

本模块交出去的门店 dict 一律是**深拷贝** —— 调用方改不动注册表本体。
(深拷贝而不是浅拷贝:门店记录将来会带上列表字段(Task 6 的 store_ids),
浅拷贝会让调用方改坏注册表本体 —— docstring 承诺过的事必须兑现。)

settings 参数的约定:
    传入了就用传入的那份 dict(调用方自己负责落盘),不传就读写全局
    settings.json。两种用法都支持,便于单元测试直接喂一份内存里的配置。
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DEFAULT_STORE_ID = "main"
DEFAULT_STORE_NAME = "总店"

# \A...\Z 而不是 ^...$ —— 正则的 $ 会匹配"末尾换行之前",
# "s002\n" 能混进目录名、日志和 JSON。
_STORE_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,32}\Z")


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
    """把改动写回 settings.json,并回读确认真的落盘了。

    settings_handler.save_settings() 会吞掉所有异常(只往 stderr 打一行
    `[settings] [WARN] _save failed:`),写失败时调用方会以为成功 ——
    门店就「建好了却不在注册表里」,Task 4 的门店闸会拒掉它的每一个请求,
    还留下一个孤儿目录。所以写完必须回读校验,不通过就抛错。
    """
    from modules.system.settings_handler import save_settings
    save_settings(settings)
    _verify_persisted(settings)


def _verify_persisted(settings: dict[str, Any]) -> None:
    """回读 settings.json,确认 stores[] 真的落盘了。

    不通过就抛 RuntimeError —— 调用方绝不能以为「门店已创建」。
    """
    from modules.system.settings_handler import get_settings
    try:
        on_disk = get_settings()
    except Exception as e:
        raise RuntimeError(f"写入 settings.json 后回读失败: {e}") from e
    if _stores_signature(on_disk) != _stores_signature(settings):
        raise RuntimeError("写入 settings.json 失败(回读校验不通过,门店注册表未落盘)")


def _stores_signature(st: dict[str, Any]) -> str:
    """stores[] 的可比签名 —— 用于「写完回读」的一致性校验。"""
    return json.dumps(st.get("stores") or [], ensure_ascii=False, sort_keys=True, default=str)


def list_stores(settings: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """全部门店(按创建顺序)。返回深拷贝 —— 调用方改不动注册表本体。"""
    st = _load_settings(settings)
    stores = st.get("stores")
    if not isinstance(stores, list):
        return []
    return [copy.deepcopy(s) for s in stores if isinstance(s, dict)]


def get_store(store_id: str, settings: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """按 ID 查门店;不存在返回 None。返回深拷贝。"""
    store = _live_store(_load_settings(settings), store_id)
    if store is None:
        return None
    return copy.deepcopy(store)


def _live_store(st: dict[str, Any], store_id: str) -> Optional[dict[str, Any]]:
    """注册表里那条活着的门店记录(内部用 —— 改动要落回本体)。"""
    stores = st.get("stores")
    if not isinstance(stores, list):
        return None
    for s in stores:
        if isinstance(s, dict) and s.get("id") == store_id:
            return s
    return None


def ensure_default_store(settings: dict[str, Any]) -> dict[str, Any]:
    """确保注册表里有默认店(总店)。已存在则原样返回。

    顺带把 stores 规整成 list —— settings.json 被人手改坏时也能自愈。

    返回的是深拷贝 —— 改它不会改到注册表本体。
    (对传入的 settings dict 的原地修改保持不变 —— Task 3 的迁移逻辑
     依赖这个行为:它用「调用前取快照 + 调用后比对」判定注册表是否落盘。)
    """
    stores = settings.setdefault("stores", [])
    if not isinstance(stores, list):
        stores = []
        settings["stores"] = stores
    for s in stores:
        if isinstance(s, dict) and s.get("id") == DEFAULT_STORE_ID:
            return copy.deepcopy(s)
    store: dict[str, Any] = {
        "id": DEFAULT_STORE_ID,
        "name": DEFAULT_STORE_NAME,
        "code": "",
        "address": "",
        "active": True,
        "created_at": _now(),
    }
    stores.append(store)
    return copy.deepcopy(store)


def add_store(store_id: str, name: str, code: str = "", address: str = "",
              settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """新增门店。ID 非法或重复时抛 ValueError。

    同时创建 stores/<id>/ 目录和空的 6 个数据文件 —— 分店建好就能直接用。

    顺序很关键:校验 → ensure_default_store() → 重复检查 → 落盘 → 建目录。
    重复检查必须排在 ensure_default_store() **之后** —— 默认店刚被补上时,
    前面的检查还没看到它,就会再 append 一条 main,注册表里出现两条总店
    (而 delete_store() 拒绝删 main → 两条都删不掉)。
    """
    if not is_valid_store_id(store_id):
        raise ValueError(f"门店 ID 非法(只允许字母/数字/下划线/连字符,1-32 位): {store_id}")
    if not name or not str(name).strip():
        raise ValueError("门店名称不能为空")
    st = _load_settings(settings)
    # 总店(默认店)必须始终在注册表里
    ensure_default_store(st)
    if _live_store(st, store_id) is not None:
        raise ValueError(f"门店已存在: {store_id}")
    _reject_case_insensitive_conflict(st, store_id)
    store: dict[str, Any] = {
        "id": store_id,
        "name": str(name).strip(),
        "code": (code or "").strip(),
        "address": (address or "").strip(),
        "active": True,
        "created_at": _now(),
    }
    st["stores"].append(store)
    if settings is None:
        # 注册表先落盘,再建目录 —— 与 Task 3 迁移同一个道理:
        # 反过来的话,目录建好了而注册表写失败 → stores/ 目录出现 →
        # multi_store_layout() 变 True,但注册表里没有已注册门店 →
        # 门店闸把全站请求都拒掉。先写注册表则反之无风险。
        _persist(st)
    try:
        _create_store_files(store_id, store["name"])
    except Exception as create_err:
        # 建目录失败 → 把刚登记的这家撤掉,不留「有门店、没数据」的幻影店。
        # 目录不删(万一里面已经有数据,删掉比留着更糟)。
        st["stores"] = [s for s in st["stores"]
                        if not (isinstance(s, dict) and s.get("id") == store_id)]
        if settings is None:
            # 回滚必须**落盘**:不落盘的话,settings.json 里就留着幻影门店条目,
            # 内存与磁盘不一致,Task 4 的门店闸会放行一个没有数据目录的门店
            # (它的每个请求都 404)。
            #
            # 回滚失败绝不能静默吞掉 —— 那等于「建店失败 + 注册表也被改坏」
            # 两件事一起被瞒下来。抛 RuntimeError,把原始异常(建目录失败)
            # 挂在异常链上,让上层知道门店没建成、注册表需要人工清理。
            try:
                _persist(st)
            except Exception as rollback_err:
                raise RuntimeError(
                    f"门店 {store_id} 建目录失败,且回滚注册表落盘也失败 —— "
                    f"settings.json 里可能残留幻影门店条目,请手工检查: {rollback_err}"
                ) from create_err
        raise
    return copy.deepcopy(store)


def _reject_case_insensitive_conflict(st: dict[str, Any], store_id: str) -> None:
    """拒绝与已有门店大小写不敏感冲突的 ID。

    macOS / Windows 的文件系统大小写不敏感:stores/MAIN 与 stores/main
    是同一个目录。不挡的话,新建的"分店"会静默读写总店的数据 ——
    正是这个功能要消灭的串店。

    不做「统一转小写」:已有门店的 ID 可能已经被用户看到、用过了,
    静默改写 ID 比拒绝新增更糟。
    """
    lowered = store_id.lower()
    for s in list_stores(st):
        sid = str(s.get("id") or "")
        if sid.lower() == lowered:
            raise ValueError(
                f"门店 ID 与已有门店冲突(大小写不敏感): {store_id} 与 {sid} "
                f"在 macOS/Windows 上会指向同一个目录"
            )


def update_store(store_id: str, fields: dict[str, Any],
                 settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """修改门店元信息。可改字段: name / code / address / active。

    与 add_store() 一致:name/code/address 存前 strip,active 存成 bool。
    """
    st = _load_settings(settings)
    store = _live_store(st, store_id)
    if store is None:
        raise ValueError(f"门店不存在: {store_id}")
    if "name" in fields:
        name = str(fields["name"] or "").strip()
        if not name:
            raise ValueError("门店名称不能为空")
        store["name"] = name
    if "code" in fields:
        store["code"] = str(fields["code"] or "").strip()
    if "address" in fields:
        store["address"] = str(fields["address"] or "").strip()
    if "active" in fields:
        store["active"] = bool(fields["active"])
    if settings is None:
        _persist(st)
    return copy.deepcopy(store)


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
    # 建目录前再验一次 ID —— 入口那道闸是给别人看的,这里是最后一道。
    if not is_valid_store_id(store_id):
        raise ValueError(f"门店 ID 非法: {store_id}")
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
