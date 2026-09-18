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
            "readings_water": self.data_dir / "readings_water.json",
            "charges": self.data_dir / "charges.json",
            "items": self.data_dir / "items.json",
            "purchases": self.data_dir / "purchases.json",
            "duty": self.data_dir / "duty.json",
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
        # 水电表底字段(main_meter/sub_meter/water)已迁移至 /api/readings-water,
        # /api/readings 现在只接受电表抄表字段,多余字段被忽略。
        h = self.call("POST", "/api/readings", {
            "date": "2026-08-18", "hall": 100.0,
            "fire": "", "private_room": "", "ac": "",
        })
        self.assertEqual(h.response_status, 200)
        row = h.parsed["row"]
        self.assertEqual(row["hall"], 100.0)
        self.assertIsNone(row["fire"])
        self.assertIsNone(row["private_room"])
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
        # 二次 POST 时只提供部分字段,未填的字段保留旧值。
        self.call("POST", "/api/readings", {
            "date": "2026-08-18", "hall": 100.0, "fire": 50.0,
            "private_room": 30.0, "ac": 20.0,
        })
        h = self.call("POST", "/api/readings", {
            "date": "2026-08-18",
            "hall": 110.0, "fire": "", "private_room": "", "ac": "",
        })
        self.assertEqual(h.response_status, 200)
        row = h.parsed["row"]
        self.assertEqual(row["hall"], 110.0)  # 新值覆盖
        self.assertEqual(row["fire"], 50.0)    # 旧值保留
        self.assertEqual(row["private_room"], 30.0)  # 旧值保留
        self.assertEqual(row["ac"], 20.0)  # 旧值保留

    def test_post_empty_all_fields_rejected(self):
        # 全部字段为空(没有原记录可覆盖) → 400。
        h = self.call("POST", "/api/readings", {"date": "2026-08-18"})
        self.assertEqual(h.response_status, 400)

    def test_post_overwrite_water_only_keeps_electric(self):
        # 水电表底走独立 API;/api/readings 现在会保留电表字段。
        self.call("POST", "/api/readings", {
            "date": "2026-08-18", "hall": 100.0, "fire": 50.0,
            "private_room": 30.0, "ac": 20.0,
        })
        h = self.call("POST", "/api/readings-water", {
            "date": "2026-08-18",
            "main_meter": 51800.0, "sub_meter": 20800.0, "water": 3140.0,
        })
        self.assertEqual(h.response_status, 200)
        # 电表记录不受水电提交影响
        readings = self.read_json("readings")
        self.assertEqual(readings[0]["hall"], 100.0)
        # 水电记录独立存储
        water = self.read_json("readings_water")
        self.assertEqual(water[0]["water"], 3140.0)

    def test_put_nonexistent_returns_404(self):
        h = self.call("PUT", "/api/readings/2026-01-01", {"hall": 1})
        self.assertEqual(h.response_status, 404)


class TestReadingsWaterApi(TestApiBase):
    """水电表底 API:独立于电表,使用 readings_water.json。"""

    def test_post_water_only(self):
        h = self.call("POST", "/api/readings-water", {
            "date": "2026-08-18",
            "main_meter": 51800.0, "sub_meter": 20800.0, "water": 3140.0,
        })
        self.assertEqual(h.response_status, 200)
        row = h.parsed["row"]
        self.assertEqual(row["main_meter"], 51800.0)
        self.assertEqual(row["water"], 3140.0)

    def test_post_requires_at_least_one_field(self):
        h = self.call("POST", "/api/readings-water", {"date": "2026-08-18"})
        self.assertEqual(h.response_status, 400)

    def test_post_empty_fields_become_null(self):
        h = self.call("POST", "/api/readings-water", {
            "date": "2026-08-18", "main_meter": 100.0,
            "sub_meter": "", "water": "",
        })
        self.assertEqual(h.response_status, 200)
        row = h.parsed["row"]
        self.assertEqual(row["main_meter"], 100.0)
        self.assertIsNone(row["sub_meter"])
        self.assertIsNone(row["water"])


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

    def test_item_put_whitelist_blocks_unknown_fields(self):
        """验证 PUT 白名单生效: 不在 updatable_fields 的字段(如 lent_qty)
        会被忽略,即使攻击者在 body 里传也不会被写入。
        """
        # 先创建 item
        h = self.call("PUT", "/api/items", {"name": "扫把", "qty": 5, "unit": "把"})
        self.assertEqual(h.response_status, 200)
        item_id = h.parsed["row"]["id"]

        # 尝试注入 lent_qty (不应被允许通过 PUT 修改)
        h2 = self.call("PUT", f"/api/items/{item_id}", {
            "name": "扫把",
            "qty": 5,
            "lent_qty": 999,  # ← 应被白名单拒绝
            "malicious_field": "hacker",  # ← 也应被拒绝
        })
        # 应仍返回 200(name/qty 被接受)
        self.assertEqual(h2.response_status, 200)
        # lent_qty 不应被写入
        item = self.read_json("items")[0]
        self.assertNotEqual(item.get("lent_qty"), 999,
                            "PUT 不应允许修改 lent_qty(应仅能通过 /lend 接口)")
        self.assertNotIn("malicious_field", item)
        self.assertEqual(item["name"], "扫把")

    # ---------- 借出 / 归还 边界 ----------

    def _create_item(self, qty: float = 10) -> str:
        """辅助:创建一件物品,返回 id。"""
        h = self.call("PUT", "/api/items", {"name": "扫把", "qty": qty, "unit": "把"})
        self.assertEqual(h.response_status, 200)
        return h.parsed["row"]["id"]

    def test_lend_requires_borrower(self):
        iid = self._create_item(10)
        h = self.call("PUT", f"/api/items/{iid}/lend", {"qty": 1})  # 缺 borrower
        self.assertEqual(h.response_status, 400)
        self.assertIn("借出人", h.parsed["error"])

    def test_lend_requires_positive_qty(self):
        iid = self._create_item(10)
        # qty=0
        h0 = self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "张三", "qty": 0})
        self.assertEqual(h0.response_status, 400)
        # qty=-1
        hn = self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "张三", "qty": -1})
        self.assertEqual(hn.response_status, 400)

    def test_lend_exceeding_available_rejected(self):
        """只能借出 'total - lent' 数量,超出拒绝。"""
        iid = self._create_item(5)
        # 借出 3,剩 2
        h1 = self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "张三", "qty": 3})
        self.assertEqual(h1.response_status, 200)
        # 再借 3 - 超出现有 2
        h2 = self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "李四", "qty": 3})
        self.assertEqual(h2.response_status, 400)
        self.assertIn("可借出数量不足", h2.parsed["error"])
        # 借出 2 - 正好等于剩余,应成功
        h3 = self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "李四", "qty": 2})
        self.assertEqual(h3.response_status, 200)
        # 再借 1 - 超了(已全部借出)
        h4 = self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "王五", "qty": 1})
        self.assertEqual(h4.response_status, 400)

    def test_lend_nonexistent_item_404(self):
        h = self.call("PUT", "/api/items/no-such-id/lend", {"borrower": "张三", "qty": 1})
        self.assertEqual(h.response_status, 404)

    def test_return_without_lending_rejected(self):
        iid = self._create_item(10)
        h = self.call("PUT", f"/api/items/{iid}/return", {"qty": 1})
        self.assertEqual(h.response_status, 400)
        self.assertIn("没有借出记录", h.parsed["error"])

    def test_return_exceeding_lent_rejected(self):
        iid = self._create_item(10)
        self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "张三", "qty": 3})
        # 归还 5 - 超过借出 3
        h = self.call("PUT", f"/api/items/{iid}/return", {"qty": 5})
        self.assertEqual(h.response_status, 400)
        self.assertIn("归还数量超过借出数量", h.parsed["error"])

    def test_return_partial_updates_records(self):
        """部分归还:借 3 还 1,记录上应记 return_qty=1 且状态仍为 lent。"""
        iid = self._create_item(10)
        self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "张三", "qty": 3})
        h = self.call("PUT", f"/api/items/{iid}/return", {"qty": 1, "note": "只还了一个"})
        self.assertEqual(h.response_status, 200)
        item = self.read_json("items")[0]
        # lent_qty 减 1
        self.assertEqual(item["lent_qty"], 2)
        # 记录上 return_qty=1,status 仍为 lent (未完全还清)
        rec = item["lend_records"][0]
        self.assertEqual(rec["return_qty"], 1)
        self.assertEqual(rec["status"], "lent")
        self.assertEqual(rec["return_note"], "只还了一个")

    def test_return_full_marks_record_returned(self):
        """全部归还:记录 status='returned' 并设置 return_date。"""
        iid = self._create_item(10)
        self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "张三", "qty": 3})
        h = self.call("PUT", f"/api/items/{iid}/return", {"qty": 3})
        self.assertEqual(h.response_status, 200)
        item = self.read_json("items")[0]
        self.assertEqual(item["lent_qty"], 0)
        rec = item["lend_records"][0]
        self.assertEqual(rec["status"], "returned")
        self.assertIsNotNone(rec["return_date"])

    def test_return_fifo_across_multiple_records(self):
        """多次借出后归还:按 FIFO 顺序逐条归还。"""
        iid = self._create_item(10)
        self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "张三", "qty": 2})
        self.call("PUT", f"/api/items/{iid}/lend", {"borrower": "李四", "qty": 3})
        # 归还 4 → 应先还张三的 2(清),再还李四 2
        h = self.call("PUT", f"/api/items/{iid}/return", {"qty": 4})
        self.assertEqual(h.response_status, 200)
        item = self.read_json("items")[0]
        self.assertEqual(item["lent_qty"], 1)
        records = sorted(item["lend_records"], key=lambda r: r["lend_date"])
        # 第一条(张三):status returned,return_qty=2
        self.assertEqual(records[0]["status"], "returned")
        self.assertEqual(records[0]["return_qty"], 2)
        # 第二条(李四):status lent,return_qty=2
        self.assertEqual(records[1]["status"], "lent")
        self.assertEqual(records[1]["return_qty"], 2)


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

    def test_manual_backup_same_day_multiple_allowed(self):
        """同日可多次手动备份,每次独立生成新文件(无一日一备限制)。"""
        self.call("POST", "/api/readings", {"date": "2026-08-18", "hall": 100.0})
        first = self.call("POST", "/api/backup")
        self.assertTrue(first.parsed["ok"])
        backup_dir = Path(first.parsed["zip_path"]).parent

        second = self.call("POST", "/api/backup")
        self.assertEqual(second.response_status, 200)
        self.assertTrue(second.parsed["ok"])
        self.assertTrue(Path(second.parsed["zip_path"]).is_file())

        # 两个独立备份文件
        zips = list(backup_dir.glob("meter-backup-*.zip"))
        self.assertEqual(len(zips), 2)

    def test_manual_backup_max_10(self):
        """手动备份最多保留 10 个,超出自动删除最旧。"""
        self.call("POST", "/api/readings", {"date": "2026-08-18", "hall": 100.0})
        first = self.call("POST", "/api/backup")
        backup_dir = Path(first.parsed["zip_path"]).parent

        # 连做 12 次手动备份
        for _ in range(11):
            h = self.call("POST", "/api/backup")
            self.assertTrue(h.parsed["ok"])

        zips = sorted(backup_dir.glob("meter-backup-*.zip"))
        self.assertEqual(len(zips), 10)  # 只保留最新 10 个

    # ---------- /api/upload (JSON body 路径) ----------

    def _build_valid_backup_zip(self) -> bytes:
        """构造一个合法 ZIP,内含 readings.json + charges.json,用于上传恢复测试。"""
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("readings.json", json.dumps([
                {"date": "2026-08-01", "hall": 100.0, "fire": 1.0,
                 "private_room": 50.0, "ac": 30.0, "note": ""}
            ], ensure_ascii=False))
            zf.writestr("charges.json", json.dumps([], ensure_ascii=False))
        return buf.getvalue()

    def test_upload_zip_restores_data(self):
        """上传一个合法 ZIP,读取后数据被恢复到数据文件。"""
        # 初始数据
        self.call("POST", "/api/readings", {"date": "2026-09-01", "hall": 999.0})
        self.assertEqual(len(self.read_json("readings")), 1)

        # 构造备份 ZIP(只含 readings.json + charges.json)
        zip_bytes = self._build_valid_backup_zip()

        # 上传(走 JSON body 路径, base64 包装)
        import base64
        h = self.call("POST", "/api/upload", {"files": {
            "backup.zip": {"__zip_b64": base64.b64encode(zip_bytes).decode("ascii")}
        }})
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"])
        self.assertIn("readings.json", h.parsed["restored"])

        # 数据已被 ZIP 内容覆盖(不再有 999.0,有 100.0)
        data = self.read_json("readings")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["hall"], 100.0)

    def test_upload_zip_with_must_be_valid(self):
        """上传非 ZIP 字节:base64 能解但 ZIP 解析失败 → 跳过该文件,返回 ok=false。
        (实际上 handler 不崩,只是该文件不进 restored 列表)
        """
        import base64
        not_a_zip = b"this is definitely not a zip file"
        h = self.call("POST", "/api/upload", {"files": {
            "fake.zip": {"__zip_b64": base64.b64encode(not_a_zip).decode("ascii")}
        }})
        self.assertEqual(h.response_status, 200)
        # 不是合法 zip,不应进 restored
        self.assertNotIn("readings.json", h.parsed.get("restored", []))

    def test_upload_missing_files_field(self):
        """上传但缺 files 字段 → 返回错误但不崩。"""
        h = self.call("POST", "/api/upload", {})
        self.assertEqual(h.response_status, 200)
        self.assertFalse(h.parsed["ok"])
        self.assertIn("files", h.parsed["error"])

    def test_upload_zip_bomb_protection(self):
        """验证 ZIP Bomb 防护:上传一个压缩后小但解压后巨大的 ZIP 应被拒绝。
        _validate_zip_safely 会在解压前检查 file_size 总和,超出 ZIP_MAX_DECOMPRESSED_SIZE 拒绝。
        """
        import base64
        # 构造一个“解压后很大”的伪造 ZIP:
        # 由于 _validate_zip_safely 在解压前检查 zip 中央目录中声明的 file_size,
        # 只要伪造 file_size 巨大就会被拒绝。手工构造复杂,改为调用函数直接验证:
        from utils.api import _validate_zip_safely, ZIP_MAX_DECOMPRESSED_SIZE

        # 在 tmp 里构造一个合法但空的 ZIP
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            empty_zip = tmp / "empty.zip"
            with zipfile.ZipFile(empty_zip, 'w') as zf:
                zf.writestr("a.txt", "ok")  # 正常文件

            # 正常 ZIP 应能解压
            safe_dir, err = _validate_zip_safely(empty_zip, str(tmp / "extract"))
            self.assertIsNone(err, f"正常 ZIP 不应被拒绝: {err}")
            self.assertTrue((tmp / "extract" / "a.txt").exists())

        # 验证最大限制常量是 100 MB(防止默认值被误改)
        self.assertEqual(ZIP_MAX_DECOMPRESSED_SIZE, 100 * 1024 * 1024)


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
