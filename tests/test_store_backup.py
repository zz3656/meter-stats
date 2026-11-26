"""Task 7 回归测试 —— 备份 / 恢复 / NAS 同步 / 图片 覆盖 stores/ 子树。

背景:
- P0「单实例、多门店」之后,业务数据都在 stores/<store_id>/ 下,顶层只剩 settings.json。
- 改造前备份/恢复/NAS 同步全部用 `get_data_paths().get("readings").parent` 当数据根目录,
  多门店布局下那只是「当前门店」的目录 → 备份只抓到一个店,严重不完整。
- 本文件锁死的行为:
  1. 备份包(含自动备份与手动备份)必须包含 **所有门店** 的数据文件;
  2. ZIP 条目名必须是相对路径(`stores/s002/readings.json`),不能被压成 `readings.json`;
  3. 恢复必须按相对路径还原到 `stores/<id>/` 下;
  4. 路径穿越(`..`、绝对路径、非法门店 ID、未知文件名)必须被挡;
  5. 值班图片目录按门店隔离;
  6. **图片不进备份** —— 维持改造前现状(照片从来没被备份过),不做半吊子。

运行:
    python3 -m unittest tests.test_store_backup -v
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from backup_paths import classify_rel, iter_backup_files  # noqa: E402
from modules.backup.handler import (  # noqa: E402
    _safe_rel_target,
    handle_get_data_files,
    handle_post_backup,
    handle_post_restore,
    handle_post_upload,
)
from modules.duty.handler import _get_images_dir  # noqa: E402
from modules.stores import context  # noqa: E402

import app_handler  # noqa: E402
import routing  # noqa: E402
from storage import DATA_FILES, backup_data, load_json  # noqa: E402

# ⚠️ modules.backup.admin_handler 不能在模块顶层 import ——
#    modules/system/admin_handler.py 顶层就 import 了 modules.backup.admin_handler,
#    先 import 后者会撞上这个**既存的**循环 import(与本 Task 无关)。
#    所以用到它的两个用例在函数体内 import(此时 modules.system 已经加载完了)。


class FakeHandler:
    """模拟 BaseHTTPRequestHandler 的最小实现,捕获响应。"""

    def __init__(self, path: str, body: Optional[dict[str, Any]] = None,
                 method: str = "GET", content_type: str = "application/json",
                 raw_body: Optional[bytes] = None) -> None:
        self.path = path
        self.command = method
        self.response_status: Optional[int] = None
        self.response_headers: dict[str, str] = {}
        self.response_body = b""
        self.wfile = io.BytesIO()
        if raw_body is not None:
            self.rfile = io.BytesIO(raw_body)
            self.headers = {
                "Content-Length": str(len(raw_body)),
                "Content-Type": content_type,
            }
        elif body is not None:
            raw = json.dumps(body).encode("utf-8")
            self.rfile = io.BytesIO(raw)
            self.headers = {
                "Content-Length": str(len(raw)),
                "Content-Type": content_type,
            }
        else:
            self.rfile = io.BytesIO(b"")
            self.headers = {"Content-Length": "0", "Content-Type": content_type}

    def send_response(self, status: int) -> None:
        self.response_status = status

    def send_header(self, k: str, v: str) -> None:
        self.response_headers[k] = v

    def end_headers(self) -> None:
        pass

    @property
    def parsed(self) -> Any:
        body = self.wfile.getvalue()
        return json.loads(body) if body else None


class StoreBackupTestBase(unittest.TestCase):
    """基类:独立临时数据目录 + 关闭业务鉴权。"""

    def setUp(self) -> None:
        self._prev_enforce = routing.ENFORCE_AUTH
        self._prev_paths = app_handler.DATA_PATHS
        self._prev_data_dir_env = os.environ.get("METER_DATA_DIR")
        routing.ENFORCE_AUTH = False
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        # 让 storage.get_data_dir() 指向临时目录 ——
        # 否则 duty 的 _get_settings() 会读到真实用户目录里的 settings.json。
        os.environ["METER_DATA_DIR"] = str(self.data_dir)
        context.clear_current_store()

    def tearDown(self) -> None:
        routing.ENFORCE_AUTH = self._prev_enforce
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        if self._prev_data_dir_env is None:
            os.environ.pop("METER_DATA_DIR", None)
        else:
            os.environ["METER_DATA_DIR"] = self._prev_data_dir_env
        self.tmp.cleanup()

    # ---- 辅助 ----

    def _write_settings(self) -> None:
        (self.data_dir / "settings.json").write_text(
            json.dumps({"auto_backup": True}, ensure_ascii=False), encoding="utf-8")

    def _make_stores(self) -> None:
        """建两个门店:各有一份 readings.json + store.json + 自己的图片目录。"""
        self._write_settings()
        for sid, hall in (("main", 1.0), ("s002", 2.0)):
            d = self.data_dir / "stores" / sid
            d.mkdir(parents=True)
            (d / "readings.json").write_text(
                json.dumps([{"date": "2026-11-01", "hall": hall}], ensure_ascii=False),
                encoding="utf-8")
            (d / "store.json").write_text(
                json.dumps({"id": sid, "name": sid}, ensure_ascii=False), encoding="utf-8")
            img = d / "images"
            img.mkdir(parents=True)
            (img / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")

    def _store_zip_bytes(self) -> bytes:
        """构造一个含门店子树的备份 ZIP。"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("readings.json", json.dumps([{"date": "2026-01-01", "hall": 1.0}]))
            zf.writestr("stores/s002/readings.json",
                        json.dumps([{"date": "2026-02-02", "hall": 2.0}]))
            zf.writestr("stores/s002/store.json",
                        json.dumps({"id": "s002", "name": "分店二"}))
        return buf.getvalue()

    def _multipart_zip_body(self, zip_bytes: bytes) -> tuple[bytes, str]:
        """构造 multipart/form-data 的 ZIP 上传体。"""
        boundary = "----MeterStatsTestBoundary"
        raw = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="backup.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8") + zip_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
        return raw, f"multipart/form-data; boundary={boundary}"


class TestBackupZipContents(StoreBackupTestBase):
    """备份包必须覆盖所有门店(stores/ 子树)。"""

    def test_backup_zip_contains_all_stores(self) -> None:
        """自动备份的 ZIP 里必须有每个门店的 readings.json。"""
        self._make_stores()
        zip_path = backup_data(self.data_dir, force=True)
        self.assertIsNotNone(zip_path)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("stores/main/readings.json", names)
        self.assertIn("stores/s002/readings.json", names)

    def test_backup_zip_contains_store_config(self) -> None:
        """门店配置 store.json 必须能被备份(恢复时门店配置要回来)。"""
        self._make_stores()
        zip_path = backup_data(self.data_dir, force=True)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("stores/s002/store.json", names)

    def test_backup_zip_contains_settings_json(self) -> None:
        self._make_stores()
        zip_path = backup_data(self.data_dir, force=True)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("settings.json", names)

    def test_backup_zip_includes_images(self) -> None:
        """值班照片进备份(0.5.1)。

        以前 images/ 从来没进过备份 —— 换机器 / 重建容器等于照片永久丢失。
        现在「备份收什么」由 backup_paths.classify_rel 统一决定,恢复侧认同一套规则,
        所以收进来不会被静默丢弃(round-trip 由下面的 TestImageRoundTrip 锁死)。
        """
        self._make_stores()
        zip_path = backup_data(self.data_dir, force=True)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("stores/s002/images/photo.jpg", names)
        self.assertIn("stores/main/images/photo.jpg", names)

    def test_manual_backup_zip_contains_all_stores(self) -> None:
        """手动备份(/api/backup)同样必须覆盖所有门店。"""
        self._make_stores()
        h = FakeHandler("/api/backup", method="POST")
        handle_post_backup(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        assert h.parsed is not None
        self.assertTrue(h.parsed["ok"], h.parsed)
        with zipfile.ZipFile(h.parsed["zip_path"]) as zf:
            names = zf.namelist()
        self.assertIn("stores/main/readings.json", names)
        self.assertIn("stores/s002/readings.json", names)
        self.assertIn("stores/s002/store.json", names)

    def test_manual_backup_zip_includes_images(self) -> None:
        """手动备份也要收图片 —— 自动/手动两条路径必须同一口径。"""
        self._make_stores()
        h = FakeHandler("/api/backup", method="POST")
        handle_post_backup(h)  # type: ignore[no-untyped-call]
        assert h.parsed is not None
        with zipfile.ZipFile(h.parsed["zip_path"]) as zf:
            names = zf.namelist()
        self.assertIn("stores/s002/images/photo.jpg", names)


class TestIterBackupFiles(StoreBackupTestBase):
    """stores/ 与 images/ 子树的列举(规则来源 backup_paths.classify_rel)。"""

    def test_lists_all_store_json_files(self) -> None:
        self._make_stores()
        rels = [rel for rel, _ in iter_backup_files(self.data_dir, include_images=False)]
        self.assertIn("stores/main/readings.json", rels)
        self.assertIn("stores/s002/readings.json", rels)
        self.assertIn("stores/s002/store.json", rels)

    def test_images_only_when_asked(self) -> None:
        """图片要显式 include_images=True 才收:
        数据文件列举接口(/api/admin/data-files)回的是 JSON 文本,不能混进二进制。"""
        self._make_stores()
        without = [r for r, _ in iter_backup_files(self.data_dir, include_images=False)]
        self.assertFalse([r for r in without if "/images/" in r])
        with_images = [r for r, _ in iter_backup_files(self.data_dir, include_images=True)]
        self.assertIn("stores/s002/images/photo.jpg", with_images)

    def test_empty_without_stores_dir(self) -> None:
        self.assertEqual(list(iter_backup_files(self.data_dir)), [])


class TestSafeRelTarget(StoreBackupTestBase):
    """路径穿越护栏。"""

    def test_rejects_traversal(self) -> None:
        self.assertIsNone(_safe_rel_target(self.data_dir, "../../etc/passwd"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/../../evil.json"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/s002/../../../evil.json"))

    def test_rejects_absolute_path(self) -> None:
        self.assertIsNone(_safe_rel_target(self.data_dir, "/etc/passwd"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "/stores/s002/readings.json"))

    def test_rejects_backslash(self) -> None:
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores\\s002\\readings.json"))

    def test_rejects_invalid_store_id(self) -> None:
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/../evil/readings.json"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/bad id/readings.json"))

    def test_accepts_store_path(self) -> None:
        p = _safe_rel_target(self.data_dir, "stores/s002/readings.json")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p, self.data_dir / "stores" / "s002" / "readings.json")

    def test_accepts_store_config(self) -> None:
        """门店配置 store.json 必须放行 —— 否则恢复后门店配置丢了。"""
        p = _safe_rel_target(self.data_dir, "stores/s002/store.json")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p, self.data_dir / "stores" / "s002" / "store.json")

    def test_accepts_top_level_data_files(self) -> None:
        self.assertEqual(_safe_rel_target(self.data_dir, "readings.json"),
                         self.data_dir / "readings.json")
        self.assertEqual(_safe_rel_target(self.data_dir, "settings.json"),
                         self.data_dir / "settings.json")

    def test_rejects_unknown_top_level_file(self) -> None:
        self.assertIsNone(_safe_rel_target(self.data_dir, "evil.json"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "passwd"))

    def test_rejects_unknown_store_file(self) -> None:
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/s002/evil.json"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/s002/readings.json.tmp"))

    def test_rejects_too_deep_path(self) -> None:
        """恢复只认备份会收的形态 —— 更深的一律不认(避免「收得进、恢复丢」)。"""
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/s002/backup/20260101/readings.json"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "a/b/c/d.json"))

    def test_accepts_store_images(self) -> None:
        """门店照片:备份收得进,恢复就得认得回。"""
        self.assertIsNotNone(_safe_rel_target(self.data_dir, "stores/s002/images/photo.jpg"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/s002/images/evil.txt"))


class TestDataFilesEndpoint(StoreBackupTestBase):
    """GET /api/admin/data-files(NAS 同步的取数接口)必须返回所有门店的文件。"""

    def test_includes_store_files(self) -> None:
        self._make_stores()
        h = FakeHandler("/api/admin/data-files", method="GET")
        handle_get_data_files(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        assert h.parsed is not None
        files = h.parsed["files"]
        self.assertIn("stores/main/readings.json", files)
        self.assertIn("stores/s002/readings.json", files)
        self.assertIn("stores/s002/store.json", files)
        # 图片不是数据文件,不应出现在这个接口里
        self.assertNotIn("stores/s002/images/photo.jpg", files)

    def test_excludes_settings_json(self) -> None:
        """settings.json 一并不回 —— 它含 users[].password 哈希与 NAS 凭据。

        这个接口是 supervisor 也能调的,原样返回等于把全站凭据交出去。
        (备份 ZIP 侧早有剥离清单,这条旁路绕过了它。)
        """
        self._make_stores()
        h = FakeHandler("/api/admin/data-files", method="GET")
        handle_get_data_files(h)  # type: ignore[no-untyped-call]
        assert h.parsed is not None
        files = h.parsed["files"]
        self.assertNotIn("settings.json", files)
        self.assertNotIn(
            "SECRET", json.dumps(files, ensure_ascii=False),
            "数据文件接口不应吐出任何凭据",)


class TestRestoreByRelativePath(StoreBackupTestBase):
    """恢复必须按相对路径还原到 stores/<id>/ 下。"""

    def test_upload_zip_restores_store_files(self) -> None:
        self._make_stores()
        zip_bytes = self._store_zip_bytes()
        h = FakeHandler("/api/upload", {
            "files": {"backup.zip": {"__zip_b64": base64.b64encode(zip_bytes).decode("ascii")}}
        }, method="POST")
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        assert h.parsed is not None
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertIn("stores/s002/readings.json", h.parsed["restored"])
        # 门店文件真的落到 stores/s002/ 下,而不是被压成顶层 readings.json
        target = self.data_dir / "stores" / "s002" / "readings.json"
        self.assertTrue(target.is_file(), "门店文件没有按相对路径还原")
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["hall"], 2.0)
        self.assertTrue((self.data_dir / "stores" / "s002" / "store.json").is_file())

    def test_restore_endpoint_restores_store_files(self) -> None:
        """POST /api/restore(从磁盘上的 ZIP 恢复)也要覆盖门店。"""
        self._make_stores()
        zip_path = self.data_dir / "backup" / "test.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(self._store_zip_bytes())
        h = FakeHandler("/api/restore", {"zip_path": str(zip_path)}, method="POST")
        handle_post_restore(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        assert h.parsed is not None
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertIn("stores/s002/readings.json", h.parsed["restored"])
        target = self.data_dir / "stores" / "s002" / "readings.json"
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["hall"], 2.0)

    def test_admin_restore_upload_restores_store_files(self) -> None:
        """POST /api/admin/restore-upload(multipart 上传 ZIP)也要覆盖门店。"""
        from modules.backup.admin_handler import handle_post_restore_upload

        self._make_stores()
        raw, content_type = self._multipart_zip_body(self._store_zip_bytes())
        h = FakeHandler("/api/admin/restore-upload", method="POST",
                        content_type=content_type, raw_body=raw)
        handle_post_restore_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        assert h.parsed is not None
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertIn("stores/s002/readings.json", h.parsed["restored"])
        target = self.data_dir / "stores" / "s002" / "readings.json"
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["hall"], 2.0)

    def test_upload_json_body_accepts_store_subpath(self) -> None:
        """JSON body 也能按 stores/<id>/<name>.json 写入(浏览器端逐文件上传)。"""
        self._make_stores()
        h = FakeHandler("/api/upload", {
            "files": {"stores/s002/readings.json": [{"date": "2026-03-03", "hall": 7.0}]}
        }, method="POST")
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        assert h.parsed is not None
        self.assertTrue(h.parsed["ok"], h.parsed)
        target = self.data_dir / "stores" / "s002" / "readings.json"
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["hall"], 7.0)

    def test_upload_json_body_rejects_traversal(self) -> None:
        """带 .. 的文件名必须被拒绝,不能写到数据目录外面。"""
        self._make_stores()
        h = FakeHandler("/api/upload", {
            "files": {"stores/../../evil.json": [{"x": 1}]}
        }, method="POST")
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        self.assertFalse((self.data_dir.parent / "evil.json").exists())
        self.assertFalse((self.data_dir / "evil.json").exists())


class TestNasSyncStorePaths(StoreBackupTestBase):
    """NAS 同步写入必须按相对路径落到 stores/<id>/ 下。"""

    def test_sync_from_nas_writes_store_files(self) -> None:
        from modules.backup.admin_handler import handle_post_sync_from_nas

        self._make_stores()
        h = FakeHandler("/api/admin/sync-from-nas", {
            "files": {
                "stores/s002/readings.json": json.dumps([{"date": "2026-04-04", "hall": 5.0}]),
            }
        }, method="POST")
        handle_post_sync_from_nas(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        assert h.parsed is not None
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertIn("stores/s002/readings.json", h.parsed["restored"])
        target = self.data_dir / "stores" / "s002" / "readings.json"
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["hall"], 5.0)

    def test_sync_from_nas_rejects_traversal(self) -> None:
        from modules.backup.admin_handler import handle_post_sync_from_nas

        self._make_stores()
        h = FakeHandler("/api/admin/sync-from-nas", {
            "files": {"stores/../../evil.json": json.dumps([{"x": 1}])}
        }, method="POST")
        handle_post_sync_from_nas(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200)
        self.assertFalse((self.data_dir.parent / "evil.json").exists())


class TestImagesDirPerStore(StoreBackupTestBase):
    """值班图片目录按门店隔离。"""

    def test_images_dir_follows_current_store(self) -> None:
        self._make_stores()
        context.set_current_store("s002")
        d = _get_images_dir()  # type: ignore[no-untyped-call]
        # 用 resolve() 比较 —— macOS 的 /var 是 /private/var 的符号链接
        self.assertEqual(d.resolve(), (self.data_dir / "stores" / "s002" / "images").resolve())
        self.assertTrue(d.is_dir())

        context.set_current_store("main")
        d2 = _get_images_dir()  # type: ignore[no-untyped-call]
        self.assertEqual(d2.resolve(), (self.data_dir / "stores" / "main" / "images").resolve())
        self.assertNotEqual(d, d2)

    def test_images_dir_single_store_layout_unchanged(self) -> None:
        """单店布局(没有 stores/ 目录)→ 仍是 data_dir/images,行为不变。"""
        self._write_settings()
        d = _get_images_dir()  # type: ignore[no-untyped-call]
        self.assertEqual(d.resolve(), (self.data_dir / "images").resolve())


class TestBackupRecoveryByRelativePath(StoreBackupTestBase):
    """崩溃恢复:按相对路径在备份里找文件。"""

    def test_main_store_recovers_from_relative_path_backup(self) -> None:
        """备份里是 stores/main/readings.json → 恢复必须按相对路径找得到。"""
        self._make_stores()
        d = self.data_dir / "backup" / "20261125"
        (d / "stores" / "main").mkdir(parents=True)
        (d / "stores" / "main" / "readings.json").write_text(
            json.dumps([{"date": "2026-05-05", "hall": 42.0}]), encoding="utf-8")
        target = self.data_dir / "stores" / "main" / "readings.json"
        target.write_text("{broken", encoding="utf-8")

        data = load_json(target, [])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["hall"], 42.0)

    def test_branch_store_never_recovers_from_top_level_backup(self) -> None:
        """⚠️ 分店绝不能从顶层 backup/ 拿总店数据来填(串店)。"""
        self._make_stores()
        d = self.data_dir / "backup" / "20261125"
        d.mkdir(parents=True)
        # 顶层旧格式(只有总店数据)
        (d / "readings.json").write_text(
            json.dumps([{"date": "2026-05-05", "hall": 42.0}]), encoding="utf-8")
        target = self.data_dir / "stores" / "s002" / "readings.json"
        target.write_text("{broken", encoding="utf-8")

        data = load_json(target, [])
        self.assertEqual(data, [], "分店不能回退顶层 backup/(那是总店的数据)")


if __name__ == "__main__":
    unittest.main()
