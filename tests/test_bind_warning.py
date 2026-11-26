"""启动时的「对外暴露」警示测试(标准库 unittest,零依赖)。

背景:这套服务的默认绑定是 `METER_BIND=0.0.0.0` —— 多台机器共用一个后端时
**必须**这样。代价是它对同网段所有机器可见,而服务**不走 HTTPS**:

- 局域网内的令牌可被嗅探(拿到就等于拿到会话)
- 登录限速是内存计数、按用户名计(换用户名可绕、重启清零)
- 一旦有人把端口映射到公网,外网也能打开登录页并爆破

原来启动日志里对此**一句提示都没有**。现在绑定到非回环地址时打一条 WARN,
让"我正在对外暴露"这件事在日志里看得见。

覆盖:
- `_is_loopback_host` / `_public_bind_notice` 的判定边界
- 警示文案必须点出:同网段可见 / 不走 HTTPS / 改默认口令 / 别映射公网 / 本机绑定做法
- 静态:main() 真的调用了它,且**在绑定成功之后**(端口占用时不该打误导性 WARN)

运行:
    python3 -m unittest tests.test_bind_warning -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
SERVER_PY = METERSTATS / "server.py"
sys.path.insert(0, str(METERSTATS))

import server  # noqa: E402


class TestLoopbackDetection(unittest.TestCase):
    LOOPBACK = ["127.0.0.1", "127.0.0.5", "::1", "[::1]", "localhost",
                "LOCALHOST", " 127.0.0.1 ", "0:0:0:0:0:0:0:1"]
    PUBLIC = ["0.0.0.0", "", "::", "192.168.1.5", "10.0.0.2", "meter.local",
              "::ffff:10.0.0.2"]

    def test_loopback_recognised(self) -> None:
        for h in self.LOOPBACK:
            self.assertTrue(server._is_loopback_host(h), "%r 应判为回环" % h)
            self.assertIsNone(server._public_bind_notice(h, 8765),
                              "%r 是回环,不该有警示" % h)

    def test_public_recognised(self) -> None:
        for h in self.PUBLIC:
            self.assertFalse(server._is_loopback_host(h), "%r 应判为对外" % h)
            self.assertIsNotNone(server._public_bind_notice(h, 8765),
                                 "%r 对外暴露却没警示" % h)

    def test_empty_bind_is_public(self) -> None:
        """空串在 HTTPServer 里等于绑定所有网卡 —— 必须按对外处理。"""
        self.assertFalse(server._is_loopback_host(""))
        self.assertIsNotNone(server._public_bind_notice("", 8765))

    def test_unknown_hostname_treated_as_public(self) -> None:
        """认不出的名字不能当作安全 —— 宁可多提醒。"""
        self.assertFalse(server._is_loopback_host("some-weird-host"))
        self.assertIsNotNone(server._public_bind_notice("some-weird-host", 8765))


class TestNoticeContent(unittest.TestCase):
    def setUp(self) -> None:
        self.msg = server._public_bind_notice("0.0.0.0", 8765) or ""

    def test_mentions_actual_bind(self) -> None:
        self.assertIn("0.0.0.0:8765", self.msg, "警示里要写清实际监听地址")

    def test_warns_about_lan_visibility(self) -> None:
        self.assertIn("同网段", self.msg)

    def test_warns_no_tls(self) -> None:
        self.assertIn("不走 HTTPS", self.msg)

    def test_warns_default_password(self) -> None:
        self.assertIn("admin123", self.msg, "没提默认口令必须改")

    def test_warns_about_port_forwarding(self) -> None:
        self.assertIn("公网", self.msg)

    def test_tells_how_to_bind_local_only(self) -> None:
        self.assertIn("METER_BIND=127.0.0.1", self.msg,
                      "没告诉用户只想本机访问该怎么做")

    def test_is_prefixed_as_warning(self) -> None:
        self.assertTrue(self.msg.startswith("[WARN]"), "日志里要能一眼看出是警告")


class TestWiringInMain(unittest.TestCase):
    def setUp(self) -> None:
        self.src = SERVER_PY.read_text(encoding="utf-8")

    def test_main_calls_notice_and_logs(self) -> None:
        self.assertRegex(
            self.src,
            r"(?m)^\s*_notice = _public_bind_notice\(bind_host, PORT\)",
            "main() 没有调用 _public_bind_notice",
        )
        self.assertRegex(self.src, r"(?m)^\s*log\(_notice\)",
                         "算出了警示却没写进日志")

    def test_notice_emitted_after_bind(self) -> None:
        """必须在 ThreadingHTTPServer(...) 之后 —— 端口占用会先抛 OSError,
        不该先打一条"我在监听 X"的误导性 WARN。"""
        bind_pos = self.src.index("ThreadingHTTPServer((bind_host, PORT)")
        notice_pos = self.src.index("_notice = _public_bind_notice(bind_host, PORT)")
        self.assertGreater(notice_pos, bind_pos,
                           "警示在绑定之前就打了 —— 绑定失败时会误导")


if __name__ == "__main__":
    unittest.main()
