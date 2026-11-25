"""门店鉴权闸(越权防护)回归测试(标准库 unittest,零依赖)。

覆盖 routing._store_gate:
- 单店布局(没有 stores/ 目录)→ 整体放行并落到默认店 —— 存量业务回归行为不变的根据
- 多店布局 → 严格按门店范围放行;越权 403;门店不存在 404
- 范围优先读 settings.json(改权限即时生效,不必重新登录)
- 查不到用户记录 → 403(fail-closed),绝不回退成「全店权限」
- 公开端点(health/version/login)根本不进门店闸 —— 404 会让 Docker HEALTHCHECK 判 unhealthy
- 数据目录未初始化 → 放行而不是 500(门店闸不是新的 500 来源)
- 鉴权关闭(ENFORCE_AUTH=False)→ 合成管理员会话,门店闸照常工作

运行:
    python3 -m unittest tests.test_store_gate -v
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.stores import context  # noqa: E402

import app_handler  # noqa: E402
import routing  # noqa: E402
from storage import DATA_FILES  # noqa: E402


class _FakeHandler:
    """最小 HTTP handler 桩 —— 只供门店闸测试用。"""

    def __init__(self, path: str, body: Optional[dict[str, Any]] = None,
                 method: str = "GET") -> None:
        self.path = path
        self.command = method
        self.response_status: Optional[int] = None
        self.response_headers: dict[str, str] = {}
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO(raw)
        self.headers = {"Content-Length": str(len(raw))}

    def send_response(self, status: int) -> None:
        self.response_status = status

    def send_header(self, k: str, v: str) -> None:
        self.response_headers[k] = v

    def end_headers(self) -> None:
        pass

    @property
    def parsed(self) -> Any:
        body = self.wfile.getvalue()
        return json.loads(body.decode("utf-8")) if body else None


class StoreGateBase(unittest.TestCase):
    """基类:临时数据目录 + 干净的用户/门店配置。"""

    def setUp(self) -> None:
        self._prev_enforce = routing.ENFORCE_AUTH
        self._prev_paths = app_handler.DATA_PATHS
        routing.ENFORCE_AUTH = True  # 生产同款:鉴权强制生效
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        from modules.system.settings_handler import init_settings
        init_settings(self.data_dir)
        context.clear_current_store()

    def tearDown(self) -> None:
        routing.ENFORCE_AUTH = self._prev_enforce
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        self.tmp.cleanup()

    # ---- 夹具 ----

    def _enable_multi_store(self) -> None:
        """造出多门店布局:总店 main + 分店 s002,并登记两个分店员工。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        (self.data_dir / "stores" / "s002").mkdir(parents=True)
        from modules.system.settings_handler import get_settings, save_settings
        settings = get_settings()
        settings["stores"] = [
            {"id": "main", "name": "总店", "active": True},
            {"id": "s002", "name": "国贸店", "active": True},
        ]
        settings["users"][0]["all_stores"] = True
        settings["users"][0]["store_ids"] = []
        settings["users"].append({
            "id": 99, "username": "branch", "password": "x", "role": "employee",
            "name": "分店员工", "enabled": True,
            "store_ids": ["s002"], "all_stores": False,
        })
        settings["users"].append({
            "id": 98, "username": "nostore", "password": "x", "role": "employee",
            "name": "未分配门店员工", "enabled": True,
            "store_ids": [], "all_stores": False,
        })
        save_settings(settings)

    def _session(self, user_id: int, role: str = "employee",
                 all_stores: bool = False,
                 store_ids: Optional[list[str]] = None) -> dict[str, Any]:
        return {"user_id": user_id, "username": "u", "role": role, "name": "u",
                "all_stores": all_stores, "store_ids": store_ids or []}

    def _call(self, method: str, path: str,
              body: Optional[dict[str, Any]] = None) -> _FakeHandler:
        h = _FakeHandler(path, body, method)
        app_handler._do_api(method, h, h.path)  # type: ignore[no-untyped-call]
        return h


class TestStoreGateSingleLayout(StoreGateBase):
    """单店布局:门店闸整体放行 —— 存量业务回归行为不变的根据。"""

    def test_gate_is_noop_in_single_store_layout(self) -> None:
        from routing import _store_gate
        ok = _store_gate(self._session(1, "admin", True), _FakeHandler("/api/readings"))
        self.assertTrue(ok)

    def test_gate_lands_on_default_store(self) -> None:
        from routing import _store_gate
        context.clear_current_store()
        ok = _store_gate(self._session(1, "admin", True), _FakeHandler("/api/readings"))
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "main")

    def test_gate_allows_unknown_user_in_single_store_layout(self) -> None:
        """存量回归测试的合成会话用户根本不在 settings.json 里 —— 也必须放行。"""
        from routing import _store_gate
        ok = _store_gate(self._session(999, "employee"), _FakeHandler("/api/readings"))
        self.assertTrue(ok)

    def test_gate_ignores_store_param_in_single_store_layout(self) -> None:
        """单店布局只有一家店,带不带 store 参数都落在默认店。"""
        from routing import _store_gate
        ok = _store_gate(self._session(999), _FakeHandler("/api/readings?store=s002"))
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "main")


class TestStoreGateMultiLayout(StoreGateBase):
    """多店布局:严格按门店范围放行。"""

    def setUp(self) -> None:
        super().setUp()
        self._enable_multi_store()

    def test_gate_allows_assigned_store(self) -> None:
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=s002")
        self.assertTrue(_store_gate(self._session(99, store_ids=["s002"]), h))
        self.assertEqual(context.get_current_store(), "s002")

    def test_gate_blocks_unassigned_store(self) -> None:
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=main")
        self.assertFalse(_store_gate(self._session(99, store_ids=["s002"]), h))
        self.assertEqual(h.response_status, 403)
        self.assertIn("无权访问门店", h.parsed["error"])

    def test_gate_allows_all_stores_user_any_store(self) -> None:
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=s002")
        self.assertTrue(_store_gate(self._session(1, "admin", True), h))
        self.assertEqual(context.get_current_store(), "s002")

    def test_gate_allows_all_stores_user_without_store_param(self) -> None:
        """总部账号不带 store 参数 → 落到默认店 main。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        self.assertTrue(_store_gate(self._session(1, "admin", True), h))
        self.assertEqual(context.get_current_store(), "main")

    def test_gate_defaults_to_first_assigned_store(self) -> None:
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        self.assertTrue(_store_gate(self._session(99, store_ids=["s002"]), h))
        self.assertEqual(context.get_current_store(), "s002")

    def test_gate_rejects_unknown_store(self) -> None:
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=nope")
        self.assertFalse(_store_gate(self._session(1, "admin", True), h))
        self.assertEqual(h.response_status, 404)
        self.assertIn("门店不存在", h.parsed["error"])

    def test_gate_rejects_user_without_any_store(self) -> None:
        """账号一个门店都没分配 → 403,而不是回退到默认店。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        self.assertFalse(_store_gate(self._session(98, store_ids=[]), h))
        self.assertEqual(h.response_status, 403)

    def test_gate_rejects_user_missing_from_settings(self) -> None:
        """账号被删但会话还在 → 必须 403(fail-closed),绝不能回退成「全店权限」。

        会话里明明写着 all_stores=True —— 回退放行就等于「删号不清权限」。
        """
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=s002")
        self.assertFalse(_store_gate(self._session(999, "admin", True, ["s002"]), h))
        self.assertEqual(h.response_status, 403)

    def test_unknown_store_is_403_not_404_for_restricted_user(self) -> None:
        """权限先判、存在性后判:分店员工探测别的门店只能拿到 403,摸不到注册表。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=nope")
        self.assertFalse(_store_gate(self._session(99, store_ids=["s002"]), h))
        self.assertEqual(h.response_status, 403)

    def test_settings_scope_wins_over_session(self) -> None:
        """settings.json 里的范围说了算 —— 改权限即时生效,不必重新登录。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=main")
        # 会话里写着 all_stores=True,但 settings.json 里这个账号只有 s002
        self.assertFalse(_store_gate(self._session(99, "admin", True, ["s002"]), h))
        self.assertEqual(h.response_status, 403)

    def test_scope_change_takes_effect_without_relogin(self) -> None:
        """管理员收回门店 → 同一个会话立刻失效,不用重新登录。"""
        from modules.system.settings_handler import get_settings, save_settings

        from routing import _store_gate

        h = _FakeHandler("/api/readings?store=s002")
        self.assertTrue(_store_gate(self._session(99, store_ids=["s002"]), h))

        settings = get_settings()
        for u in settings["users"]:
            if u.get("id") == 99:
                u["store_ids"] = []
        save_settings(settings)

        h2 = _FakeHandler("/api/readings?store=s002")
        self.assertFalse(_store_gate(self._session(99, store_ids=["s002"]), h2))
        self.assertEqual(h2.response_status, 403)


class TestStoreGatePublicEndpoints(StoreGateBase):
    """公开端点不进门店闸 —— /api/health 404 会让 Docker HEALTHCHECK 判 unhealthy。"""

    def _enable_multi_store_without_registry(self) -> None:
        """stores/ 目录存在,但注册表里一家店都没有(最坏情况)。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True)

    def test_public_endpoints_never_reach_store_gate(self) -> None:
        self._enable_multi_store_without_registry()
        calls: list[Any] = []
        original = routing._store_gate

        def spy(sess: dict[str, Any], handler: Any) -> bool:
            calls.append(sess)
            return original(sess, handler)

        routing._store_gate = spy
        try:
            health = self._call("GET", "/api/health")
            version = self._call("GET", "/api/version")
            login = self._call("POST", "/api/auth/login", {"username": "x", "password": "y"})
        finally:
            routing._store_gate = original
        self.assertEqual(calls, [])
        self.assertEqual(health.response_status, 200)
        self.assertEqual(version.response_status, 200)
        self.assertEqual(login.response_status, 200)

    def test_health_is_not_404_in_multi_store_layout(self) -> None:
        """最坏情况:stores/ 存在但注册表为空 —— /api/health 仍然 200,不能是 404。"""
        self._enable_multi_store_without_registry()
        h = self._call("GET", "/api/health")
        self.assertEqual(h.response_status, 200)
        self.assertNotIn("error", h.parsed)


class TestStoreGateFailSafe(StoreGateBase):
    """门店闸是「拦越权」的闸,不是新的 500 来源。"""

    def test_gate_survives_uninitialized_data_paths(self) -> None:
        """DATA_PATHS 未初始化 → 判不出布局就按单店放行,绝不抛异常。"""
        from routing import _store_gate
        app_handler.DATA_PATHS = {}
        try:
            ok = _store_gate(self._session(1, "admin", True), _FakeHandler("/api/readings"))
        finally:
            app_handler.DATA_PATHS = self.paths
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "main")

    def test_auth_gate_returns_synthetic_session_when_auth_disabled(self) -> None:
        """ENFORCE_AUTH=False → 合成管理员会话,门店闸拿得到 session(不是空/None)。"""
        routing.ENFORCE_AUTH = False
        sess = routing._auth_gate("GET", "/api/readings", _FakeHandler("/api/readings"))
        self.assertIsInstance(sess, dict)
        assert sess is not None
        self.assertEqual(sess.get("role"), "admin")
        self.assertTrue(sess.get("all_stores"))

    def test_auth_gate_returns_none_when_not_logged_in(self) -> None:
        routing.ENFORCE_AUTH = True
        h = _FakeHandler("/api/readings")
        self.assertIsNone(routing._auth_gate("GET", "/api/readings", h))
        self.assertEqual(h.response_status, 401)

    def test_store_gate_still_works_when_auth_disabled(self) -> None:
        """鉴权关闭(测试模式)→ 合成会话照样能过门店闸,请求不会被 403/404 拦掉。"""
        self._enable_multi_store()
        routing.ENFORCE_AUTH = False
        h = self._call("GET", "/api/readings?store=s002")
        self.assertEqual(h.response_status, 200)
        self.assertEqual(context.get_current_store(), "s002")


class TestStoreGateDeletedStore(StoreGateBase):
    """管理员删掉门店后,员工不该被锁死。

    删店只摘掉注册表条目,用户记录里的 store_ids 仍留着那个 ID。
    修复前:默认门店 = store_ids[0] → 撞上 404「门店不存在」→ 员工每个请求都 404。
    修复后:默认门店 = 「他有权访问的、且仍然存在的」第一个门店;
            一个都不剩 → 403「账号未分配有效门店,请联系管理员」。
    """

    def setUp(self) -> None:
        super().setUp()
        self._enable_three_stores()

    def _enable_three_stores(self) -> None:
        """总店 main + 分店 s002 + 分店 s003,登记 3 个账号。"""
        for sid in ("main", "s002", "s003"):
            (self.data_dir / "stores" / sid).mkdir(parents=True, exist_ok=True)
        from modules.system.settings_handler import get_settings, save_settings
        settings = get_settings()
        settings["stores"] = [
            {"id": "main", "name": "总店", "active": True},
            {"id": "s002", "name": "国贸店", "active": True},
            {"id": "s003", "name": "太古里店", "active": True},
        ]
        settings["users"][0]["all_stores"] = True
        settings["users"][0]["store_ids"] = []
        settings["users"].append({
            "id": 99, "username": "branch", "password": "x", "role": "employee",
            "name": "分店员工", "enabled": True,
            "store_ids": ["s002"], "all_stores": False,
        })
        settings["users"].append({
            "id": 97, "username": "multi", "password": "x", "role": "employee",
            "name": "多分店员工", "enabled": True,
            "store_ids": ["s002", "s003"], "all_stores": False,
        })
        settings["users"].append({
            "id": 96, "username": "hq", "password": "x", "role": "supervisor",
            "name": "总部账号", "enabled": True,
            "store_ids": ["s002"], "all_stores": True,
        })
        save_settings(settings)

    def _delete_store(self, store_id: str) -> None:
        """模拟管理员删店:只摘注册表条目,用户记录里的 store_ids 原样不动。"""
        from modules.stores import registry
        self.assertTrue(registry.delete_store(store_id))

    # ---- 1. 有权访问的店被删了 → 不许 404 锁死 ----

    def test_deleted_store_does_not_lock_out_employee(self) -> None:
        """员工唯一的店被删 → 不是 404「门店不存在」,而是能看懂的 403。"""
        from routing import _store_gate
        self._delete_store("s002")
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(99, store_ids=["s002"]), h)
        self.assertFalse(ok)
        self.assertNotEqual(h.response_status, 404)
        self.assertEqual(h.response_status, 403)

    def test_employee_falls_back_to_another_still_existing_store(self) -> None:
        """员工的第一个店被删 → 落到他仍有权访问的另一个店(不是 404)。"""
        from routing import _store_gate
        self._delete_store("s002")
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(97, store_ids=["s002", "s003"]), h)
        self.assertTrue(ok)
        self.assertEqual(h.response_status, None)
        self.assertEqual(context.get_current_store(), "s003")

    # ---- 2. 店全被删了 → 403,文案要说清找管理员 ----

    def test_all_assigned_stores_deleted_gives_clear_403(self) -> None:
        """有权访问的店全被删 → 403 + 文案提到「门店」和「联系管理员」。"""
        from routing import _store_gate
        self._delete_store("s002")
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(99, store_ids=["s002"]), h)
        self.assertFalse(ok)
        self.assertEqual(h.response_status, 403)
        err = h.parsed["error"]
        self.assertIn("门店", err)
        self.assertIn("联系管理员", err)

    # ---- 3. 显式 ?store= 已删除的店 → 仍然 404 ----

    def test_explicit_deleted_store_still_404(self) -> None:
        """用户点名问那个店 → 店不存在就是不存在,仍然 404。"""
        from routing import _store_gate
        self._delete_store("s002")
        h = _FakeHandler("/api/readings?store=s002")
        ok = _store_gate(self._session(97, store_ids=["s002", "s003"]), h)
        self.assertFalse(ok)
        self.assertEqual(h.response_status, 404)
        self.assertIn("门店不存在", h.parsed["error"])

    def test_explicit_deleted_store_404_for_single_store_employee(self) -> None:
        """只有 s002 的员工显式点名 s002(已删)→ 404,不是 403。"""
        from routing import _store_gate
        self._delete_store("s002")
        h = _FakeHandler("/api/readings?store=s002")
        ok = _store_gate(self._session(99, store_ids=["s002"]), h)
        self.assertFalse(ok)
        self.assertEqual(h.response_status, 404)

    # ---- 4. 总部账号行为不变 ----

    def test_headquarters_without_store_ids_lands_on_main(self) -> None:
        """总部账号 store_ids 为空 → 落默认店 main(行为不变)。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(1, "admin", True, []), h)
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "main")

    def test_headquarters_with_store_ids_lands_on_first_store(self) -> None:
        """总部账号 store_ids 非空且第一个存在 → 仍落 store_ids[0](行为不变)。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(96, "supervisor", True, ["s002"]), h)
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "s002")

    def test_headquarters_skips_deleted_store_but_keeps_store_ids_order(self) -> None:
        """总部账号 store_ids[0] 被删 → 跳到下一个仍存在的(store_ids 顺序不变)。"""
        from routing import _store_gate
        self._delete_store("s002")
        from modules.system.settings_handler import get_settings, save_settings
        settings = get_settings()
        for u in settings["users"]:
            if u.get("id") == 96:
                u["store_ids"] = ["s002", "s003"]
        save_settings(settings)
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(96, "supervisor", True, ["s002", "s003"]), h)
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "s003")

    # ---- 5. 回归护栏:正常场景行为完全不变 ----

    def test_normal_case_unchanged_single_store_employee(self) -> None:
        """店都在 → 仍落第一个有权访问的店。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(99, store_ids=["s002"]), h)
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "s002")

    def test_normal_case_unchanged_multi_store_employee(self) -> None:
        """店都在 → 多店员工仍落 store_ids[0](不是 store_ids[-1])。"""
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(97, store_ids=["s002", "s003"]), h)
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "s002")

    def test_recreated_store_restores_access(self) -> None:
        """删店后用同样的 ID 重新建店 → 访问恢复(不变式不能被破坏)。"""
        from modules.stores import registry

        from routing import _store_gate
        self._delete_store("s002")
        h = _FakeHandler("/api/readings")
        self.assertFalse(_store_gate(self._session(99, store_ids=["s002"]), h))

        registry.add_store("s002", "国贸店(重建)")
        h2 = _FakeHandler("/api/readings")
        ok = _store_gate(self._session(99, store_ids=["s002"]), h2)
        self.assertTrue(ok)
        self.assertEqual(context.get_current_store(), "s002")


if __name__ == "__main__":
    unittest.main()
