"""分店功能回归测试(标准库 unittest,零依赖)。

覆盖:
- 门店上下文:当前门店读写、线程隔离
- 按门店路径解析:单店布局原样返回 DATA_PATHS;多店布局指向 stores/<id>/
- 默认店在迁移前可回退顶层旧文件;分店不回退(否则会读到总店数据)
- 路径解析失败时必须报错,绝不静默回退到真实用户数据目录
- 崩溃恢复:总店可回退顶层 backup/;分店绝不能拿总店备份来填(串店)
- 报表缓存按门店隔离(总店的月报不能被分店命中)
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.stores import config, context, registry  # noqa: E402

import app_handler  # noqa: E402
import routing  # noqa: E402
from storage import DATA_FILES  # noqa: E402


class StoreTestBase(unittest.TestCase):
    """基类:独立临时数据目录 + 关闭鉴权开关(业务回归用)。"""

    def setUp(self):
        self._prev_enforce = routing.ENFORCE_AUTH
        self._prev_paths = app_handler.DATA_PATHS
        routing.ENFORCE_AUTH = False
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        context.clear_current_store()

    def tearDown(self):
        routing.ENFORCE_AUTH = self._prev_enforce
        # 必须还原 DATA_PATHS —— 否则全局变量会一直指着已删除的临时目录
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        self.tmp.cleanup()


class TestStoreContext(StoreTestBase):
    """门店上下文本身。"""

    def test_default_store_id_is_main(self):
        self.assertEqual(context.DEFAULT_STORE_ID, "main")

    def test_set_and_get_current_store(self):
        context.set_current_store("s002")
        self.assertEqual(context.get_current_store(), "s002")

    def test_get_current_store_defaults_to_main(self):
        context.clear_current_store()
        self.assertEqual(context.get_current_store(), "main")

    def test_current_store_is_thread_local(self):
        context.set_current_store("s002")
        seen = {}

        def worker():
            seen["value"] = context.get_current_store()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        # 子线程没有继承当前门店 → 回到默认店
        self.assertEqual(seen["value"], "main")
        # 主线程不受影响
        self.assertEqual(context.get_current_store(), "s002")

    def test_base_data_dir_follows_data_paths(self):
        self.assertEqual(context.base_data_dir(), self.data_dir)

    def test_store_dir_is_under_stores_root(self):
        self.assertEqual(
            context.store_dir("s002"),
            self.data_dir / "stores" / "s002",
        )

    def test_base_data_dir_raises_when_data_paths_not_initialized(self):
        """DATA_PATHS 未初始化 → 明确报错,绝不猜一个目录。

        回退到 storage.get_data_dir() 会静默落到真实用户数据目录
        (用户表、密码哈希、NAS 凭据、备份目录),比直接报错危险得多。
        """
        app_handler.DATA_PATHS = {}
        with self.assertRaises(RuntimeError):
            context.base_data_dir()

    def test_base_data_dir_never_calls_storage_get_data_dir(self):
        """路径解析绝不许触达 storage.get_data_dir()。

        get_data_dir() 不是纯查询:它会 mkdir、可能迁移老目录的数据并打日志。
        """
        import storage

        called = []
        original = storage.get_data_dir

        def fake_get_data_dir() -> Path:
            called.append(1)
            return Path("/should-not-be-used")

        storage.get_data_dir = fake_get_data_dir
        try:
            # 未初始化 → 报错,且不调用 get_data_dir()
            app_handler.DATA_PATHS = {}
            with self.assertRaises(RuntimeError):
                context.base_data_dir()
            # 正常路径 → 直接用 DATA_PATHS,同样不调用 get_data_dir()
            app_handler.DATA_PATHS = self.paths
            self.assertEqual(context.base_data_dir(), self.data_dir)
            self.assertEqual(called, [])
        finally:
            storage.get_data_dir = original


class TestStorePaths(StoreTestBase):
    """按门店解析数据路径。"""

    def test_single_store_layout_returns_data_paths_unchanged(self):
        """单店布局(没有 stores/ 目录)→ 原样返回 DATA_PATHS。

        这是 169 个存量测试能继续通过的关键。
        """
        paths = context.current_store_paths()
        self.assertEqual(paths["readings"], self.data_dir / "readings.json")
        self.assertEqual(paths["charges"], self.data_dir / "charges.json")

    def test_multi_store_layout_points_into_store_dir(self):
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        context.set_current_store("s002")
        paths = context.current_store_paths()
        self.assertEqual(
            paths["readings"],
            self.data_dir / "stores" / "s002" / "readings.json",
        )

    def test_default_store_falls_back_to_legacy_top_level_file(self):
        """迁移前 / 迁移失败:默认店可回退顶层旧文件(读双写单)。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        paths = context.current_store_paths()
        self.assertEqual(paths["readings"], self.data_dir / "readings.json")

    def test_branch_store_never_falls_back_to_top_level(self):
        """分店不回退顶层 —— 否则分店会读到总店数据。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        context.set_current_store("s002")
        paths = context.current_store_paths()
        self.assertEqual(
            paths["readings"],
            self.data_dir / "stores" / "s002" / "readings.json",
        )

    def test_resolve_store_path_is_scoped_by_store(self):
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        p = context.resolve_store_path("readings", "s002")
        self.assertEqual(p, self.data_dir / "stores" / "s002" / "readings.json")

    def test_resolve_store_path_single_store_uses_data_paths(self):
        """单店布局 → 直接用 DATA_PATHS[model](与 current_store_paths() 同一来源)。"""
        self.assertEqual(
            context.resolve_store_path("readings", "main"),
            self.data_dir / "readings.json",
        )
        self.assertEqual(
            context.resolve_store_path("charges", "main"),
            self.data_dir / "charges.json",
        )

    def test_resolve_store_path_filename_follows_model(self):
        """文件名由 DATA_FILES[model] 推导 —— 不能传错文件名就返回错文件。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        self.assertEqual(
            context.resolve_store_path("charges", "s002"),
            self.data_dir / "stores" / "s002" / "charges.json",
        )
        self.assertEqual(
            context.resolve_store_path("readings", "s002"),
            self.data_dir / "stores" / "s002" / "readings.json",
        )

    def test_resolve_store_path_rejects_stale_three_arg_call(self):
        """旧的三参数签名(自带 filename)必须消失 —— 否则又会有两套文件名来源。"""
        with self.assertRaises(TypeError):
            context.resolve_store_path(  # type: ignore[call-arg]
                "readings", "s002", "readings.json"
            )


class TestHandlerStoreScoping(StoreTestBase):
    """CRUD handler 自动按当前门店读写(不改任何业务 handler)。"""

    def test_readings_written_to_current_store(self):
        from modules._base import get_data_paths

        from storage import load_json

        (self.data_dir / "stores" / "main").mkdir(parents=True)
        (self.data_dir / "stores" / "s002").mkdir(parents=True)
        context.set_current_store("s002")

        paths = get_data_paths()
        self.assertEqual(
            paths["readings"],
            self.data_dir / "stores" / "s002" / "readings.json",
        )
        # 直接写一次,验证落到分店目录
        from storage import save_json
        save_json(paths["readings"], [{"date": "2026-11-25", "hall": 1.0}])
        saved = load_json(self.data_dir / "stores" / "s002" / "readings.json")
        self.assertEqual(len(saved), 1)
        # 总店目录不应被创建
        self.assertFalse((self.data_dir / "stores" / "main" / "readings.json").exists())


class TestStoreBackupRecovery(StoreTestBase):
    """门店数据的崩溃恢复。

    顶层 backup/ 里存的是**总店**的数据,只能回退给总店自己;
    分店绝不能拿总店快照来填(那是串店)。
    """

    def _write_backup(self, day: str, filename: str, data) -> None:
        d = self.data_dir / "backup" / day
        d.mkdir(parents=True)
        (d / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_main_store_recovers_from_top_level_backup(self):
        """总店(stores/main/)损坏 → 可以从顶层 backup/ 恢复。

        顶层 backup/ 里存的就是总店数据(backup_data() 只复制顶层目录的文件),
        默认店 main 就是总店,所以这条回退是安全的。
        """
        import storage

        payload = [{"date": "2026-01-01", "hall": 1.0}]
        self._write_backup("20260101", "readings.json", payload)
        store = self.data_dir / "stores" / "main"
        store.mkdir(parents=True)
        target = store / "readings.json"
        target.write_text("{损坏", encoding="utf-8")

        self.assertEqual(storage.load_json(target, []), payload)
        # 恢复后文件被写回原位
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)

    def test_top_level_file_still_recovers_from_own_backup(self):
        """单店布局下顶层文件仍从自己的 backup/ 恢复(不回归)。"""
        import storage

        payload = [{"date": "2026-01-01", "hall": 2.0}]
        self._write_backup("20260101", "readings.json", payload)
        target = self.data_dir / "readings.json"
        target.write_text("{损坏", encoding="utf-8")

        self.assertEqual(storage.load_json(target, []), payload)

    def test_branch_store_never_recovers_from_top_level_backup(self):
        """分店绝不能从顶层 backup/ 恢复 —— 那是总店的数据。

        顶层备份里存的是总店快照,门店文件在 stores/<id>/ 下,顶层备份里
        根本没有分店的文件。按文件名匹配会把总店内容写进分店 —— 串店。
        """
        import storage

        hq_payload = [{"date": "2026-01-01", "hall": 999.0, "_store": "HQ(总店)"}]
        self._write_backup("20260101", "readings.json", hq_payload)
        store = self.data_dir / "stores" / "s002"
        store.mkdir(parents=True)
        target = store / "readings.json"
        target.write_text("{损坏", encoding="utf-8")

        # 不恢复 → 返回默认值
        self.assertEqual(storage.load_json(target, []), [])
        # 分店文件绝不能被总店数据覆盖
        self.assertEqual(target.read_text(encoding="utf-8"), "{损坏")
        self.assertNotIn("总店", target.read_text(encoding="utf-8"))

    def test_missing_branch_store_file_is_not_restored_from_top_level_backup(self):
        """分店文件整个丢失 → 也不能拿总店的备份来填。"""
        import storage

        hq_payload = [{"date": "2026-01-02", "hall": 3.0, "_store": "HQ(总店)"}]
        self._write_backup("20260102", "charges.json", hq_payload)
        store = self.data_dir / "stores" / "s002"
        store.mkdir(parents=True)

        self.assertEqual(storage.load_json(store / "charges.json", []), [])
        # 分店目录里不应该凭空多出总店的备份文件
        self.assertFalse((store / "charges.json").exists())

    def test_branch_store_prefers_its_own_backup(self):
        """门店自己的 backup/ 优先 —— 恢复源必须是本门店的数据。"""
        import storage

        own = [{"date": "2026-02-01", "hall": 11.0}]
        hq = [{"date": "2026-01-01", "hall": 999.0, "_store": "HQ(总店)"}]
        self._write_backup("20260101", "readings.json", hq)
        store = self.data_dir / "stores" / "s002"
        store.mkdir(parents=True)
        own_day = store / "backup" / "20260201"
        own_day.mkdir(parents=True)
        (own_day / "readings.json").write_text(
            json.dumps(own, ensure_ascii=False), encoding="utf-8"
        )
        target = store / "readings.json"
        target.write_text("{损坏", encoding="utf-8")

        self.assertEqual(storage.load_json(target, []), own)


class TestReportCacheStoreScoping(StoreTestBase):
    """报表缓存必须带门店维度 —— 否则总店的月报会被分店命中。"""

    # 两组不同的抄表数据:总店用 A,分店用 B
    READINGS_A = [
        {"date": "2026-06-01", "hall": 100.0, "fire": 0, "private_room": 0, "ac": 0},
        {"date": "2026-06-05", "hall": 80.0, "fire": 0, "private_room": 0, "ac": 0},
    ]
    READINGS_B = [
        {"date": "2026-06-01", "hall": 200.0, "fire": 0, "private_room": 0, "ac": 0},
        {"date": "2026-06-05", "hall": 40.0, "fire": 0, "private_room": 0, "ac": 0},
    ]

    def setUp(self):
        super().setUp()
        from report import invalidate_report_cache
        invalidate_report_cache()

    def tearDown(self):
        from report import invalidate_report_cache
        invalidate_report_cache()
        super().tearDown()

    def test_monthly_report_cache_does_not_leak_across_stores(self):
        """同一月份:总店先算 → 分店再算,必须重新计算,不能命中总店缓存。"""
        from report import calculate_monthly_report

        context.set_current_store("main")
        r_main = calculate_monthly_report(self.READINGS_A, [], "2026-06")
        context.set_current_store("s002")
        r_s002 = calculate_monthly_report(self.READINGS_B, [], "2026-06")
        self.assertNotEqual(
            r_main["summary"]["total_kwh"],
            r_s002["summary"]["total_kwh"],
        )

    def test_monthly_report_cache_still_hits_within_same_store(self):
        """同一门店重复请求仍然命中缓存(不能把缓存改没了)。"""
        from report import calculate_monthly_report

        context.set_current_store("s002")
        r1 = calculate_monthly_report(self.READINGS_A, [], "2026-06")
        r2 = calculate_monthly_report(self.READINGS_B, [], "2026-06")
        self.assertIs(r1, r2)  # 命中缓存 → 返回同一个对象

    def test_yearly_report_cache_does_not_leak_across_stores(self):
        """年报缓存同样要带门店维度。"""
        from report import calculate_yearly_report

        context.set_current_store("main")
        y_main = calculate_yearly_report(self.READINGS_A, [], "2026")
        context.set_current_store("s002")
        y_s002 = calculate_yearly_report(self.READINGS_B, [], "2026")
        self.assertNotEqual(y_main["year_total_kwh"], y_s002["year_total_kwh"])

    def test_report_cache_stats_expose_store_and_month(self):
        """管理端缓存统计:month 字段保持原样,另加 store 字段。"""
        from report import calculate_monthly_report, get_report_cache_stats

        context.set_current_store("s002")
        calculate_monthly_report(self.READINGS_A, [], "2026-06")
        stats = get_report_cache_stats()
        self.assertEqual(stats["size"], 1)
        self.assertEqual(stats["entries"][0]["store"], "s002")
        self.assertEqual(stats["entries"][0]["month"], "2026-06")


class TestStoreRegistry(StoreTestBase):
    """门店注册表。"""

    def _settings(self) -> dict[str, Any]:
        from modules.system.settings_handler import get_settings, init_settings
        init_settings(self.data_dir)
        return get_settings()

    def test_ensure_default_store_creates_main(self) -> None:
        settings = self._settings()
        store = registry.ensure_default_store(settings)
        self.assertEqual(store["id"], "main")
        self.assertEqual(store["name"], "总店")
        self.assertEqual(len(registry.list_stores(settings)), 1)

    def test_ensure_default_store_is_idempotent(self) -> None:
        settings = self._settings()
        registry.ensure_default_store(settings)
        registry.ensure_default_store(settings)
        self.assertEqual(len(registry.list_stores(settings)), 1)

    def test_add_store_registers_and_creates_directory(self) -> None:
        settings = self._settings()
        store = registry.add_store("s002", "国贸店", code="B002", settings=settings)
        self.assertEqual(store["name"], "国贸店")
        self.assertTrue((self.data_dir / "stores" / "s002").is_dir())
        self.assertEqual(len(registry.list_stores(settings)), 2)

    def test_add_store_rejects_duplicate_id(self) -> None:
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        with self.assertRaises(ValueError):
            registry.add_store("s002", "重复店", settings=settings)

    def test_add_store_rejects_invalid_id(self) -> None:
        settings = self._settings()
        with self.assertRaises(ValueError):
            registry.add_store("../evil", "越权店", settings=settings)

    def test_delete_store_cannot_delete_default(self) -> None:
        settings = self._settings()
        registry.ensure_default_store(settings)
        self.assertFalse(registry.delete_store("main", settings=settings))
        self.assertIsNotNone(registry.get_store("main", settings=settings))

    def test_delete_store_removes_branch(self) -> None:
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        self.assertTrue(registry.delete_store("s002", settings=settings))
        self.assertIsNone(registry.get_store("s002", settings=settings))

    def test_update_store_changes_name(self) -> None:
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        updated = registry.update_store("s002", {"name": "国贸分店"}, settings=settings)
        self.assertEqual(updated["name"], "国贸分店")

    def test_update_store_rejects_empty_name(self) -> None:
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        with self.assertRaises(ValueError):
            registry.update_store("s002", {"name": "   "}, settings=settings)

    def test_user_store_scope_reads_all_stores_flag(self) -> None:
        settings = self._settings()
        users = settings.get("users", [])
        users[0]["all_stores"] = True
        scope = registry.user_store_scope(users[0]["id"], settings=settings)
        self.assertIsNotNone(scope)
        assert scope is not None  # mypy:assertIsNotNone 不做类型收窄
        self.assertTrue(scope[0])

    def test_user_store_scope_returns_none_for_unknown_user(self) -> None:
        settings = self._settings()
        self.assertIsNone(registry.user_store_scope(999999, settings=settings))

    # --- 以下为简报用例未覆盖、但属于本任务明确要求的行为 ---

    def test_add_store_creates_data_files_and_store_json(self) -> None:
        """分店建好就要能用:6 个空数据文件 + 默认 store.json 都要落盘。"""
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        store_dir = self.data_dir / "stores" / "s002"
        for fname in DATA_FILES.values():
            p = store_dir / fname
            self.assertTrue(p.exists(), fname)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), [])
        cfg = json.loads((store_dir / "store.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["id"], "s002")
        self.assertEqual(cfg["name"], "国贸店")
        self.assertEqual(len(cfg["meters"]), 4)

    def test_add_store_persists_to_settings_file(self) -> None:
        """不传 settings 时,改动必须落回全局 settings.json。"""
        self._settings()
        registry.add_store("s002", "国贸店")
        on_disk = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in on_disk["stores"]], ["main", "s002"])

    def test_add_store_rejects_empty_name(self) -> None:
        settings = self._settings()
        with self.assertRaises(ValueError):
            registry.add_store("s002", "   ", settings=settings)

    def test_add_store_always_registers_default_store(self) -> None:
        """总店必须始终在注册表里 —— 挂分店不能把总店挤掉。"""
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        self.assertIsNotNone(registry.get_store("main", settings=settings))
        self.assertEqual(registry.list_stores(settings)[0]["id"], "main")

    def test_is_valid_store_id_blocks_path_traversal(self) -> None:
        self.assertTrue(registry.is_valid_store_id("s002"))
        self.assertTrue(registry.is_valid_store_id("Main_Store-1"))
        self.assertFalse(registry.is_valid_store_id("../evil"))
        self.assertFalse(registry.is_valid_store_id("a/b"))
        self.assertFalse(registry.is_valid_store_id(""))
        self.assertFalse(registry.is_valid_store_id("x" * 33))

    def test_user_store_scope_defaults_admin_to_all_stores(self) -> None:
        """没有 all_stores 字段时:admin 默认 True,其它角色默认 False。"""
        settings = self._settings()
        users = settings["users"]
        users.append({"id": 2, "username": "staff", "role": "employee", "enabled": True})
        self.assertEqual(registry.user_store_scope(users[0]["id"], settings=settings), (True, []))
        self.assertEqual(registry.user_store_scope(2, settings=settings), (False, []))

    def test_user_store_scope_returns_assigned_store_ids(self) -> None:
        settings = self._settings()
        users = settings["users"]
        users.append({"id": 2, "username": "staff", "role": "employee",
                      "enabled": True, "store_ids": ["s002"]})
        self.assertEqual(registry.user_store_scope(2, settings=settings), (False, ["s002"]))

    # --- 复核修复轮 1:4 个 Important + 4 个 Minor ---

    def _break_settings_write(self) -> None:
        """把 settings.json 的写入打桩成静默失败。

        settings_handler._save() 会吞掉所有异常(只打 stderr 警告),
        正是这个行为让「写失败」在调用方看起来像「写成功」。
        """
        from modules.system import settings_handler
        original = settings_handler.save_settings

        def broken_save(data: dict[Any, Any]) -> Any:
            return None

        settings_handler.save_settings = broken_save
        self.addCleanup(setattr, settings_handler, "save_settings", original)

    def test_add_store_rejects_duplicate_default_store_id(self) -> None:
        """新注册表上 add_store("main", ...) 不能产生两条 main。

        重复检查必须排在 ensure_default_store() 之后 —— 否则默认店刚被补上,
        前面的重复检查还没看到它,就会 append 出第二条 main。
        """
        settings = self._settings()
        with self.assertRaises(ValueError):
            registry.add_store("main", "总店分店", settings=settings)
        ids = [s["id"] for s in registry.list_stores(settings)]
        self.assertEqual(ids, ["main"])

    def test_add_store_rejects_case_insensitive_duplicate_id(self) -> None:
        """macOS/Windows 文件系统大小写不敏感 → MAIN 与 main 是同一个目录。

        不挡的话,新建的"分店"会静默读写总店的数据 —— 正是本功能要消灭的串店。
        """
        settings = self._settings()
        registry.ensure_default_store(settings)
        with self.assertRaises(ValueError) as cm:
            registry.add_store("MAIN", "国贸店", settings=settings)
        msg = str(cm.exception)
        self.assertIn("MAIN", msg)
        self.assertIn("main", msg)
        self.assertEqual([s["id"] for s in registry.list_stores(settings)], ["main"])

    def test_add_store_rejects_case_insensitive_conflict_with_branch(self) -> None:
        """分店之间同样不能只差大小写。"""
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        with self.assertRaises(ValueError):
            registry.add_store("S002", "国贸二店", settings=settings)
        self.assertEqual(len(registry.list_stores(settings)), 2)

    def test_add_store_allows_ids_differing_beyond_case(self) -> None:
        """只有大小写相同的才算冲突 —— s002 与 s003、main 与 main2 都该放行。"""
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        registry.add_store("s003", "南京店", settings=settings)
        registry.add_store("main2", "二号总店", settings=settings)
        ids = [s["id"] for s in registry.list_stores(settings)]
        self.assertEqual(ids, ["main", "s002", "s003", "main2"])

    def test_add_store_raises_when_settings_write_fails(self) -> None:
        """写 settings.json 失败必须报错,不能报成功。

        否则管理页显示"门店已创建",但这家店不在注册表里 ——
        Task 4 的门店闸会拒掉它的每一个请求,还留下一个孤儿目录。
        """
        self._settings()
        self._break_settings_write()
        with self.assertRaises(RuntimeError) as cm:
            registry.add_store("s002", "国贸店")
        self.assertIn("settings.json", str(cm.exception))
        # 注册表里不能有这家店
        on_disk = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertIsNone(on_disk.get("stores"))
        # 也不能留下孤儿目录:注册表先落盘,目录后建 —— 写失败时目录根本没建
        self.assertFalse((self.data_dir / "stores" / "s002").exists())

    def test_add_store_rolls_back_when_store_files_cannot_be_created(self) -> None:
        """建目录失败 → 把刚登记的门店撤掉,不留「有门店、没数据」的幻影店。"""
        from unittest import mock

        settings = self._settings()
        patcher = mock.patch.object(registry, "_create_store_files",
                                    side_effect=OSError("磁盘满了"))
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.assertRaises(OSError):
            registry.add_store("s002", "国贸店", settings=settings)
        self.assertIsNone(registry.get_store("s002", settings=settings))
        self.assertIsNotNone(registry.get_store("main", settings=settings))

    def test_update_store_raises_when_settings_write_fails(self) -> None:
        self._settings()
        registry.add_store("s002", "国贸店")
        self._break_settings_write()
        with self.assertRaises(RuntimeError):
            registry.update_store("s002", {"name": "国贸分店"})

    def test_delete_store_raises_when_settings_write_fails(self) -> None:
        self._settings()
        registry.add_store("s002", "国贸店")
        self._break_settings_write()
        with self.assertRaises(RuntimeError):
            registry.delete_store("s002")
        # 门店必须还在注册表里(删除没生效)
        on_disk = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in on_disk["stores"]], ["main", "s002"])

    def test_is_valid_store_id_rejects_trailing_newline(self) -> None:
        """正则的 $ 会匹配末尾换行之前 → "s002\\n" 能混进目录名。"""
        self.assertFalse(registry.is_valid_store_id("s002\n"))
        self.assertFalse(registry.is_valid_store_id("s002\n\n"))

    def test_create_store_files_rejects_invalid_id(self) -> None:
        """建目录前也要验一次 ID(防御纵深:别只靠入口那一道闸)。"""
        with self.assertRaises(ValueError):
            registry._create_store_files("../evil")
        self.assertFalse((self.data_dir / "evil").exists())

    def test_update_store_strips_name_and_coerces_active(self) -> None:
        """改名要 strip、active 要转 bool —— 与 add_store() 保持一致。"""
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        updated = registry.update_store(
            "s002", {"name": "  国贸分店  ", "active": 0}, settings=settings
        )
        self.assertEqual(updated["name"], "国贸分店")
        self.assertIs(updated["active"], False)

    def test_list_stores_returns_copies(self) -> None:
        """list_stores() 交出去的是副本 —— 调用方不能在内存里就地改坏注册表。"""
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        stores = registry.list_stores(settings)
        stores[0]["name"] = "被改坏了"
        stores[1]["id"] = "hacked"
        main = registry.get_store("main", settings=settings)
        s002 = registry.get_store("s002", settings=settings)
        assert main is not None and s002 is not None  # mypy:收窄
        self.assertEqual(main["name"], "总店")
        self.assertEqual(s002["name"], "国贸店")

    # --- 复核修复轮 2 ---

    def test_add_store_rolls_back_registry_on_disk_when_store_files_cannot_be_created(self) -> None:
        """全局模式(不传 settings)下建目录失败 → 注册表必须回滚**落盘**。

        轮 1 的用例只覆盖了内存模式(settings=...):那条路径由调用方自己落盘,
        registry 根本不碰 settings.json。全局模式才会调 _persist() 落盘 ——
        也正是「磁盘上留着幻影门店条目」的路径,此前完全没有测试覆盖。

        幻影条目的后果:内存里已经删了这家店,磁盘上还在 →
        Task 4 的门店闸会放行一个**没有数据目录**的门店,它的每个请求都 404。
        """
        from unittest import mock

        self._settings()
        patcher = mock.patch.object(registry, "_create_store_files",
                                    side_effect=OSError("磁盘满了"))
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.assertRaises(OSError):
            registry.add_store("s002", "国贸店")

        on_disk = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        ids = [s["id"] for s in on_disk.get("stores") or []]
        # 这家店不能留在注册表里
        self.assertNotIn("s002", ids)
        # 总店必须还在,而且只能有一条(回滚不能把 main 挤掉或写成两条)
        self.assertIn("main", ids)
        self.assertEqual(ids.count("main"), 1)
        # 不留孤儿目录
        self.assertFalse((self.data_dir / "stores" / "s002").exists())

    def test_add_store_raises_when_rollback_persist_fails(self) -> None:
        """回滚落盘失败必须喊出来 —— 绝不能静默吞掉。

        静默吞掉的结局:内存里已删这家店,settings.json 里却留着幻影条目
        (内存与磁盘不一致),而且**没人知道**。必须抛错,让上层知道
        「门店没建成,而且注册表也需要人工清理」。
        """
        from unittest import mock

        self._settings()
        calls: list[int] = []

        def flaky_persist(settings: dict[Any, Any]) -> None:
            calls.append(1)
            if len(calls) == 1:
                return  # 第一次(登记新店)成功
            raise RuntimeError("模拟回滚落盘失败")

        patcher = mock.patch.object(registry, "_persist", side_effect=flaky_persist)
        patcher.start()
        self.addCleanup(patcher.stop)
        create_patcher = mock.patch.object(registry, "_create_store_files",
                                           side_effect=OSError("磁盘满了"))
        create_patcher.start()
        self.addCleanup(create_patcher.stop)

        with self.assertRaises(RuntimeError) as cm:
            registry.add_store("s002", "国贸店")
        self.assertIn("回滚", str(cm.exception))
        # 原始异常(建目录失败)必须挂在异常链上,不能被吞掉
        self.assertIsInstance(cm.exception.__cause__, OSError)

    def test_registry_returns_deep_copies_of_nested_fields(self) -> None:
        """交出去的门店 dict 必须是**深**拷贝。

        模块 docstring 承诺「调用方改不动注册表本体」。当前门店字段全是标量,
        浅拷贝看不出问题 —— 但 Task 6 会给用户记录加 store_ids 列表字段,
        Task 4 的门店闸要遍历这些字段;一旦门店记录带上任何列表/字典,
        浅拷贝就会漏。
        """
        settings = self._settings()
        registry.ensure_default_store(settings)
        settings["stores"].append(
            {"id": "s003", "name": "嵌套店", "store_ids": ["a"]}
        )

        one = registry.get_store("s003", settings=settings)
        assert one is not None  # mypy:收窄
        one["store_ids"].append("b")
        self.assertEqual(settings["stores"][1]["store_ids"], ["a"])

        listed = registry.list_stores(settings)
        listed[1]["store_ids"].append("c")
        self.assertEqual(settings["stores"][1]["store_ids"], ["a"])

    def test_add_store_returns_deep_copy(self) -> None:
        """add_store() 的返回值也不能是注册表本体的引用。"""
        settings = self._settings()
        store = registry.add_store("s002", "国贸店", settings=settings)
        store["name"] = "被改坏了"
        again = registry.get_store("s002", settings=settings)
        assert again is not None  # mypy:收窄
        self.assertEqual(again["name"], "国贸店")

    def test_update_store_returns_deep_copy(self) -> None:
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        # 给门店记录补一个嵌套字段(模拟将来的 store_ids)
        settings["stores"][1]["store_ids"] = ["a"]
        updated = registry.update_store("s002", {"name": "国贸分店"}, settings=settings)
        updated["store_ids"].append("b")
        self.assertEqual(settings["stores"][1]["store_ids"], ["a"])


class TestStoreConfig(StoreTestBase):
    """门店配置 store.json。"""

    def test_default_meters_are_four_tables(self) -> None:
        self.assertEqual(len(config.DEFAULT_METERS), 4)
        self.assertEqual(config.DEFAULT_METERS[0]["key"], "hall")

    def test_write_and_read_store_config(self) -> None:
        cfg = {"id": "s002", "name": "国贸店", "meters": config.DEFAULT_METERS, "config": {}}
        config.write_store_config("s002", cfg)
        read = config.read_store_config("s002")
        self.assertEqual(read["name"], "国贸店")
        self.assertEqual(len(read["meters"]), 4)

    def test_get_store_settings_falls_back_to_defaults(self) -> None:
        """门店还没有 store.json 时返回默认表定义,不抛异常。"""
        cfg = config.get_store_settings()
        self.assertEqual(len(cfg.get("meters", [])), 4)

    def test_get_store_meters_returns_list(self) -> None:
        self.assertIsInstance(config.get_store_meters(), list)

    # --- 以下为简报用例未覆盖、但属于本任务明确要求的行为 ---

    def test_store_config_path_rejects_path_traversal(self) -> None:
        """门店 ID 会拼进路径 —— 非法 ID 必须报错,不能落到 stores/ 外面。"""
        with self.assertRaises(ValueError):
            config.store_config_path("../evil")

    def test_read_store_config_returns_defaults_when_corrupted(self) -> None:
        """store.json 损坏 → 返回默认配置,不抛异常。"""
        p = config.store_config_path("s002")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{损坏", encoding="utf-8")
        cfg = config.read_store_config("s002")
        self.assertEqual(len(cfg["meters"]), 4)

    def test_get_store_prices_returns_defaults(self) -> None:
        prices = config.get_store_prices()
        self.assertEqual(prices["electricity_price"], 0.9)
        self.assertEqual(prices["water_price"], 4.5)
        self.assertEqual(prices["main_mult"], 50)
        self.assertEqual(prices["sub_mult"], 40)

    # --- 复核修复轮 1 ---

    def test_store_config_goes_through_storage_layer(self) -> None:
        """store.json 的读写必须走 storage.load_json / storage.save_json。

        绕过存储层 = 绕过 LRU 缓存、绕过「文件损坏 → 从备份恢复」、
        写的时候也不失效 storage 的缓存(将来别人读会拿到陈旧值)。
        """
        import storage

        calls = []
        original_save = storage.save_json
        original_load = storage.load_json

        def spy_save(path: Path, data: Any) -> None:
            calls.append(("save", path))
            original_save(path, data)

        def spy_load(path: Path, default: Any = None) -> Any:
            calls.append(("load", path))
            return original_load(path, default)

        storage.save_json = spy_save
        storage.load_json = spy_load
        try:
            cfg = {"id": "s002", "name": "国贸店", "meters": config.DEFAULT_METERS, "config": {}}
            config.write_store_config("s002", cfg)
            read = config.read_store_config("s002")
        finally:
            storage.save_json = original_save
            storage.load_json = original_load

        self.assertEqual(read["name"], "国贸店")
        kinds = [c[0] for c in calls]
        self.assertIn("save", kinds)
        self.assertIn("load", kinds)

    def test_store_config_readable_through_storage_load_json(self) -> None:
        """store.json 必须能被 storage.load_json 正常读出(格式与缓存路径通用)。"""
        from storage import load_json

        config.write_store_config("s002", {
            "id": "s002", "name": "国贸店",
            "meters": config.DEFAULT_METERS, "config": dict(config.DEFAULT_CONFIG),
        })
        data = load_json(config.store_config_path("s002"))
        self.assertEqual(data["name"], "国贸店")
        self.assertEqual(len(data["meters"]), 4)

    def test_store_config_write_creates_parent_directory(self) -> None:
        """save_json 不会建父目录 —— 写入前必须自己 mkdir。"""
        path = config.store_config_path("s003")
        self.assertFalse(path.parent.exists())
        config.write_store_config("s003", {"id": "s003", "name": "南京店", "meters": [], "config": {}})
        self.assertTrue(path.exists())


class TestStoreConfigIsolation(StoreTestBase):
    """门店配置与 storage 层 LRU 缓存的隔离。

    storage.load_json 命中缓存时**直接返回缓存里那个解析后的对象本身** ——
    调用方改它的嵌套结构,改的就是缓存本体。文件 mtime 没变时,下次读到的
    就是被改坏的内存值(磁盘上的文件是好的)。

    这是 P2「每店可自定义表数和倍率」的地基:P2 前端一改倍率,写盘前的
    中间态就已经把缓存改坏了;写盘失败时磁盘是旧值、内存是新值。
    """

    def _write(self, store_id: str = "s002", **overrides: Any) -> None:
        cfg: dict[str, Any] = {
            "id": store_id,
            "name": "国贸店",
            "meters": [dict(m) for m in config.DEFAULT_METERS],
            "config": dict(config.DEFAULT_CONFIG),
        }
        cfg.update(overrides)
        config.write_store_config(store_id, cfg)

    def test_read_store_config_does_not_leak_nested_mutations(self) -> None:
        """读出来的配置改坏了不能影响下一次读。"""
        self._write()
        cfg = config.read_store_config("s002")
        cfg["meters"][0]["multiplier"] = 999
        cfg["meters"].append({"key": "xx", "multiplier": 1})
        cfg["config"]["electricity_price"] = 0.1

        cfg2 = config.read_store_config("s002")
        self.assertEqual(cfg2["meters"][0]["multiplier"], 160)
        self.assertEqual(len(cfg2["meters"]), 4)
        self.assertEqual(cfg2["config"]["electricity_price"], 0.9)

    def test_read_store_config_does_not_pollute_storage_cache(self) -> None:
        """改返回值绝不能改坏 storage 的 LRU 缓存本体。"""
        from storage import load_json

        self._write()
        cfg = config.read_store_config("s002")
        cfg["meters"][0]["multiplier"] = 999

        raw = load_json(config.store_config_path("s002"))
        self.assertEqual(raw["meters"][0]["multiplier"], 160)

    def test_get_store_meters_returns_deep_copy(self) -> None:
        """get_store_meters() 交出去的 list 必须是副本。"""
        context.set_current_store("s002")
        self._write()
        meters = config.get_store_meters()
        meters[0]["multiplier"] = 999
        meters.append({"key": "xx", "multiplier": 1})

        again = config.get_store_meters()
        self.assertEqual(again[0]["multiplier"], 160)
        self.assertEqual(len(again), 4)

    def test_get_store_prices_returns_deep_copy(self) -> None:
        """get_store_prices() 的值是引用拷贝 —— 嵌套结构会被改坏。"""
        context.set_current_store("s002")
        self._write(config={"electricity_price": 0.9, "tariff": {"peak": 1.2}})
        prices = config.get_store_prices()
        prices["electricity_price"] = 0.0
        prices["tariff"]["peak"] = 99.0

        again = config.get_store_prices()
        self.assertEqual(again["electricity_price"], 0.9)
        self.assertEqual(again["tariff"]["peak"], 1.2)

    def test_default_meters_are_not_mutated_by_callers(self) -> None:
        """默认值也不能被调用方改坏(模块级常量必须是只读的)。"""
        context.set_current_store("s999")
        meters = config.get_store_meters()
        meters[0]["multiplier"] = 999
        self.assertEqual(config.DEFAULT_METERS[0]["multiplier"], 160)
