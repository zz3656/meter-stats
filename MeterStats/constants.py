"""全局常量 — 电表倍率、价格等。

所有硬编码的魔法数字统一在此定义，业务代码从这里 import，
避免在 app.js、report.py、settings.py 等多个文件中重复定义。
"""
from __future__ import annotations

from typing import Any

# ============ 电表倍率 (表读数值 × 倍率 = 实际度数) ============
METER_MULTIPLIERS: dict[str, int] = {
    "hall": 160,        # 大厅
    "fire": 1,          # 消防
    "private_room": 160,  # 包厢
    "ac": 160,          # 空调
}

# ============ 总表/分表倍率 (水电月报专用) ============
MAIN_METER_MULT = 50   # 总表倍率
SUB_METER_MULT = 40    # 分表倍率

# ============ 默认表定义 (P2) ============
# report.py 的 tables 参数默认值 —— 全项目只有这一份「默认 4 表」的乘率口径。
# 字段用 `mult`(不是 store.json 的 `multiplier`):report.py 里 9 处 `t["mult"]`,
# 改名只会扩大改动面且毫无收益。两套名字的转换在调用方做一次
# (modules/reports/handler.py::_report_tables)。
# 注意:本表顺序即界面顺序(key 顺序被前端 METER_KEYS 复用)。
DEFAULT_TABLES: list[dict[str, Any]] = [
    {"key": "hall", "label": "1#大厅", "mult": METER_MULTIPLIERS["hall"]},
    {"key": "fire", "label": "2#消防", "mult": METER_MULTIPLIERS["fire"]},
    {"key": "private_room", "label": "3#包厢", "mult": METER_MULTIPLIERS["private_room"]},
    {"key": "ac", "label": "4#空调", "mult": METER_MULTIPLIERS["ac"]},
]

# ============ 价格（元） ============
ELECTRICITY_PRICE = 0.9  # 电费单价 元/度
WATER_PRICE = 4.5        # 水费单价 元/吨

# ============ 电表标签定义（前端共用） ============
METER_LABELS: dict[str, str] = {
    "hall": "大厅",
    "fire": "消防",
    "private_room": "包厢",
    "ac": "空调",
}

METER_ICONS: dict[str, str] = {
    "hall": "🎤",
    "fire": "🧯",
    "private_room": "🛋️",
    "ac": "❄️",
}

METER_COLORS: dict[str, str] = {
    "hall": "#2563eb",
    "fire": "#dc2626",
    "private_room": "#059669",
    "ac": "#d97706",
}

# Aliases for report.py compatibility
PRICE = ELECTRICITY_PRICE

# ============ 端口与网络配置 ============
DEFAULT_PORT = 8765

# ============ 角色 ============
ROLE_ADMIN = "admin"
ROLE_SUPERVISOR = "supervisor"
ROLE_EMPLOYEE = "employee"

ROLES = {
    ROLE_ADMIN: "管理员",
    ROLE_SUPERVISOR: "主管",
    ROLE_EMPLOYEE: "员工",
}
