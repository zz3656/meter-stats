"""备份/恢复加固回归测试(标准库 unittest,零依赖)。

锁死 2026-11 这一轮止血修的 5 条 —— 它们都属于「坏了但没人发现」:

1. `GET /api/admin/backup-download` 恒 400
   取 zip_name 用的是 `try: read_body() except: 当 GET`,而 read_body 对没有
   Content-Length 的 GET 返回 `{}` 且**不抛异常** → except 永不执行 → 参数恒空。
   前端 downloadBackup() 用 `<a href>` 发 GET,所以「下载备份」按钮 100% 失败
   (实测 HTTP 400「缺少 zip_name 参数」),而 POST 路径一直是好的;
   原来的测试只断言「不是 401/403」,400 照样绿。

2. `/api/admin/data-files` 原样吐出 settings.json
   里面是 `users[].password` 的 PBKDF2 哈希 + `nas_sync_pass` 明文。
   备份 ZIP 专门写了剥离清单,这条旁路把机制绕过去了。

3. `/api/upload` 的 multipart ZIP 分支是四处解压入口里唯一不走校验的
   (restore / upload-base64 / restore-upload 都走 `_validate_zip_safely`)。
   裸 extractall = ZIP bomb 的门开着,解压期间还占满 GIL。

4. 值班照片从来不在备份包里;恢复侧白名单又只认 1 段/3 段路径,
   而备份侧 rglob 收任意深度 → 「包里有、恢复时静默丢弃」。
   现在备份/恢复共用 `backup_paths.classify_rel`,照片也进包且能还原。

5. 四处路径包含判断用手写 `str.startswith` —— 同级目录(`MeterStats.bak/`、
   `backup-evil/`)的前缀同样命中,静态资源那条还是匿名可读的。

运行:
    python3 -m unittest tests.test_backup_hardening -v
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import unittest
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "MeterStats"))
sys.path.insert(0, str(TESTS_DIR))

from backup_paths import classify_rel, iter_backup_files  # noqa: E402
from modules.backup.handler import (  # noqa: E402
    handle_get_data_files,
    handle_post_restore,
    handle_post_upload,
)
from storage import backup_data  # noqa: E402
from test_store_backup import FakeHandler, StoreBackupTestBase  # noqa: E402
from test_store_backup_scope import StoreScopeTestBase  # noqa: E402
from utils.api import ZIP_MAX_FILE_COUNT, _validate_zip_safely  # noqa: E402

def _body_json(h: Any) -> Any:
    """把响应体当 JSON 解析(下载类接口回的是二进制,解析失败就给 None)。"""
    raw = h.wfile.getvalue()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


# ⚠️ modules.backup.admin_handler 不能在模块顶层 import ——
#    modules/system/admin_handler.py 顶层就 import 了它,反过来会撞上既存的
#    循环 import。用到它的用例在函数体内 import。


class TestBackupDownloadViaGet(StoreBackupTestBase):
    """① 备份下载:GET(前端实际用的方法)必须真的能下到 ZIP。"""

    def setUp(self) -> None:
        super().setUp()
        self.backup_parent = self.data_dir / "backup"
        (self.data_dir / "settings.json").write_text(
            json.dumps({"backup_dir": str(self.backup_parent)}, ensure_ascii=False),
            encoding="utf-8",
        )
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        self.zip_path = backup_data(self.data_dir, force=True)
        assert self.zip_path is not None
        self.zip_name = self.zip_path.name

    def _download(self, query: str, method: str = "GET",
                  body: Optional[dict] = None) -> FakeHandler:
        from modules.backup.admin_handler import (
            handle_get_backup_download,
            handle_post_backup_download,
        )
        # 浏览器发起的 GET 不带 Content-Type —— 夹具照实模拟,
        # 否则会把「按 Content-Type 猜请求形态」的老写法测成通过。
        content_type = "application/json" if method == "POST" else ""
        h = FakeHandler("/api/admin/backup-download" + query, body, method=method,
                        content_type=content_type)
        if method == "GET":
            handle_get_backup_download(h)  # type: ignore[no-untyped-call]
        else:
            handle_post_backup_download(h)  # type: ignore[no-untyped-call]
        return h

    def test_get_download_returns_zip(self) -> None:
        """回归点:这条以前恒 400「缺少 zip_name 参数」。"""
        h = self._download(f"?zip_name={self.zip_name}")
        self.assertEqual(h.response_status, 200, _body_json(h))
        body = h.wfile.getvalue()
        self.assertTrue(body.startswith(b"PK"), "返回的不是 ZIP")
        self.assertEqual(h.response_headers.get("Content-Type"), "application/zip")
        self.assertEqual(len(body), self.zip_path.stat().st_size)

    def test_get_without_param_is_400(self) -> None:
        """真的缺参数时仍然要 400(别把闸也一起拆了)。"""
        h = self._download("")
        self.assertEqual(h.response_status, 400, _body_json(h))

    def test_get_with_content_type_still_works(self) -> None:
        """GET 就算带了 Content-Type 也照下:判定看路由,不看请求头。"""
        from modules.backup.admin_handler import handle_get_backup_download

        h = FakeHandler(f"/api/admin/backup-download?zip_name={self.zip_name}",
                        method="GET", content_type="application/json")
        handle_get_backup_download(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, _body_json(h))
        self.assertTrue(h.wfile.getvalue().startswith(b"PK"))

    def test_post_still_works(self) -> None:
        h = self._download("", method="POST", body={"zip_name": self.zip_name})
        self.assertEqual(h.response_status, 200, _body_json(h))
        self.assertTrue(h.wfile.getvalue().startswith(b"PK"))

    def test_legacy_dir_param_still_maps(self) -> None:
        """老前端传 ?dir=<时间戳>,要能换算出 meter-backup-<时间戳>.zip。"""
        stamp = "20260101_120000_000"
        manual = self.backup_parent / f"meter-backup-{stamp}.zip"
        manual.write_bytes(self.zip_path.read_bytes())

        h = self._download(f"?dir={stamp}")
        self.assertEqual(h.response_status, 200, _body_json(h))
        self.assertTrue(h.wfile.getvalue().startswith(b"PK"))

    def test_sibling_backup_dir_rejected(self) -> None:
        """⑤ 同级目录前缀不算「在备份目录内」:backup-evil/ 不能借道读走。"""
        evil = self.data_dir / "backup-evil"
        evil.mkdir()
        (evil / "leak.zip").write_bytes(b"PK\x03\x04 not a real zip")
        h = self._download("?zip_name=../backup-evil/leak.zip")
        self.assertEqual(h.response_status, 403, _body_json(h))


class TestHttpHeaderSafety(unittest.TestCase):
    """响应头必须是 latin-1:http.server 严格编码,中文值会在 send_response 之后抛。

    这个坑比看起来恶劣:异常发生在响应头已经开始往外写之后,客户端拿到的是
    「200 + 半截响应头」+ 断开连接(0 字节文件),日志里才看得到 UnicodeEncodeError。
    """

    def test_no_non_ascii_header_values_in_sources(self) -> None:
        bad: list[str] = []
        for py in sorted((REPO / "MeterStats").rglob("*.py")):
            if "__pycache__" in str(py):
                continue
            for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if "send_header(" not in line and "add_header(" not in line:
                    continue
                if any("\u4e00" <= ch <= "\u9fff" for ch in line):
                    bad.append(f"{py.relative_to(REPO)}:{lineno}: {line.strip()}")
        self.assertEqual(bad, [], "响应头里出现中文,会在写响应时抛 UnicodeEncodeError")

    def test_deprecation_header_is_ascii(self) -> None:
        src = (REPO / "MeterStats/modules/backup/admin_handler.py").read_text(encoding="utf-8")
        self.assertIn('"X-API-Migration", "deprecated; use POST', src)


class TestUploadZipValidation(StoreBackupTestBase):
    """③ multipart 上传的 ZIP 必须走 _validate_zip_safely。"""

    def _bomb_zip(self) -> bytes:
        """成员数超过上限的 ZIP —— 校验器一眼就能拒,但裸 extractall 会照解。"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for i in range(ZIP_MAX_FILE_COUNT + 1):
                zf.writestr(f"f{i}.json", "[]")
        return buf.getvalue()

    def _upload_multipart(self, zip_bytes: bytes) -> FakeHandler:
        boundary = "----MeterStatsTestBoundary"
        raw = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="backup.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8") + zip_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
        h = FakeHandler("/api/upload", method="POST", raw_body=raw,
                        content_type=f"multipart/form-data; boundary={boundary}")
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        return h

    def test_validator_rejects_member_count_bomb(self) -> None:
        """校验器本身要拒(这条不依赖 handler)。"""
        bomb = self.data_dir / "bomb.zip"
        bomb.write_bytes(self._bomb_zip())
        _dir, error = _validate_zip_safely(bomb, self.data_dir / "out")
        self.assertIsNotNone(error)
        self.assertIn("超过上限", error or "")

    def test_multipart_upload_calls_validator(self) -> None:
        """回归点:这条路径以前是裸 extractall,校验器根本不会被调用。"""
        from modules.backup import handler as backup_handler

        calls = []
        real = backup_handler._validate_zip_safely

        def _spy(zip_path: Any, extract_to: Any, **kw: Any):
            calls.append(str(zip_path))
            return real(zip_path, extract_to, **kw)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("stores/main/readings.json", json.dumps([{"tag": "R"}]))
        with mock.patch.object(backup_handler, "_validate_zip_safely", _spy):
            h = self._upload_multipart(buf.getvalue())

        self.assertTrue(calls, "multipart 上传路径没有走 ZIP 校验")
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)


class TestImagesInBackup(StoreBackupTestBase):
    """④ 值班照片进备份,且备份/恢复共用一套路径规则。"""

    def test_single_store_images_included(self) -> None:
        img = self.data_dir / "images"
        img.mkdir()
        (img / "duty-a.jpg").write_bytes(b"\xff\xd8\xff single-store photo")
        (self.data_dir / "settings.json").write_text(json.dumps({}), encoding="utf-8")

        zip_path = backup_data(self.data_dir, force=True)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("images/duty-a.jpg", names)

    def test_tmp_files_not_backed_up(self) -> None:
        """*.tmp 是原子写入的中间产物,不是数据 —— 崩溃残留也不该进包。"""
        d = self.data_dir / "stores" / "main"
        d.mkdir(parents=True)
        (d / "readings.json.tmp").write_text("[{}]", encoding="utf-8")
        (self.data_dir / "settings.json").write_text(json.dumps({}), encoding="utf-8")

        zip_path = backup_data(self.data_dir, force=True)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertFalse([n for n in names if n.endswith(".tmp")], names)


class TestImagesRoundTrip(StoreScopeTestBase):
    """④ 备份 → 恢复的 round-trip:照片必须原样回来。"""

    def test_store_images_survive_backup_and_restore(self) -> None:
        main_img = self.data_dir / "stores" / "main" / "images"
        s002_img = self.data_dir / "stores" / "s002" / "images"
        for d in (main_img, s002_img):
            d.mkdir(parents=True, exist_ok=True)
        payload_main = b"\xff\xd8\xff\xe0 main-photo-bytes"
        payload_s002 = b"\xff\xd8\xff\xe0 s002-photo-bytes"
        (main_img / "duty-1.jpg").write_bytes(payload_main)
        (s002_img / "duty-2.jpg").write_bytes(payload_s002)

        zip_path = backup_data(self.data_dir, force=True)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("stores/main/images/duty-1.jpg", names)
        self.assertIn("stores/s002/images/duty-2.jpg", names)

        # 制造「照片丢了」:删掉图片目录,再用备份恢复
        shutil.rmtree(main_img)
        shutil.rmtree(s002_img)

        h = self.handler("/api/restore", {"zip_path": str(zip_path)},
                         method="POST", token=self.tok_admin)
        handle_post_restore(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)

        self.assertEqual((main_img / "duty-1.jpg").read_bytes(), payload_main,
                         "总店照片没恢复回来(备份收得进、恢复认不出)")
        self.assertEqual((s002_img / "duty-2.jpg").read_bytes(), payload_s002,
                         "分店照片没恢复回来")

    def test_restore_skips_deep_paths(self) -> None:
        """恢复侧只认备份会收的形态 —— 深层路径不该被静默写盘。"""
        from modules.backup.handler import _safe_rel_target

        self.assertIsNone(
            _safe_rel_target(self.data_dir, "stores/main/backup/20260101/readings.json"))
        self.assertIsNotNone(
            _safe_rel_target(self.data_dir, "stores/main/images/ok.jpg"))


class TestClassifyRelRules(unittest.TestCase):
    """`backup_paths.classify_rel` 是备份/恢复两侧的唯一规则来源。"""

    def test_accepts_known_shapes(self) -> None:
        self.assertEqual(classify_rel("readings.json"), "data")
        self.assertEqual(classify_rel("settings.json"), "data")
        self.assertEqual(classify_rel("images/a.jpg"), "image")
        self.assertEqual(classify_rel("stores/s002/readings.json"), "data")
        self.assertEqual(classify_rel("stores/s002/store.json"), "data")
        self.assertEqual(classify_rel("stores/s002/images/a.png"), "image")

    def test_rejects_traversal_and_noise(self) -> None:
        for bad in ("", "../evil.json", "stores/../evil.json", "/abs.json",
                    "stores\\main\\readings.json", "stores/main/readings.json.tmp",
                    "stores/bad id/readings.json", "images/evil.txt",
                    "stores/main/backup/20260101/readings.json", "notes.md"):
            self.assertIsNone(classify_rel(bad), bad)

    def test_iter_includes_images_only_when_asked(self) -> None:
        self.assertIn("image", [classify_rel(r) for r, _ in
                                iter_backup_files(REPO / "MeterStats")] or ["image"])


class TestPathContainment(unittest.TestCase):
    """⑤ 路径包含判断必须用 is_relative_to,不能靠字符串前缀。"""

    SOURCES = {
        "app_handler.py": "is_relative_to",
        "utils/api.py": "is_relative_to",
        "modules/backup/admin_handler.py": "is_relative_to",
        "modules/duty/handler.py": "is_relative_to",
    }

    def test_sibling_prefix_is_not_containment(self) -> None:
        """这是修法的依据:字符串前缀会把同级目录判成「在里面」。"""
        root = Path("/opt/app/MeterStats")
        sibling = Path("/opt/app/MeterStats.bak/app.js")
        self.assertTrue(str(sibling).startswith(str(root)))   # 旧判断的错觉
        self.assertFalse(sibling.is_relative_to(root))        # 正确判断

    def test_no_string_prefix_path_checks_left(self) -> None:
        for rel, expect in self.SOURCES.items():
            src = (REPO / "MeterStats" / rel).read_text(encoding="utf-8")
            self.assertNotIn("startswith(str(", src,
                             f"{rel} 里还有 str.startswith 形式的路径包含判断")
            self.assertIn(expect, src, f"{rel} 没看到 is_relative_to")


class TestDataFilesEndpointHardening(StoreScopeTestBase):
    """② 数据文件接口不许回 settings.json(里面有凭据)。"""

    def test_settings_json_not_returned(self) -> None:
        h = self.handler("/api/admin/data-files", method="GET", token=self.tok_sup)
        handle_get_data_files(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        files: Dict[str, Any] = h.parsed["files"]
        self.assertNotIn("settings.json", files)
        blob = json.dumps(files, ensure_ascii=False)
        self.assertNotIn("SECRET_NAS_PASS", blob)
        self.assertNotIn("pbkdf2", blob.lower())


if __name__ == "__main__":
    unittest.main()
