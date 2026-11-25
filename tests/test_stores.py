"""分店功能回归测试(标准库 unittest,零依赖)。

覆盖:
- 门店上下文:当前门店读写、线程隔离
- 按门店路径解析:单店布局原样返回 DATA_PATHS;多店布局指向 stores/<id>/
- 默认店在迁移前可回退顶层旧文件;分店不回退(否则会读到总店数据)
- 路径解析失败时必须报错,绝不静默回退到真实用户数据目录
- 门店数据的崩溃恢复:从顶层 backup/ 恢复
- 报表缓存按门店隔离(总店的月报不能被分店命中)
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.stores import context  # noqa: E402

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
        storage.get_data_dir = lambda: called.append(1) or Path("/should-not-be-used")
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
    """门店数据的崩溃恢复 —— 备份在顶层,门店自己的 backup/ 不存在。"""

    def _write_backup(self, day: str, filename: str, data) -> None:
        d = self.data_dir / "backup" / day
        d.mkdir(parents=True)
        (d / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_store_file_recovers_from_top_level_backup(self):
        """门店文件损坏 → 从顶层 backup/ 恢复。

        门店路径是 stores/<id>/readings.json,它同级的 stores/<id>/backup/ 不存在;
        不回退顶层就等于「崩溃后从 backup/ 自动恢复」对门店数据静默失效。
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

    def test_missing_store_file_is_restored_from_top_level_backup(self):
        """门店文件整个丢失 → 同样从顶层 backup/ 恢复。"""
        import storage

        payload = [{"date": "2026-01-02", "hall": 3.0}]
        self._write_backup("20260102", "charges.json", payload)
        store = self.data_dir / "stores" / "s002"
        store.mkdir(parents=True)

        self.assertEqual(storage.load_json(store / "charges.json", []), payload)


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
