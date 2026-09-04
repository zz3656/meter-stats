"""并发场景下的 settings 初始化测试。"""
import sys
import threading
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from handlers.settings import init_settings  # noqa: E402


class TestSettingsInitThreadSafety(unittest.TestCase):
    """多线程同时调用 init_settings 的安全测试。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_concurrent_init_only_one_writes(self):
        """并发 50 个 init_settings 调用，应只有一个成功创建文件。"""
        data_dir = Path(self.tmp.name)
        results = []
        errors = []

        def worker(i):
            try:
                result = init_settings(data_dir)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 没有异常
        self.assertEqual(errors, [])

        # 恰好只有一个 worker 返回了非 None（成功创建了 settings）
        created_count = sum(1 for r in results if r is not None)
        self.assertEqual(created_count, 1, f"应该有 1 个成功，实际 {created_count}")

        # settings.json 文件存在且格式正确
        settings_path = data_dir / "settings.json"
        self.assertTrue(settings_path.exists())
        import json
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertIn("users", settings)
        self.assertEqual(len(settings["users"]), 1)
        self.assertEqual(settings["users"][0]["role"], "admin")

    def test_second_init_returns_none(self):
        """已存在 settings.json 时，再次调用应返回 None。"""
        data_dir = Path(self.tmp.name)
        r1 = init_settings(data_dir)
        self.assertIsNotNone(r1)  # 第一次成功创建

        r2 = init_settings(data_dir)
        self.assertIsNone(r2)  # 第二次返回 None


if __name__ == "__main__":
    unittest.main(verbosity=2)
