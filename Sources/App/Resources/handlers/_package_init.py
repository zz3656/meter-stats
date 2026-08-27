"""handlers 包。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# 动态加载 handlers.py (同名 .py 文件)
_resources = Path(__file__).resolve().parent.parent
_handlers_py_path = _resources / "handlers.py"

_spec = importlib.util.spec_from_file_location("_handlers_module", str(_handlers_py_path))
_handlers_module = importlib.util.module_from_spec(_spec)
sys.modules["handlers._handlers_module"] = _handlers_module
_spec.loader.exec_module(_handlers_module)

# 将 DATA_PATHS 和 _do_api 导出到 handlers 包级别
DATA_PATHS: dict = _handlers_module.DATA_PATHS
_do_api = _handlers_module._do_api
Handler = _handlers_module.Handler
ROOT = _handlers_module.ROOT
PORT = _handlers_module.PORT


def sync_data_paths(paths: dict):
    """将 DATA_PATHS 同步到所有 handlers 子模块。"""
    modules = [
        "handlers.readings",
        "handlers.charges",
        "handlers.items",
        "handlers.purchases",
        "handlers.reports",
        "handlers.backup",
    ]
    for mod_name in modules:
        mod = sys.modules.get(mod_name)
        if mod is not None:
            if hasattr(mod, "_DATA_PATHS"):
                mod._DATA_PATHS.clear()
                mod._DATA_PATHS.update(paths)
