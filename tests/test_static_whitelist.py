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


def _fetch(port: int, path: str):
    """返回 (status, headers dict, body bytes);失败返回 (-1, {}, b"")。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
            return int(r.status), dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return int(e.code), dict(e.headers), b""
    except Exception:
        return -1, {}, b""


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

    def test_assets_are_versioned_and_cacheable(self) -> None:
        """index.html 里的本地资源必须带 ?v=<内容哈希>,且带号的可长缓存。

        以前只有 admin.js 拿到了版本号(那段注入逻辑只替换 <TIMESTAMP> 占位符,
        对普通路径直接原样返回),其余 30 多个文件既不版本化又被 no-store ——
        每次刷新重下 ~620KB / 37 个请求。
        """
        status, _headers, body = _fetch(self.port, "/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        import re as _re
        local = [
            ref for ref in _re.findall(r'(?:src|href)="([^"]+)"', html)
            if not ref.startswith(("http://", "https://", "//", "#", "data:"))
        ]
        self.assertGreater(len(local), 30, "index.html 的本地资源数量异常")
        unversioned = [ref for ref in local if "?v=" not in ref]
        self.assertEqual(unversioned, [], "这些本地资源没带版本号,无法长缓存")

        # 带版本号的 JS:一年 + immutable
        js_ref = [r for r in local if ".js?v=" in r][0]
        status, headers, _ = _fetch(self.port, "/" + js_ref)
        self.assertEqual(status, 200)
        cc = headers.get("Cache-Control", "")
        self.assertIn("immutable", cc, "带版本号的 JS 应当可长缓存,实际: %r" % cc)

    def test_index_html_never_cached(self) -> None:
        """index.html 自己绝不能缓存:它带着当前的版本号引用。"""
        status, headers, _ = _fetch(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers.get("Cache-Control", ""))

    def test_unversioned_asset_not_cached(self) -> None:
        """不带 ?v= 的静态资源维持 no-store(兜底,正常不会走到)。"""
        status, headers, _ = _fetch(self.port, "/js/core/api.js")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers.get("Cache-Control", ""))

    def test_head_requests_supported(self) -> None:
        """HEAD 必须返回 200 + 同样的头、空 body。

        以前没有 do_HEAD,http.server 直接回 501 —— `curl -I`、多数监控探针
        (Uptime Kuma 一类)与部分反代健康检查都走 HEAD,会被判成"服务挂了"。
        """
        import http.client

        for path, expect_type in (("/", "text/html"), ("/js/core/api.js", "javascript")):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                conn.request("HEAD", path)
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200, f"HEAD {path} → {resp.status}")
                self.assertIn(expect_type, resp.getheader("Content-Type", ""))
                self.assertTrue(resp.getheader("Content-Length"),
                                f"HEAD {path} 缺 Content-Length")
                self.assertEqual(resp.read(), b"", f"HEAD {path} 不该有 body")
            finally:
                conn.close()

    def test_head_on_api_endpoint(self) -> None:
        """API 的 HEAD 也不该 501(健康检查常打 /api/health)。"""
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("HEAD", "/api/health")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")
        finally:
            conn.close()

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
