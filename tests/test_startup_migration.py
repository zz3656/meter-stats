"""启动迁移的布局分派测试(标准库 unittest,零依赖)。

**背景**:`run_startup_migration()` 原来只对**数据根目录**跑水电字段迁移。
多门店布局下应用读的是 `stores/<id>/`,顶层 `readings.json` 只是「总店的旧位置」——
于是它同时犯了两个错:

1. 白改一个没人读的文件(还可能让人以为顶层仍是权威来源);
2. **漏掉每个门店自己的数据**:老部署里门店的 `readings.json` 若还留着内联的
   `main_meter` / `sub_meter` / `water` 字段,不迁移就永远进不了该店的
   `readings_water.json` → 水电月报空着,而且不报错。

现在按布局分派:多门店 → 逐个门店目录;单店 → 数据根目录。

运行:
    python3 -m unittest tests.test_startup_migration -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "MeterStats"))

from unittest import mock  # noqa: E402

import app_handler  # noqa: E402
import storage  # noqa: E402

ROW_WITH_WATER = {
    "date": "2026-06-01", "hall": 100.0, "fire": 2000.0,
    "private_room": 150.0, "ac": 120.0,
    "main_meter": 300.0, "sub_meter": 280.0, "water": 42.0,
}


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class TestStartupMigrationDispatch(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_single_store_migrates_top_level(self) -> None:
        _write(self.base / "readings.json", [dict(ROW_WITH_WATER)])
        storage.run_startup_migration(self.base)

        top = _read(self.base / "readings.json")
        water = _read(self.base / "readings_water.json")
        self.assertEqual(len(water), 1, "单店布局下顶层水电字段没迁出来")
        self.assertNotIn("water", top[0], "迁移后 readings.json 仍留着水电字段")

    def _run_multi(self) -> None:
        """在多门店布局下跑启动迁移 —— 布局由 data_dir/stores/ 判定,不依赖全局状态。"""
        storage.run_startup_migration(self.base)

    def test_multi_store_migrates_each_store(self) -> None:
        main = self.base / "stores" / "main"
        s002 = self.base / "stores" / "s002"
        _write(main / "readings.json", [dict(ROW_WITH_WATER)])
        _write(s002 / "readings.json", [dict(ROW_WITH_WATER, hall=50.0)])
        (main / ".migrated").write_text("2026-11-27T00:00:00", encoding="utf-8")

        self._run_multi()

        for d in (main, s002):
            water = _read(d / "readings_water.json")
            self.assertEqual(len(water), 1, f"{d.name} 门店的水电字段没迁出来")
            self.assertNotIn("water", _read(d / "readings.json")[0], d.name)

    def test_layout_detected_without_global_data_paths(self) -> None:
        """回归:迁移不能依赖 app_handler.DATA_PATHS(启动时它还没初始化)。

        2026-11-27 实测过:那条路径上 base_data_dir() 必抛 RuntimeError,
        代码按"判不出布局"回退单店 → 多门店下又去改顶层遗留文件。
        """
        _write(self.base / "stores" / "main" / "readings.json", [dict(ROW_WITH_WATER)])
        top_before = self.base / "readings.json"
        _write(top_before, [{"date": "2026-06-01", "hall": 1.0}])
        before_text = top_before.read_text(encoding="utf-8")

        # 模拟 server.py 启动时的真实状态:此刻 DATA_PATHS 还没被赋值
        empty = {k: None for k in app_handler.DATA_PATHS}
        with mock.patch.object(app_handler, "DATA_PATHS", empty):
            storage.run_startup_migration(self.base)

        self.assertEqual(len(_read(self.base / "stores" / "main" / "readings_water.json")), 1,
                         "多门店布局没被识别出来(仍在按单店处理)")
        self.assertEqual(top_before.read_text(encoding="utf-8"), before_text,
                         "顶层遗留文件又被改写了")

    def test_multi_store_does_not_touch_legacy_top_level(self) -> None:
        """顶层是「总店的旧位置」,多门店布局下不该被重写。"""
        _write(self.base / "readings.json", [dict(ROW_WITH_WATER)])
        before = (self.base / "readings.json").read_text(encoding="utf-8")
        _write(self.base / "stores" / "main" / "readings.json", [{"date": "2026-06-02", "hall": 1.0}])

        self._run_multi()

        after = (self.base / "readings.json").read_text(encoding="utf-8")
        self.assertEqual(before, after, "多门店布局下顶层遗留文件被无谓改写了")

    def test_idempotent(self) -> None:
        d = self.base / "stores" / "main"
        _write(d / "readings.json", [dict(ROW_WITH_WATER)])
        self._run_multi()
        first = (d / "readings.json").read_text(encoding="utf-8")
        self._run_multi()
        self.assertEqual((d / "readings.json").read_text(encoding="utf-8"), first,
                         "第二次启动又改了文件(迁移不幂等)")


class TestJsonCacheCapacity(unittest.TestCase):
    """缓存容量必须覆盖多门店工作集 —— 否则第 3 家店起缓存永久抖动。"""

    def test_capacity_covers_three_stores(self) -> None:
        files_per_store = len(storage.DATA_FILES) + 1   # 6 个模型 + store.json
        stores = 3
        self.assertGreaterEqual(
            storage._JSON_CACHE_SIZE, files_per_store * stores,
            f"缓存 {storage._JSON_CACHE_SIZE} 条 < {stores} 家店 × {files_per_store} 文件 = "
            f"{files_per_store * stores};开到第 3 家店就会每次请求都全量重解析")


if __name__ == "__main__":
    unittest.main()
