"""
MeterStats — 模块注册表

所有业务功能以模块形式组织在 modules/ 下。
新增或修改功能时，只需更新对应模块的 handler.py 和 __init__.py。
"""
from __future__ import annotations

# 模块基类 (供 handler 继承)
from ._base import JsonModelHandler, get_data_paths

__all__ = ['JsonModelHandler', 'get_data_paths']
