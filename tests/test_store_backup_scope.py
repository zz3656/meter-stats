"""多门店 P0 修复轮回归测试 —— 备份/恢复/NAS 同步的**门店范围闸**。

背景(独立复核实测出来的跨店覆写):
```
员工 session: role=employee, all_stores=False, store_ids=['s002']
POST /api/upload  body={"files":{"stores/main/readings.json":[...],
                                 "stores/s003/readings.json":[...]}}
  auth_gate  -> ALLOW
  store_gate -> ALLOW (current store=s002)
结果: stores/main/readings.json 与 stores/s003/readings.json 都被覆写
```
**门店闸对「查询参数」有效、对「载荷里的目标门店」无效** —— 这正是 P0 要消灭的
「跨店串数据」本身。

本文件锁死的行为:
- R1 门店范围闸:载荷里的目标门店必须在调用方范围内(单店布局不受影响);
- R2 破坏性/导出接口提权到主管以上;
- R3 旧格式备份在多店布局下恢复总店 = 桥接到 stores/main/(不能静默无效);
- R4 自动备份与手动备份剥离同一份部署字段(NAS 密码不许进 ZIP);
- R5 同一秒内两次备份不许互相覆盖。

运行:
    python3 -m unittest tests.test_store_backup_scope -v
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
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.backup.handler import (  # noqa: E402
    handle_get_data_files,
    handle_post_backup,
    handle_post_restore,
    handle_post_upload,
)
from modules.stores import context  # noqa: E402
from modules.stores.handler import (  # noqa: E402
    parse_store_target,
    store_scope_check,
)
from modules.system.auth_handler import _SESSIONS, create_session  # noqa: E402

import app_handler  # noqa: E402
import routing  # noqa: E402
from storage import DATA_FILES, backup_data  # noqa: E402

# ⚠️ modules.backup.admin_handler 不能在模块顶层 import ——
#    modules/system/admin_handler.py 顶层就 import 了 modules.backup.admin_handler,
#    先 import 后者会撞上这个**既存的**循环 import(与本轮无关)。
#    所以用到它的用例在函数体内 import。


class FakeHandler:
    """模拟 BaseHTTPRequestHandler 的最小实现,捕获响应。

    token 通过 Authorization: Bearer 传(与真实前端一致);
    也支持直接挂 _auth_session(routing 走完后会挂)。
    """

    def __init__(self, path: str, body: Optional[dict[str, Any]] = None,
                 method: str = "GET", token: str = "",
                 raw_body: Optional[bytes] = None,
                 content_type: str = "application/json") -> None:
        self.path = path
        self.command = method
        self.response_status: Optional[int] = None
        self.response_headers: dict[str, str] = {}
        self.response_body = b""
        self.wfile = io.BytesIO()
        if raw_body is not None:
            self.rfile = io.BytesIO(raw_body)
            payload = raw_body
        elif body is not None:
            payload = json.dumps(body).encode("utf-8")
            self.rfile = io.BytesIO(payload)
        else:
            payload = b""
            self.rfile = io.BytesIO(b"")
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": content_type,
        }
        if token:
            self.headers["Authorization"] = "Bearer " + token

    def send_response(self, status: int) -> None:
        self.response_status = status

    def send_header(self, k: str, v: str) -> None:
        self.response_headers[k] = v

    def end_headers(self) -> None:
        pass

    @property
    def parsed(self) -> Any:
        raw = self.wfile.getvalue()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            # 下载类接口回的是二进制(如 ZIP),不是 JSON —— 原样给出
            return raw

    @property
    def parsed_json(self) -> Any:
        """只取 JSON 响应;非 JSON 返回 None(下载类接口用)。"""
        raw = self.wfile.getvalue()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None


class StoreScopeTestBase(unittest.TestCase):
    """基类:多门店布局 + 真实员工会话(routing.ENFORCE_AUTH=True)。

    ⚠️ 必须用**真实会话**(不是 _synthetic):合成会话是「全店放行」,
    拿它测门店范围闸等于没测。
    """

    EMP_ID = 99
    ADMIN_ID = 1
    SUP_ID = 2

    def setUp(self) -> None:
        self._prev_enforce = routing.ENFORCE_AUTH
        routing.ENFORCE_AUTH = True
        self._prev_paths = app_handler.DATA_PATHS
        self._prev_data_dir_env = os.environ.get("METER_DATA_DIR")

        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        os.environ["METER_DATA_DIR"] = str(self.data_dir)
        context.clear_current_store()

        # 会话表隔离
        self._saved_sessions = dict(_SESSIONS)
        _SESSIONS.clear()

        self._write_settings()
        self._make_stores()

        self.tok_emp = self._session(self.EMP_ID, "emp", "employee", False, ["s002"])
        self.tok_sup = self._session(self.SUP_ID, "sup", "supervisor", True, [])
        self.tok_admin = self._session(self.ADMIN_ID, "boss", "admin", True, [])

    def tearDown(self) -> None:
        _SESSIONS.clear()
        _SESSIONS.update(self._saved_sessions)
        routing.ENFORCE_AUTH = self._prev_enforce
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        if self._prev_data_dir_env is None:
            os.environ.pop("METER_DATA_DIR", None)
        else:
            os.environ["METER_DATA_DIR"] = self._prev_data_dir_env
        self.tmp.cleanup()

    # ---- 夹具 ----

    def _write_settings(self) -> None:
        (self.data_dir / "settings.json").write_text(json.dumps({
            "users": [
                {"id": self.ADMIN_ID, "username": "boss", "password": "x",
                 "role": "admin", "name": "总部", "enabled": True,
                 "all_stores": True, "store_ids": []},
                {"id": self.SUP_ID, "username": "sup", "password": "x",
                 "role": "supervisor", "name": "主管", "enabled": True,
                 "all_stores": True, "store_ids": []},
                {"id": self.EMP_ID, "username": "emp", "password": "x",
                 "role": "employee", "name": "员工", "enabled": True,
                 "all_stores": False, "store_ids": ["s002"]},
                # 受门店范围限制的主管 —— 用来测「范围外的数据拿不到」。
                # ⚠️ 必须真的写进 settings.json:门店范围闸查的是**盘上的用户记录**,
                #    查不到就是 fail-closed 拒绝(会话里有 fallback 也没用)。
                {"id": 77, "username": "scoped", "password": "x",
                 "role": "supervisor", "name": "受限主管", "enabled": True,
                 "all_stores": False, "store_ids": ["s002"]},
            ],
            "stores": [
                {"id": "main", "name": "总店", "active": True},
                {"id": "s002", "name": "国贸店", "active": True},
                {"id": "s003", "name": "太古店", "active": True},
            ],
            "nas_sync_user": "nasuser",
            "nas_sync_pass": "SECRET_NAS_PASS",
            "backup_dir": str(self.data_dir / "backup"),
            "backup_retention_count": 5,
        }, ensure_ascii=False), encoding="utf-8")

    def _make_stores(self) -> None:
        """三个门店,各有一份可辨识内容的 readings.json。"""
        for sid, tag in (("main", "MAIN"), ("s002", "S002"), ("s003", "S003")):
            d = self.data_dir / "stores" / sid
            d.mkdir(parents=True, exist_ok=True)
            for fname in DATA_FILES.values():
                (d / fname).write_text("[]", encoding="utf-8")
            (d / "readings.json").write_text(
                json.dumps([{"tag": tag}], ensure_ascii=False), encoding="utf-8")
            (d / "store.json").write_text(
                json.dumps({"id": sid, "name": sid}, ensure_ascii=False), encoding="utf-8")

    def _session(self, uid: int, username: str, role: str,
                 all_stores: bool, store_ids: list[str]) -> str:
        return create_session({
            "id": uid, "username": username, "role": role, "name": username,
            "all_stores": all_stores, "store_ids": store_ids,
        })

    # ---- 调用helper ----

    def handler(self, path: str, body: Optional[dict[str, Any]] = None,
                method: str = "GET", token: str = "") -> FakeHandler:
        return FakeHandler(path, body, method=method, token=token)

    def route(self, method: str, path: str, body: Optional[dict[str, Any]] = None,
              token: str = "") -> FakeHandler:
        """走完整路由(routing._auth_gate + _store_gate + 分发)。"""
        h = self.handler(path, body, method=method, token=token)
        app_handler._do_api(method, h, h.path)  # type: ignore[no-untyped-call]
        return h

    def readings_of(self, store_id: str) -> Any:
        p = self.data_dir / "stores" / store_id / "readings.json"
        return json.loads(p.read_text(encoding="utf-8"))

    def _zip_bytes(self, entries: dict[str, Any]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in entries.items():
                zf.writestr(name, content if isinstance(content, str)
                            else json.dumps(content, ensure_ascii=False))
        return buf.getvalue()


class TestStoreScopeGate(StoreScopeTestBase):
    """R1:载荷里的目标门店必须在调用方范围内。"""

    def test_upload_other_store_main_rejected(self) -> None:
        """员工写 stores/main/readings.json → 必须被拒,盘上内容不变。"""
        h = self.handler("/api/upload", {
            "files": {"stores/main/readings.json": [{"tag": "HACK"}]}
        }, method="POST", token=self.tok_emp)
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 403, h.parsed)
        self.assertIn("无权访问门店", h.parsed.get("error", ""))
        self.assertEqual(self.readings_of("main"), [{"tag": "MAIN"}], "总店数据被改写了")

    def test_upload_other_store_s003_rejected(self) -> None:
        """员工写 stores/s003/readings.json → 必须被拒,盘上内容不变。"""
        h = self.handler("/api/upload", {
            "files": {"stores/s003/readings.json": [{"tag": "HACK"}]}
        }, method="POST", token=self.tok_emp)
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 403, h.parsed)
        self.assertEqual(self.readings_of("s003"), [{"tag": "S003"}], "别家门店数据被改写了")

    def test_upload_own_store_allowed(self) -> None:
        """员工写**自己**的 stores/s002/readings.json → 必须成功(不能把正常操作堵死)。"""
        h = self.handler("/api/upload", {
            "files": {"stores/s002/readings.json": [{"tag": "MINE"}]}
        }, method="POST", token=self.tok_emp)
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual(self.readings_of("s002"), [{"tag": "MINE"}])

    def test_upload_top_level_allowed(self) -> None:
        """顶层文件没有门店维度 → 必须成功。"""
        h = self.handler("/api/upload", {
            "files": {"readings.json": [{"tag": "TOP"}]}
        }, method="POST", token=self.tok_emp)
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)
        top = self.data_dir / "readings.json"
        self.assertEqual(json.loads(top.read_text(encoding="utf-8")), [{"tag": "TOP"}])

    def test_upload_store_id_is_case_sensitive(self) -> None:
        """大小写敏感:"MAIN" != "main" —— macOS 上这两个是同一个目录。"""
        h = self.handler("/api/upload", {
            "files": {"stores/MAIN/readings.json": [{"tag": "HACK"}]}
        }, method="POST", token=self.tok_emp)
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 403, h.parsed)
        self.assertEqual(self.readings_of("main"), [{"tag": "MAIN"}])

    def test_restore_zip_other_store_rejected(self) -> None:
        """ZIP 里带别家门店 → 必须被拒,盘上内容不变。"""
        zip_bytes = self._zip_bytes({
            "stores/s003/readings.json": [{"tag": "HACK"}],
        })
        zip_path = self.data_dir / "backup" / "evil.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(zip_bytes)
        h = self.handler("/api/restore", {"zip_path": str(zip_path)},
                         method="POST", token=self.tok_emp)
        handle_post_restore(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 403, h.parsed)
        self.assertEqual(self.readings_of("s003"), [{"tag": "S003"}])

    def test_restore_zip_own_store_allowed(self) -> None:
        """ZIP 里带自己门店 → 必须成功。"""
        zip_bytes = self._zip_bytes({
            "stores/s002/readings.json": [{"tag": "MINE"}],
        })
        zip_path = self.data_dir / "backup" / "mine.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(zip_bytes)
        h = self.handler("/api/restore", {"zip_path": str(zip_path)},
                         method="POST", token=self.tok_emp)
        handle_post_restore(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual(self.readings_of("s002"), [{"tag": "MINE"}])

    def test_sync_from_nas_other_store_rejected(self) -> None:
        """NAS 同步跨店写入 → 必须被拒。"""
        from modules.backup.admin_handler import handle_post_sync_from_nas

        h = self.handler("/api/admin/sync-from-nas", {
            "files": {"stores/s003/readings.json": json.dumps([{"tag": "HACK"}])}
        }, method="POST", token=self.tok_emp)
        handle_post_sync_from_nas(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 403, h.parsed)
        self.assertEqual(self.readings_of("s003"), [{"tag": "S003"}])

    def test_data_files_only_lists_in_scope(self) -> None:
        """GET /api/admin/data-files → 只返回范围内的门店文件。"""
        h = self.handler("/api/admin/data-files", method="GET", token=self.tok_emp)
        handle_get_data_files(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        files = h.parsed["files"]
        self.assertIn("stores/s002/readings.json", files)
        self.assertNotIn("stores/main/readings.json", files)
        self.assertNotIn("stores/s003/readings.json", files)
        # 顶层业务数据文件在多店布局下归属总店 → 越权时也不给
        self.assertNotIn("readings.json", files)
        # settings.json 一律不给:它含 users[].password 哈希与 nas_sync_pass 明文,
        # 而这个接口 supervisor 也能调(实测过原样返回)。
        self.assertNotIn("settings.json", files)

    def test_data_files_admin_sees_all_stores(self) -> None:
        """总部账号 → 返回全部门店。"""
        h = self.handler("/api/admin/data-files", method="GET", token=self.tok_admin)
        handle_get_data_files(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        files = h.parsed["files"]
        for sid in ("main", "s002", "s003"):
            self.assertIn(f"stores/{sid}/readings.json", files)

    def test_backup_only_packages_in_scope(self) -> None:
        """POST /api/backup → 只打包范围内的门店。"""
        h = self.handler("/api/backup", method="POST", token=self.tok_emp)
        handle_post_backup(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)
        with zipfile.ZipFile(h.parsed["zip_path"]) as zf:
            names = zf.namelist()
        self.assertIn("stores/s002/readings.json", names)
        self.assertNotIn("stores/main/readings.json", names)
        self.assertNotIn("stores/s003/readings.json", names)

    def test_backup_admin_packages_all_stores(self) -> None:
        """总部账号 → 备份包含全部门店。"""
        h = self.handler("/api/backup", method="POST", token=self.tok_admin)
        handle_post_backup(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        with zipfile.ZipFile(h.parsed["zip_path"]) as zf:
            names = zf.namelist()
        for sid in ("main", "s002", "s003"):
            self.assertIn(f"stores/{sid}/readings.json", names)


class TestStoreScopeHelper(StoreScopeTestBase):
    """R1 helper 自身的语义。"""

    def test_single_store_layout_allows(self) -> None:
        """单店布局(没有 stores/ 目录)→ 直接放行,行为与改造前一致。"""
        import shutil

        shutil.rmtree(self.data_dir / "stores")
        h = self.handler("/api/x", method="GET", token=self.tok_emp)
        ok, err = store_scope_check(h, ["main", "s003"])
        self.assertTrue(ok, err)
        self.assertEqual(err, "")

    def test_deleted_user_denied(self) -> None:
        """查不到用户记录 → 拒绝(fail-closed),绝不回退成「全部门店」。"""
        settings_path = self.data_dir / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["users"] = [u for u in settings["users"] if u["id"] != self.EMP_ID]
        settings_path.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        h = self.handler("/api/x", method="GET", token=self.tok_emp)
        ok, err = store_scope_check(h, ["s002"])
        self.assertFalse(ok)
        self.assertIn("账号不存在", err)

    def test_all_stores_allows_any(self) -> None:
        """all_stores=True(总部账号)→ 放行。"""
        h = self.handler("/api/x", method="GET", token=self.tok_admin)
        ok, err = store_scope_check(h, ["main", "s003", "whatever"])
        self.assertTrue(ok, err)

    def test_case_sensitive(self) -> None:
        """"MAIN" != "main"。"""
        h = self.handler("/api/x", method="GET", token=self.tok_emp)
        ok, err = store_scope_check(h, ["S002"])
        self.assertFalse(ok)
        self.assertIn("无权访问门店", err)

    def test_parse_store_target(self) -> None:
        """目标门店解析:顶层无维度 / 门店子路径 / 非法 ID 一律拒绝。"""
        self.assertEqual(parse_store_target("readings.json"), (True, None))
        self.assertEqual(parse_store_target("stores/s002/readings.json"), (True, "s002"))
        ok, sid = parse_store_target("stores/bad id/readings.json")
        self.assertFalse(ok)
        self.assertIsNone(sid)
        ok, sid = parse_store_target("stores/../evil.json")
        self.assertFalse(ok)
        self.assertIsNone(sid)


class TestRoleEscalation(StoreScopeTestBase):
    """R2:破坏性/导出接口提权到主管以上(走完整路由)。"""

    PROTECTED = [
        ("POST", "/api/upload"),
        ("POST", "/api/restore"),
        ("POST", "/api/backup"),
        ("GET", "/api/admin/backup-download"),
    ]

    def test_employee_denied(self) -> None:
        for method, path in self.PROTECTED:
            h = self.route(method, path, token=self.tok_emp)
            self.assertEqual(h.response_status, 403, f"{path} 对员工放行了")
            self.assertIn("主管", h.parsed.get("error", ""))

    def test_supervisor_allowed(self) -> None:
        for method, path in self.PROTECTED:
            h = self.route(method, path, token=self.tok_sup)
            self.assertNotIn(h.response_status, (401, 403), f"{path} 拦住了主管")

    def test_admin_allowed(self) -> None:
        for method, path in self.PROTECTED:
            h = self.route(method, path, token=self.tok_admin)
            self.assertNotIn(h.response_status, (401, 403), f"{path} 拦住了管理员")


class TestSingleStoreUnchanged(StoreScopeTestBase):
    """单店布局下行为不变(P0 的验收标准)。"""

    def _drop_stores(self) -> None:
        import shutil

        shutil.rmtree(self.data_dir / "stores")

    def test_upload_top_level_ok_in_single_store(self) -> None:
        self._drop_stores()
        h = self.handler("/api/upload", {
            "files": {"readings.json": [{"tag": "TOP"}]}
        }, method="POST", token=self.tok_emp)
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)

    def test_employee_not_blocked_in_single_store(self) -> None:
        """单店布局 → 员工除了 R2 那三个接口,其余照旧能用。"""
        self._drop_stores()
        h = self.route("GET", "/api/readings", token=self.tok_emp)
        self.assertNotIn(h.response_status, (401, 403), h.parsed)


class TestOldFormatRestoreBridge(StoreScopeTestBase):
    """R3:旧格式备份(只有顶层文件)在多店布局下要落到 stores/main/。"""

    def test_old_format_zip_bridges_to_main(self) -> None:
        live = self.data_dir / "stores" / "main" / "readings.json"
        live.write_text(json.dumps([{"tag": "LIVE"}]), encoding="utf-8")

        zip_bytes = self._zip_bytes({
            "readings.json": [{"tag": "OLDBACKUP"}],
            "settings.json": {"auto_backup": True},
        })
        zip_path = self.data_dir / "backup" / "old.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(zip_bytes)

        h = self.handler("/api/restore", {"zip_path": str(zip_path)},
                         method="POST", token=self.tok_admin)
        handle_post_restore(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)
        # 总店数据必须真的变成备份里的内容
        self.assertEqual(self.readings_of("main"), [{"tag": "OLDBACKUP"}],
                         "旧格式备份恢复后总店数据纹丝不动")
        # 响应里能看出走了桥接
        self.assertIn("stores/main/readings.json", h.parsed["restored"])
        self.assertIn("stores/main/", (h.parsed.get("message") or ""), h.parsed)

    def test_old_format_zip_via_upload_bridges_to_main(self) -> None:
        """上传 ZIP 的那条路径也要桥接。"""
        live = self.data_dir / "stores" / "main" / "readings.json"
        live.write_text(json.dumps([{"tag": "LIVE"}]), encoding="utf-8")
        zip_bytes = self._zip_bytes({"readings.json": [{"tag": "OLDBACKUP"}]})
        h = self.handler("/api/upload", {
            "files": {"backup.zip": {"__zip_b64": base64.b64encode(zip_bytes).decode("ascii")}}
        }, method="POST", token=self.tok_admin)
        handle_post_upload(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual(self.readings_of("main"), [{"tag": "OLDBACKUP"}])


class TestSettingsStripped(StoreScopeTestBase):
    """R4:自动备份与手动备份剥离同一份部署字段。"""

    def _zip_settings(self, zip_path: Path) -> Dict[str, Any]:
        with zipfile.ZipFile(zip_path) as zf:
            data: Dict[str, Any] = json.loads(zf.read("settings.json").decode("utf-8"))
            return data

    def test_auto_backup_excludes_nas_credentials(self) -> None:
        zip_path = backup_data(self.data_dir, force=True)
        self.assertIsNotNone(zip_path)
        assert zip_path is not None
        settings = self._zip_settings(zip_path)
        self.assertNotIn("nas_sync_pass", settings)
        self.assertNotIn("nas_sync_user", settings)
        self.assertNotIn("backup_dir", settings)
        self.assertNotIn("backup_retention_count", settings)

    def test_manual_backup_excludes_nas_credentials(self) -> None:
        h = self.handler("/api/backup", method="POST", token=self.tok_admin)
        handle_post_backup(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        settings = self._zip_settings(Path(h.parsed["zip_path"]))
        self.assertNotIn("nas_sync_pass", settings)
        self.assertNotIn("nas_sync_user", settings)
        self.assertNotIn("backup_dir", settings)


class TestBackupTimestampCollision(StoreScopeTestBase):
    """R5:同一秒内两次备份不许互相覆盖。"""

    def test_two_backups_same_second_do_not_overwrite(self) -> None:
        """同一秒内连续两次备份 → 两个不同路径,第一个文件还在。

        把时钟钉死成同一毫秒,这样「会不会撞名」不取决于跑测机器的快慢
        (否则有一半概率两个调用正好跨过秒边界 → 测不出问题)。
        """
        from unittest import mock

        import storage

        fixed = storage._local_now()  # type: ignore[no-untyped-call]
        with mock.patch.object(storage, "_local_now", return_value=fixed):
            first = backup_data(self.data_dir, force=True)
            second = backup_data(self.data_dir, force=True)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertNotEqual(first, second, "同秒两次备份拿到同一个路径 → 后者覆盖前者")
        self.assertTrue(first.is_file(), "第一个备份文件不见了")
        self.assertTrue(second.is_file())

    def test_backup_name_carries_milliseconds(self) -> None:
        """备份文件名必须带毫秒段(YYYYMMDD_HHMMSS_<毫秒>)。

        秒级时间戳会让同一秒内的两次调用拿到同一个路径。
        """
        zip_path = backup_data(self.data_dir, force=True)
        self.assertIsNotNone(zip_path)
        assert zip_path is not None
        stamp = zip_path.name[len("auto-bak-"):-len(".zip")]
        self.assertRegex(stamp, r"^\d{8}_\d{6}_\d{3}$", f"备份名没有毫秒段: {zip_path.name}")

    def test_pre_backup_does_not_clobber_restore_source(self) -> None:
        """恢复前的 pre_backup 不能覆盖正在恢复的那个 ZIP。"""
        zip_bytes = self._zip_bytes({"readings.json": [{"tag": "OLDBACKUP"}]})
        zip_path = self.data_dir / "backup" / "auto-bak-20261125_120000.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(zip_bytes)
        before = zip_path.read_bytes()
        h = self.handler("/api/restore", {"zip_path": str(zip_path)},
                         method="POST", token=self.tok_admin)
        handle_post_restore(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertEqual(zip_path.read_bytes(), before, "正在恢复的 ZIP 被 pre_backup 覆盖了")


class TestBackupDownloadScope(StoreScopeTestBase):
    """备份**下载**也必须过门店范围闸。

    「新建备份时按范围过滤」不等于「下载时按范围过滤」:
    备份包是**盘上已有的文件**,不经过 backup_data(store_filter=...) 那条路 ——
    自动备份永远是全量的。受门店范围限制的调用方能下载整包,
    就等于跨店导出了别家门店的数据。
    """

    def setUp(self) -> None:
        super().setUp()
        # 造一个**受门店范围限制**的主管(store_ids=['s002'])
        self.tok_scoped_sup = self._session(77, "scoped", "supervisor", False, ["s002"])

    def _write_zip(self, name: str, entries: dict[str, Any]) -> Path:
        p = self.data_dir / "backup" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self._zip_bytes(entries))
        return p

    def test_scoped_supervisor_cannot_download_full_backup(self) -> None:
        """包里有别家门店 → 受限主管下载必须被拒。"""
        from modules.backup.admin_handler import handle_post_backup_download

        self._write_zip("full.zip", {
            "readings.json": [{"tag": "MAIN"}],
            "stores/main/readings.json": [{"tag": "MAIN"}],
            "stores/s003/readings.json": [{"tag": "S003"}],
        })
        h = self.handler("/api/admin/backup-download", {"zip_name": "full.zip"},
                         method="POST", token=self.tok_scoped_sup)
        handle_post_backup_download(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 403, h.parsed)

    def test_scoped_supervisor_can_download_own_store_backup(self) -> None:
        """包里只有自己的店 → 受限主管照常能下载。"""
        from modules.backup.admin_handler import handle_post_backup_download

        self._write_zip("mine.zip", {
            "stores/s002/readings.json": [{"tag": "S002"}],
        })
        h = self.handler("/api/admin/backup-download", {"zip_name": "mine.zip"},
                         method="POST", token=self.tok_scoped_sup)
        handle_post_backup_download(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)

    def test_admin_can_download_full_backup(self) -> None:
        """总部账号不受限。"""
        from modules.backup.admin_handler import handle_post_backup_download

        self._write_zip("full.zip", {
            "readings.json": [{"tag": "MAIN"}],
            "stores/main/readings.json": [{"tag": "MAIN"}],
            "stores/s003/readings.json": [{"tag": "S003"}],
        })
        h = self.handler("/api/admin/backup-download", {"zip_name": "full.zip"},
                         method="POST", token=self.tok_admin)
        handle_post_backup_download(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 200, h.parsed)

    def test_deleted_user_cannot_download_backup(self) -> None:
        """账号被删 → fail-closed,不许下载(查不到用户记录 = 拒绝)。"""
        from modules.backup.admin_handler import handle_post_backup_download

        self._write_zip("mine.zip", {"stores/s002/readings.json": [{"tag": "S002"}]})
        # 把主管从 settings.json 里删掉(会话还在)
        sp = self.data_dir / "settings.json"
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["users"] = [u for u in st["users"] if u["id"] != 77]
        sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        try:
            import storage
            storage._cache_clear()
        except Exception:
            pass

        h = self.handler("/api/admin/backup-download", {"zip_name": "mine.zip"},
                         method="POST", token=self.tok_scoped_sup)
        handle_post_backup_download(h)  # type: ignore[no-untyped-call]
        self.assertEqual(h.response_status, 403, h.parsed)


if __name__ == "__main__":
    unittest.main()
