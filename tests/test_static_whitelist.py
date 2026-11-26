"""静态资源白名单测试(标准库 unittest,零依赖)。

既存缺陷:`app_handler` 的静态文件分支把 **ROOT 之下的任意文件**直接发出去。
后果(实测):

    GET /routing.py   → 200, 25354 字节   ← 后端源码
    GET /storage.py   → 200, 34455 字节
    GET /server.py    → 200,  9714 字节

而服务监听在 `*:8765`(不是 127.0.0.1),等于**同网段任何人都能下载后端源码**,
接口面与鉴权逻辑一览无余。`.db` / `.log` / `.plist` / `.sh` / `.swift` 同理。

修法:按**扩展名白名单**服务,不在表里的一律 404(不是 403 —— 不告诉外面
"这个文件存在但不能读")。

这里用真进程验证,因为"路由层放行/拦截"这种判断只有发真实请求才靠得住。

运行:
    python3 -m unittest tests.test_static_whitelist -v
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
SERVER_PY = METERSTATS / "server.py"
APP_HANDLER_PY = METERSTATS / "app_handler.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _status(port: int, path: str) -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=3) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except Exception:
        return -1


class TestSourceGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.src = APP_HANDLER_PY.read_text(encoding="utf-8")

    def test_whitelist_defined(self) -> None:
        self.assertIn("_STATIC_ALLOWED_SUFFIXES", self.src)

    def test_whitelist_excludes_backend_and_secrets(self) -> None:
        block = self.src[self.src.index("_STATIC_ALLOWED_SUFFIXES"):]
        block = block[:block.index("})")]
        for bad in (".py", ".json", ".db", ".log", ".plist", ".sh", ".swift"):
            self.assertNotIn('"%s"' % bad, block,
                             "白名单里混进了 %s —— 后端文件/配置会继续被下载" % bad)

    def test_whitelist_includes_frontend_assets(self) -> None:
        block = self.src[self.src.index("_STATIC_ALLOWED_SUFFIXES"):]
        block = block[:block.index("})")]
        for good in (".html", ".css", ".js", ".png", ".svg"):
            self.assertIn('"%s"' % good, block, "白名单漏了 %s" % good)

    def test_suffix_check_is_applied(self) -> None:
        """白名单必须真的被用在请求路径上,不能只是定义着好看。"""
        self.assertRegex(
            self.src,
            r"(?m)^\s*if file_path\.suffix\.lower\(\) not in _STATIC_ALLOWED_SUFFIXES:",
            "定义了白名单但没有在静态分支里校验",
        )


class TestLiveServing(unittest.TestCase):
    """真起进程发请求(需要能监听本机端口)。"""

    port: int
    _tmp: tempfile.TemporaryDirectory[str]
    _proc: "subprocess.Popen[bytes]"

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.port = _free_port()
        env = dict(**os.environ)
        env.update({
            "METER_PORT": str(cls.port),
            "METER_DATA_DIR": cls._tmp.name,
            "METER_BIND": "127.0.0.1",
            "METER_INITIAL_PASS": "admin123",
            "PYTHONUNBUFFERED": "1",
        })
        cls._proc = subprocess.Popen(
            [sys.executable, str(SERVER_PY)],
            cwd=str(METERSTATS), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        cls.addClassCleanup(cls._shutdown)
        deadline = time.time() + 25
        while time.time() < deadline:
            if _status(cls.port, "/api/health") == 200:
                return
            if cls._proc.poll() is not None:
                out = cls._proc.stdout.read().decode("utf-8", "replace") if cls._proc.stdout else ""
                raise AssertionError("服务没能启动:\n%s" % out)
            time.sleep(0.2)
        raise AssertionError("服务 25 秒内没起来")

    @classmethod
    def _shutdown(cls) -> None:
        if cls._proc.poll() is None:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()
                cls._proc.wait(timeout=5)
        if cls._proc.stdout:
            cls._proc.stdout.close()

    def test_backend_sources_not_served(self) -> None:
        for path in ("/routing.py", "/storage.py", "/server.py", "/app_handler.py",
                     "/report.py"):
            self.assertEqual(_status(self.port, path), 404,
                             "%s 仍可下载 —— 后端源码泄露" % path)

    def test_config_and_caches_not_served(self) -> None:
        for path in ("/settings.json", "/audit.json", "/.gitignore"):
            self.assertEqual(_status(self.port, path), 404, "%s 仍可访问" % path)

    def test_frontend_assets_still_served(self) -> None:
        """收口不能收过头:页面、脚本、样式、图片必须照常。"""
        checks = {
            "/": 200,
            "/index.html": 200,
            "/style.css": 200,
            "/js/core/api.js": 200,
            "/js/core/meterForm.js": 200,
            "/admin.js": 200,
            "/favicon-32.png": 200,
        }
        for path, want in checks.items():
            self.assertEqual(_status(self.port, path), want, "%s 应返回 %d" % (path, want))


if __name__ == "__main__":
    unittest.main()
