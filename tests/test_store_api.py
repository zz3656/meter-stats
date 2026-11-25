"""门店管理 HTTP API 测试(标准库 unittest,零依赖)。

单独成文件(不追加到 tests/test_stores.py):那个文件由并行 Task 修改,
两个 worker 写同一个测试文件会在 git 上撞冲突。

覆盖:
- GET    /api/stores         → 只返回该用户有权限的门店
- GET    /api/stores/current → 当前门店(且不被 /api/stores 前缀吃掉)
- POST   /api/stores         → 仅管理员可新增
- PUT    /api/stores/<id>    → 仅管理员可修改
- DELETE /api/stores/<id>    → 仅管理员可删除;默认店 main 不可删
- fail-closed:查不到用户记录 → 不返回全部门店;没有有效会话 → 401

运行:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.stores import context, registry  # noqa: E402
from modules.system.auth_handler import _SESSIONS, create_session  # noqa: E402
from modules.system.settings_handler import (  # noqa: E402
    get_settings,
    init_settings,
    save_settings,
)

import app_handler  # noqa: E402
import routing  # noqa: E402
from storage import DATA_FILES  # noqa: E402


class _ApiHandler:
    """最小 HTTP handler 桩 —— 供门店 API 测试用(与 app_handler.Handler 同形)。"""

    def __init__(self, path: str, body: Optional[Dict[str, Any]] = None,
                 method: str = "GET", token: str = "") -> None:
        self.path = path
        self.command = method
        self.response_status: Optional[int] = None
        self.response_headers: Dict[str, str] = {}
        self.wfile = io.BytesIO()
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            self.rfile = io.BytesIO(raw)
            self.headers = {"Content-Length": str(len(raw))}
        else:
            self.rfile = io.BytesIO(b"")
            self.headers = {"Content-Length": "0"}
        if token:
            sep = "&" if "?" in path else "?"
            self.path = path + sep + "token=" + token

    def send_response(self, status: int) -> None:
        self.response_status = status

    def send_header(self, k: str, v: str) -> None:
        self.response_headers[k] = v

    def end_headers(self) -> None:
        pass

    @property
    def parsed(self) -> Any:
        raw = self.wfile.getvalue()
        return json.loads(raw) if raw else None


class StoreApiTestBase(unittest.TestCase):
    """基类:独立临时数据目录 + 真实会话(鉴权开着,走完整鉴权链)。"""

    def setUp(self) -> None:
        self._prev_enforce = routing.ENFORCE_AUTH
        self._prev_paths = app_handler.DATA_PATHS
        self._prev_sessions = dict(_SESSIONS)
        _SESSIONS.clear()
        # 门店 API 必须走真实鉴权 —— ENFORCE_AUTH=False 时的合成会话
        # 会把「查不到用户记录」这条分支整条盖掉,测不出 fail-closed。
        routing.ENFORCE_AUTH = True
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.paths: Dict[str, Path] = {
            m: self.data_dir / fn for m, fn in DATA_FILES.items()
        }
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        # settings_handler 的目录取自 DATA_PATHS["readings"].parent → 本临时目录,
        # 所以用户表/门店注册表读写都在临时目录里,不会碰到真实数据。
        init_settings(self.data_dir)
        self._write_settings(users=self._users(), stores=self._stores())
        context.clear_current_store()

    def tearDown(self) -> None:
        routing.ENFORCE_AUTH = self._prev_enforce
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        _SESSIONS.clear()
        _SESSIONS.update(self._prev_sessions)
        self.tmp.cleanup()

    # ---- 固定数据 ----

    def _users(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": 1, "username": "admin", "password": "x", "role": "admin",
                "name": "管理员", "enabled": True, "all_stores": True, "store_ids": [],
            },
            {
                "id": 2, "username": "emp", "password": "x", "role": "employee",
                "name": "员工", "enabled": True, "all_stores": False,
                "store_ids": ["s002"],
            },
        ]

    def _stores(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "main", "name": "总店", "code": "", "address": "",
                "active": True, "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": "s002", "name": "国贸店", "code": "B002", "address": "国贸",
                "active": True, "created_at": "2026-01-02T00:00:00",
            },
        ]

    # ---- 辅助 ----

    def _write_settings(self, users: Optional[List[Dict[str, Any]]] = None,
                        stores: Optional[List[Dict[str, Any]]] = None) -> None:
        """改写 settings.json 里的用户表 / 门店注册表。"""
        settings = get_settings()
        if users is not None:
            settings["users"] = users
        if stores is not None:
            settings["stores"] = stores
        save_settings(settings)

    def _multi_store_layout(self) -> None:
        """建 stores/ 目录 → 门店闸进入多店布局(严格模式)。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True, exist_ok=True)

    def _session(self, user: Dict[str, Any]) -> str:
        """给一个用户建会话,返回 token。"""
        payload: Dict[str, Any] = {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "name": user["name"],
        }
        # 门店范围:会话里的兜底字段(create_session 支持时带上)。
        # 不带也行 —— handler 侧必须查 settings.json,查不到就拒绝。
        if "all_stores" in user:
            payload["all_stores"] = user["all_stores"]
        if "store_ids" in user:
            payload["store_ids"] = user["store_ids"]
        return create_session(payload)

    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
              token: str = "") -> _ApiHandler:
        """走完整路由分发(鉴权闸 → 门店闸 → handler)。"""
        h = _ApiHandler(path, body, method, token=token)
        app_handler._do_api(method, h, h.path)  # type: ignore[no-untyped-call]
        return h

    def _store(self, store_id: str) -> Dict[str, Any]:
        """从注册表里取门店(取不到就让测试失败)。"""
        store = registry.get_store(store_id)
        self.assertIsNotNone(store, store_id)
        return store if store else {}


class TestStoreApiRead(StoreApiTestBase):
    """读接口:任何登录用户可读,但只看到自己有权限的门店。"""

    def setUp(self) -> None:
        super().setUp()
        self._multi_store_layout()

    def test_admin_sees_all_stores(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("GET", "/api/stores", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual([s["id"] for s in h.parsed["stores"]], ["main", "s002"])

    def test_employee_sees_only_assigned_stores(self) -> None:
        """分店员工只能看到分配给自己的门店。"""
        tok = self._session(self._users()[1])
        h = self._call("GET", "/api/stores", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual([s["id"] for s in h.parsed["stores"]], ["s002"])

    def test_get_stores_without_session_returns_401(self) -> None:
        """没有有效会话 → 401,不是空列表、更不是全部门店。"""
        h = self._call("GET", "/api/stores")
        self.assertEqual(h.response_status, 401)

    def test_get_current_store_returns_current(self) -> None:
        """当前门店 = 门店闸按用户范围解析出来的门店。"""
        tok = self._session(self._users()[1])
        h = self._call("GET", "/api/stores/current", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual(h.parsed["store_id"], "s002")
        self.assertEqual(h.parsed["store"]["name"], "国贸店")

    def test_current_route_not_shadowed_by_stores_route(self) -> None:
        """/api/stores/current 必须精确命中,不能被 /api/stores 前缀吃掉。"""
        tok = self._session(self._users()[0])
        h = self._call("GET", "/api/stores/current", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertIn("store_id", h.parsed)
        self.assertNotIn("stores", h.parsed)


class TestStoreApiFailClosed(StoreApiTestBase):
    """fail-closed:查不到用户记录 / 没有有效会话,都不能拿到全部门店。

    这些用例走**单店布局**(没有 stores/ 目录):单店布局下门店闸整体放行,
    「查不到用户记录」这一关只剩 handler 自己守 —— 守不住就越权了。
    """

    def test_deleted_admin_does_not_get_all_stores(self) -> None:
        """被删掉的**管理员**账号,旧会话还在 → 也不能列全部门店。

        这就是简报里那个 fail-open 缺陷最危险的样子:会话里带着
        all_stores=True(总部账号),一旦 handler 回退放行,被删账号
        就能看见全部门店。查不到用户记录 = 拒绝,不是放行。
        """
        ghost = {
            "id": 999, "username": "ghost", "role": "admin", "name": "幽灵管理员",
            "all_stores": True,
        }
        tok = self._session(ghost)
        h = self._call("GET", "/api/stores", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"], h.parsed)
        # 注册表里明明有 main / s002 两家店 —— 一家都不该给
        self.assertEqual(h.parsed["stores"], [])

    def test_deleted_user_does_not_get_all_stores(self) -> None:
        """账号被删除但会话还在 → 只能拿到空列表,不是全部门店。"""
        ghost = {
            "id": 999, "username": "ghost", "role": "employee", "name": "幽灵",
        }
        tok = self._session(ghost)
        h = self._call("GET", "/api/stores", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"], h.parsed)
        # 注册表里明明有 main / s002 两家店 —— 一家都不该给
        self.assertEqual(h.parsed["stores"], [])

    def test_user_without_store_assignment_gets_empty_list(self) -> None:
        """受限账号但一个门店都没分配 → 空列表,不是全部门店。"""
        users = self._users()
        users.append({
            "id": 3, "username": "no_store", "password": "x", "role": "employee",
            "name": "无门店", "enabled": True, "all_stores": False, "store_ids": [],
        })
        self._write_settings(users=users)
        tok = self._session(users[2])
        h = self._call("GET", "/api/stores", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertEqual(h.parsed["stores"], [])

    def test_handler_without_session_returns_401(self) -> None:
        """直接调 handler(没有会话)→ 401,绝不放行成「全部门店」。"""
        from modules.stores.handler import handle_get_stores
        h = _ApiHandler("/api/stores", None, "GET")
        handle_get_stores(h)
        self.assertEqual(h.response_status, 401)
        self.assertFalse(h.parsed["ok"])


class TestStoreApiWrite(StoreApiTestBase):
    """写接口:增删改仅管理员。"""

    def setUp(self) -> None:
        super().setUp()
        self._multi_store_layout()

    def test_admin_can_create_store(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("POST", "/api/stores", {"id": "s003", "name": "望京店"}, token=tok)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual(h.parsed["store"]["name"], "望京店")
        # 注册表里真的有了,且建好了数据目录
        self.assertIsNotNone(registry.get_store("s003"))
        self.assertTrue((self.data_dir / "stores" / "s003").is_dir())

    def test_post_store_rejects_invalid_id(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("POST", "/api/stores", {"id": "../evil", "name": "越权店"}, token=tok)
        self.assertFalse(h.parsed["ok"])
        self.assertIn("ID", h.parsed["error"])

    def test_post_store_rejects_empty_name(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("POST", "/api/stores", {"id": "s004", "name": "   "}, token=tok)
        self.assertFalse(h.parsed["ok"])

    def test_post_store_rejects_duplicate_id(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("POST", "/api/stores", {"id": "s002", "name": "重复店"}, token=tok)
        self.assertFalse(h.parsed["ok"])
        self.assertIn("已存在", h.parsed["error"])

    def test_employee_cannot_create_store(self) -> None:
        tok = self._session(self._users()[1])
        h = self._call("POST", "/api/stores", {"id": "s003", "name": "越权店"}, token=tok)
        self.assertFalse(h.parsed["ok"])
        self.assertIn("管理员", h.parsed["error"])
        self.assertIsNone(registry.get_store("s003"))

    def test_admin_can_update_store(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("PUT", "/api/stores/s002",
                       {"name": "国贸分店", "code": "B9"}, token=tok)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual(h.parsed["store"]["name"], "国贸分店")
        self.assertEqual(self._store("s002")["code"], "B9")

    def test_admin_can_deactivate_store(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("PUT", "/api/stores/s002", {"active": False}, token=tok)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertFalse(h.parsed["store"]["active"])

    def test_employee_cannot_update_store(self) -> None:
        tok = self._session(self._users()[1])
        h = self._call("PUT", "/api/stores/s002", {"name": "改名"}, token=tok)
        self.assertFalse(h.parsed["ok"])
        self.assertIn("管理员", h.parsed["error"])
        self.assertEqual(self._store("s002")["name"], "国贸店")

    def test_update_unknown_store_returns_error(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("PUT", "/api/stores/nope", {"name": "x"}, token=tok)
        self.assertFalse(h.parsed["ok"])
        self.assertIn("不存在", h.parsed["error"])

    def test_admin_can_delete_store(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("DELETE", "/api/stores/s002", token=tok)
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertIsNone(registry.get_store("s002"))

    def test_delete_default_store_forbidden(self) -> None:
        """默认店 main 不可删。"""
        tok = self._session(self._users()[0])
        h = self._call("DELETE", "/api/stores/main", token=tok)
        self.assertFalse(h.parsed["ok"])
        self.assertIsNotNone(registry.get_store("main"))

    def test_delete_unknown_store_returns_error(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("DELETE", "/api/stores/nope", token=tok)
        self.assertFalse(h.parsed["ok"])

    def test_employee_cannot_delete_store(self) -> None:
        """非管理员删不了门店(鉴权闸或 handler 拦住都行,但门店必须还在)。"""
        tok = self._session(self._users()[1])
        h = self._call("DELETE", "/api/stores/s002", token=tok)
        self.assertIn(h.response_status, (200, 403))
        if h.response_status == 200:
            self.assertFalse(h.parsed["ok"])
        self.assertIsNotNone(registry.get_store("s002"))
