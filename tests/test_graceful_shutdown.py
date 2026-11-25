"""优雅关闭回归测试(标准库 unittest,零依赖)。

背景:`server.py` 曾经把 `server.shutdown()` 直接写在 `signal` 处理器里,
而 `serve_forever()` 与信号处理器都在**主线程** —— 两边互等,进程卡死。

现象(改造前实测):
    kill <pid>          # SIGTERM
    → 进程一直不退出,只能 `kill -9`
    → `docker stop` 每次都要等满 10 秒超时才被强杀

这个 bug 不会让任何业务测试变红,只能靠**真起一个进程发信号**来验证,
所以这里用子进程做端到端断言。

运行:
    python3 -m unittest tests.test_graceful_shutdown -v
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
SERVER_PY = METERSTATS / "server.py"


def _free_port() -> int:
    """要一个当前空闲的端口(绑 0 让内核分配)。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/api/health" % port, timeout=0.5
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


class TestServerSourceGuard(unittest.TestCase):
    """静态护栏 —— 信号处理器里不许直接调 shutdown()。"""

    def test_shutdown_handler_uses_helper_thread(self) -> None:
        src = SERVER_PY.read_text(encoding="utf-8")
        start = src.index("def _shutdown(")
        end = src.index("atexit.register", start)
        body = src[start:end]
        self.assertIn("threading.Thread", body,
                      "_shutdown 没有把 server.shutdown 丢到辅助线程 —— 会死锁")
        self.assertNotIn("server.shutdown()\n        _remove_pid()", body,
                         "_shutdown 里还在主线程直接调 server.shutdown()")

    def test_server_close_in_finally(self) -> None:
        """关闭时要把监听套接字关掉,否则紧跟着的重启会撞端口占用。"""
        src = SERVER_PY.read_text(encoding="utf-8")
        self.assertIn("server.server_close()", src)


@unittest.skipUnless(hasattr(signal, "SIGTERM"), "该平台没有 SIGTERM")
class TestSigtermExits(unittest.TestCase):
    """真起进程 → 发 SIGTERM → 必须在几秒内自行退出。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port = _free_port()
        self.env = dict(**os.environ)
        self.env.update({
            "METER_PORT": str(self.port),
            "METER_DATA_DIR": self.tmp.name,
            "METER_BIND": "127.0.0.1",
            "METER_INITIAL_PASS": "admin123",
            "PYTHONUNBUFFERED": "1",
        })

    def test_sigterm_terminates_within_timeout(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, str(SERVER_PY)],
            cwd=str(METERSTATS), env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.time() + 25
            while time.time() < deadline:
                if proc.poll() is not None:
                    out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
                    self.fail("服务没能启动就退出了:\n%s" % out)
                if _healthy(self.port):
                    break
                time.sleep(0.2)
            else:
                self.fail("服务 25 秒内没起来")

            proc.send_signal(signal.SIGTERM)
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.fail(
                    "SIGTERM 后 5 秒仍未退出 —— 这就是那个死锁:"
                    "signal 处理器与 serve_forever() 都在主线程,"
                    "处理器里调 server.shutdown() 会互等"
                )
            self.assertEqual(rc, 0, "退出码不是 0(非优雅退出),实际 %r" % rc)

            # 端口要已被释放(否则紧接着的重启会「端口被占用」)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", self.port))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stdout:
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
