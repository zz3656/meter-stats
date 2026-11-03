"""NAS 同步鉴权回归测试(标准库 unittest,零依赖)。

背景:远端实例从 v0.4.1 起全局启用接口鉴权,/api/admin/data-files 没有会话
一律 401("未登录或会话已过期"),而本机的 NAS 代理不携带任何凭据 —— 表现为
前端「同步失败: 需要登录认证（401）」。

修法:本机 settings.json 保存远端账号密码,代理先 POST /api/auth/login 换
token,再带着 token 去拉数据。

覆盖:
- 未配置凭据 → 代理直接给出可操作的错误,且**不发起任何网络请求**
- 已配置凭据 → 先登录远端换 token,再带 Authorization 头拉数据
- 远端登录被拒(密码错/被限速)→ 把远端的错误原样透出
- /api/admin/nas-config 存取凭据,且**绝不回传密码**
- /api/admin/nas-config 需要主管及以上
- 同步写入后失效月报缓存(否则报表最长 5 分钟还是旧值,看起来像同步没生效)
- NAS 密码不进备份 ZIP

运行:
    python3 -m unittest tests.test_nas_sync -v
"""
import io
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from typing import Optional
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

import app_handler  # noqa: E402
import routing  # noqa: E402
from modules.system.auth_handler import create_session, _SESSIONS  # noqa: E402


class FakeHandler:
    """模拟 BaseHTTPRequestHandler 的最小实现,捕获响应。"""

    def __init__(self, path: str, body: Optional[dict] = None, method: str = "POST",
                 token: str = "", bearer: str = ""):
        self.path = path
        self.command = method
        self.response_status = None
        self.response_headers = {}
        self.response_body = b""
        self.wfile = io.BytesIO()
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            self.rfile = io.BytesIO(raw)
            # 必须带 Content-Type: /api/proxy/nas-data 只在
            # Content-Type 含 application/json 时才去读 body(真实前端也是这么发的)
            self.headers = {
                "Content-Length": str(len(raw)),
                "Content-Type": "application/json",
            }
        else:
            self.rfile = io.BytesIO(b"")
            self.headers = {"Content-Length": "0", "Content-Type": "application/json"}
        if bearer:
            self.headers["Authorization"] = "Bearer " + bearer
        if token:
            sep = "&" if "?" in path else "?"
            self.path = path + sep + "token=" + token

    def send_response(self, status):
        self.response_status = status

    def send_header(self, k, v):
        self.response_headers[k] = v

    def end_headers(self):
        pass

    @property
    def parsed(self):
        body = self.wfile.getvalue()
        return json.loads(body) if body else None


class FakeResp:
    """模拟 urlopen 返回的响应对象。"""

    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class NasBase(unittest.TestCase):
    """基类:隔离数据目录 + 关闭业务鉴权(鉴权单独用真实会话测)。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name)
        self.data_dir = data_dir
        app_handler.DATA_PATHS = {
            "readings": data_dir / "readings.json",
            "readings_water": data_dir / "readings_water.json",
            "charges": data_dir / "charges.json",
            "items": data_dir / "items.json",
            "purchases": data_dir / "purchases.json",
            "duty": data_dir / "duty.json",
        }
        for p in app_handler.DATA_PATHS.values():
            p.write_text("[]", encoding="utf-8")
        (data_dir / "settings.json").write_text(
            json.dumps({"users": [], "meter": {}, "config": {}}, ensure_ascii=False),
            encoding="utf-8",
        )

        self._prev_enforce = routing.ENFORCE_AUTH
        routing.ENFORCE_AUTH = False

    def tearDown(self):
        routing.ENFORCE_AUTH = self._prev_enforce
        self.tmp.cleanup()

    def call(self, method: str, path: str, body: Optional[dict] = None) -> FakeHandler:
        h = FakeHandler(path, body, method)
        app_handler._do_api(method, h, path)
        return h

    def settings(self) -> dict:
        return json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))


class TestNasProxyAuth(NasBase):
    """代理必须先向远端认证,再带 token 拉数据。"""

    NAS_URL = "https://nas.example.com"

    def test_missing_credentials_fails_without_network_call(self):
        """未配置凭据 → 直接报错,一个字都不能往外发。"""
        def boom(*a, **k):
            raise AssertionError("未配置凭据时不应发起任何网络请求")

        with mock.patch.object(urllib.request, "urlopen", boom):
            h = self.call("POST", "/api/proxy/nas-data", {"nasUrl": self.NAS_URL})

        body = h.parsed
        self.assertFalse(body["ok"])
        self.assertIn("未配置 NAS 账号密码", body["error"])

    def test_logs_in_then_fetches_with_token(self):
        """配置了凭据 → 先登录换 token,再带 Authorization 头拉数据。"""
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            if req.full_url.endswith("/api/auth/login"):
                return FakeResp({"ok": True, "token": "remote-token-123"})
            if req.full_url.endswith("/api/admin/data-files"):
                return FakeResp({"ok": True, "files": {"readings.json": "[]"}})
            raise AssertionError("意外请求: " + req.full_url)

        self.call("PUT", "/api/admin/nas-config", {
            "nas_user": "admin", "nas_pass": "admin123",
        })

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            h = self.call("POST", "/api/proxy/nas-data", {"nasUrl": self.NAS_URL})

        body = h.parsed
        self.assertTrue(body["ok"], msg=f"代理应成功: {body}")
        self.assertIn("readings.json", body["files"])

        # 两次请求:先登录,后拉数据
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].full_url.endswith("/api/auth/login"))
        self.assertTrue(calls[1].full_url.endswith("/api/admin/data-files"))

        # 登录时带的是配置好的账号密码
        login_payload = json.loads(calls[0].data.decode("utf-8"))
        self.assertEqual(login_payload["username"], "admin")
        self.assertEqual(login_payload["password"], "admin123")

        # 拉数据时带上远端给的 token
        self.assertEqual(calls[1].get_header("Authorization"), "Bearer remote-token-123")

    def test_remote_login_rejected_surfaces_remote_error(self):
        """远端拒绝登录(密码错) → 把远端错误原样透出,不能吞成通用报错。"""
        def fake_urlopen(req, timeout=None):
            if req.full_url.endswith("/api/auth/login"):
                return FakeResp({"ok": False, "error": "密码错误"})
            raise AssertionError("登录失败时不该继续请求数据")

        self.call("PUT", "/api/admin/nas-config", {
            "nas_user": "admin", "nas_pass": "wrong",
        })

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            h = self.call("POST", "/api/proxy/nas-data", {"nasUrl": self.NAS_URL})

        body = h.parsed
        self.assertFalse(body["ok"])
        self.assertIn("密码错误", body["error"])


class TestNasConfigEndpoint(NasBase):
    """凭据存取端点。"""

    def test_get_never_returns_password(self):
        """GET 只能回传"是否已配置",绝不回传密码本身。"""
        self.call("PUT", "/api/admin/nas-config", {
            "nas_user": "admin", "nas_pass": "s3cret", "nas_url": "https://nas.example.com",
        })
        h = self.call("GET", "/api/admin/nas-config")
        body = h.parsed

        self.assertTrue(body["ok"])
        self.assertEqual(body["nas_user"], "admin")
        self.assertTrue(body["nas_pass_set"])
        self.assertEqual(body["nas_url"], "https://nas.example.com")
        self.assertNotIn("nas_pass", body)
        self.assertNotIn("s3cret", json.dumps(body, ensure_ascii=False))

    def test_put_saves_credentials(self):
        """PUT 保存账号密码到 settings.json。"""
        self.call("PUT", "/api/admin/nas-config", {
            "nas_user": "admin", "nas_pass": "admin123",
        })
        st = self.settings()
        self.assertEqual(st["nas_sync_user"], "admin")
        self.assertEqual(st["nas_sync_pass"], "admin123")

    def test_empty_password_keeps_existing(self):
        """密码留空 = 不改动已保存的密码(前端不回传密码时用)。"""
        self.call("PUT", "/api/admin/nas-config", {"nas_user": "admin", "nas_pass": "admin123"})
        self.call("PUT", "/api/admin/nas-config", {"nas_user": "root"})  # 不带 nas_pass
        self.assertEqual(self.settings()["nas_sync_pass"], "admin123")

    def test_blank_password_clears(self):
        """密码传空字符串 = 明确清除。"""
        self.call("PUT", "/api/admin/nas-config", {"nas_user": "admin", "nas_pass": "admin123"})
        self.call("PUT", "/api/admin/nas-config", {"nas_user": "admin", "nas_pass": ""})
        self.assertNotIn("nas_sync_pass", self.settings())


class TestNasConfigPermissions(unittest.TestCase):
    """凭据端点属于管理操作,员工不该能读写。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name)
        app_handler.DATA_PATHS = {
            "readings": data_dir / "readings.json",
            "readings_water": data_dir / "readings_water.json",
            "charges": data_dir / "charges.json",
            "items": data_dir / "items.json",
            "purchases": data_dir / "purchases.json",
            "duty": data_dir / "duty.json",
        }
        for p in app_handler.DATA_PATHS.values():
            p.write_text("[]", encoding="utf-8")
        (data_dir / "settings.json").write_text(
            json.dumps({"users": [], "meter": {}, "config": {}}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._prev_enforce = routing.ENFORCE_AUTH
        routing.ENFORCE_AUTH = True
        self._saved_sessions = dict(_SESSIONS)
        _SESSIONS.clear()

    def tearDown(self):
        _SESSIONS.clear()
        _SESSIONS.update(self._saved_sessions)
        routing.ENFORCE_AUTH = self._prev_enforce
        self.tmp.cleanup()

    def _session(self, role: str) -> str:
        return create_session({
            "id": {"admin": 1, "supervisor": 2, "employee": 3}[role],
            "username": role, "role": role, "name": role,
        })

    def _call(self, method: str, path: str, body=None, token: str = "") -> FakeHandler:
        h = FakeHandler(path, body, method, token=token)
        app_handler._do_api(method, h, h.path)
        return h

    def test_anonymous_rejected(self):
        h = self._call("GET", "/api/admin/nas-config")
        self.assertEqual(h.response_status, 401)

    def test_employee_rejected(self):
        """员工能录入,但不该能读写远端凭据。"""
        h = self._call("GET", "/api/admin/nas-config", token=self._session("employee"))
        self.assertEqual(h.response_status, 403)

    def test_supervisor_allowed(self):
        h = self._call("GET", "/api/admin/nas-config", token=self._session("supervisor"))
        self.assertEqual(h.response_status, 200)

    def test_admin_allowed(self):
        h = self._call("GET", "/api/admin/nas-config", token=self._session("admin"))
        self.assertEqual(h.response_status, 200)


class TestSyncInvalidatesCaches(NasBase):
    """同步写入后必须失效缓存,否则报表最长 5 分钟还是旧值。"""

    def test_report_cache_invalidated_after_sync(self):
        from report import _get_cached_report, _cache_report

        _cache_report("2026-11", {"stale": True})
        self.assertIsNotNone(_get_cached_report("2026-11"), "前置条件:缓存应已写入")

        h = self.call("POST", "/api/admin/sync-from-nas", {
            "files": {"readings.json": "[]"},
        })
        self.assertTrue(h.parsed["ok"])
        self.assertIsNone(_get_cached_report("2026-11"), "同步后月报缓存必须失效")

    def test_file_cache_invalidated_after_sync(self):
        """同步是直接 write_text 写的,绕过 save_json,必须手动失效文件缓存。"""
        from storage import load_json

        path = self.data_dir / "readings.json"
        path.write_text('[{"date":"2026-11-01","hall":1}]', encoding="utf-8")
        self.assertEqual(len(load_json(path)), 1)  # 先读一次,进缓存

        h = self.call("POST", "/api/admin/sync-from-nas", {
            "files": {"readings.json": '[{"date":"2026-11-02","hall":2},{"date":"2026-11-03","hall":3}]'},
        })
        self.assertTrue(h.parsed["ok"])
        self.assertEqual(len(load_json(path)), 2, "同步后读到的应是新数据而不是缓存里的旧数据")


class TestPasswordNotInBackup(NasBase):
    """NAS 密码不能进备份 ZIP —— 备份会被下载/同步出去。"""

    def test_nas_password_excluded_from_backup(self):
        from modules.backup.handler import _filter_settings_for_backup

        filtered = _filter_settings_for_backup({
            "users": [],
            "nas_sync_user": "admin",
            "nas_sync_pass": "s3cret",
            "backup_dir": "/tmp/x",
        })
        self.assertNotIn("nas_sync_pass", filtered)
        self.assertNotIn("nas_sync_user", filtered)
        self.assertNotIn("s3cret", json.dumps(filtered, ensure_ascii=False))


class TestSyncKeepsLocalCredentials(NasBase):
    """同步回来的 settings.json 不能把本机凭据冲掉。

    远端实例不知道本机的 nas_sync_* / backup_dir —— 那是本机部署字段。
    同步路径必须"合并"而不是"覆盖",否则同步一次凭据就没了,下次同步直接失败。
    """

    def test_sync_preserves_local_nas_credentials(self):
        self.call("PUT", "/api/admin/nas-config", {
            "nas_user": "admin", "nas_pass": "admin123", "nas_url": "https://nas.example.com",
        })

        # 远端回传的 settings.json 里没有 nas_sync_* (远端不知道本机配置)
        remote_settings = json.dumps({
            "users": [{"id": 1, "username": "admin", "role": "admin"}],
            "meter": {"hall": {"label": "大厅"}},
            "config": {"electricity_price": 0.9},
        }, ensure_ascii=False)

        h = self.call("POST", "/api/admin/sync-from-nas", {
            "files": {"settings.json": remote_settings},
        })
        self.assertTrue(h.parsed["ok"], msg=str(h.parsed))

        st = self.settings()
        self.assertEqual(st.get("nas_sync_user"), "admin", "同步不能冲掉本机 NAS 账号")
        self.assertEqual(st.get("nas_sync_pass"), "admin123", "同步不能冲掉本机 NAS 密码")
        self.assertEqual(st.get("nas_sync_url"), "https://nas.example.com")
        # 远端的业务字段仍然要同步过来
        self.assertEqual(st["meter"]["hall"]["label"], "大厅")
        self.assertEqual(st["config"]["electricity_price"], 0.9)

    def test_sync_rejects_malformed_settings_json(self):
        """远端返回的 settings.json 不是合法 JSON 时要跳过,不能写坏本机配置。"""
        self.call("PUT", "/api/admin/nas-config", {"nas_user": "admin", "nas_pass": "admin123"})

        h = self.call("POST", "/api/admin/sync-from-nas", {
            "files": {"settings.json": "{ 这不是 JSON"},
        })
        self.assertTrue(h.parsed["ok"])
        self.assertNotIn("settings.json", h.parsed["restored"])
        # 本机配置没被破坏
        self.assertEqual(self.settings().get("nas_sync_pass"), "admin123")


class TestApiNamespaceNotBroken(NasBase):
    """前端不得引用不存在的 Api 子对象。

    模块化重构(2026-10-24)后 reports.js 仍写着 Api.adminTools.migrateWaterStatus(),
    而 api.js 里只有 Api.migrate —— 每次页面加载都抛 TypeError,
    水电迁移提示整条链路是死的。
    """

    def test_reports_js_does_not_reference_missing_admintools(self):
        src = (Path(__file__).resolve().parent.parent / "MeterStats" / "js" / "modules"
               / "reports.js").read_text(encoding="utf-8")
        self.assertNotIn(
            "Api.adminTools", src,
            "Api.adminTools 不存在 —— api.js 里是 Api.migrate,"
            "引用它会让 checkAndPromptMigration() 每次加载都抛错",
        )

    def test_api_exposes_migrate_namespace(self):
        src = (Path(__file__).resolve().parent.parent / "MeterStats" / "js" / "core"
               / "api.js").read_text(encoding="utf-8")
        self.assertIn("migrate: migrate", src, "api.js 必须导出 migrate 命名空间")
        self.assertIn("waterStatus:", src)


if __name__ == "__main__":
    unittest.main()
