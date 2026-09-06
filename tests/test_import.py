"""
数据导入 - 单元测试
======================
测试 CSV 导入解析、验证、以及 dataimport 模块的核心逻辑。
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

# 让 Python 找到 MeterStats 模块
TEST_BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TEST_BASE / "MeterStats"))

# 预置目录, 让 Import 和 storage 模块不写实际磁盘
_IMPORT_TEST_DIR = Path(tempfile.mkdtemp(prefix="meter_import_test_"))
os.environ["METER_DATA_DIR"] = str(_IMPORT_TEST_DIR)
os.environ["METER_DATA_DIR"] = str(_IMPORT_TEST_DIR)


class TestDataImportParsing(unittest.TestCase):
    """纯解析测试（无磁盘 I/O）。"""

    def test_parse_number_valid(self):
        from handlers.dataimport import _parse_number
        self.assertEqual(_parse_number("123.45"), 123.45)
        self.assertEqual(_parse_number("0"), 0.0)
        self.assertIsNone(_parse_number(""))
        self.assertIsNone(_parse_number("abc"))
        self.assertEqual(_parse_number("  42  "), 42.0)

    def test_parse_number_chinese_comma(self):
        from handlers.dataimport import _parse_number
        self.assertEqual(_parse_number("1,5"), 1.5)  # ASCII 逗号作小数点
        self.assertEqual(_parse_number("1，5"), 1.5)  # 中文逗号

    def test_parse_number_thousands_sep(self):
        from handlers.dataimport import _parse_number
        self.assertEqual(_parse_number("1,000"), 1000.0)  # 千分位
        self.assertEqual(_parse_number("12,345"), 12345.0)

    def test_parse_number_empty(self):
        from handlers.dataimport import _parse_number
        self.assertIsNone(_parse_number(""))
        self.assertIsNone(_parse_number("  "))

    def test_parse_int_valid(self):
        from handlers.dataimport import _parse_int
        self.assertEqual(_parse_int("5"), 5)
        self.assertEqual(_parse_int("0"), 0)
        self.assertIsNone(_parse_int(""))
        self.assertIsNone(_parse_int("abc"))

    def test_validate_date_valid(self):
        from handlers.dataimport import _validate_date
        self.assertTrue(_validate_date("2026-08-18"))
        self.assertTrue(_validate_date("2026-01-01"))
        self.assertFalse(_validate_date("2026/08/18"))
        self.assertFalse(_validate_date(""))
        self.assertFalse(_validate_date("08-18-2026"))
        self.assertFalse(_validate_date("2026-8-1"))

    def test_model_fields(self):
        from handlers.dataimport import VALID_MODELS, MODEL_FIELDS
        expected = {"readings", "charges", "items", "purchases"}
        self.assertEqual(VALID_MODELS, expected)
        self.assertIn("date", MODEL_FIELDS["readings"])
        self.assertIn("hall", MODEL_FIELDS["readings"])
        self.assertIn("date", MODEL_FIELDS["charges"])
        self.assertIn("name", MODEL_FIELDS["items"])

    def test_csv_parse_basic(self):
        """验证 CSV 解析基础功能。"""
        csv_text = "date,hall,fire,private_room,ac\n2026-08-18,100.0,1.0,50.0,200.0\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-08-18")
        self.assertEqual(rows[0]["hall"], "100.0")


class TestDataImportDisk(unittest.TestCase):
    """带磁盘 I/O 的导入测试。"""

    @classmethod
    def setUpClass(cls):
        # 目录已在模块级别创建
        _IMPORT_TEST_DIR.mkdir(parents=True, exist_ok=True)
        # 初始化 storage DATA_PATHS (写回 app_handler)
        import storage
        paths = storage.init_data_files(_IMPORT_TEST_DIR)
        # init_data_files 返回 {model: filepath} 但不自动写回全局
        # 写回 app_handler.DATA_PATHS，供 handler 使用
        import app_handler
        for model, filepath in paths.items():
            if model in app_handler.DATA_PATHS:
                app_handler.DATA_PATHS[model] = filepath
        # 初始化 settings
        from handlers.settings import init_settings
        init_settings(_IMPORT_TEST_DIR)

    @classmethod
    def tearDownClass(cls):
        # 保留临时目录供调试（生产测试中可删除）
        pass

    def setUp(self):
        # 清空各数据文件
        import app_handler
        paths = app_handler.DATA_PATHS
        for model, path in paths.items():
            if path:
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("[]", encoding="utf-8")

    def test_readings_import_success(self):
        """有效 readings CSV 应成功导入。"""
        from handlers.dataimport import _import_readings

        csv_text = "date,hall,fire,private_room,ac\n2026-08-18,100.0,1.0,50.0,200.0\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_readings(rows)
        self.assertEqual(count, 1)
        self.assertEqual(failed, 0)
        self.assertEqual(len(errors), 0)

    def test_readings_import_duplicate_updates(self):
        """同一日期的导入应更新而非重复。"""
        from handlers.dataimport import _import_readings
        from storage import load_json

        # 先创建一条
        from storage import save_json
        from app_handler import DATA_PATHS as storage_paths
        save_json(storage_paths["readings"], [
            {"date": "2026-08-18", "hall": 100.0, "fire": 1.0}
        ])

        csv_text = "date,hall,private_room\n2026-08-18,101.0,51.0\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_readings(rows)
        self.assertEqual(count, 1)
        self.assertEqual(failed, 0)

        data = load_json(storage_paths["readings"])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["hall"], 101.0)
        self.assertEqual(data[0]["private_room"], 51.0)
        self.assertEqual(data[0]["fire"], 1.0)  # 旧值保留

    def test_readings_import_invalid_date(self):
        """无效日期应被拒绝。"""
        from handlers.dataimport import _import_readings

        csv_text = "date,hall\n08-18-2026,100.0\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_readings(rows)
        self.assertEqual(count, 0)
        self.assertEqual(failed, 1)
        self.assertIn("日期格式无效", errors[0])

    def test_readings_import_all_zero(self):
        """所有表都未填应被拒绝。"""
        from handlers.dataimport import _import_readings

        csv_text = "date\n2026-08-18\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_readings(rows)
        self.assertEqual(count, 0)
        self.assertEqual(failed, 1)
        self.assertIn("至少需要填写一个表", errors[0])

    def test_charges_import_success(self):
        """有效 charges CSV 应导入成功。"""
        from handlers.dataimport import _import_charges

        csv_text = "date,hall,fire\n2026-08-18,50.0,10.0\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_charges(rows)
        self.assertEqual(count, 1)
        self.assertEqual(failed, 0)

    def test_charges_import_zero_rejected(self):
        """充值全为零应被拒绝。"""
        from handlers.dataimport import _import_charges

        csv_text = "date\n2026-08-18\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_charges(rows)
        self.assertEqual(count, 0)
        self.assertEqual(failed, 1)

    def test_items_import_success(self):
        """有效 items CSV 应导入成功。"""
        from handlers.dataimport import _import_items

        csv_text = "id,name,qty,unit\nitem-1,扫把,5,把\nitem-2,垃圾袋,100,卷\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_items(rows)
        self.assertEqual(count, 2)
        self.assertEqual(failed, 0)

    def test_items_import_duplicate_updates(self):
        """同一名称的 item 应更新而非重复。"""
        from handlers.dataimport import _import_items
        from storage import load_json

        csv_text = "id,name,qty,unit\nitem-1,扫把,10,把\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        # 先存在一个
        from storage import save_json
        from app_handler import DATA_PATHS as storage_paths
        save_json(storage_paths["items"], [
            {"id": "item-old", "name": "扫把", "qty": 5, "unit": "把"}
        ])

        count, failed, errors = _import_items(rows)
        self.assertEqual(count, 1)

        data = load_json(storage_paths["items"])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "item-1")
        self.assertEqual(data[0]["qty"], 10)

    def test_items_import_negative_qty(self):
        """负数数量应被拒绝。"""
        from handlers.dataimport import _import_items

        csv_text = "id,name,qty,unit\nitem-1,扫把,-5,把\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_items(rows)
        self.assertEqual(count, 0)
        self.assertEqual(failed, 1)

    def test_items_import_empty_name(self):
        """空名称应被拒绝。"""
        from handlers.dataimport import _import_items

        csv_text = "id,name,qty,unit\nitem-1,,5,把\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_items(rows)
        self.assertEqual(count, 0)
        self.assertEqual(failed, 1)

    def test_purchases_import_success(self):
        """有效 purchases CSV 应导入成功。"""
        from handlers.dataimport import _import_purchases

        csv_text = "date,name,qty,unit,est_price\n2026-08-18,扫把,5,把,10.5\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_purchases(rows)
        self.assertEqual(count, 1)
        self.assertEqual(failed, 0)

    def test_purchases_import_multiple_same_day(self):
        """purchases 允许同日同名多个。"""
        from handlers.dataimport import _import_purchases

        csv_text = "date,name,qty,unit\n2026-08-18,扫把,5,把\n2026-08-18,扫把,3,把\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        count, failed, errors = _import_purchases(rows)
        self.assertEqual(count, 2)
        self.assertEqual(failed, 0)

    def test_multi_thread_import(self):
        """并发导入应安全（每个线程导入同一数据）。"""
        from handlers.dataimport import _import_items

        csv_text = "id,name,qty,unit\nitem-1,扫把,1,把\n"
        results = []
        errors = []

        def import_worker():
            try:
                reader = csv.DictReader(io.StringIO(csv_text))
                rows = list(reader)
                count, failed, errs = _import_items(rows)
                results.append(count)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=import_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(sum(results), 10)


class TestImportTemplate(unittest.TestCase):
    """模板下载测试：handler、字段对齐、无效模型。"""

    def test_examples_aligned_with_fields(self):
        """每个模型的示例行字段数必须和表头字段数一致（防止以后改字段忘了同步示例）。"""
        from handlers.dataimport import MODEL_FIELDS, MODEL_EXAMPLES, VALID_MODELS
        for model in VALID_MODELS:
            self.assertEqual(
                len(MODEL_EXAMPLES[model]),
                len(MODEL_FIELDS[model]),
                f"模型 {model} 的示例行与表头字段数不一致",
            )

    def test_examples_first_col_is_meaningful(self):
        """示例行应包含可识别的数据，不应全空（避免用户下载到空模板不知格式）。"""
        from handlers.dataimport import MODEL_EXAMPLES, VALID_MODELS
        for model in VALID_MODELS:
            example = MODEL_EXAMPLES[model]
            non_empty = [v for v in example if v and v.strip()]
            self.assertGreater(
                len(non_empty), 0,
                f"模型 {model} 的示例行为空，无法起到示范作用",
            )

    def test_get_template_handler_returns_csv(self):
        """GET /api/import/template?model=items 应返回 text/csv 格式的模板。"""
        import csv as csv_mod
        from io import StringIO
        from handlers.dataimport import (
            handle_get_import_template, MODEL_FIELDS,
        )

        captured = {"headers": {}, "body": b""}

        class _FakeHandler:
            path = "/api/import/template?model=items"
            def send_response(self, status):
                captured["status"] = status
            def send_header(self, k, v):
                captured["headers"][k] = v
            def end_headers(self):
                pass

        class _FakeWFile:
            def write(self, data):
                captured["body"] += data

        h = _FakeHandler()
        h.wfile = _FakeWFile()
        handle_get_import_template(h, h.path)

        self.assertEqual(captured["status"], 200)
        headers = captured["headers"]
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertIn("import-template-items.csv", headers.get("Content-Disposition", ""))

        body = captured["body"].decode("utf-8")
        reader = csv_mod.DictReader(StringIO(body))
        rows = list(reader)
        self.assertEqual(len(rows), 1, "模板应只包含一行示例数据")
        # 示例行字段应与表头一致
        self.assertEqual(
            set(rows[0].keys()),
            set(MODEL_FIELDS["items"]),
            "模板表头应与 MODEL_FIELDS 一致",
        )

    def test_get_template_all_models(self):
        """4 个模型都应能成功生成模板。"""
        from handlers.dataimport import (
            handle_get_import_template, VALID_MODELS, MODEL_FIELDS,
        )
        import csv as csv_mod
        from io import StringIO

        for model in VALID_MODELS:
            captured = {"headers": {}, "body": b""}

            class _FakeHandler:
                path = f"/api/import/template?model={model}"
                def send_response(self, status):
                    captured["status"] = status
                def send_header(self, k, v):
                    captured["headers"][k] = v
                def end_headers(self):
                    pass

            class _FakeWFile:
                def write(self, data):
                    captured["body"] += data

            h = _FakeHandler()
            h.wfile = _FakeWFile()
            handle_get_import_template(h, h.path)

            self.assertEqual(captured["status"], 200, f"{model} 模板下载应返回 200")
            body = captured["body"].decode("utf-8")
            reader = csv_mod.DictReader(StringIO(body))
            rows = list(reader)
            self.assertEqual(len(rows), 1, f"{model} 模板应包含一行示例")
            self.assertEqual(
                set(rows[0].keys()),
                set(MODEL_FIELDS[model]),
                f"{model} 表头不匹配",
            )

    def test_get_template_invalid_model(self):
        """未知模型应返回 400 JSON 错误。"""
        import json as json_mod
        from handlers.dataimport import handle_get_import_template

        captured = {"headers": {}, "body": b""}

        class _FakeHandler:
            path = "/api/import/template?model=bogus"
            def send_response(self, status):
                captured["status"] = status
            def send_header(self, k, v):
                captured["headers"][k] = v
            def end_headers(self):
                pass

        class _FakeWFile:
            def write(self, data):
                captured["body"] += data

        h = _FakeHandler()
        h.wfile = _FakeWFile()
        handle_get_import_template(h, h.path)

        self.assertEqual(captured["status"], 400)
        self.assertIn("application/json", captured["headers"].get("Content-Type", ""))
        payload = json_mod.loads(captured["body"].decode("utf-8"))
        self.assertIn("error", payload)
        self.assertIn("bogus", payload["error"])


if __name__ == "__main__":
    unittest.main()
