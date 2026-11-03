"""/api/* 全局强制鉴权回归测试(标准库 unittest,零依赖)。

覆盖 routing._auth_gate 的四类行为:
- 白名单端点匿名可访问(Docker 健康检查 / run.sh 探测 / 登录页版本号 / 登录入口)
- 其余端点无 token 或无效 token 一律 401(fail-closed,不再"无 token 放行")
- DELETE 需要主管或管理员,员工 403
- 用户管理需要管理员,否则可自我提权
- <img src> / <a href> 这类带不了请求头的请求,靠 ?token= 查询参数通过校验

运行:
    python3 -m unittest tests.test_auth_enforcement -v
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

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
            self.headers = {"Content-Length": str(len(raw))}
        else:
            self.rfile = io.BytesIO(b"")
            self.headers = {"Content-Length": "0"}
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


def make_session(role: str) -> str:
    """建一个指定角色的会话,返回 token。"""
    return create_session({
        "id": {"admin": 1, "supervisor": 2, "employee": 3}[role],
        "username": role + "_user",
        "role": role,
        "name": role,
    })


class AuthBase(unittest.TestCase):
    """基类:开启强制鉴权 + 隔离数据目录,并保证会话清理干净。"""

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

        # settings_handler 的目录取自 DATA_PATHS["readings"].parent,即本临时目录,
        # 所以登录与用户管理接口读写的都是临时 settings.json,不会碰到真实数据。
        from modules.system.settings_handler import init_settings
        init_settings(data_dir)

        self._prev_enforce = routing.ENFORCE_AUTH
        routing.ENFORCE_AUTH = True  # 本文件专测鉴权,必须处于强制状态

        self._saved_sessions = dict(_SESSIONS)
        _SESSIONS.clear()
        self.tok_admin = make_session("admin")
        self.tok_super = make_session("supervisor")
        self.tok_emp = make_session("employee")

    def tearDown(self):
        _SESSIONS.clear()
        _SESSIONS.update(self._saved_sessions)
        routing.ENFORCE_AUTH = self._prev_enforce
        self.tmp.cleanup()

    def call(self, method: str, path: str, body: Optional[dict] = None,
             token: str = "", bearer: str = "") -> FakeHandler:
        h = FakeHandler(path, body, method, token=token, bearer=bearer)
        app_handler._do_api(method, h, h.path)
        return h


class TestPublicWhitelist(AuthBase):
    """白名单:未登录也必须可用,否则容器健康检查和登录本身会挂。"""

    def test_health_anonymous_ok(self):
        self.assertEqual(self.call("GET", "/api/health").response_status, 200)

    def test_version_anonymous_ok(self):
        h = self.call("GET", "/api/version")
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed.get("version"))

    def test_login_endpoint_is_public(self):
        # 登录入口不能被拦:错误凭据应返回 ok:false,而不是 401
        h = self.call("POST", "/api/auth/login", {"username": "x", "password": "y"})
        self.assertEqual(h.response_status, 200)
        self.assertFalse(h.parsed.get("ok"))


class TestFailClosed(AuthBase):
    """核心修复:业务接口不带 token 不再放行。"""

    PROTECTED_GET = [
        "/api/readings",
        "/api/charges",
        "/api/items",
        "/api/purchases",
        "/api/duty",
        "/api/snapshot",
        "/api/export",
        "/api/meters",
        "/api/readings-water",
    ]

    def test_all_business_get_401_without_token(self):
        for path in self.PROTECTED_GET:
            h = self.call("GET", path)
            self.assertEqual(h.response_status, 401, f"{path} 未鉴权却返回 {h.response_status}")
            self.assertIn("未登录", h.parsed.get("error", ""))

    def test_bogus_token_401(self):
        h = self.call("GET", "/api/readings", token="deadbeef")
        self.assertEqual(h.response_status, 401)

    def test_valid_token_via_query_ok(self):
        h = self.call("GET", "/api/readings", token=self.tok_emp)
        self.assertEqual(h.response_status, 200)

    def test_valid_token_via_bearer_header_ok(self):
        h = self.call("GET", "/api/readings", bearer=self.tok_emp)
        self.assertEqual(h.response_status, 200)

    def test_post_write_requires_token(self):
        body = {"date": "2026-11-03", "hall": 10.0, "fire": 20.0,
                "private_room": 30.0, "ac": 40.0}
        self.assertEqual(self.call("POST", "/api/readings", body).response_status, 401)
        h = self.call("POST", "/api/readings", body, token=self.tok_emp)
        self.assertEqual(h.response_status, 200)

    def test_duty_image_requires_token_but_query_works(self):
        # <img src> 只能靠 ?token=;这里只断言鉴权层:匿名 401、带 token 不再是 401
        self.assertEqual(self.call("GET", "/api/duty/image/none.png").response_status, 401)
        self.assertNotEqual(
            self.call("GET", "/api/duty/image/none.png", token=self.tok_emp).response_status,
            401,
        )


class TestRolePolicy(AuthBase):
    """角色策略:删除需主管及以上,用户管理仅管理员。"""

    def test_delete_denied_for_employee(self):
        h = self.call("DELETE", "/api/readings?date=2026-11-03", token=self.tok_emp)
        self.assertEqual(h.response_status, 403)
        self.assertIn("删除", h.parsed.get("error", ""))

    def test_delete_allowed_for_supervisor_role(self):
        # 只断言不被鉴权层拦成 403/401;数据本身不存在导致的业务错误不在本页范围
        h = self.call("DELETE", "/api/readings?date=2026-11-03", token=self.tok_super)
        self.assertNotIn(h.response_status, (401, 403))

    def test_delete_allowed_for_admin(self):
        h = self.call("DELETE", "/api/readings?date=2026-11-03", token=self.tok_admin)
        self.assertNotIn(h.response_status, (401, 403))

    def test_user_management_denied_for_non_admin(self):
        payload = {"username": "escalate", "password": "p", "name": "提权", "role": "admin"}
        for tok, who in ((self.tok_emp, "employee"), (self.tok_super, "supervisor")):
            h = self.call("POST", "/api/admin/users", payload, token=tok)
            self.assertEqual(h.response_status, 403, f"{who} 竟可创建账号")
            self.assertIn("管理员", h.parsed.get("error", ""))

    def test_user_management_not_blocked_for_admin(self):
        payload = {"username": "newone", "password": "secret123", "name": "新人", "role": "employee"}
        h = self.call("POST", "/api/admin/users", payload, token=self.tok_admin)
        self.assertNotIn(h.response_status, (401, 403))

    def test_manager_endpoints_denied_for_employee(self):
        # 审计日志 / 电价配置 / NAS 同步 / 备份删除 不应向"只能录入"的员工开放
        for path in ("/api/admin/audit", "/api/admin/meter", "/api/admin/data-files"):
            h = self.call("GET", path, token=self.tok_emp)
            self.assertEqual(h.response_status, 403, f"{path} 对员工放行")
            self.assertIn("主管", h.parsed.get("error", ""))

    def test_manager_endpoints_allowed_for_supervisor(self):
        for path in ("/api/admin/audit", "/api/admin/data-files"):
            h = self.call("GET", path, token=self.tok_super)
            self.assertNotIn(h.response_status, (401, 403), f"{path} 拦住了主管")


class TestSessionTtlTouch(AuthBase):
    """通过校验的请求应续期会话,和装饰器旧行为保持一致。"""

    def test_active_session_is_extended(self):
        import time as _t
        from modules.system.auth_handler import _touch_session
        # 先把会话伪造成"很久没动",但仍在 TTL 内
        _SESSIONS[self.tok_emp]["_access_time"] = _t.time() - 60
        before = _SESSIONS[self.tok_emp]["_access_time"]
        self.call("GET", "/api/readings", token=self.tok_emp)
        self.assertGreater(_SESSIONS[self.tok_emp]["_access_time"], before)
        _touch_session  # noqa: B018 (确认符号可导入)


if __name__ == "__main__":
    unittest.main()
