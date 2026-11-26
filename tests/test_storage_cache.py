"""存储层缓存一致性回归测试(标准库 unittest,零依赖)。

背景:`storage.load_json()` 命中缓存时返回的是**缓存里那个对象本身,不是副本**,
而 `modules/_base.py` 的 `handle_post` / `handle_put` 拿到它之后是**原地改**
(append / 改字段)再交给 `save_json()` 存盘。

原来的 `save_json()` 把「失效缓存」写在成功路径的最后一行 —— 一旦写盘失败
(磁盘满 / 权限 / 临时文件建不出来),`_cache_invalidate()` 就**根本不会执行**:

    盘上:旧值(1 条)          ← tmp.replace() 没走到
    缓存:被调用方改过的对象(2 条)

`load_json()` 用 mtime 校验缓存,而失败的写入**没有**改变磁盘文件的 mtime →
mtime 依然匹配 → 继续返回那份幻影对象。**直到重启才消失。**

更糟的是它骗过人眼:GET 接口照样返回 2 条,用户以为存进去了,重启后数据回到 1 条。
这是 CHANGELOG 0.5.0「已知问题」里记的「`modules/_base.py` 缓存别名地雷」。

修法:把 `_cache_invalidate()` 挪进 `finally` —— 成功与失败都失效。

覆盖:
- 写盘失败后,`load_json()` 必须返回**盘上的真值**,不是内存里的幻影
- 写盘成功后缓存也要失效(否则别的路径改动源文件后读到旧值)
- 走完整 `handle_post` 链路(原地 append → 存盘失败 → GET)不出现幻影

运行:
    python3 -m unittest tests.test_storage_cache -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

import storage  # noqa: E402


class TestSaveJsonCacheInvalidation(unittest.TestCase):
    """`save_json()` 在失败路径上也必须失效缓存。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "demo.json"
        self.path.write_text('[{"id": 1}]', encoding="utf-8")
        # 每个用例都从干净缓存开始,避免用例间互相污染
        storage._cache_clear()
        self.addCleanup(storage._cache_clear)

    def _fail_dump(self) -> Any:
        """让 json.dump 抛 OSError —— 模拟磁盘满。

        打的是 `json` 这个模块对象上的 `dump`(`storage` 里 `import json` 拿到的是
        同一个模块),所以 storage 的 `json.dump(...)` 也会命中这个桩。
        """
        def boom(*_a: Any, **_k: Any) -> None:
            raise OSError("disk full (simulated)")
        return mock.patch.object(json, "dump", boom)

    def test_failed_save_does_not_leave_phantom_data(self) -> None:
        """写盘失败后必须读回盘上真值 —— 缓存里那份被原地改过的对象要丢掉。

        这是「幻影数据」那条:旧实现把失效放在成功路径,失败时缓存仍是被改过的
        对象,而磁盘 mtime 没变 → mtime 校验通不过去也拦不住,返回幻影。
        """
        data = storage.load_json(self.path, [])
        self.assertEqual(len(data), 1)

        # 模拟 _base.handle_post:原地 append 到**缓存对象本身**
        data.append({"id": 2})
        self.assertEqual(len(data), 2)

        with self._fail_dump(), self.assertRaises(OSError):
            storage.save_json(self.path, data)

        # 盘上还是 1 条(写入失败,tmp 没 replace)
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")), [{"id": 1}],
        )
        # 关键断言:再读必须回到盘上真值,不能是 2 条幻影
        reloaded = storage.load_json(self.path, [])
        self.assertEqual(
            reloaded, [{"id": 1}],
            "写盘失败后 load_json 返回了内存里的幻影数据(%d 条),盘上只有 1 条 —— "
            "缓存失效没有放在 finally 里" % len(reloaded),
        )

    def test_successful_save_invalidates_cache(self) -> None:
        """正常写盘后也要失效 —— 断言保留,防止有人把失效整个删掉。"""
        data = storage.load_json(self.path, [])
        data.append({"id": 2})
        storage.save_json(self.path, data)

        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")), [{"id": 1}, {"id": 2}],
        )
        self.assertEqual(len(storage.load_json(self.path, [])), 2)

    def test_failed_save_leaves_no_temp_file_dirty_state(self) -> None:
        """写盘失败后不得留下能被误读的 .tmp 残留 —— 下次保存要能正常覆盖。"""
        data = storage.load_json(self.path, [])
        with self._fail_dump(), self.assertRaises(OSError):
            storage.save_json(self.path, data)

        # 失败后同路径再存一次必须成功(中间态没有把路径搞坏)
        storage.save_json(self.path, [{"id": 9}])
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")), [{"id": 9}],
        )


class TestBaseHandlerPhantomData(unittest.TestCase):
    """走 `modules/_base.py` 的真实链路:原地改缓存对象 → 存盘失败 → GET 不许出现幻影。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "readings.json"
        self.path.write_text('[{"id": "r1"}]', encoding="utf-8")
        storage._cache_clear()
        self.addCleanup(storage._cache_clear)

    def test_handle_post_failure_does_not_corrupt_read_view(self) -> None:
        """`_base` 的 _load() → append → _save() 在 _save 失败后不能污染后续读。

        `_load()` 直接返回 `load_json()` 的结果(即缓存对象),append 是原地改。
        存盘失败若不让缓存失效,下次 `_load()` 还是那份含幻影行的对象。
        """
        from modules._base import JsonModelHandler

        # 只借用它的 _load / _save 血统,不跑 HTTP 层
        class Probe(JsonModelHandler):
            model = "readings"

            def __init__(self, target: Path) -> None:
                self.target = target

            def _path(self) -> Path:
                return self.target

        probe = Probe(self.path)

        data = probe._load()
        self.assertEqual(len(data), 1)
        data.append({"id": "r2"})   # 原地改缓存对象,模拟 handle_post

        with mock.patch.object(json, "dump",
                               side_effect=OSError("disk full (simulated)")), \
                self.assertRaises(OSError):
            probe._save(data)

        after = probe._load()
        self.assertEqual(
            [r["id"] for r in after], ["r1"],
            "存盘失败后 _load() 读到了幻影行 %s —— 缓存没失效"
            % ([r["id"] for r in after],),
        )


if __name__ == "__main__":
    unittest.main()


class TestReportCacheInvalidation(unittest.TestCase):
    """写盘即失效:报表缓存的新鲜度不再依赖「每个 handler 记得写一行」。

    以前 11 处 handler 各写一行 invalidate_report_cache();漏一处就是脏读,
    典型症状是「改完电表倍率/录完抄表,报表数字半天不变,重启才好」。
    现在收敛在 storage.save_json,这里锁死「写这 5 个文件必然失效、写别的不会」。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        import report as _report
        self.report = _report
        self.report.invalidate_report_cache()

    def _seed_cache(self) -> None:
        self.report._cache_report("2026-06", {"total": 71226.1})

    def test_readings_write_clears_cache(self) -> None:
        self._seed_cache()
        self.assertTrue(self.report._report_cache)
        storage.save_json(self.dir / "readings.json", [{"date": "2026-06-01"}])
        self.assertEqual(self.report._report_cache, {}, "抄表写盘后月报缓存还留着")

    def test_charges_write_clears_cache(self) -> None:
        self._seed_cache()
        storage.save_json(self.dir / "charges.json", [])
        self.assertEqual(self.report._report_cache, {})

    def test_store_config_write_clears_cache(self) -> None:
        """改电价/倍率/表集合后,报表必须立刻用新口径(这条以前是断的)。"""
        self._seed_cache()
        storage.save_json(self.dir / "store.json", {"config": {"electricity_price": 1.2}})
        self.assertEqual(self.report._report_cache, {})

    def test_unrelated_model_does_not_clear_cache(self) -> None:
        """物品/值班这类与报表无关的写入不该把缓存打掉(避免无谓重算)。"""
        self._seed_cache()
        storage.save_json(self.dir / "items.json", [{"id": "1"}])
        storage.save_json(self.dir / "duty.json", [])
        self.assertTrue(self.report._report_cache, "无关模型写盘把报表缓存清了")
