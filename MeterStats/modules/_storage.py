"""
MeterStats — 模块存储层
========================
每个模块持有自己的 ModuleStorage 实例，封装 JSON 读写和并发锁。

与全局 storage.py 的区别:
- 每个模块只操作自己的数据文件 (读隔离)
- 但仍共享 storage.py 的全局缓存机制 (写时仍可能有竞争，但概率极低)
- 保留 storage.py 的全局兼容函数 (load_json/save_json) 用于跨模块操作
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from storage import load_json, save_json, get_lock, log


class ModuleStorage:
    """模块级存储抽象。每个模块一个实例，操作自己的数据文件。
    
    用法:
        storage = ModuleStorage('readings')
        data = storage.read()      # 等同于 load_json(filepath)
        storage.write(new_data)    # 等同于 save_json(filepath, data)
        storage.invalidate()       # 清除缓存
    """
    
    def __init__(self, name: str):
        self.name = name
    
    def _get_filepath(self) -> Path:
        """获取数据文件路径 (动态从 app_handler 获取)。"""
        try:
            from app_handler import DATA_PATHS
            path = DATA_PATHS.get(self.name)
            if path:
                return Path(path)
        except (ImportError, AttributeError):
            pass
        # 回退到默认路径
        return Path(self.name + '.json')
    
    def read(self) -> List[Any]:
        """读取模块数据。"""
        with get_lock(self.name):
            return load_json(self._get_filepath())
    
    def write(self, data: List[Any]) -> None:
        """写入模块数据。"""
        with get_lock(self.name):
            save_json(self._get_filepath(), data)
    
    def invalidate(self) -> None:
        """清除缓存 (使后续 read 重新从磁盘加载)。"""
        from storage import _cache_invalidate
        _cache_invalidate(self.name)


# 全局兼容函数 (保留，用于跨模块操作)
def get_storage(name: str) -> ModuleStorage:
    """获取或创建模块存储实例。"""
    return ModuleStorage(name)
