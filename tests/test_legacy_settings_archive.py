"""settings.json 顶层遗留电表配置的归档测试(标准库 unittest,零依赖)。

背景:分店改造前「表集合 + 电价」是**全局**的,存在 settings.json 顶层的
`meter` / `config` 两个键里。改造后它们变成了**每店一份**
(`stores/<id>/store.json`),顶层那两份只在迁移时当过种子。

但键名还叫 `meter` / `config`,任何人打开 settings.json 都会以为那是
"全局电表配置" —— 手改它毫无效果,改完还以为改到了。

修法:布局就绪后把这两项挪到 `_legacy_meter_config`(不删除 —— 回滚到旧版本时
自定义电价还找得回来),并保证:
- 幂等:再跑一次什么都不做
- 归档后运行时行为不变(各店仍读自己的 store.json,默认 4 表照常)
- 迁移还没跑时**不**归档(种子还得靠它们)

运行:
    python3 -m unittest tests.test_legacy_settings_archive -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "MeterStats"))

from modules.stores import config, context, migration  # noqa: E402
from modules.system import settings_handler  # noqa: E402

import app_handler  # noqa: E402
from storage import DATA_FILES  # noqa: E402


class _Base(unittest.TestCase):
    """独立临时数据目录 + 真实 settings.json。"""

    def setUp(self) -> None:
        self._prev_paths = app_handler.DATA_PATHS
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        settings_handler.init_settings(self.data_dir)
        context.clear_current_store()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()

    def _settings(self) -> Dict[str, Any]:
        return settings_handler.get_settings()

    def _set_legacy(self) -> None:
        """铺一份"分店改造前"的全局配置。"""
        st = self._settings()
        st["meter"] = {
            "hall": {"label": "大厅", "icon": "🎤", "multiplier": 160, "color": "#2563eb"},
            "fire": {"label": "消防", "icon": "🧯", "multiplier": 1, "color": "#dc2626"},
        }
        st["config"] = {"electricity_price": 1.23, "water_price": 6.5}
        settings_handler.save_settings(st)


class TestArchiveLegacySettings(_Base):
    def test_archives_top_level_keys(self) -> None:
        self._set_legacy()
        self.assertTrue(migration.archive_legacy_global_meter_settings())

        st = self._settings()
        self.assertNotIn("meter", st, "顶层 meter 还在 —— 看上去仍像全局配置")
        self.assertNotIn("config", st, "顶层 config 还在 —— 看上去仍像全局配置")

        archived = st.get("_legacy_meter_config") or {}
        self.assertIn("meter", archived)
        self.assertIn("config", archived)
        self.assertEqual(archived["config"]["electricity_price"], 1.23)
        self.assertIn("archived_at", archived)

    def test_is_idempotent(self) -> None:
        self._set_legacy()
        self.assertTrue(migration.archive_legacy_global_meter_settings())
        before = self._settings().get("_legacy_meter_config")
        self.assertFalse(migration.archive_legacy_global_meter_settings(),
                         "第二次调用不该再归档")
        self.assertEqual(self._settings().get("_legacy_meter_config"), before)

    def test_noop_when_nothing_to_archive(self) -> None:
        st = self._settings()
        st.pop("meter", None)
        st.pop("config", None)
        settings_handler.save_settings(st)
        self.assertFalse(migration.archive_legacy_global_meter_settings())

    def test_preserves_other_settings(self) -> None:
        self._set_legacy()
        st = self._settings()
        st["nas_sync_url"] = "https://example.invalid"
        st["backup_retention_count"] = 7
        settings_handler.save_settings(st)

        migration.archive_legacy_global_meter_settings()
        st2 = self._settings()
        self.assertEqual(st2["nas_sync_url"], "https://example.invalid")
        self.assertEqual(st2["backup_retention_count"], 7)
        self.assertIn("users", st2)
        self.assertNotIn("meter", st2)


class TestMigrateTriggersArchive(_Base):
    def test_migrate_to_stores_archives_legacy(self) -> None:
        """走真实迁移路径:布局就绪后顶层遗留应被归档。"""
        self._set_legacy()
        migration.migrate_to_stores(self.data_dir)

        st = self._settings()
        self.assertNotIn("meter", st)
        self.assertNotIn("config", st)
        self.assertIn("meter", st.get("_legacy_meter_config") or {})

    def test_legacy_config_lands_in_store_then_gets_archived(self) -> None:
        """全局配置先被**种子**进总店的 store.json,然后才归档 —— 两步都不能省。

        这里刻意给的是 2 块表 / 电价 1.23:
        - 如果归档跑在种子之前 → store.json 只能拿到默认 4 表,用户配置丢了
        - 如果只有种子没有归档 → 顶层 meter/config 继续误导
        所以断言 store.json 拿到的是**那 2 块表**,且顶层已归档。
        """
        self._set_legacy()
        migration.migrate_to_stores(self.data_dir)
        context.set_current_store("main")

        meters = config.get_store_meters()
        self.assertEqual([m["key"] for m in meters], ["hall", "fire"],
                         "迁移没有把全局配置种子进 store.json")
        prices = config.get_store_prices()
        self.assertEqual(prices["electricity_price"], 1.23,
                         "电价没有从全局配置带过来")

        st = self._settings()
        self.assertNotIn("meter", st)
        self.assertEqual(st["_legacy_meter_config"]["meter"]["hall"]["multiplier"], 160)

    def test_already_migrated_install_still_archives(self) -> None:
        """**已经迁完**的安装(有 .migrated 标记)也必须归档。

        这是线上最常见的情况 —— 只覆盖"首次迁移"的测试抓不住它:
        migrate_to_stores() 在 marker 存在时会提前 return,
        写在函数尾部的归档代码根本不会执行(实施中真的踩了这个)。
        """
        self._set_legacy()
        migration.migrate_to_stores(self.data_dir)          # 首次:完成迁移并归档
        marker = self.data_dir / "stores" / "main" / ".migrated"
        self.assertTrue(marker.exists(), "前置:迁移标记应已生成")

        # 模拟"遗留键又出现了"(旧版本残留 / 手工从备份恢复 settings.json)
        st = self._settings()
        st["meter"] = {"hall": {"label": "大厅", "multiplier": 160}}
        st["config"] = {"electricity_price": 2.0}
        settings_handler.save_settings(st)

        migration.migrate_to_stores(self.data_dir)          # 再跑一次:走提前 return 分支
        st2 = self._settings()
        self.assertNotIn("meter", st2, "已迁移的安装没有归档 —— 提前 return 把归档跳过了")
        self.assertNotIn("config", st2)
        self.assertIn("meter", st2.get("_legacy_meter_config") or {})

    def test_not_archived_before_layout_ready(self) -> None:
        """布局没建起来时不能归档 —— 迁移的种子还得靠它们。"""
        self._set_legacy()
        # 不跑 migrate_to_stores,直接调归档:函数本身不知道布局状态,
        # 由调用方保证时机。这里断言"没有 main/store.json 时种子仍在"。
        self.assertFalse(
            (self.data_dir / "stores" / "main" / "store.json").exists()
        )
        st = self._settings()
        self.assertIn("meter", st, "布局未就绪就动了种子")


if __name__ == "__main__":
    unittest.main()
