"""门店切换回归测试(标准库 unittest,零依赖)。

覆盖 P1 的后端契约:
- GET /api/stores         → 带 all_stores 标记(前端据此决定是否显示切换器)
- GET /api/stores/current → 带 all_stores;不带 store 参数时落到后端默认店
- ?store= 参数决定读哪一家店的数据
- ?store= 参数决定写进哪一家店的文件
- 越权 403;门店不存在 404
- 引导端点(/api/stores、/api/stores/current)不带 store 参数时照常可用

运行:
    python3 -m unittest tests.test_store_switch -v
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from modules.stores import context  # noqa: E402
from modules.system.auth_handler import _SESSIONS, create_session  # noqa: E402
from modules.system.settings_handler import (  # noqa: E402
    get_settings,
    init_settings,
    save_settings,
)

import app_handler  # noqa: E402
import routing  # noqa: E402
from storage import DATA_FILES  # noqa: E402


class _ApiHandler:
    """最小 HTTP handler 桩(与 tests/test_store_api.py 同形)。"""

    def __init__(self, path: str, body: Optional[Dict[str, Any]] = None,
                 method: str = "GET", token: str = "") -> None:
        self.path = path
        self.command = method
        self.response_status: Optional[int] = None
        self.response_headers: Dict[str, str] = {}
        self.wfile = io.BytesIO()
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            self.rfile = io.BytesIO(raw)
            self.headers = {"Content-Length": str(len(raw))}
        else:
            self.rfile = io.BytesIO(b"")
            self.headers = {"Content-Length": "0"}
        if token:
            sep = "&" if "?" in path else "?"
            self.path = path + sep + "token=" + token

    def send_response(self, status: int) -> None:
        self.response_status = status

    def send_header(self, k: str, v: str) -> None:
        self.response_headers[k] = v

    def end_headers(self) -> None:
        pass

    @property
    def parsed(self) -> Any:
        raw = self.wfile.getvalue()
        return json.loads(raw) if raw else None


class StoreSwitchTestBase(unittest.TestCase):
    """基类:独立临时数据目录 + 真实会话 + 两店布局。"""

    def setUp(self) -> None:
        self._prev_enforce = routing.ENFORCE_AUTH
        self._prev_paths = app_handler.DATA_PATHS
        self._prev_sessions = dict(_SESSIONS)
        _SESSIONS.clear()
        routing.ENFORCE_AUTH = True
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.paths: Dict[str, Path] = {
            m: self.data_dir / fn for m, fn in DATA_FILES.items()
        }
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        init_settings(self.data_dir)
        self._write_settings()
        # 两店布局 → 门店闸进入严格模式
        for sid in ("main", "s002"):
            (self.data_dir / "stores" / sid).mkdir(parents=True, exist_ok=True)
        context.clear_current_store()

    def tearDown(self) -> None:
        routing.ENFORCE_AUTH = self._prev_enforce
        app_handler.DATA_PATHS = self._prev_paths
        context.clear_current_store()
        _SESSIONS.clear()
        _SESSIONS.update(self._prev_sessions)
        self.tmp.cleanup()

    # ---- 固定数据 ----

    def _users(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": 1, "username": "admin", "password": "x", "role": "admin",
                "name": "管理员", "enabled": True, "all_stores": True, "store_ids": [],
            },
            {
                "id": 2, "username": "emp", "password": "x", "role": "employee",
                "name": "员工", "enabled": True, "all_stores": False,
                "store_ids": ["s002"],
            },
        ]

    def _stores(self) -> List[Dict[str, Any]]:
        return [
            {"id": "main", "name": "总店", "code": "", "address": "",
             "active": True, "created_at": "2026-01-01T00:00:00"},
            {"id": "s002", "name": "国贸店", "code": "B002", "address": "国贸",
             "active": True, "created_at": "2026-01-02T00:00:00"},
        ]

    def _write_settings(self) -> None:
        settings = get_settings()
        settings["users"] = self._users()
        settings["stores"] = self._stores()
        save_settings(settings)

    # ---- 辅助 ----

    def _session(self, user: Dict[str, Any]) -> str:
        payload: Dict[str, Any] = {
            "id": user["id"], "username": user["username"],
            "role": user["role"], "name": user["name"],
        }
        if "all_stores" in user:
            payload["all_stores"] = user["all_stores"]
        if "store_ids" in user:
            payload["store_ids"] = user["store_ids"]
        return create_session(payload)

    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
              token: str = "") -> _ApiHandler:
        h = _ApiHandler(path, body, method, token=token)
        app_handler._do_api(method, h, h.path)  # type: ignore[no-untyped-call]
        return h

    def _seed_readings(self, store_id: str, rows: List[Dict[str, Any]]) -> None:
        """往某家店的 readings.json 写数据。"""
        path = self.data_dir / "stores" / store_id / "readings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def _read_store_readings(self, store_id: str) -> List[Dict[str, Any]]:
        path = self.data_dir / "stores" / store_id / "readings.json"
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return rows


class TestStoreSwitchFlags(StoreSwitchTestBase):
    """读接口补 all_stores 标记 + 后端默认店。"""

    def test_stores_list_reports_all_stores_true_for_admin(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("GET", "/api/stores", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["all_stores"])
        self.assertEqual(len(h.parsed["stores"]), 2)

    def test_stores_list_reports_all_stores_false_for_limited_user(self) -> None:
        tok = self._session(self._users()[1])
        h = self._call("GET", "/api/stores", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertFalse(h.parsed["all_stores"])
        self.assertEqual([s["id"] for s in h.parsed["stores"]], ["s002"])

    def test_current_store_falls_back_to_backend_default(self) -> None:
        """不带 store 参数 → 后端按用户范围解析出默认店(员工 → 他唯一的那家)。"""
        tok = self._session(self._users()[1])
        h = self._call("GET", "/api/stores/current", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertEqual(h.parsed["store_id"], "s002")
        self.assertFalse(h.parsed["all_stores"])

    def test_current_store_honours_explicit_store_param(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("GET", "/api/stores/current?store=s002", token=tok)
        self.assertEqual(h.response_status, 200)
        self.assertEqual(h.parsed["store_id"], "s002")

    def test_bootstrap_endpoints_work_without_store_param(self) -> None:
        """前端引导必须能在「当前店已失效」时也拿到门店列表 —— 否则用户锁死。"""
        tok = self._session(self._users()[0])
        for path in ("/api/stores", "/api/stores/current"):
            h = self._call("GET", path, token=tok)
            self.assertEqual(h.response_status, 200, path)


class TestStoreSwitchReadWrite(StoreSwitchTestBase):
    """?store= 决定读哪一家、写进哪一家。"""

    def setUp(self) -> None:
        super().setUp()
        self._seed_readings("main", [{"date": "2026-01-01", "hall": 10.0}])
        self._seed_readings("s002", [{"date": "2026-01-01", "hall": 99.0}])

    def test_readings_are_read_from_requested_store(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("GET", "/api/readings?store=s002", token=tok)
        self.assertEqual(h.response_status, 200)
        rows = h.parsed if isinstance(h.parsed, list) else h.parsed.get("data", [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["hall"]), 99.0)

    def test_readings_default_to_main_without_store_param(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("GET", "/api/readings", token=tok)
        self.assertEqual(h.response_status, 200)
        rows = h.parsed if isinstance(h.parsed, list) else h.parsed.get("data", [])
        self.assertEqual(float(rows[0]["hall"]), 10.0)

    def test_write_lands_in_requested_store_only(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("POST", "/api/readings?store=s002",
                       {"date": "2026-02-01", "hall": 5.0}, token=tok)
        self.assertEqual(h.response_status, 200)
        s002 = self._read_store_readings("s002")
        self.assertTrue(any(r.get("date") == "2026-02-01" for r in s002))
        main = self._read_store_readings("main")
        self.assertFalse(any(r.get("date") == "2026-02-01" for r in main))

    def test_limited_user_cannot_read_other_store(self) -> None:
        tok = self._session(self._users()[1])
        h = self._call("GET", "/api/readings?store=main", token=tok)
        self.assertEqual(h.response_status, 403)
        self.assertIn("无权访问门店", h.parsed["error"])

    def test_unknown_store_returns_404(self) -> None:
        tok = self._session(self._users()[0])
        h = self._call("GET", "/api/readings?store=nope", token=tok)
        self.assertEqual(h.response_status, 404)
        self.assertIn("门店不存在", h.parsed["error"])


if __name__ == "__main__":
    unittest.main()
