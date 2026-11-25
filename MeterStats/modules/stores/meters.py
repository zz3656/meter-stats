"""表定义与表值读取 —— 每店表集合的唯一入口。

P2「每店自己的表数量与倍率」的后端地基。两件事在这里收口:

1. **记录怎么读**:旧 4 表在记录**顶层**字段,自定义表在 `meters` 字典里。
   `row_values()` 把两种存法统一成一个读法 —— 调用方不需要知道这块表是哪来的。
2. **表定义怎么算合法**:key 规则、倍率规则、归一化。写接口与读接口共用一份。

记录格式(向后兼容,零迁移)::

    {"date": "2026-11-25", "hall": 65.3, "ac": 52.1,
     "meters": {"m1": 12.3, "m2": 45.6}, "note": ""}

为什么旧 4 表不搬进 `meters`:历史数据全在顶层(全年上千条),搬一次就是一次
不可逆迁移,收益只是「整齐」。`row_values()` 一层薄封装就把两种读法抹平了。
"""
from __future__ import annotations

import re
from typing import Any

# 旧 4 表 —— 固定在记录顶层。新表 key 禁止与它们重名(P2 计划 D3):
# 若允许重名,`meters` 里一份、顶层一份,`row_values()` 的优先级就成了隐藏口径,
# 导入/迁移时极易写出「两处不一致」的数据。
LEGACY_KEYS: tuple[str, ...] = ("hall", "fire", "private_room", "ac")

# 新表 key 规则:小写字母开头,后续小写字母/数字/下划线,总长 2~32。
# 大写一律拒(门店闸的门店 ID 大小写敏感那套教训,表 key 同理 —— 盘上
# `m1` 与 `M1` 是两个 key,但在人的眼里是同一块表)。
_KEY_RE = re.compile(r"\A[a-z][a-z0-9_]{1,31}\Z")

# 表定义里能带的字段 —— 归一化时只保留这些,别把脏数据透给前端
_ALLOWED_FIELDS: tuple[str, ...] = ("key", "label", "icon", "multiplier", "color")

_DEFAULT_LABEL_ICON_COLOR = {"label": "", "icon": "", "color": "#888"}


def row_values(row: dict[str, Any], key: str) -> Any:
    """读一行里某块表的表底值。

    先查 `meters` 字典,缺失再 fallback 到顶层字段。`meters` 优先 —— 这个优先级
    是 D2 明文定的口径,不要反过来:反过来等于「将来某天把一块自定义表改名成
    旧 key 之后,历史数据悄悄盖住新数据」。
    """
    meters = row.get("meters")
    if isinstance(meters, dict) and key in meters:
        return meters[key]
    return row.get(key)


def row_has_any_value(row: dict[str, Any], tables: list[dict[str, Any]]) -> bool:
    """这一行有没有**任意一块**表的读数。

    替代 `report.py` 里原来硬编码的 `row.get("hall") is not None` ——
    那个判断在两处害人:门店没有 hall 表时(2 表门店),**所有**抄表行都被当成
    「只录了水电的行」跳过 → 月报 0 度、不报错、界面看起来「这个月没用电」。

    注意 `0` 是有效读数(表底真到 0 了),只有 `None` 才算没录。
    """
    return any(row_values(row, t["key"]) is not None for t in tables)


def is_valid_meter_key(key: Any) -> bool:
    """表 key 是否合法(D3:小写字母开头、不含大写/中文/连字符、2~32 位)。"""
    return isinstance(key, str) and bool(_KEY_RE.match(key))


def _coerce_multiplier(value: Any) -> int | None:
    """倍率归一化成正整数。非法(0 / 负数 / 非数字 / 布尔)返回 None。

    布尔要单独挡:`isinstance(True, int)` 在 Python 里是 True,不挡的话
    `multiplier: true` 会被当成 1。
    """
    if isinstance(value, bool):
        return None
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and value != num:
        return None   # 2.5 这种非整数倍率没有物理意义
    return num if num > 0 else None


def normalize_tables(meters: Any) -> list[dict[str, Any]]:
    """把 store.json 里的 `meters` 归一化成干净的 `[{key,label,icon,multiplier,color}]`。

    只做「能不能用」的筛选,**不补默认表**:数量不足由写接口拒绝(P2 计划 D5),
    读路径拿到空列表时由 `modules.stores.config.get_store_meters()` 回落
    `DEFAULT_METERS` —— 两处各管一段,不要在这里偷偷塞一块表进去。
    """
    if not isinstance(meters, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in meters:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not is_valid_meter_key(key) or key in seen:
            continue
        mult = _coerce_multiplier(item.get("multiplier", item.get("mult")))
        if mult is None:
            continue
        seen.add(key)
        entry: dict[str, Any] = {"key": key, "multiplier": mult}
        for field in ("label", "icon", "color"):
            value = item.get(field)
            entry[field] = value if isinstance(value, str) else _DEFAULT_LABEL_ICON_COLOR[field]
        out.append(entry)
    return out


def validate_tables_payload(meters: Any) -> str:
    """校验写接口收到的表定义。返回错误文案,空字符串表示通过。

    这几条都是「拒绝」而不是「自动修正」:静默修一个错配置,用户看到的是
    「保存成功了但表不对」,比直接报错难排查得多。
    """
    if not isinstance(meters, list):
        return "meters 必须是数组"
    if not meters:
        return "至少要有 1 块表"
    seen: set[str] = set()
    for item in meters:
        if not isinstance(item, dict):
            return "meters 里的每一项都必须是对象"
        key = item.get("key")
        if not isinstance(key, str) or not is_valid_meter_key(key):
            return f"表 key 非法: {key!r}(只能小写字母开头、小写字母/数字/下划线,2~32 位)"
        if key in LEGACY_KEYS:
            return f"表 key {key!r} 是系统保留的旧表名,请换一个"
        if key in seen:
            return f"表 key 重复: {key!r}"
        seen.add(key)
        if _coerce_multiplier(item.get("multiplier", item.get("mult"))) is None:
            return f"表 {key!r} 的倍率必须是正整数"
    return ""
