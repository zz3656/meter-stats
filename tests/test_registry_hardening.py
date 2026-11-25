"""门店注册表加固测试(标准库 unittest,零依赖)。

复核修复轮 3 的用例 —— 每一条都盯住一个**具体的实现细节**,
而不是「跑起来不报错」:

- 建目录**半失败**(目录建了、文件写了、然后抛错)→ 不能留下孤儿目录;
  调用前就存在的门店目录**绝不能删**(里面可能有真实数据)
- add_store() / ensure_default_store() 返回的必须是**深**拷贝 ——
  嵌套字段也要隔离(浅拷贝只隔离标量,上一轮的用例没有区分力)
- DEFAULT_CONFIG 是模块级常量 → 调用方改返回值不能污染它
- 回滚必须**重新读盘合并** → 不能把过期的内存快照整份写回
  (settings_handler._load() 不持锁,整份写回会吞掉并发请求的改动)
- 回滚失败时,建目录异常与回滚异常的类型与消息**都要**带出来
- DELETE /api/admin/users 写盘失败必须报错,不能报 ok:true

运行:
    python3 -m unittest tests.test_registry_hardening -v
"""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.stores import config, context, registry  # noqa: E402  # type: ignore[import-not-found]
from modules.system import settings_handler  # noqa: E402  # type: ignore[import-not-found]
from modules.system.users_handler import handle_delete_users  # noqa: E402  # type: ignore[import-not-found]

import app_handler  # noqa: E402  # type: ignore[import-not-found]
import storage  # noqa: E402  # type: ignore[import-not-found]
from storage import DATA_FILES  # noqa: E402  # type: ignore[import-not-found]

# handle_delete_users 没有类型注解(strict 模式下「调用未标注函数」会报 no-untyped-call)
delete_users: Any = handle_delete_users


class FakeHandler:
    """模拟 BaseHTTPRequestHandler 的最小实现,捕获响应。"""

    def __init__(self, path: str, method: str = "DELETE") -> None:
        self.path = path
        self.command = method
        self.response_status: Optional[int] = None
        self.response_headers: Dict[str, str] = {}
        self.response_body = b""
        self.wfile = io.BytesIO()
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


class RegistryHardeningBase(unittest.TestCase):
    """基类:独立临时数据目录 —— 测试绝不碰真实数据目录。"""

    def setUp(self) -> None:
        self._prev_paths = app_handler.DATA_PATHS
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = paths
        for p in paths.values():
            p.write_text("[]", encoding="utf-8")
        context.clear_current_store()

    def tearDown(self) -> None:
        # 必须还原 DATA_PATHS —— 否则全局变量会一直指着已删除的临时目录
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        self.tmp.cleanup()

    def _settings(self) -> Dict[str, Any]:
        """初始化并读回 settings.json(落在临时目录里)。"""
        settings_handler.init_settings(self.data_dir)
        return cast(Dict[str, Any], settings_handler.get_settings())

    def _on_disk(self) -> Dict[str, Any]:
        raw = (self.data_dir / "settings.json").read_text(encoding="utf-8")
        return cast(Dict[str, Any], json.loads(raw))

    def _user_on_disk(self, username: str) -> Any:
        for u in settings_handler.get_settings().get("users") or []:
            if u.get("username") == username:
                return u
        return None


class TestOrphanStoreDirCleanup(RegistryHardeningBase):
    """建目录失败 → 不能留下孤儿目录;调用前就存在的目录绝不能删。"""

    def test_add_store_cleans_up_orphan_dir_when_creation_half_fails(self) -> None:
        """半失败(目录建了、文件写了、然后抛错)→ 目录必须被清理干净。

        上一轮的实现只说「目录不删(万一里面有数据)」—— 顾虑是对的,
        但它把「本次调用新建的空目录」和「调用前就存在的目录」混为一谈。
        这里的场景是:目录是**本次调用新建的**,里面只有一个刚写的空文件,
        调用失败后它就是纯垃圾 —— 留着会让 multi_store_layout() 变 True,
        门店闸开始按多店布局拦截,而注册表里根本没有这家店。
        """

        def half_create(store_id: str, name: str = "") -> None:
            d = registry.context_store_dir(store_id)
            d.mkdir(parents=True, exist_ok=True)
            (d / "readings.json").write_text("[]", encoding="utf-8")
            raise OSError("磁盘满了")

        self._settings()
        with mock.patch.object(registry, "_create_store_files", side_effect=half_create), \
                self.assertRaises(OSError):
            registry.add_store("s002", "国贸店")

        store_dir = self.data_dir / "stores" / "s002"
        self.assertFalse(store_dir.exists(), f"留下了孤儿目录: {store_dir}")

    def test_add_store_keeps_preexisting_store_dir_on_failure(self) -> None:
        """调用前就存在的门店目录绝不能被删 —— 里面可能有真实数据。

        典型场景:门店被删过(注册表条目没了,数据目录还在),又用同样的 ID
        重建 → 目录是旧的,里面有真实数据。这次建店失败不能把老数据删了。
        """
        store_dir = self.data_dir / "stores" / "s002"
        store_dir.mkdir(parents=True)
        keep = store_dir / "readings.json"
        keep.write_text('[{"value": 1}]', encoding="utf-8")

        def half_create(store_id: str, name: str = "") -> None:
            d = registry.context_store_dir(store_id)
            (d / "extra.json").write_text("[]", encoding="utf-8")
            raise OSError("磁盘满了")

        self._settings()
        with mock.patch.object(registry, "_create_store_files", side_effect=half_create), \
                self.assertRaises(OSError):
            registry.add_store("s002", "国贸店")

        # 目录必须还在
        self.assertTrue(store_dir.is_dir())
        # 调用前就有的文件内容必须一字不差
        self.assertEqual(keep.read_text(encoding="utf-8"), '[{"value": 1}]')
        # 本次调用自己新建的文件要清掉(只清理「本次新建的」)
        self.assertFalse((store_dir / "extra.json").exists())

    def test_add_store_cleanup_does_not_mask_original_error(self) -> None:
        """清理本身失败不能掩盖原始异常 —— 原始异常才是根因。"""
        self._settings()

        def half_create(store_id: str, name: str = "") -> None:
            d = registry.context_store_dir(store_id)
            d.mkdir(parents=True, exist_ok=True)
            (d / "readings.json").write_text("[]", encoding="utf-8")
            raise OSError("磁盘满了")

        with mock.patch.object(registry, "_create_store_files", side_effect=half_create), \
                mock.patch.object(registry, "_cleanup_store_dir",
                                  side_effect=OSError("清理也失败了")), \
                self.assertRaises(OSError) as cm:
            registry.add_store("s002", "国贸店")
        self.assertIn("磁盘满了", str(cm.exception))


class TestCreateStoreFilesCleanup(RegistryHardeningBase):
    """_create_store_files() 自己的回滚契约。

    它知道自己新建了哪些文件 —— 失败时只删这些,调用前就存在的目录
    与文件一律不动。
    """

    def test_create_store_files_cleans_up_its_own_partial_writes(self) -> None:
        """写到一半失败 → 本次新建的文件必须删掉,目录也不能留。"""
        self._settings()
        original_save = storage.save_json
        calls: List[int] = []

        def flaky_save(path: Path, data: Any) -> None:
            calls.append(1)
            if len(calls) >= 3:
                raise OSError("磁盘满了")
            original_save(path, data)

        with mock.patch.object(storage, "save_json", side_effect=flaky_save), \
                self.assertRaises(OSError):
            registry._create_store_files("s002", "国贸店")

        store_dir = self.data_dir / "stores" / "s002"
        self.assertFalse(store_dir.exists(), f"留下了半成品目录: {store_dir}")

    def test_create_store_files_keeps_preexisting_dir_and_files(self) -> None:
        """调用前就存在的目录与文件 → 失败时也绝不能删。"""
        self._settings()
        store_dir = self.data_dir / "stores" / "s002"
        store_dir.mkdir(parents=True)
        keep = store_dir / "readings.json"
        keep.write_text('[{"value": 1}]', encoding="utf-8")

        # store.json 写失败 → 前面几个数据文件已经建好了
        with mock.patch.object(config, "write_store_config",
                               side_effect=OSError("磁盘满了")), self.assertRaises(OSError):
            registry._create_store_files("s002", "国贸店")

        self.assertTrue(store_dir.is_dir())
        self.assertEqual(keep.read_text(encoding="utf-8"), '[{"value": 1}]')
        # 本次新建的那些数据文件要删掉
        for fname in DATA_FILES.values():
            if fname == "readings.json":
                continue
            self.assertFalse((store_dir / fname).exists(), fname)


class TestRegistryDeepCopyContract(RegistryHardeningBase):
    """注册表交出去的门店记录必须是**深**拷贝。"""

    def test_add_store_returns_deep_copy_isolates_nested_fields(self) -> None:
        """add_store() 返回值里的嵌套对象不能串回注册表本体。

        上一轮的用例只改了标量 name —— 浅拷贝(dict(store))一样隔离标量,
        所以那条断言对深/浅拷贝毫无区分力(改成 dict(store) 全绿)。
        这里在**登记之后**往门店条目注入一个嵌套字段,再改**返回值**里的
        嵌套对象 → 浅拷贝会串,断言会红。

        断言对象是**注册表本体**(内存里那份 st),不是盘上的快照 ——
        盘上的内容在注入时就写好了,返回值之后再改根本影响不到它,
        那样断言就恒真了。
        """
        self._settings()
        original_persist = registry._persist
        captured: Dict[str, Any] = {}

        def persist_with_tags(st: Dict[str, Any]) -> None:
            captured["st"] = st
            # 此刻 st["stores"][-1] 与 add_store() 里的 store 是同一个对象
            st["stores"][-1]["tags"] = ["a"]
            original_persist(st)

        with mock.patch.object(registry, "_persist", side_effect=persist_with_tags):
            store = registry.add_store("s002", "国贸店")

        self.assertEqual(store["tags"], ["a"])
        store["tags"].append("b")

        # 注册表本体不能被返回值改坏
        registry_body = captured["st"]["stores"][-1]
        self.assertEqual(registry_body["tags"], ["a"],
                         "返回值里的嵌套对象串回了注册表本体(浅拷贝?)")
        # 盘上的那份也不能被改坏
        on_disk = self._on_disk()
        self.assertEqual(on_disk["stores"][-1]["tags"], ["a"])

    def test_ensure_default_store_returns_deep_copy_isolates_nested_fields(self) -> None:
        """ensure_default_store() 返回的必须是深拷贝(docstring 承诺过)。

        改深拷贝之前没有任何用例断言这一点 —— 把 return copy.deepcopy(store)
        改成 return store 全绿。
        """
        settings = self._settings()
        registry.ensure_default_store(settings)
        settings["stores"][0]["tags"] = ["a"]

        store = registry.ensure_default_store(settings)
        store["tags"].append("b")

        self.assertEqual(settings["stores"][0]["tags"], ["a"],
                         "ensure_default_store() 返回的不是深拷贝")

    def test_ensure_default_store_still_mutates_settings_in_place(self) -> None:
        """原地修改语义必须保住 —— Task 3 的迁移逻辑依赖它。

        迁移逻辑用「调用前取快照 + 调用后比对」判定注册表是否真的落盘,
        靠的就是 ensure_default_store() 把 stores[] 直接改到传入的 dict 上。
        """
        settings = self._settings()
        self.assertNotIn("stores", settings)
        registry.ensure_default_store(settings)
        self.assertEqual([s["id"] for s in settings["stores"]], ["main"])


class TestStoreConfigConstantIsolation(RegistryHardeningBase):
    """模块级常量不能被调用方改坏。"""

    def test_default_config_is_not_mutated_by_callers(self) -> None:
        """DEFAULT_CONFIG 必须与 DEFAULT_METERS 一样是只读的。

        get_store_prices() 里把 out = copy.deepcopy(DEFAULT_CONFIG) 改回
        out = DEFAULT_CONFIG,调用方往返回值里塞的键就会**永久污染模块级常量**
        —— 跨请求泄漏(下一个请求读到上一个请求塞进去的键)。
        """
        before = copy.deepcopy(config.DEFAULT_CONFIG)

        def restore() -> None:
            config.DEFAULT_CONFIG.clear()
            config.DEFAULT_CONFIG.update(before)

        self.addCleanup(restore)

        context.set_current_store("s999")
        prices = config.get_store_prices()
        prices["electricity_price"] = 0.0
        prices["injected"] = True

        self.assertEqual(config.DEFAULT_CONFIG["electricity_price"], 0.9)
        self.assertNotIn("injected", config.DEFAULT_CONFIG)


class TestRollbackSemantics(RegistryHardeningBase):
    """建目录失败后的回滚。"""

    def test_rollback_keeps_concurrent_settings_changes(self) -> None:
        """回滚必须**重新读盘合并** —— 不能把过期的内存快照整份写回。

        settings_handler._load() 不持锁(只有 _save() 持锁)。add_store() 从
        读盘到回滚之间隔了一次建目录的 IO —— 期间若有并发请求改了
        settings.json,那份过期快照会把那次变更**整份覆盖丢失**。
        """
        self._settings()

        def half_create(store_id: str, name: str = "") -> None:
            # 模拟并发:别的请求在这期间改了 settings.json
            st = settings_handler.get_settings()
            users = st.get("users") or []
            users.append({
                "id": 99, "username": "concurrent", "password": "x",
                "role": "employee", "name": "并发用户", "enabled": True,
            })
            st["users"] = users
            settings_handler.save_settings(st)
            raise OSError("磁盘满了")

        with mock.patch.object(registry, "_create_store_files", side_effect=half_create), \
                self.assertRaises(OSError):
            registry.add_store("s002", "国贸店")

        on_disk = self._on_disk()
        usernames = [u["username"] for u in on_disk.get("users") or []]
        self.assertIn("concurrent", usernames,
                      "并发请求对 settings.json 的改动被回滚覆盖丢失了")
        ids = [s["id"] for s in on_disk.get("stores") or []]
        self.assertNotIn("s002", ids, "失败的门店必须从注册表里撤掉")

    def test_rollback_failure_reports_both_exceptions(self) -> None:
        """回滚失败时,两个异常的类型与消息都要带出来。

        原始异常(建目录失败)挂在 __cause__ 上 ✓,但回滚失败的原因只拼在
        message 里 —— 程序化区分「是不是回滚失败」只能去解析字符串。
        """
        self._settings()
        calls: List[int] = []

        def flaky_persist(st: Dict[str, Any]) -> None:
            calls.append(1)
            if len(calls) == 1:
                return  # 第一次(登记新店)成功
            raise RuntimeError("模拟回滚落盘失败")

        with mock.patch.object(registry, "_persist", side_effect=flaky_persist), \
                mock.patch.object(registry, "_create_store_files",
                                  side_effect=OSError("磁盘满了")), \
                self.assertRaises(RuntimeError) as cm:
            registry.add_store("s002", "国贸店")

        msg = str(cm.exception)
        self.assertIn("OSError", msg)
        self.assertIn("磁盘满了", msg)
        self.assertIn("RuntimeError", msg)
        self.assertIn("模拟回滚落盘失败", msg)
        # 原始异常不能丢
        self.assertIsInstance(cm.exception.__cause__, OSError)
        # 回滚失败的异常也在异常链上(__context__)—— 不用去解析 message 文本
        self.assertIsInstance(cm.exception.__context__, RuntimeError)
        self.assertIn("模拟回滚落盘失败", str(cm.exception.__context__))


class TestDeleteUserPersistence(RegistryHardeningBase):
    """DELETE /api/admin/users 的写盘校验(与 POST/PUT 同一套)。"""

    def _make_user(self, username: str = "emp") -> int:
        st = settings_handler.get_settings()
        users = st.get("users") or []
        rec = settings_handler.add_user(users, username, "pw123456", "员工", "employee",
                                        store_ids=["s002"])
        assert rec is not None
        st["users"] = users
        settings_handler.save_settings(st)
        return int(rec["id"])

    def test_delete_users_persists_deletion(self) -> None:
        """正常删除 → ok:true,且用户确实从盘上消失。"""
        self._settings()
        uid = self._make_user()

        h = FakeHandler(f"/api/admin/users?id={uid}")
        delete_users(h, "/api/admin/users")

        self.assertTrue(h.parsed["ok"])
        self.assertIsNone(self._user_on_disk("emp"))

    def test_delete_users_detects_silent_write_loss(self) -> None:
        """写盘失败(被 _save 吞掉)→ 绝不能报 ok:true。

        _save() 会吞掉所有异常(只往 stderr 打一行警告),写失败时调用方
        会以为删除成功 —— 用户还在盘上,权限与门店归属全都还在。
        """
        self._settings()
        uid = self._make_user()

        with mock.patch.object(settings_handler, "_save", lambda data: None):
            h = FakeHandler(f"/api/admin/users?id={uid}")
            delete_users(h, "/api/admin/users")

        self.assertFalse(h.parsed["ok"], "写盘失败却报成功")
        self.assertTrue(h.parsed["error"])
        self.assertIsNotNone(self._user_on_disk("emp"), "写盘失败,用户却消失了")

    def test_delete_users_reports_save_failure(self) -> None:
        """写盘直接抛异常 → 必须报错,不能报成功。"""
        self._settings()
        uid = self._make_user()

        with mock.patch.object(settings_handler, "_save", side_effect=OSError("磁盘已满")):
            h = FakeHandler(f"/api/admin/users?id={uid}")
            delete_users(h, "/api/admin/users")

        self.assertFalse(h.parsed["ok"])
        self.assertTrue(h.parsed["error"])


if __name__ == "__main__":
    unittest.main()
