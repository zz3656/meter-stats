"""分店功能回归测试(标准库 unittest,零依赖)。

覆盖:
- 门店上下文:当前门店读写、线程隔离
- 按门店路径解析:单店布局原样返回 DATA_PATHS;多店布局指向 stores/<id>/
- 默认店在迁移前可回退顶层旧文件;分店不回退(否则会读到总店数据)
"""
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
        p = context.resolve_store_path("readings", "s002", "readings.json")
        self.assertEqual(p, self.data_dir / "stores" / "s002" / "readings.json")


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
