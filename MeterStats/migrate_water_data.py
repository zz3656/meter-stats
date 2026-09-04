#!/usr/bin/env python3
"""迁移脚本：将 readings.json 中的水电字段迁移到独立的 readings_water.json。

1. 读取 readings.json 和 readings_water.json
2. 从 readings.json 中提取有水电字段的记录，构建 readings_water.json
3. 从 readings.json 中移除水电字段(main_meter/sub_meter/water)
4. 写入新文件
"""
from pathlib import Path
import json
import sys

DATA_DIR = Path.home() / "Library" / "Application Support" / "com.meter.stats"
READINGS_PATH = DATA_DIR / "readings.json"
WATER_PATH = DATA_DIR / "readings_water.json"


def load_json(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    readings = load_json(READINGS_PATH)
    existing_water = load_json(WATER_PATH)

    water_by_date = {w["date"]: w for w in existing_water}

    migrated = 0
    updated_readings = []
    for r in readings:
        has_water = (
            r.get("main_meter") is not None or
            r.get("sub_meter") is not None or
            r.get("water") is not None
        )
        if has_water:
            water_by_date[r["date"]] = {
                "date": r["date"],
                "main_meter": r.get("main_meter"),
                "sub_meter": r.get("sub_meter"),
                "water": r.get("water"),
                "note": r.get("note", ""),
            }
            migrated += 1
            # 保留 date 和 note，移除水电字段
            cleaned = {
                "date": r["date"],
                "note": r.get("note", ""),
            }
            # 保留四表数据
            for key in ["hall", "fire", "private_room", "ac"]:
                if r.get(key) is not None:
                    cleaned[key] = r[key]
            updated_readings.append(cleaned)
        else:
            updated_readings.append(r)

    # 写入 readings_water.json
    water_list = sorted(water_by_date.values(), key=lambda w: w["date"])
    save_json(WATER_PATH, water_list)

    # 写入 cleaned readings.json
    save_json(READINGS_PATH, updated_readings)

    print(f"迁移完成:")
    print(f"  - 从 readings.json 迁移了 {migrated} 条水电记录")
    print(f"  - readings.json: {len(updated_readings)} 条 (已移除水电字段)")
    print(f"  - readings_water.json: {len(water_list)} 条 (独立存储)")


if __name__ == "__main__":
    main()
