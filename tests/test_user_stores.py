"""用户门店归属(Task 6)回归测试(标准库 unittest,零依赖)。

覆盖:
- add_user / update_user 的 all_stores / store_ids 语义
- 降级(admin → employee)时 all_stores 必须收敛为 False
- /api/admin/users 的 store_ids 合法性校验(不存在的门店必须报错)
- 写盘失败必须报错,不能报成功(写完回读校验)
- create_session / 登录返回带上门店范围

运行:
    python3 -m unittest tests.test_user_stores -v
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.stores import context, registry  # noqa: E402  # type: ignore[import-not-found]
from modules.system import settings_handler  # noqa: E402  # type: ignore[import-not-found]
from modules.system.auth_handler import (  # noqa: E402  # type: ignore[import-not-found]
    _SESSIONS,
    create_session,
    get_session,
    handle_post_login,
)
from modules.system.settings_handler import (  # noqa: E402  # type: ignore[import-not-found]
    add_user,
    get_settings,
    init_settings,
    save_settings,
    update_user,
)
from modules.system.users_handler import (  # noqa: E402  # type: ignore[import-not-found]
    handle_post_users,
    handle_put_users,
)

import app_handler  # noqa: E402  # type: ignore[import-not-found]
from storage import DATA_FILES  # noqa: E402  # type: ignore[import-not-found]

# 这几个 handler 没有类型注解(strict 模式下「调用未标注函数」会报 no-untyped-call)。
# 测试只关心 HTTP 层的返回内容,这里显式声明成 Any。
post_users: Any = handle_post_users
put_users: Any = handle_put_users
post_login: Any = handle_post_login


def _user(record: Any) -> Dict[str, Any]:
    """add_user / update_user 声明成 Optional —— 收窄成 dict 再用。"""
    return cast(Dict[str, Any], record)


def _sess(sess: Any) -> Dict[str, Any]:
    """get_session 返回 Optional —— 收窄成 dict 再用。"""
    return cast(Dict[str, Any], sess)


class FakeHandler:
    """模拟 BaseHTTPRequestHandler 的最小实现,捕获响应。"""

    def __init__(self, path: str, body: Optional[Dict[str, Any]] = None,
                 method: str = "POST") -> None:
        self.path = path
        self.command = method
        self.response_status: Optional[int] = None
        self.response_headers: Dict[str, str] = {}
        self.response_body = b""
        self.wfile = io.BytesIO()
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            self.rfile = io.BytesIO(raw)
            self.headers = {"Content-Length": str(len(raw))}
        else:
            self.rfile = io.BytesIO(b"")
            self.headers = {"Content-Length": "0"}

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


class UserStoreTestBase(unittest.TestCase):
    """基类:独立临时数据目录 + 已注册的门店(main / s002)。"""

    def setUp(self) -> None:
        self._prev_paths = app_handler.DATA_PATHS
        self._prev_sessions = dict(_SESSIONS)
        _SESSIONS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = paths
        for p in paths.values():
            p.write_text("[]", encoding="utf-8")
        # settings_handler 的目录取自 DATA_PATHS["readings"].parent → 本临时目录,
        # 所以用户表读写都在临时目录里,不会碰到真实数据。
        init_settings(self.data_dir)
        self._register_stores("main", "s002")
        context.clear_current_store()

    def tearDown(self) -> None:
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        _SESSIONS.clear()
        _SESSIONS.update(self._prev_sessions)
        self.tmp.cleanup()

    # ---- 辅助 ----

    def _register_stores(self, *ids: str) -> None:
        """往 settings.json 的门店注册表里登记几个门店。"""
        settings = get_settings()
        settings["stores"] = [
            {
                "id": sid,
                "name": f"门店{sid}",
                "code": "",
                "address": "",
                "active": True,
                "created_at": "2026-01-01T00:00:00",
            }
            for sid in ids
        ]
        save_settings(settings)

    def _post_users(self, body: Dict[str, Any]) -> FakeHandler:
        h = FakeHandler("/api/admin/users", body, "POST")
        post_users(h)
        return h

    def _put_users(self, uid: int, body: Dict[str, Any]) -> FakeHandler:
        h = FakeHandler(f"/api/admin/users?id={uid}", body, "PUT")
        put_users(h, "/api/admin/users")
        return h

    def _user_on_disk(self, username: str) -> Any:
        """从磁盘上的 settings.json 里取某个用户记录。"""
        for u in get_settings().get("users", []):
            if u.get("username") == username:
                return u
        return None


class TestUserStoreFields(UserStoreTestBase):
    """用户记录上的 all_stores / store_ids 字段。"""

    def test_add_user_admin_defaults_to_all_stores(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "boss", "pw123456", "老板", "admin"))
        self.assertTrue(u["all_stores"])
        self.assertEqual(u["store_ids"], [])

    def test_add_user_employee_defaults_to_no_stores(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "emp", "pw123456", "员工", "employee"))
        self.assertEqual(u["store_ids"], [])
        self.assertFalse(u["all_stores"])

    def test_add_user_accepts_store_ids(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "emp2", "pw123456", "员工2", "employee",
                           store_ids=["s002"]))
        self.assertEqual(u["store_ids"], ["s002"])

    def test_add_user_explicit_all_stores_false_beats_admin_default(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "boss2", "pw123456", "老板2", "admin", all_stores=False))
        self.assertFalse(u["all_stores"])

    def test_add_user_store_ids_none_becomes_empty_list(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "emp3", "pw123456", "员工3", "employee", store_ids=None))
        self.assertEqual(u["store_ids"], [])

    def test_update_user_changes_store_ids(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "emp4", "pw123456", "员工4", "employee"))
        updated = _user(update_user(users, u["id"], {"store_ids": ["s002", "main"]}))
        self.assertEqual(updated["store_ids"], ["s002", "main"])

    def test_update_user_changes_all_stores(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "boss3", "pw123456", "老板3", "admin"))
        updated = _user(update_user(users, u["id"], {"all_stores": False}))
        self.assertFalse(updated["all_stores"])

    def test_user_store_scope_reflects_update(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "emp5", "pw123456", "员工5", "employee"))
        self.assertEqual(registry.user_store_scope(u["id"], settings={"users": users}),
                         (False, []))
        update_user(users, u["id"], {"store_ids": ["s002"]})
        self.assertEqual(registry.user_store_scope(u["id"], settings={"users": users}),
                         (False, ["s002"]))


class TestRoleChangeScope(UserStoreTestBase):
    """改角色时 all_stores 必须跟着收敛(降级后不能还是「总部账号」)。"""

    def test_demotion_converges_all_stores_to_false(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "boss", "pw123456", "老板", "admin"))
        self.assertTrue(u["all_stores"])
        updated = _user(update_user(users, u["id"], {"role": "employee"}))
        self.assertFalse(updated["all_stores"])

    def test_demotion_keeps_explicitly_passed_all_stores(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "boss", "pw123456", "老板", "admin"))
        updated = _user(update_user(users, u["id"], {"role": "employee", "all_stores": True}))
        self.assertTrue(updated["all_stores"])

    def test_promotion_keeps_explicit_all_stores_false(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "emp", "pw123456", "员工", "employee"))
        updated = _user(update_user(users, u["id"], {"role": "admin"}))
        self.assertFalse(updated["all_stores"])

    def test_promotion_of_legacy_record_defaults_to_all_stores(self) -> None:
        # 老 settings.json 里的用户记录没有 all_stores 字段 → 升为 admin 时默认 True
        users: List[Dict[str, Any]] = [{
            "id": 7, "username": "old", "password": "x", "role": "employee",
            "name": "老用户", "enabled": True,
        }]
        updated = _user(update_user(users, 7, {"role": "admin"}))
        self.assertTrue(updated["all_stores"])

    def test_demoted_user_scope_is_restricted(self) -> None:
        users: List[Dict[str, Any]] = []
        u = _user(add_user(users, "boss", "pw123456", "老板", "admin"))
        update_user(users, u["id"], {"role": "supervisor"})
        self.assertEqual(registry.user_store_scope(u["id"], settings={"users": users}),
                         (False, []))


class TestUsersApiStoreValidation(UserStoreTestBase):
    """store_ids 里的门店必须真的存在。"""

    def test_post_users_accepts_known_store(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"], "all_stores": False,
        })
        self.assertTrue(h.parsed["ok"])
        self.assertEqual(h.parsed["user"]["store_ids"], ["s002"])
        self.assertFalse(h.parsed["user"]["all_stores"])

    def test_post_users_rejects_unknown_store(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s999"],
        })
        self.assertFalse(h.parsed["ok"])
        self.assertIn("s999", h.parsed["error"])

    def test_post_users_rejected_store_is_not_persisted(self) -> None:
        self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s999"],
        })
        self.assertIsNone(self._user_on_disk("emp"))

    def test_put_users_accepts_known_store(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"],
        })
        uid = h.parsed["user"]["id"]
        h2 = self._put_users(uid, {"store_ids": ["main"]})
        self.assertTrue(h2.parsed["ok"])
        self.assertEqual(h2.parsed["user"]["store_ids"], ["main"])

    def test_put_users_rejects_unknown_store(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"],
        })
        uid = h.parsed["user"]["id"]
        h2 = self._put_users(uid, {"store_ids": ["nope"]})
        self.assertFalse(h2.parsed["ok"])
        self.assertIn("nope", h2.parsed["error"])

    def test_put_users_rejected_store_is_not_persisted(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"],
        })
        uid = h.parsed["user"]["id"]
        self._put_users(uid, {"store_ids": ["nope"]})
        self.assertEqual(self._user_on_disk("emp")["store_ids"], ["s002"])


class TestUsersApiPersistence(UserStoreTestBase):
    """写盘失败必须报错 —— 报「成功」会让用户被锁在自己门店外面。"""

    def test_post_users_persists_store_ids(self) -> None:
        self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"], "all_stores": False,
        })
        rec = self._user_on_disk("emp")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["store_ids"], ["s002"])
        self.assertFalse(rec["all_stores"])

    def test_post_users_reports_save_failure(self) -> None:
        with mock.patch.object(settings_handler, "_save", side_effect=OSError("磁盘已满")):
            h = self._post_users({
                "username": "emp", "password": "pw123456", "name": "员工",
                "role": "employee", "store_ids": ["s002"],
            })
        self.assertFalse(h.parsed["ok"])
        self.assertTrue(h.parsed["error"])

    def test_post_users_detects_silent_write_loss(self) -> None:
        # _save 什么都不做 = 生产里「写失败但被 _save 吞掉」的样子
        with mock.patch.object(settings_handler, "_save", lambda data: None):
            h = self._post_users({
                "username": "emp", "password": "pw123456", "name": "员工",
                "role": "employee", "store_ids": ["s002"],
            })
        self.assertFalse(h.parsed["ok"])
        self.assertIsNone(self._user_on_disk("emp"))

    def test_put_users_persists_store_ids(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"],
        })
        uid = h.parsed["user"]["id"]
        self._put_users(uid, {"store_ids": ["main", "s002"]})
        self.assertEqual(self._user_on_disk("emp")["store_ids"], ["main", "s002"])

    def test_put_users_reports_save_failure(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"],
        })
        uid = h.parsed["user"]["id"]
        with mock.patch.object(settings_handler, "_save", side_effect=OSError("磁盘已满")):
            h2 = self._put_users(uid, {"store_ids": ["main"]})
        self.assertFalse(h2.parsed["ok"])
        self.assertTrue(h2.parsed["error"])

    def test_put_users_detects_silent_write_loss(self) -> None:
        h = self._post_users({
            "username": "emp", "password": "pw123456", "name": "员工",
            "role": "employee", "store_ids": ["s002"],
        })
        uid = h.parsed["user"]["id"]
        with mock.patch.object(settings_handler, "_save", lambda data: None):
            h2 = self._put_users(uid, {"store_ids": ["main"]})
        self.assertFalse(h2.parsed["ok"])
        self.assertEqual(self._user_on_disk("emp")["store_ids"], ["s002"])


class TestSessionStoreScope(UserStoreTestBase):
    """会话与登录返回里带上门店范围。"""

    def test_create_session_carries_store_scope(self) -> None:
        token = create_session({
            "id": 2, "username": "emp", "role": "employee", "name": "员工",
            "all_stores": False, "store_ids": ["s002"],
        })
        sess = _sess(get_session(token))
        self.assertFalse(sess["all_stores"])
        self.assertEqual(sess["store_ids"], ["s002"])

    def test_create_session_defaults_admin_to_all_stores(self) -> None:
        token = create_session({
            "id": 1, "username": "admin", "role": "admin", "name": "管理员",
        })
        sess = _sess(get_session(token))
        self.assertTrue(sess["all_stores"])
        self.assertEqual(sess["store_ids"], [])

    def test_create_session_defaults_employee_to_restricted(self) -> None:
        token = create_session({
            "id": 3, "username": "emp", "role": "employee", "name": "员工",
        })
        sess = _sess(get_session(token))
        self.assertFalse(sess["all_stores"])
        self.assertEqual(sess["store_ids"], [])

    def test_login_response_includes_store_scope(self) -> None:
        settings = get_settings()
        users = settings["users"]
        created = _user(add_user(users, "login_emp", "pw123456", "员工", "employee",
                                 store_ids=["s002"]))
        self.assertNotIn("error", created)
        save_settings(settings)

        h = FakeHandler("/api/auth/login",
                        {"username": "login_emp", "password": "pw123456"}, "POST")
        post_login(h)
        self.assertTrue(h.parsed["ok"])
        self.assertFalse(h.parsed["user"]["all_stores"])
        self.assertEqual(h.parsed["user"]["store_ids"], ["s002"])
