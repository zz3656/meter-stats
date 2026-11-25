"""门店上下文 — 当前门店(thread-local)与按门店的数据路径解析。

为什么用 thread-local:
    ThreadingHTTPServer 每个请求一个线程,把当前门店放在 threading.local 里,
    天然做到「请求之间不串店」,不需要给每个 handler 函数加参数。

为什么路径以 app_handler.DATA_PATHS 为基准:
    单元测试直接把 app_handler.DATA_PATHS 指向临时目录(见 tests/test_handlers.py),
    若绕开 DATA_PATHS 自行调 get_data_dir() 推导目录,存量测试会全部读不到数据。
    DATA_PATHS 永远指向**顶层**数据目录,迁移后也不改变 —— 否则 stores_root()
    会被算成 stores/main/stores/,路径全错。

单店兼容:
    未启用 stores/ 布局时,current_store_paths() 原样返回 DATA_PATHS,
    行为与分店改造前完全一致。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict

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


def base_data_dir() -> Path:
    """顶层数据目录 —— settings.json 所在处,全局唯一。

    取 app_handler.DATA_PATHS["readings"] 的父目录;DATA_PATHS 为空时回退
    storage.get_data_dir()(服务尚未启动完时的兜底)。
    """
    paths = getattr(app_handler_module(), "DATA_PATHS", None) or {}
    ref = paths.get("readings")
    if ref:
        return Path(ref).parent
    from storage import get_data_dir
    return Path(get_data_dir())


def app_handler_module() -> Any:
    """延迟 import app_handler —— 避免模块级循环依赖。"""
    import app_handler as _h
    return _h


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


def resolve_store_path(model: str, store_id: str, filename: str) -> Path:
    """解析某门店某模型的数据文件路径。

    - 单店布局 → 顶层目录(与改造前一致)
    - 多店布局 → stores/<store_id>/<filename>
    - 默认店 main 且该文件不存在、顶层旧文件存在 → 回退顶层旧文件
      (迁移前 / 迁移失败时的「读双写单」)
    - 分店**不回退**顶层:否则分店会读到总店数据
    """
    base = base_data_dir()
    if not multi_store_layout():
        return base / filename
    target = store_dir(store_id) / filename
    if not target.exists() and store_id == DEFAULT_STORE_ID:
        legacy = base / filename
        if legacy.exists():
            return legacy
    return target


def current_store_paths() -> Dict[str, Path]:
    """当前门店的 {model: Path} 映射。

    单店布局 → 原样返回 app_handler.DATA_PATHS;
    多店布局 → 按当前门店解析。
    """
    if not multi_store_layout():
        return dict(getattr(app_handler_module(), "DATA_PATHS", None) or {})
    from storage import DATA_FILES
    store_id = get_current_store()
    return {m: resolve_store_path(m, store_id, fn) for m, fn in DATA_FILES.items()}
