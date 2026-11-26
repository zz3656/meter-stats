"""日志脱敏护栏(标准库 unittest,零依赖)。

**背景**:前端大量用 `?token=` 拼图片/下载链接(见 AGENTS.md)。而错误分支里的
`log(f"... {handler.path}")` 会把**完整查询串**写进日志 —— 等于把会话 token 抄一份:
Docker 环境里 `docker logs` 谁都能看,报 issue 时也常整段贴日志。
实测复现:一次 500 错误(`X-API-Migration` 响应头写中文触发)把
`GET /api/admin/backup-download?zip_name=…&token=0203b1…` 整行写进了日志。

修法:`utils.api.mask_secret_query()` 把敏感参数值抹成 `***`,所有"记 path"的地方都过它。

运行:
    python3 -m unittest tests.test_log_redaction -v
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "MeterStats"))

from utils.api import mask_secret_query  # noqa: E402

METERSTATS = REPO / "MeterStats"


class TestMaskSecretQuery(unittest.TestCase):

    def test_masks_token_value(self) -> None:
        out = mask_secret_query("/api/admin/backup-download?zip_name=a.zip&token=deadbeefcafe")
        self.assertIn("token=***", out)
        self.assertNotIn("deadbeefcafe", out)
        # 非敏感参数要保留,方便排查
        self.assertIn("zip_name=a.zip", out)

    def test_masks_password_and_nas_pass(self) -> None:
        out = mask_secret_query("/api/auth/login?password=hunter2&nas_pass=s3cret&a=1")
        self.assertNotIn("hunter2", out)
        self.assertNotIn("s3cret", out)
        self.assertIn("password=***", out)
        self.assertIn("nas_pass=***", out)
        self.assertIn("a=1", out)

    def test_no_query_untouched(self) -> None:
        self.assertEqual(mask_secret_query("/api/health"), "/api/health")
        self.assertEqual(mask_secret_query(""), "")

    def test_first_param_is_secret(self) -> None:
        self.assertEqual(mask_secret_query("/api/x?token=abc"), "/api/x?token=***")


class TestLogSitesAreRedacted(unittest.TestCase):
    """源码级护栏:凡把请求 path 写进日志的地方都必须脱敏。"""

    LOG_WITH_PATH = re.compile(r'log\(f"[^"]*\{(?:handler\.|self\.)?path\}')

    def test_no_unmasked_path_in_logs(self) -> None:
        offenders = []
        for rel in ("app_handler.py", "routing.py"):
            src = (METERSTATS / rel).read_text(encoding="utf-8")
            for no, line in enumerate(src.split("\n"), 1):
                if self.LOG_WITH_PATH.search(line) and "mask_secret_query" not in line:
                    offenders.append(f"{rel}:{no}: {line.strip()[:80]}")
        self.assertEqual(offenders, [], "这些日志把请求 path(可能含 ?token=)原样写进日志")


if __name__ == "__main__":
    unittest.main()
