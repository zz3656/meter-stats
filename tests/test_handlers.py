"""app_handler.py API 层回归测试(标准库 unittest,零依赖)。

用 FakeHandler 模拟 HTTP 请求,直接调用 _do_api,
覆盖数据安全核心路径:
- 抄表 POST/PUT:空字段 → null(不是 0)
- 充值 POST/PUT:全 0 / 负数 拒绝
- 物品/申购:负数拒绝
- 手动备份 /api/backup
- 数据损坏自动恢复(load_json)

运行:
    cd ~/Documents/electricity-stats-app
    env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_handlers -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

import app_handler  # noqa: E402


class FakeHandler:
    """模拟 BaseHTTPRequestHandler 的最小实现,捕获响应。"""

    def __init__(self, path: str, body: Optional[dict] = None, method: str = "POST"):
        self.path = path
        self.command = method
        self.response_status = None
        self.response_headers = {}
        self.response_body = b""
        self.wfile = io.BytesIO()
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            self.rfile = io.BytesIO(raw)
            self.headers = {"Content-Length": str(len(raw))}
        else:
            self.rfile = io.BytesIO(b"")
            self.headers = {"Content-Length": "0"}

    def send_response(self, status):
        self.response_status = status

    def send_header(self, k, v):
        self.response_headers[k] = v

    def end_headers(self):
        pass

    @property
    def parsed(self):
        """解析捕获的 JSON 响应。"""
        body = self.wfile.getvalue()
        return json.loads(body) if body else None


class TestApiBase(unittest.TestCase):
    """基类:每个测试用独立临时数据目录,隔离数据。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        paths = {
            "readings": self.data_dir / "readings.json",
            "charges": self.data_dir / "charges.json",
            "items": self.data_dir / "items.json",
            "purchases": self.data_dir / "purchases.json",
        }
        app_handler.DATA_PATHS = paths
        for p in paths.values():
            p.write_text("[]", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method: str, path: str, body: Optional[dict] = None) -> FakeHandler:
        h = FakeHandler(path, body, method)
        app_handler._do_api(method, h, path)
        return h

    # ---- 辅助读取 ----
    def read_json(self, model: str) -> list:
        return json.loads(app_handler.DATA_PATHS[model].read_text(encoding="utf-8"))


class TestReadingsApi(TestApiBase):
    def test_post_empty_fields_become_null(self):
        h = self.call("POST", "/api/readings", {
            "date": "2026-08-18", "hall": 100.0,
            "fire": "", "private_room": "", "ac": "",
            "main_meter": "", "sub_meter": "", "water": "",
        })
        self.assertEqual(h.response_status, 200)
        row = h.parsed["row"]
        self.assertEqual(row["hall"], 100.0)
        self.assertIsNone(row["fire"])
        self.assertIsNone(row["water"])
        self.assertIsNone(row["ac"])

    def test_post_requires_at_least_one_field(self):
        h = self.call("POST", "/api/readings", {"date": "2026-08-18"})
        self.assertEqual(h.response_status, 400)

    def test_put_empty_field_keeps_null_not_zero(self):
        self.call("POST", "/api/readings", {
            "date": "2026-08-18", "hall": 100.0, "fire": 50.0,
            "private_room": 30.0, "ac": 20.0,
        })
        h = self.call("PUT", "/api/readings/2026-08-18", {
            "hall": 100.0, "fire": "", "private_room": 30.0, "ac": 20.0,
        })
        self.assertEqual(h.response_status, 200)
        row = h.parsed["row"]
        self.assertIsNone(row["fire"])

    def test_post_overwrite_preserves_old_null_fields(self):
        self.call("POST", "/api/readings", {
            "date": "2026-08-18", "hall": 100.0, "fire": 50.0,
            "private_room": 30.0, "ac": 20.0,
        })
        h = self.call("POST", "/api/readings", {
            "date": "2026-08-18",
            "main_meter": 51800.0, "sub_meter": 20800.0, "water": 3140.0,
        })
        self.assertEqual(h.response_status, 200)
        row = h.parsed["row"]
        self.assertEqual(row["hall"], 100.0)
        self.assertEqual(row["main_meter"], 51800.0)
        self.assertEqual(row["water"], 3140.0)

    def test_put_nonexistent_returns_404(self):
        h = self.call("PUT", "/api/readings/2026-01-01", {"hall": 1})
        self.assertEqual(h.response_status, 404)


class TestChargesApi(TestApiBase):
    def test_post_all_zero_rejected(self):
        h = self.call("POST", "/api/charges", {
            "date": "2026-08-18",
            "hall": 0, "fire": 0, "private_room": 0, "ac": 0,
        })
        self.assertEqual(h.response_status, 400)
        self.assertIn("error", h.parsed)

    def test_post_valid_charge_saved(self):
        h = self.call("POST", "/api/charges", {
            "date": "2026-08-18", "hall": 80.0,
            "fire": 0, "private_room": 0, "ac": 0,
        })
        self.assertEqual(h.response_status, 200)
        self.assertEqual(len(self.read_json("charges")), 1)

    def test_put_negative_charge_rejected(self):
        self.call("POST", "/api/charges", {
            "date": "2026-08-18", "hall": 80.0,
        })
        cid = self.read_json("charges")[0]["id"]
        h = self.call("PUT", f"/api/charges/{cid}", {"hall": -10.0})
        self.assertEqual(h.response_status, 400)
        self.assertIn("error", h.parsed)


class TestItemsPurchasesApi(TestApiBase):
    def test_item_negative_qty_rejected(self):
        h = self.call("PUT", "/api/items", {"name": "扫把", "qty": -5, "unit": "把"})
        self.assertEqual(h.response_status, 400)

    def test_item_valid_saved(self):
        h = self.call("PUT", "/api/items", {"name": "扫把", "qty": 5, "unit": "把"})
        self.assertEqual(h.response_status, 200)
        self.assertEqual(len(self.read_json("items")), 1)

    def test_purchase_negative_price_rejected(self):
        h = self.call("PUT", "/api/purchases", {
            "name": "灯泡", "qty": 10, "est_price": -5,
        })
        self.assertEqual(h.response_status, 400)

    def test_purchase_negative_qty_rejected(self):
        h = self.call("PUT", "/api/purchases", {
            "name": "灯泡", "qty": -10, "est_price": 5,
        })
        self.assertEqual(h.response_status, 400)


class TestBackupApi(TestApiBase):
    def test_manual_backup_creates_zip(self):
        self.call("POST", "/api/readings", {"date": "2026-08-18", "hall": 100.0})
        h = self.call("POST", "/api/backup")
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"])
        zip_path = Path(h.parsed["zip_path"])
        self.assertTrue(zip_path.is_file())
        self.assertEqual(zip_path.suffix, ".zip")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            self.assertIn("readings.json", zf.namelist())

    def test_manual_backup_same_day_returns_exists(self):
        """同日再次手动备份:返回 exists,不新增备份文件。"""
        self.call("POST", "/api/readings", {"date": "2026-08-18", "hall": 100.0})
        first = self.call("POST", "/api/backup")
        self.assertTrue(first.parsed["ok"])
        backup_dir = Path(first.parsed["zip_path"]).parent

        second = self.call("POST", "/api/backup")
        self.assertEqual(second.response_status, 200)
        self.assertFalse(second.parsed["ok"])
        self.assertTrue(second.parsed["exists"])
        self.assertTrue(second.parsed["existing"])

        # 备份文件数量不变(仍只有 1 个今日手动备份)
        today = datetime.now().strftime("%Y%m%d")
        zips = list(backup_dir.glob(f"meter-backup-{today}_*.zip"))
        self.assertEqual(len(zips), 1)

    def test_manual_backup_force_overwrites_same_day(self):
        """force=1 时删除旧今日备份并重新打包当前数据。"""
        self.call("POST", "/api/readings", {"date": "2026-08-18", "hall": 100.0})
        first = self.call("POST", "/api/backup")
        backup_dir = Path(first.parsed["zip_path"]).parent

        # 再写入一条数据,force 覆盖(同秒内新旧文件同路径,按内容验证)
        self.call("POST", "/api/readings", {"date": "2026-08-19", "hall": 50.0})
        forced = self.call("POST", "/api/backup?force=1")
        self.assertEqual(forced.response_status, 200)
        self.assertTrue(forced.parsed["ok"])
        new_zip = Path(forced.parsed["zip_path"])
        self.assertTrue(new_zip.is_file())

        # 今日手动备份仍只有 1 个,且内容是最新数据(2 条抄表)
        today = datetime.now().strftime("%Y%m%d")
        zips = list(backup_dir.glob(f"meter-backup-{today}_*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(new_zip, 'r') as zf:
            names = zf.namelist()
            self.assertIn("readings.json", names)
            readings = json.loads(zf.read("readings.json").decode("utf-8"))
            self.assertEqual(len(readings), 2)


class TestStorageRecovery(unittest.TestCase):
    def test_corrupt_json_recovers_from_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "backup" / "20260817").mkdir(parents=True)
            (d / "backup" / "20260817" / "readings.json").write_text(
                json.dumps([{"date": "2026-08-01", "hall": 1.0}]), encoding="utf-8")
            (d / "readings.json").write_text("{broken json!!", encoding="utf-8")

            from storage import load_json
            data = load_json(d / "readings.json", [])
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["date"], "2026-08-01")
            self.assertTrue((d / "readings.json").read_text(encoding="utf-8").startswith("["))


if __name__ == "__main__":
    unittest.main()
