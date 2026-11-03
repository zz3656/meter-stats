"""登录失败限速回归测试。

历史 bug：`_check_login_rate_limit` 把"是否处于冷却期"写成 `if failed_attempts:`，
而失败记录的时间戳就是刚刚，cooldown_remaining 必然 > 0 —— 结果**输错一次密码就被锁
5 分钟**。设计意图是"1 分钟内连续错满 5 次才锁"。

另一个隐藏问题：尝试记录只保留 60 秒窗口，锁定到期时间必须单独记，否则锁 5 分钟会在
60 秒后随记录被清理而静默失效。

运行:
    python3 -m unittest tests.test_login_rate_limit -v
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

import modules.system.auth_handler as auth  # noqa: E402


class RateLimitBase(unittest.TestCase):
    def setUp(self):
        self._saved_attempts = dict(auth._LOGIN_ATTEMPTS)
        self._saved_lockout = dict(auth._LOGIN_LOCKOUT_UNTIL)
        auth._LOGIN_ATTEMPTS.clear()
        auth._LOGIN_LOCKOUT_UNTIL.clear()

    def tearDown(self):
        auth._LOGIN_ATTEMPTS.clear()
        auth._LOGIN_ATTEMPTS.update(self._saved_attempts)
        auth._LOGIN_LOCKOUT_UNTIL.clear()
        auth._LOGIN_LOCKOUT_UNTIL.update(self._saved_lockout)

    def inject_failures(self, user: str, n: int, ago_sec: float = 1.0):
        """伪造 n 次窗口内的失败记录（默认都发生在 1 秒前）。"""
        now = time.time() - ago_sec
        auth._LOGIN_ATTEMPTS[user] = [
            {"timestamp": now, "success": False} for _ in range(n)
        ]


class TestNoLockoutBelowThreshold(RateLimitBase):
    def test_single_wrong_password_does_not_lock(self):
        """核心用例：输错一次密码必须能立刻再试。"""
        auth._record_login_attempt("admin", False)
        allowed, msg = auth._check_login_rate_limit("admin")
        self.assertTrue(allowed, f"错 1 次就被拦: {msg}")
        self.assertEqual(msg, "")

    def test_four_failures_still_allowed(self):
        self.inject_failures("admin", auth._LOGIN_MAX_FAILED - 1)
        allowed, msg = auth._check_login_rate_limit("admin")
        self.assertTrue(allowed, f"未达阈值却拦了: {msg}")

    def test_retry_after_each_typo_keeps_working(self):
        """逐次输错（每次之间都通过校验）不应在第 2 次就被锁。"""
        for i in range(auth._LOGIN_MAX_FAILED - 1):
            allowed, msg = auth._check_login_rate_limit("admin")
            self.assertTrue(allowed, f"第 {i + 1} 次尝试被误锁: {msg}")
            auth._record_login_attempt("admin", False)


class TestLockoutAtThreshold(RateLimitBase):
    def test_locks_after_max_failures(self):
        self.inject_failures("admin", auth._LOGIN_MAX_FAILED)
        allowed, msg = auth._check_login_rate_limit("admin")
        self.assertFalse(allowed, "错满 5 次却没锁")
        self.assertIn("锁定", msg)

    def test_lockout_survives_attempt_window_cleanup(self):
        """锁定不能因为 60 秒尝试窗口过期被清理而失效。"""
        self.inject_failures("admin", auth._LOGIN_MAX_FAILED)
        self.assertFalse(auth._check_login_rate_limit("admin")[0])
        # 尝试记录已被清空、且早已超出 60 秒窗口，锁定仍须生效
        auth._LOGIN_ATTEMPTS.clear()
        allowed, msg = auth._check_login_rate_limit("admin")
        self.assertFalse(allowed, f"锁定被记录清理绕过: {msg}")

    def test_lockout_expires_after_cooldown(self):
        self.inject_failures("admin", auth._LOGIN_MAX_FAILED)
        self.assertFalse(auth._check_login_rate_limit("admin")[0])
        # 把锁定到期时间推到过去，模拟 5 分钟已过
        auth._LOGIN_LOCKOUT_UNTIL["admin"] = time.time() - 1
        allowed, msg = auth._check_login_rate_limit("admin")
        self.assertTrue(allowed, f"冷却期已过仍被锁: {msg}")
        self.assertNotIn("admin", auth._LOGIN_LOCKOUT_UNTIL, "解锁后没清掉锁定记录")

    def test_lockout_is_per_username(self):
        self.inject_failures("admin", auth._LOGIN_MAX_FAILED)
        self.assertFalse(auth._check_login_rate_limit("admin")[0])
        allowed, msg = auth._check_login_rate_limit("zhang")
        self.assertTrue(allowed, f"别人被锁却连累 zhang: {msg}")


class TestSuccessClearsState(RateLimitBase):
    def test_successful_login_clears_failures_and_lockout(self):
        auth._LOGIN_LOCKOUT_UNTIL["admin"] = time.time() + 300
        auth._record_login_attempt("admin", True)
        self.assertNotIn("admin", auth._LOGIN_LOCKOUT_UNTIL)
        self.assertEqual(auth._LOGIN_ATTEMPTS.get("admin", []), [])
        self.assertTrue(auth._check_login_rate_limit("admin")[0])


if __name__ == "__main__":
    unittest.main()
