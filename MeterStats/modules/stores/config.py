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
"""
from __future__ import annotations

import json
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

    store_id 本身非法时抛 ValueError —— 那是调用方的错,不是「配置损坏」。
    """
    path = store_config_path(store_id)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {"id": store_id, "name": "", "meters": [dict(m) for m in DEFAULT_METERS],
            "config": dict(DEFAULT_CONFIG)}


def write_store_config(store_id: str, cfg: dict[str, Any]) -> None:
    """原子写入门店配置。"""
    path = store_config_path(store_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_store_settings() -> dict[str, Any]:
    """当前门店的配置(表定义 + 价格)。"""
    from modules.stores.context import get_current_store
    return read_store_config(get_current_store())


def get_store_meters() -> list[dict[str, Any]]:
    """当前门店的表定义列表。"""
    meters = get_store_settings().get("meters")
    if isinstance(meters, list) and meters:
        return meters
    return [dict(m) for m in DEFAULT_METERS]


def get_store_prices() -> dict[str, Any]:
    """当前门店的价格/倍率配置(缺失项用默认值补齐)。"""
    cfg = get_store_settings().get("config")
    out: dict[str, Any] = dict(DEFAULT_CONFIG)
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            out[str(k)] = v
    return out
