"""会话 TTL 与自动清理测试。

验证:
- create_session 返回唯一 token
- get_session 返回正确会话
- destroy_session 正确删除
- TTL 过期后 session 自动不可访问
- _touch_session 延长会话寿命
- get_session 在并发下线程安全
- _cleanup_expired_sessions 清理过期会话

运行:
    cd ~/Documents/electricity-stats-app
    python3 -m unittest tests.test_sessions -v
"""
import sys
import time
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from handlers.admin import (  # noqa: E402
    _SESSIONS,
    _SESSIONS_LOCK,
    SESSION_TIMEOUT_SECONDS,
    create_session,
    get_session,
    destroy_session,
    get_active_session_count,
    _touch_session,
    _cleanup_expired_sessions,
    _last_cleanup_time,
)


class TestSessionBasic(unittest.TestCase):
    """基础会话 CRUD。"""

    def setUp(self):
        _SESSIONS.clear()

    def test_create_returns_unique_tokens(self):
        """连续创建 100 个会话应得到 100 个不同 token。"""
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        tokens = {create_session(user) for _ in range(100)}
        self.assertEqual(len(tokens), 100)

    def test_create_session_has_required_fields(self):
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        token = create_session(user)
        sess = get_session(token)
        self.assertEqual(sess["user_id"], 1)
        self.assertEqual(sess["username"], "alice")
        self.assertEqual(sess["role"], "admin")
        self.assertEqual(sess["name"], "Alice")
        self.assertIn("created_at", sess)
        self.assertIn("_access_time", sess)

    def test_get_session_invalid_token_returns_none(self):
        self.assertIsNone(get_session("nonexistent"))

    def test_destroy_session_removes_it(self):
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        token = create_session(user)
        self.assertIsNotNone(get_session(token))
        destroy_session(token)
        self.assertIsNone(get_session(token))

    def test_destroy_nonexistent_is_safe(self):
        # 销毁不存在的 token 不应抛异常
        destroy_session("doesnt_exist")

    def test_get_active_session_count(self):
        self.assertEqual(get_active_session_count(), 0)
        create_session({"id": 1, "username": "a", "role": "admin", "name": "A"})
        create_session({"id": 2, "username": "b", "role": "user", "name": "B"})
        self.assertEqual(get_active_session_count(), 2)


class TestSessionTTL(unittest.TestCase):
    """会话 TTL 与过期清理。"""

    def setUp(self):
        _SESSIONS.clear()

    def test_touch_session_extends_access_time(self):
        """_touch_session 应更新 _access_time，延长会话寿命。"""
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        token = create_session(user)
        sess = get_session(token)
        original_access_time = sess["_access_time"]

        time.sleep(0.05)
        _touch_session(token)

        sess = get_session(token)
        self.assertGreater(sess["_access_time"], original_access_time)

    def test_session_expires_after_timeout(self):
        """会话超过 SESSION_TIMEOUT_SECONDS 后应不可访问。"""
        # 直接插入一个已过期的会话
        token = "expired_token"
        _SESSIONS[token] = {
            "user_id": 1,
            "username": "alice",
            "role": "admin",
            "name": "Alice",
            "created_at": "2020-01-01T00:00:00",
            "_access_time": time.time() - SESSION_TIMEOUT_SECONDS - 100,
        }
        # get_session 触发懒清理，应返回 None
        self.assertIsNone(get_session(token))
        # 会话应已从 dict 移除
        self.assertNotIn(token, _SESSIONS)

    def test_cleanup_removes_only_expired(self):
        """清理函数只移除过期会话。"""
        import handlers.admin as admin_mod
        # 重置 last_cleanup_time 确保清理不会被限流抑制
        admin_mod._last_cleanup_time = 0
        now = time.time()
        # 一个活跃会话
        _SESSIONS["active"] = {
            "user_id": 1, "username": "a", "role": "admin", "name": "A",
            "created_at": "2020-01-01", "_access_time": now,
        }
        # 两个过期会话
        _SESSIONS["expired1"] = {
            "user_id": 2, "username": "b", "role": "user", "name": "B",
            "created_at": "2020-01-01", "_access_time": now - SESSION_TIMEOUT_SECONDS - 100,
        }
        _SESSIONS["expired2"] = {
            "user_id": 3, "username": "c", "role": "user", "name": "C",
            "created_at": "2020-01-01", "_access_time": now - SESSION_TIMEOUT_SECONDS - 200,
        }
        _cleanup_expired_sessions()
        self.assertIn("active", _SESSIONS)
        self.assertNotIn("expired1", _SESSIONS)
        self.assertNotIn("expired2", _SESSIONS)


class TestSessionThreadSafety(unittest.TestCase):
    """并发场景下的会话管理。"""

    def setUp(self):
        _SESSIONS.clear()

    def test_concurrent_create_session(self):
        """并发创建 50 个会话，全部可正确读出。"""
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        tokens = []
        lock = threading.Lock()

        def worker():
            for _ in range(10):
                t = create_session(user)
                with lock:
                    tokens.append(t)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 50 个不同 token
        self.assertEqual(len(set(tokens)), 50)
        # 全部可读
        for t in tokens:
            sess = get_session(t)
            self.assertIsNotNone(sess)
            self.assertEqual(sess["username"], "alice")

    def test_concurrent_destroy_session(self):
        """并发销毁不会引发 KeyError。"""
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        tokens = [create_session(user) for _ in range(20)]

        errors = []

        def worker(token):
            try:
                destroy_session(token)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in tokens]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(_SESSIONS), 0)


class TestSessionIntegration(unittest.TestCase):
    """端到端场景：模拟用户登录→操作→退出。"""

    def setUp(self):
        _SESSIONS.clear()

    def test_login_then_query_then_logout(self):
        """完整流程：登录 → 查询 → 退出 → 不可用。"""
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        token = create_session(user)

        # 模拟 /api/auth/me
        sess = get_session(token)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["username"], "alice")

        # 模拟 /api/auth/logout
        destroy_session(token)
        sess = get_session(token)
        self.assertIsNone(sess)

    def test_active_session_extends_via_touch(self):
        """活跃用户每次请求都会重置 TTL，永不过期。"""
        user = {"id": 1, "username": "alice", "role": "admin", "name": "Alice"}
        token = create_session(user)

        # 模拟 5 次连续访问，每次间隔 0.05 秒
        for i in range(5):
            time.sleep(0.05)
            sess = get_session(token)
            self.assertIsNotNone(sess, f"会话在第 {i+1} 次访问后失效")
            _touch_session(token)


if __name__ == "__main__":
    unittest.main(verbosity=2)