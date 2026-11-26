"""门店上下文 — 当前门店(thread-local)与按门店的数据路径解析。

为什么用 thread-local:
    ThreadingHTTPServer 每个请求一个线程,把当前门店放在 threading.local 里,
    天然做到「请求之间不串店」,不需要给每个 handler 函数加参数。

为什么路径以 app_handler.DATA_PATHS 为基准:
    单元测试直接把 app_handler.DATA_PATHS 指向临时目录(见 tests/test_handlers.py),
    若绕开 DATA_PATHS 自行调 get_data_dir() 推导目录,存量测试会全部读不到数据。
    DATA_PATHS 永远指向**顶层**数据目录,迁移后也不改变 —— 否则 stores_root()
    会被算成 stores/main/stores/,路径全错。

路径解析绝不回退到 storage.get_data_dir():
    get_data_dir() 不是纯查询 —— 它会 mkdir、可能把老目录的数据迁移到
    ~/Library/Application Support/ 并 copytree 备份、还往 stdout 打日志。
    路径解析一旦回退到它,在 DATA_PATHS 尚未初始化时就会**静默落到真实用户
    数据目录**(用户表、密码哈希、NAS 凭据、备份目录)。宁可抛 RuntimeError。

单店兼容:
    未启用 stores/ 布局时,current_store_paths() 原样返回 DATA_PATHS,
    行为与分店改造前完全一致。
"""
from __future__ import annotations

import contextlib
import threading
import types
from pathlib import Path
from typing import Iterator

# 默认店(总店)的 ID。历史数据迁移后落到这个名字下。
DEFAULT_STORE_ID = "main"

_ctx = threading.local()


def set_current_store(store_id: str) -> None:
    """设置当前门店(仅本请求线程可见)。"""
    _ctx.store_id = store_id


def get_current_store() -> str:
    """当前门店 ID。未设置时返回默认店。"""
    return getattr(_ctx, "store_id", None) or DEFAULT_STORE_ID


def clear_current_store() -> None:
    """清空当前门店(单元测试用)。"""
    _ctx.store_id = None


@contextlib.contextmanager
def store_scope(store_id: str) -> Iterator[None]:
    """临时切到某门店，退出时恢复**原始**值（含「从未设置过」这个状态）。

    用途:总部总览要逐店跑一遍月报(P3)。`report._report_cache_key()` 用的是
    **当前门店** —— 不切上下文就逐店计算,两家表集合相同的店会命中同一份缓存,
    把 A 店的数字当成 B 店的,而且不报错。

    ⚠️ 不能用 `get_current_store()` 当"原值"来恢复:它在未设置时返回
    `DEFAULT_STORE_ID`("main"),拿它恢复会把「从未设置」悄悄改成「已设为 main」,
    掩盖掉真正的初始化缺失。

    ⚠️ 必须 `finally`:遍历多店时任何一家抛异常,上下文没恢复 →
    本请求后续所有的读都会落到那家店上(表现为「总览算完之后,页面上
    的抄表数据变成了别家店的」)。
    """
    prev = getattr(_ctx, "store_id", None)
    set_current_store(store_id)
    try:
        yield
    finally:
        if prev is None:
            clear_current_store()
        else:
            set_current_store(prev)


def app_handler_module() -> types.ModuleType:
    """延迟 import app_handler —— 避免模块级循环依赖。"""
    import app_handler as _h
    return _h


def _data_paths() -> dict[str, Path]:
    """当前的 app_handler.DATA_PATHS(永远指向顶层数据目录,不随门店改变)。"""
    paths: dict[str, Path] = getattr(app_handler_module(), "DATA_PATHS", None) or {}
    return paths


def base_data_dir() -> Path:
    """顶层数据目录 —— settings.json 所在处,全局唯一。

    取 app_handler.DATA_PATHS["readings"] 的父目录。

    DATA_PATHS 尚未初始化时抛 RuntimeError —— **不做任何猜测式回退**。
    回退到 storage.get_data_dir() 会静默解析到真实用户数据目录,那里放着
    用户表、密码哈希、NAS 凭据和备份目录;静默读到/写错地方,比直接报错危险得多。
    """
    ref = _data_paths().get("readings")
    if not ref:
        raise RuntimeError(
            "数据目录未初始化:app_handler.DATA_PATHS['readings'] 为空 —— "
            "请先调用 storage.init_data_files() 并把结果写入 app_handler.DATA_PATHS"
        )
    return Path(ref).parent


def stores_root() -> Path:
    """stores/ 根目录。"""
    return base_data_dir() / "stores"


def store_dir(store_id: str) -> Path:
    """某门店的数据目录(可能尚不存在)。"""
    return stores_root() / store_id


def multi_store_layout() -> bool:
    """是否已启用多门店布局(stores/ 目录存在)。

    单店布局下门店闸门整体放行 —— 此时只有一家店,无从越权。
    """
    return stores_root().is_dir()


def resolve_store_path(model: str, store_id: str) -> Path:
    """解析某门店某模型的数据文件路径。

    文件名由 storage.DATA_FILES[model] 推导 —— 「模型 → 文件名」只有一个真相来源。
    单店分支直接取 app_handler.DATA_PATHS[model],与 current_store_paths() 同一来源。

    - 单店布局 → DATA_PATHS[model](与改造前一致)
    - 多店布局 → stores/<store_id>/<DATA_FILES[model]>
    - 默认店 main 且该文件不存在、顶层旧文件存在 → 回退顶层旧文件
      (迁移前 / 迁移失败时的「读双写单」)
    - 分店**不回退**顶层:否则分店会读到总店数据
    """
    from storage import DATA_FILES
    filename = DATA_FILES[model]
    if not multi_store_layout():
        ref = _data_paths().get(model)
        if ref:
            return Path(ref)
        # DATA_PATHS 里没有这个模型 → 用 DATA_FILES 的文件名拼顶层目录
        return base_data_dir() / filename
    target = store_dir(store_id) / filename
    if not target.exists() and store_id == DEFAULT_STORE_ID:
        legacy = base_data_dir() / filename
        if legacy.exists():
            return legacy
    return target


def current_store_paths() -> dict[str, Path]:
    """当前门店的 {model: Path} 映射。

    单店布局 → 原样返回 app_handler.DATA_PATHS;
    多店布局 → 按当前门店解析。
    """
    if not multi_store_layout():
        return dict(_data_paths())
    from storage import DATA_FILES
    store_id = get_current_store()
    return {m: resolve_store_path(m, store_id) for m in DATA_FILES}
