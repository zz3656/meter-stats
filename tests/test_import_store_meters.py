"""CSV 导入按店表集合工作(标准库 unittest,零依赖)。

P2 遗留债务:改造前 `dataimport` 按写死的 4 表列名解析。
门店换成 2 块表后导入一份 4 表的老 CSV,多出来的列会被**静默丢掉** ——
用户看到「导入成功 20 条」却少了一半数据,而且永远查不出是哪一步丢的。

现在:
- 列校验与 CSV 模板都跟着**当前门店**的表集合走
- CSV 里出现本店没有的列 → 整个文件拒收并明确说明(不再静默丢)
- 自定义表的值写进记录的 `meters` 字典,旧 4 表仍写顶层字段(零迁移)

运行:
    python3 -m unittest tests.test_import_store_meters -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, cast

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "MeterStats"))
sys.path.insert(0, str(TESTS_DIR))

from modules._base import get_data_paths  # noqa: E402
from modules.dataimport.handler import (  # noqa: E402
    _import_charges,
    _import_readings,
    handle_get_import_template,
)
from modules.stores import config, context  # noqa: E402
from test_store_api import _ApiHandler  # noqa: E402
from test_stores import StoreTestBase  # noqa: E402

from storage import load_json  # noqa: E402


class _ImportBase(StoreTestBase):
    """在 StoreTestBase 之上:按需给当前门店配表集合。"""

    def set_meters(self, meters: List[Dict[str, Any]]) -> None:
        (self.data_dir / "stores" / "main").mkdir(parents=True, exist_ok=True)
        config.write_store_config("main", {
            "id": "main", "name": "总店",
            "meters": meters,
            "config": dict(config.DEFAULT_CONFIG),
        })
        context.set_current_store("main")

    def rows_now(self, model: str) -> List[Dict[str, Any]]:
        return cast(List[Dict[str, Any]], load_json(get_data_paths()[model], []))


class TestReadingsImportPerStore(_ImportBase):
    def test_custom_meters_go_into_meters_dict(self) -> None:
        self.set_meters([
            {"key": "m1", "label": "吧台", "multiplier": 2},
            {"key": "m2", "label": "后厨", "multiplier": 3},
        ])
        rows = [
            {"date": "2026-09-01", "m1": "100", "m2": "50", "note": "首日"},
            {"date": "2026-09-11", "m1": "90", "m2": "40", "note": ""},
        ]
        ok, failed, errors = _import_readings(rows)
        self.assertEqual((ok, failed, errors), (2, 0, []))

        saved = self.rows_now("readings")
        self.assertEqual(len(saved), 2)
        first = saved[0]
        self.assertEqual(first["date"], "2026-09-01")
        self.assertEqual(first["meters"], {"m1": 100.0, "m2": 50.0})
        # 旧 4 表的 key 不该出现在这块表的门店里
        self.assertNotIn("hall", first)
        self.assertEqual(first["note"], "首日")

    def test_unknown_column_rejects_whole_file(self) -> None:
        """2 表门店导入 4 表 CSV → 整份拒收,而不是静默丢掉多出来的列。"""
        self.set_meters([
            {"key": "m1", "label": "吧台", "multiplier": 2},
            {"key": "m2", "label": "后厨", "multiplier": 3},
        ])
        rows = [{"date": "2026-09-01", "hall": "100", "m1": "5"}]
        ok, failed, errors = _import_readings(rows)
        self.assertEqual(ok, 0, "有本店不存在的列却还是导进去了")
        self.assertEqual(failed, len(rows))
        self.assertEqual(len(errors), 1)
        self.assertIn("hall", errors[0], "错误里要指出是哪一列不属于本店")
        self.assertEqual(self.rows_now("readings"), [], "拒收时不该落任何数据")

    def test_legacy_four_tables_still_import(self) -> None:
        """默认 4 表门店:行为与改造前一致(回归)。"""
        rows = [{"date": "2026-09-01", "hall": "100", "fire": "20", "note": ""}]
        ok, failed, errors = _import_readings(rows)
        self.assertEqual((ok, failed, errors), (1, 0, []))
        saved = self.rows_now("readings")
        self.assertEqual(saved[0]["hall"], 100.0)
        self.assertEqual(saved[0]["fire"], 20.0)
        self.assertNotIn("meters", saved[0])

    def test_water_only_row_still_importable(self) -> None:
        """只填水电表底的行仍可导入(改造前就允许)。"""
        rows = [{"date": "2026-09-02", "main_meter": "51800", "water": "3140"}]
        ok, failed, errors = _import_readings(rows)
        self.assertEqual((ok, failed, errors), (1, 0, []))
        saved = self.rows_now("readings")
        self.assertEqual(saved[0]["main_meter"], 51800.0)

    def test_overwrite_keeps_other_meter_values(self) -> None:
        """同日期重复导入只更新填了的表,不把别的表清空。"""
        self.set_meters([
            {"key": "m1", "label": "吧台", "multiplier": 2},
            {"key": "m2", "label": "后厨", "multiplier": 3},
        ])
        _import_readings([{"date": "2026-09-01", "m1": "100", "m2": "50"}])
        _import_readings([{"date": "2026-09-01", "m1": "80"}])
        saved = self.rows_now("readings")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["meters"], {"m1": 80.0, "m2": 50.0},
                         "合并时把没填的自定义表清空了")


class TestChargesImportPerStore(_ImportBase):
    def test_custom_meter_charge(self) -> None:
        self.set_meters([{"key": "m1", "label": "吧台", "multiplier": 2}])
        ok, failed, errors = _import_charges([{"date": "2026-09-05", "m1": "7"}])
        self.assertEqual((ok, failed, errors), (1, 0, []))
        saved = self.rows_now("charges")
        self.assertEqual(saved[0]["meters"], {"m1": 7.0})

    def test_unknown_column_rejected(self) -> None:
        self.set_meters([{"key": "m1", "label": "吧台", "multiplier": 2}])
        ok, failed, errors = _import_charges([{"date": "2026-09-05", "private_room": "7"}])
        self.assertEqual(ok, 0)
        self.assertIn("private_room", errors[0])


class TestImportTemplatePerStore(_ImportBase):
    def _template(self, model: str) -> str:
        h = _ApiHandler("/api/import/template?model=" + model)
        handle_get_import_template(h, "/api/import/template")
        return h.wfile.getvalue().decode("utf-8")

    def test_readings_template_uses_store_columns(self) -> None:
        self.set_meters([
            {"key": "m1", "label": "吧台", "multiplier": 2},
            {"key": "m2", "label": "后厨", "multiplier": 3},
        ])
        text = self._template("readings")
        self.assertIn("m1", text)
        self.assertIn("m2", text)
        self.assertNotIn("hall", text, "模板还在给别的店的列 —— 照着填必然导不进去")

    def test_charges_template_uses_store_columns(self) -> None:
        self.set_meters([{"key": "m1", "label": "吧台", "multiplier": 2}])
        text = self._template("charges")
        self.assertIn("m1", text)
        self.assertNotIn("private_room", text)


if __name__ == "__main__":
    unittest.main()
