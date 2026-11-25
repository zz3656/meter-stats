"""门店配置 store.json —— 该店自己的表定义与价格/倍率。

每店一个文件:stores/<store_id>/store.json
{
  "id": "s002",
  "name": "国贸店",
  "meters": [ {"key": "hall", "label": "大厅", "icon": "🎤",
               "multiplier": 160, "color": "#2563eb"}, ... ],
  "config": {"electricity_price": 0.9, "water_price": 4.5,
             "main_mult": 50, "sub_mult": 40}
}

P0 阶段:每店先复制一份默认表定义(与总店一致),P2 再开放自定义编辑。

读写统一走 storage.load_json / storage.save_json:
    - 吃存储层的 LRU 缓存(同一份配置不重复解析)
    - 文件损坏时自动走「从备份恢复」,而不是静默降级成默认值
    - 写的时候由存储层失效缓存,不会留下陈旧值

**读出来的配置一律是深拷贝**:
storage.load_json 命中缓存时直接交出缓存里那个解析后的对象本身(不是副本)。
只做顶层浅拷贝的话,调用方改一下 cfg["meters"][0] 就是在改缓存本体 ——
文件 mtime 没变时,下次读到的就是被改坏的内存值(磁盘上的文件是好的)。
P2「每店自定义表数和倍率」正是走这条路,写盘前的中间态就会污染缓存。
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

# 默认表定义 —— 与 constants.METER_MULTIPLIERS / settings.json 的 meter 字段一致。
# P0 之前,所有门店都用这一份;P2 起各店可独立配置。
DEFAULT_METERS: list[dict[str, Any]] = [
    {"key": "hall", "label": "大厅", "icon": "🎤", "multiplier": 160, "color": "#2563eb"},
    {"key": "fire", "label": "消防", "icon": "🧯", "multiplier": 1, "color": "#dc2626"},
    {"key": "private_room", "label": "包厢", "icon": "🛋️", "multiplier": 160, "color": "#059669"},
    {"key": "ac", "label": "空调", "icon": "❄️", "multiplier": 160, "color": "#d97706"},
]

DEFAULT_CONFIG: dict[str, Any] = {
    "electricity_price": 0.9,
    "water_price": 4.5,
    "main_mult": 50,
    "sub_mult": 40,
}


def store_config_path(store_id: str) -> Path:
    """门店配置文件路径 stores/<store_id>/store.json。

    store_id 会拼进文件路径 —— 这里再挡一次路径穿越。注册表入口
    (registry.add_store)已经挡过一次,这里是最后一道闸:直接拿用户输入
    调本函数的调用方也拦得住。
    """
    from modules.stores.registry import is_valid_store_id
    if not is_valid_store_id(store_id):
        raise ValueError(f"门店 ID 非法: {store_id}")
    from modules.stores.context import store_dir
    return store_dir(store_id) / "store.json"


def read_store_config(store_id: str) -> dict[str, Any]:
    """读取门店配置。文件不存在或损坏时返回默认配置(不抛异常)。

    走 storage.load_json —— 文件损坏时存储层会尝试从备份恢复,
    恢复不了才回落到这里的默认配置。

    **返回深拷贝**:storage 的 LRU 缓存命中时交出的是缓存里那个对象本身。
    调用方改嵌套结构就是在改缓存本体 —— 文件 mtime 不变时,下次读到的
    就是被改坏的内存值(磁盘上的文件是好的)。

    store_id 本身非法时抛 ValueError —— 那是调用方的错,不是「配置损坏」。
    """
    from storage import load_json
    # default 每次调用新建 —— 调用方改它也不会碰到模块级常量或缓存
    default: dict[str, Any] = {
        "id": store_id, "name": "",
        "meters": copy.deepcopy(DEFAULT_METERS),
        "config": copy.deepcopy(DEFAULT_CONFIG),
    }
    path = store_config_path(store_id)
    data = load_json(path, default)
    # 文件内容不是 dict(被人手改坏)→ 用默认配置
    if not isinstance(data, dict):
        return default
    return copy.deepcopy(data)


def write_store_config(store_id: str, cfg: dict[str, Any]) -> None:
    """原子写入门店配置(走 storage.save_json:tmp+rename,并失效存储层缓存)。"""
    from storage import save_json
    path = store_config_path(store_id)
    # save_json 不会建父目录 —— 写入前必须自己 mkdir
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, cfg)


def get_store_settings() -> dict[str, Any]:
    """当前门店的配置(表定义 + 价格)。"""
    from modules.stores.context import get_current_store
    return read_store_config(get_current_store())


def get_store_meters() -> list[dict[str, Any]]:
    """当前门店的表定义列表。返回深拷贝 —— 调用方改不动缓存本体。"""
    meters = get_store_settings().get("meters")
    if isinstance(meters, list) and meters:
        return copy.deepcopy(meters)
    return copy.deepcopy(DEFAULT_METERS)


def get_report_tables() -> list[dict[str, Any]]:
    """当前门店的表定义 → `report.py` 要的形状 `{key,label,mult}`。

    两套字段名必须在这里**只转换一次**:`store.json` 用 `multiplier`,
    `report.py` 用 `mult`(9 处 `t["mult"]`,改名只会扩大改动面)。
    谁要喂 `report.py` 的 `tables` 参数就只有这一个入口 —— 散落各处的转换
    迟早漏一个,漏的那个会在 `KeyError: 'mult'` 上炸掉整个请求。
    """
    return [
        {"key": m["key"], "label": m["label"], "mult": m["multiplier"]}
        for m in get_store_meters()
    ]


def get_store_prices() -> dict[str, Any]:
    """当前门店的价格/倍率配置(缺失项用默认值补齐)。返回深拷贝。

    值必须是深拷贝而不是引用拷贝:store.json 的 config 里将来可能有嵌套
    结构(标量时代看不出来),引用拷贝会让调用方改坏缓存本体。

    DEFAULT_CONFIG 同理:它是**模块级常量**,out 必须是它的深拷贝 ——
    否则调用方往返回值里塞的键会永久污染常量,跨请求泄漏
    (下一个请求读到上一个请求塞进去的键)。
    """
    cfg = get_store_settings().get("config")
    out: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            out[str(k)] = copy.deepcopy(v)
    return out
