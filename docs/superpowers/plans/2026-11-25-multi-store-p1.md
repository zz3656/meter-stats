# 分店功能 P1 实施计划 —— 门店切换器 + 前端 `store` 参数贯通

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让前端能切换门店，并且**所有**后端请求都带上当前门店，使整个应用在多门店布局下真正按门店读写。

**Architecture:** 后端 P0 已经把「门店闸 + 按店读写」做完了（`routing._store_gate()` 认 `?store=` 查询参数）。P1 不动后端的隔离机制，只补一个前端要用的字段（`all_stores`）；主体工作在前端：新增 `js/core/storeContext.js` 作为**唯一的门店状态源**，`js/core/api.js::_request()` 把当前门店拼进每个请求，切店时把上一个门店的数据（State / 裸全局 / 离线缓存 / 报表缓存 / 充值归属缓存）清干净。

**Tech Stack:** Python 3.9+（零外部依赖，仅标准库）、纯 HTML/CSS/JS（无构建步骤）、`unittest`（存量 484 用例）+ node 行为验证（沿用 `tests/test_stores_frontend.py` 的 vm 沙箱范式）。

---

## Global Constraints

这些约束适用于**每一个** Task，不需要在 Task 里重复：

- **Python 3.9+**：新模块首行 `from __future__ import annotations`；**零外部依赖**（仅标准库）。
- **存储读写**统一走 `storage.load_json` / `storage.save_json`；写操作用 `storage.get_lock(model)`。
- **HTTP 响应**统一 `utils.send_json(handler, status, payload)`；读体 `utils.read_body(handler)`。
- **鉴权与门店闸**统一在 `routing._route()` 拦截；**新增接口默认就带鉴权 + 门店隔离**，不需要单独加。
- **前端 token 只从 `admin.js` 的 `currentAuthToken()` 取**。历史上 `token` / `meter_admin_token` / `meter_token` 三套键名，后两个是死键。**不要再直接读 `localStorage.getItem('token')`**（`api.js` 现有的几处本次一并收口）。
- **门店 ID 规则**：`[A-Za-z0-9_-]{1,32}`。后端用 `re.compile(r"\A[A-Za-z0-9_-]{1,32}\Z")`（`modules/stores/registry.py:38`）。**JS 里必须等价实现** —— JS 的 `$` 会匹配结尾换行符之前，与 Python 的 `\Z` 不等价（见 Task 2 Step 4 的写法）。
- **存量回归**：原有 **484** 个单元测试必须全部通过（`python3 -m unittest discover -s tests -v`）。AGENTS.md 里写的 147 已过时。
- **口径不变**：2026 年 6 月核对值 **71226.1 度**是自动化断言（`tests/test_monthly_report.py:313`），**不许改任何计算口径**。P1 不碰 `report.py`。
- **ruff ≤ 273 条、mypy ≤ 793 条**（当前基线，仓库本身不干净），**新文件必须 0 错**。mypy 正确口径是 `mypy . --exclude 'data/'`（仓库根旧版 `data/` 副本与 `MeterStats/server.py` 重名，裸跑直接失败）。
- **禁止手动编辑 `MeterStats/.data/` 或 `~/Library/Application Support/com.meter.stats/` 下的 JSON**。
- **提交用约定式提交**（feat/fix/refactor/docs/style/scope）。**`git add` 只写明确路径，禁用 `-A` / `.`**。
- **`MeterStats/VERSION` 本期不动**（0.5.0 已在 P0 定版；P1 是同一版本内的功能补齐，不再递增）。
- **fail-closed 统一口径**：查不到用户记录 = 拒绝（403），不回退放行。
- **权限先判、存在性后判**：探测未注册 ID 只能拿 403，不能从 403/404 差别摸到别家店是否存在。

---

## 本期的关键设计决策（实现时不要自行改口径）

| # | 决策 | 理由 |
|---|---|---|
| D1 | **门店只走 query 参数 `?store=`，不加 `X-Store` 头** | 设计文档 §3.2 明确「最终由前端统一放 query」；后端 `_requested_store()`（`routing.py:302`）只读 query。 |
| D2 | **`/api/stores*` 与 `/api/auth/*` 请求一律不带 `store`** | 见下方「锁死链路」，这是本期**最容易踩且最难排查**的坑。 |
| D3 | **门店选择存 `localStorage`，不存后端** | 后端门店是**请求级**上下文（每个请求带 `?store=`），不是会话状态。门店 ID 在全局注册表里，本地记住即可。 |
| D4 | **切换器可见条件：`all_stores === true` 或可见门店数 ≥ 2** | 总部账号即使只有 1 家店也要能看到「当前在哪家店」；单店员工没有可切的对象，不显示。 |
| D5 | **切店必须清 5 类缓存** | State / `window.CURRENT_*` / localStorage 离线缓存 / 报表缓存 / 充值归属缓存。漏一个就是「切到 B 店还显示 A 店数据」。 |
| D6 | **`admin.js` 的备份下载/删除 URL 不加 `store`** | 那是**全局**操作（按调用方的门店范围过滤，不按当前店过滤），加 `?store=` 没有收益，只会多一条失败路径。 |

### 锁死链路（Task 2 / Task 3 的核心约束）

```
管理员删掉了用户当前所在的门店 s002
  → 前端 localStorage 里还留着 s002
  → 前端请求 /api/stores?store=s002
  → 后端门店闸:该店不在注册表 → 404
  → 前端连「门店列表」都拿不到
  → 无从切店 → 用户永久卡死
```

所以 **`/api/stores` 与 `/api/stores/current` 必须能在「当前店已失效」时照常返回**。
同样的道理适用于 `/api/auth/me`：它带一个失效的 `?store=` → 404 → 前端判定「会话过期」→ **把用户踢出登录**，而真实原因只是门店被删了。

---

## 文件地图

| 文件 | 归属 Task | 职责 |
|---|---|---|
| `MeterStats/modules/stores/handler.py` | 1 | 两个读接口补 `all_stores` 字段 |
| `tests/test_store_switch.py` | 1 | **新建**：后端按店读写 + 越权 + 404 回归网 |
| `MeterStats/js/core/storeContext.js` | 2 | **新建**：门店状态源（当前店 / 列表 / 切店 / 清缓存 / 失效恢复）。**不含任何 DOM 操作** |
| `MeterStats/js/core/state.js` | 2 | 加 `State.reset()`；`init()` 的键列表补 `water` |
| `MeterStats/js/core/meterConfig.js` | 2 | 加 `resetChargeAttrCache()` |
| `tests/test_store_switch_frontend.py` | 2 | **新建**：node 沙箱验证切店清缓存 + 失效恢复 |
| `MeterStats/js/core/api.js` | 3 | `_request()` 拼 `store=`；store-free 白名单；6 处裸 `fetch` 补 `store`；收口 token 读取；合并重复的 `var backup` |
| `MeterStats/js/shared/accessibility.js` | 3 | `api()` 辅助函数补 `store` |
| `MeterStats/js/shared/image_settings.js` | 3 | 2 处裸 `fetch` 补 `store` |
| `MeterStats/js/helpers/utils.js` | 3 | `getDutyImageUrl()` / `uploadImages()` 补 `store` |
| `MeterStats/js/modules/storeSwitcher.js` | 4 | **新建**：侧栏切换器渲染 + 事件 |
| `MeterStats/index.html` | 4 | 切换器 DOM + 两个新 `<script>` |
| `MeterStats/style.css` | 4 | 切换器样式 |
| `MeterStats/admin.js` | 4 | `setLoggedIn()` 先 `await StoreContext.init()` 再 `loadAppData()`；`clearAuth()` 重置门店上下文 |
| `tests/test_store_switcher_ui.py` | 4 | **新建**：切换器接线回归（**不写进 `test_stores_frontend.py`** —— 那个文件归 Task 3，两边并行写会撞 git 冲突） |

**并行约束**：
- **Task 1 ∥ Task 2 ∥ Task 3 可并行** —— 三者的文件互不重叠，各自有独立的新测试文件。
- **Task 4 必须串在 Task 2 + Task 3 之后** —— 它要用 `StoreContext` 的 API，也要 `?store=` 已经在跑。
- Task 4 的测试写进**新文件** `tests/test_store_switcher_ui.py`，不追加到 `tests/test_stores_frontend.py`（那个文件归 Task 3）。

---

### Task 1: 后端 —— 门店上下文读接口补字段

**Files:**
- Modify: `MeterStats/modules/stores/handler.py`（`handle_get_stores` 约 275-292 行；`handle_get_current_store` 约 295-312 行）
- Test: `tests/test_store_switch.py`（新建）

**Interfaces:**
- Consumes: `registry.list_stores()`、`registry.get_store()`、`_visible_store_ids(sess)`（同文件已有，无需新增 import）。
- Produces:
  - `GET /api/stores` → `{"ok": true, "stores": [...], "all_stores": true|false}`
  - `GET /api/stores/current` → `{"ok": true, "store_id": "main", "store": {...}, "all_stores": true|false}`
  - `all_stores` 的口径 = `_visible_store_ids(sess)` 的第一个返回值（该用户是否可访问全部门店）。

- [ ] **Step 1: 先写失败测试**

新建 `tests/test_store_switch.py`，内容如下（照抄 `tests/test_store_api.py` 的夹具写法 —— 真实会话 + `ENFORCE_AUTH=True`）：

```python
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
        return json.loads(path.read_text(encoding="utf-8"))


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_store_switch -v
```

Expected: `test_stores_list_reports_all_stores_true_for_admin` 等 **4 个 `all_stores` 断言 FAIL**（`KeyError: 'all_stores'`），其余用例通过（后端 P0 已实现按店读写）。

- [ ] **Step 3: 后端补字段**

修改 `MeterStats/modules/stores/handler.py`：

`handle_get_stores` 末尾，把

```python
    send_json(handler, 200, {"ok": True, "stores": stores})
```

改成

```python
    # all_stores:调用方是不是总部账号(可见全部门店)。
    # 前端据此决定要不要显示门店切换器 —— 总部账号即使只有 1 家店也要能看到
    # 「当前在哪家店」,所以不能只看 stores 的条数。
    send_json(handler, 200, {"ok": True, "stores": stores, "all_stores": all_stores})
```

`handle_get_current_store` 末尾，把

```python
    send_json(handler, 200, {"ok": True, "store_id": store_id, "store": store})
```

改成

```python
    all_stores, _ = _visible_store_ids(sess)
    send_json(handler, 200, {"ok": True, "store_id": store_id, "store": store,
                             "all_stores": all_stores})
```

- [ ] **Step 4: 运行测试确认全绿**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_store_switch -v
```

Expected: 全部 OK（9 个用例）。

- [ ] **Step 5: 跑存量回归**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest discover -s tests -v 2>&1 | tail -5
```

Expected: `OK`，用例数 ≥ 484 + 9。

- [ ] **Step 6: 提交**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
git add MeterStats/modules/stores/handler.py tests/test_store_switch.py
git commit -m "feat(stores): 门店读接口补 all_stores 标记,前端据此显示切换器"
```

---

### Task 2: 前端核心 —— 门店上下文模块

**Files:**
- Create: `MeterStats/js/core/storeContext.js`
- Modify: `MeterStats/js/core/state.js`（加 `State.reset()`；`init()` 键列表补 `water`）
- Modify: `MeterStats/js/core/meterConfig.js`（加 `resetChargeAttrCache()`）
- Test: `tests/test_store_switch_frontend.py`（新建）

**Interfaces:**
- Consumes: `Api.stores.list()` / `Api.stores.current()`（Task 3 会让它们**不带** `store` 参数 —— 本模块依赖这一点，必须与 Task 3 一起验收）。
- Produces —— `window.StoreContext` 的公开 API（Task 3 / Task 4 都用它）：

```js
StoreContext.getStoreId()      // → string  当前门店 ID('' = 尚未确定)
StoreContext.getStores()       // → Array   当前用户可见的门店列表
StoreContext.getAllStores()    // → boolean 是否总部账号
StoreContext.isReady()         // → boolean bootstrap 是否完成
StoreContext.hasNoStore()      // → boolean 账号未分配门店(空态)
StoreContext.init(reason)      // → Promise<string>  引导;reason 透传给监听者
StoreContext.switchTo(id)      // → Promise<boolean> 切店
StoreContext.reset()           // → void    登出时清空本地状态
StoreContext.clearCaches()     // → void    清 5 类缓存
StoreContext.handleStoreError(status, text)  // → void  门店失效恢复入口
StoreContext.onChange(cb)      // → Function 订阅;返回退订函数
                                  // cb(state, reason)  reason ∈ 'init'|'switch'|'recovered'|'no-store'|'reset'
```

- [ ] **Step 1: 先写失败测试（node 沙箱）**

新建 `tests/test_store_switch_frontend.py`。沿用 `tests/test_stores_frontend.py` 的 vm 沙箱范式：

```python
"""门店切换前端行为验证(标准库 unittest,零依赖)。

用 node 的 vm 沙箱跑真实的 js/core/storeContext.js,验证:
- 切店后 State / 裸全局 / 离线缓存 / 报表缓存 / 充值归属缓存全被清空
- 门店 ID 校验与后端 \A[A-Za-z0-9_-]{1,32}\Z 等价(尾随换行必须被拒)
- 失效门店(被删/权限被收回)会触发恢复,而不是把用户踢出登录
- 引导端点不带 store 参数(锁死链路)

运行:
    python3 -m unittest tests.test_store_switch_frontend -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
STORE_CONTEXT_JS = METERSTATS / "js" / "core" / "storeContext.js"

_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

const sandbox = {
  console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
  Promise, RegExp, Error, isNaN, parseInt, parseFloat,
  localStorage: (function () {
    const map = {};
    return {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null),
      setItem: (k, v) => { map[k] = String(v); },
      removeItem: (k) => { delete map[k]; },
      __dump: () => map,
    };
  })(),
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// ---- 替身:State / 裸全局 / 报表缓存 / 充值归属缓存 ----
const StateData = {
  readings: [{ date: '2026-01-01', hall: 1 }],
  charges: [{ id: 1 }],
  water: [{ date: '2026-01-01' }],
  items: [{ id: 1 }],
  purchases: [{ id: 1 }],
  duty: [{ id: 1 }],
};
sandbox.State = {
  get: (k) => StateData[k],
  set: (k, v) => { StateData[k] = v; },
  reset: () => { for (const k of Object.keys(StateData)) StateData[k] = []; },
};
sandbox.CURRENT_READINGS = [{ date: '2026-01-01', hall: 1 }];
sandbox.CURRENT_CHARGES = [{ id: 1 }];
sandbox.CURRENT_WATER_READINGS = [];
sandbox.CURRENT_ITEMS = [];
sandbox.CURRENT_PURCHASES = [];
sandbox.CURRENT_DUTY = [];
sandbox._currentReport = { month: '2026-01' };
sandbox._currentYearly = { year: 2026 };
sandbox._currentUtilities = { month: '2026-01' };
sandbox.__chargeAttrCache = { sig: 'x', map: [] };
sandbox.resetChargeAttrCache = function () { sandbox.__chargeAttrCache = null; };

// ---- 替身:Api ----
const calls = [];
sandbox.__calls = calls;
sandbox.Api = {
  stores: {
    list: async () => { calls.push('/api/stores'); return { ok: true, stores: [
      { id: 'main', name: '总店' }, { id: 's002', name: '国贸店' },
    ], all_stores: true }; },
    current: async () => { calls.push('/api/stores/current'); return { ok: true, store_id: 'main', all_stores: true }; },
  },
};

vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/storeContext.js'), 'utf8'),
                sandbox, { filename: 'storeContext.js' });

(async () => {
  const out = {};
  await sandbox.StoreContext.init();
  out.storeIdAfterInit = sandbox.StoreContext.getStoreId();

  // 切店 → 缓存必须被清空
  const ok = await sandbox.StoreContext.switchTo('s002');
  out.switched = ok;
  out.storeIdAfterSwitch = sandbox.StoreContext.getStoreId();
  out.stateAfter = JSON.parse(JSON.stringify(StateData));
  out.globalsAfter = {
    readings: sandbox.CURRENT_READINGS.length,
    charges: sandbox.CURRENT_CHARGES.length,
    items: sandbox.CURRENT_ITEMS.length,
    purchases: sandbox.CURRENT_PURCHASES.length,
    duty: sandbox.CURRENT_DUTY.length,
  };
  out.reportCaches = {
    report: sandbox._currentReport,
    yearly: sandbox._currentYearly,
    utilities: sandbox._currentUtilities,
  };
  out.chargeAttrCache = sandbox.__chargeAttrCache;
  out.offlineCache = {
    readings: sandbox.localStorage.getItem('meter_readings_v1'),
    charges: sandbox.localStorage.getItem('meter_charges_v1'),
  };

  // ID 校验:后端 \A..\Z 不接受尾随换行,JS 的 $ 会 —— 必须等价
  out.idValid = sandbox.StoreContext.isValidStoreId('s002');
  out.idNewline = sandbox.StoreContext.isValidStoreId('s002\n');
  out.idSlash = sandbox.StoreContext.isValidStoreId('../etc');
  out.idTooLong = sandbox.StoreContext.isValidStoreId('a'.repeat(33));

  // 引导请求不得带 store(由 api.js 负责,这里只验证 StoreContext 不自己塞)
  out.calls = calls.slice();
  console.log(JSON.stringify(out));
})();
"""


class TestStoreContextBehaviour(unittest.TestCase):
    """用真实的 js/core/storeContext.js 跑一遍(需要 node,缺失则跳过)。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env.update(MS_ROOT=str(METERSTATS))
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_switch_clears_all_store_scoped_caches(self) -> None:
        """切店后上一个店的数据必须全部清干净 —— 漏一个就是跨店显示。"""
        out = self._run()
        self.assertTrue(out["switched"])
        self.assertEqual(out["storeIdAfterSwitch"], "s002")
        for key, value in out["stateAfter"].items():
            self.assertEqual(value, [], "State.%s 没被清空" % key)
        for key, value in out["globalsAfter"].items():
            self.assertEqual(value, 0, "CURRENT_%s 没被清空" % key.upper())
        self.assertIsNone(out["reportCaches"]["report"])
        self.assertIsNone(out["reportCaches"]["yearly"])
        self.assertIsNone(out["reportCaches"]["utilities"])
        self.assertIsNone(out["chargeAttrCache"])
        self.assertIsNone(out["offlineCache"]["readings"])
        self.assertIsNone(out["offlineCache"]["charges"])

    def test_store_id_validation_matches_backend(self) -> None:
        """前端校验必须与后端 \\A[A-Za-z0-9_-]{1,32}\\Z 等价。"""
        out = self._run()
        self.assertTrue(out["idValid"])
        self.assertFalse(out["idNewline"], "尾随换行必须被拒(JS 的 $ 会放行)")
        self.assertFalse(out["idSlash"])
        self.assertFalse(out["idTooLong"])

    def test_bootstrap_calls_do_not_carry_store(self) -> None:
        out = self._run()
        self.assertIn("/api/stores", out["calls"])
        self.assertIn("/api/stores/current", out["calls"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_store_switch_frontend -v
```

Expected: FAIL —— `js/core/storeContext.js` 不存在（node 报 MODULE_NOT_FOUND，断言失败）。

- [ ] **Step 3: `State.reset()` + `init()` 键列表**

修改 `MeterStats/js/core/state.js`。

把

```js
        /** 初始化所有数据为 [] */
        init: function() {
            var keys = ["readings", "charges", "items", "purchases", "duty", "settings"];
            for (var i = 0; i < keys.length; i++) {
                if (data[keys[i]] === undefined) data[keys[i]] = [];
            }
        },
```

改成

```js
        /** 初始化所有数据为 [] */
        init: function() {
            // "water" 必须在列表里:renderAll() 会 State.set("water", …),
            // 漏了它 → State.get("water") 初始是 undefined,
            // 渲染水电表时 .sort() 直接抛 TypeError。
            var keys = ["readings", "charges", "water", "items", "purchases", "duty", "settings"];
            for (var i = 0; i < keys.length; i++) {
                if (data[keys[i]] === undefined) data[keys[i]] = [];
            }
        },

        /**
         * 清空所有数据(切门店时调用)。
         *
         * 必须连报表缓存一起清:_currentReport / _currentYearly / _currentUtilities
         * 存的是上一个门店的月报/年报/水电报表,不清 → 切店后「复制表格」复制的是
         * 上一家店的数字。
         */
        reset: function() {
            data = {};
            init();
            _currentReport = null;
            _currentYearly = null;
            _currentUtilities = null;
        },
```

- [ ] **Step 4: `resetChargeAttrCache()`**

修改 `MeterStats/js/core/meterConfig.js`。找到

```js
let _chargeAttrCache = null;
```

在它**后面**紧接着加：

```js
/**
 * 清空充值归属缓存(切门店时调用)。
 *
 * 缓存里是上一家店的表底序列与充值记录算出来的归属区间。
 * 它的签名(sig)带数据内容,理论上换店自然失配 —— 但那是「碰巧对」,
 * 不该依赖:显式清掉,换店就不再有任何跨店残留。
 */
function resetChargeAttrCache() {
    _chargeAttrCache = null;
}
window.resetChargeAttrCache = resetChargeAttrCache;
```

- [ ] **Step 5: 新建 `MeterStats/js/core/storeContext.js`**

内容如下（完整文件）：

```javascript
/**
 * 门店上下文(P1)—— 当前门店 + 可见门店列表 + 切店事件。
 *
 * 这是前端**唯一的**门店状态源。任何地方想知道「现在是哪家店」都问这里,
 * 不要自己存一份 —— 两份状态必然会不同步。
 *
 * 设计要点(每条都对应后端的既有行为,别凭印象改):
 *
 * 1. **门店选择存在 localStorage,不存后端。**
 *    后端的门店是「每个请求带 ?store=」的**请求级**上下文,不是会话状态
 *    (见 routing._store_gate / _requested_store)。门店 ID 在全局注册表里,
 *    本地记住即可;存后端会导致换浏览器要重新切店。
 *
 * 2. **引导端点(/api/stores、/api/stores/current)必须能不带 store 参数调用。**
 *    锁死链路:管理员删掉了用户当前所在的门店 → 前端还留着那个 ID →
 *    列表请求带着它 → 后端 404 → 连门店列表都拿不到 → 无从切店 → 用户永久卡死。
 *    所以「取列表」这件事永远不能依赖「当前店是有效的」。
 *
 * 3. **切店必须清干净上一家店的数据。**
 *    State / window.CURRENT_* / localStorage 离线缓存 / 报表缓存 / 充值归属缓存,
 *    全都要清。漏一个就出现「切到 B 店,页面还显示 A 店的数据」。
 *    离线缓存(meter_readings_v1 / meter_charges_v1)最阴险:后端不可用时会
 *    回退读它,不清就是把 A 店的数据当成 B 店的显示出来。
 *
 * 4. **门店 ID 必须先校验再拼进 URL。**
 *    后端会校验(registry.is_valid_store_id),前端也校验一次:
 *    不把任意字符串原样透传进 ?store=。
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'meter_current_store';
  // 后端用 re.compile(r"\A[A-Za-z0-9_-]{1,32}\Z")。
  // ⚠️ JS 的 $ 会匹配「结尾换行符之前」,与 Python 的 \Z 不等价 ——
  //    "s002\n" 在 JS 里能通过 /^[...]{1,32}$/,在 Python 里通不过。
  //    所以这里不用 ^...$,改成「长度检查 + 逐字符白名单」。
  var STORE_ID_MAX_LEN = 32;

  var state = {
    storeId: '',        // 当前门店 ID('' = 还没定)
    stores: [],         // 当前用户可见的门店列表
    allStores: false,   // 是否总部账号(all_stores=true)
    ready: false,       // bootstrap 是否完成
    noStore: false,     // 账号未分配门店(要显示空态)
    recovering: false,  // 失效恢复进行中(防重入)
  };

  var listeners = [];

  // ===== 基础工具 =====

  /**
   * 门店 ID 是否合法 —— 与后端 registry.is_valid_store_id 等价。
   * 暴露成公开方法:测试与其它模块要用同一套口径。
   */
  function isValidStoreId(id) {
    if (typeof id !== 'string') return false;
    if (id.length < 1 || id.length > STORE_ID_MAX_LEN) return false;
    for (var i = 0; i < id.length; i++) {
      var ch = id.charAt(i);
      var ok = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')
            || (ch >= '0' && ch <= '9') || ch === '_' || ch === '-';
      if (!ok) return false;
    }
    return true;
  }

  function _localStorage() {
    try { return window.localStorage; } catch (e) { return null; }
  }

  function _readPersisted() {
    var ls = _localStorage();
    if (!ls) return '';
    try { return String(ls.getItem(STORAGE_KEY) || ''); } catch (e) { return ''; }
  }

  function _persist(id) {
    var ls = _localStorage();
    if (!ls) return;
    try {
      if (id) ls.setItem(STORAGE_KEY, id);
      else ls.removeItem(STORAGE_KEY);
    } catch (e) { /* 隐私模式等,忽略 */ }
  }

  /** 离线缓存键。accessibility.js 里是顶层 const,加载顺序在���文件之后,
   *  这里用 try/catch 兜底(取不到时用字面量)。 */
  function _offlineCacheKeys() {
    var readings = 'meter_readings_v1';
    var charges = 'meter_charges_v1';
    try { readings = STORAGE_KEY_READINGS; } catch (e) { /* 尚未加载 */ }
    try { charges = STORAGE_KEY_CHARGES; } catch (e) { /* 尚未加载 */ }
    return { readings: readings, charges: charges };
  }

  function _hasStore(id) {
    if (!id) return false;
    for (var i = 0; i < state.stores.length; i++) {
      if (String(state.stores[i].id) === id) return true;
    }
    return false;
  }

  function _notify(reason) {
    var snapshot = {
      storeId: state.storeId,
      stores: state.stores.slice(),
      allStores: state.allStores,
      ready: state.ready,
      noStore: state.noStore,
    };
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](snapshot, reason || 'init'); } catch (e) {
        console.warn('门店上下文监听器抛错:', e);
      }
    }
  }

  // ===== 缓存清理 =====

  /**
   * 清掉上一家店留在前端的全部痕迹。
   *
   * 5 类,少一类就是一次跨店串数据:
   *   1. State 里的业务数据(readings/charges/water/items/purchases/duty)
   *   2. 裸全局快照 window.CURRENT_*(报表模块读的是它们,不是 State)
   *   3. localStorage 离线缓存(后端不可用时的回退数据源 —— 最阴险的一个)
   *   4. 报表缓存(上一个店的月报/年报/水电报表)
   *   5. 充值归属缓存(上一个店的表底序列算出来的归属区间)
   */
  function clearCaches() {
    // 1. State
    try {
      if (typeof State !== 'undefined' && State && typeof State.reset === 'function') {
        State.reset();
      }
    } catch (e) { console.warn('清理 State 失败:', e); }
    // 2. 裸全局快照
    window.CURRENT_READINGS = [];
    window.CURRENT_CHARGES = [];
    window.CURRENT_WATER_READINGS = [];
    window.CURRENT_ITEMS = [];
    window.CURRENT_PURCHASES = [];
    window.CURRENT_DUTY = [];
    // 3. 离线缓存
    var ls = _localStorage();
    if (ls) {
      var keys = _offlineCacheKeys();
      try { ls.removeItem(keys.readings); } catch (e) { /* 忽略 */ }
      try { ls.removeItem(keys.charges); } catch (e) { /* 忽略 */ }
    }
    // 4. 报表缓存
    try {
      if (typeof resetReportCaches === 'function') resetReportCaches();
      else {
        window._currentReport = null;
        window._currentYearly = null;
        window._currentUtilities = null;
      }
    } catch (e) { console.warn('清理报表缓存失败:', e); }
    // 5. 充值归属缓存
    try {
      if (typeof resetChargeAttrCache === 'function') resetChargeAttrCache();
    } catch (e) { console.warn('清理充值归属缓存失败:', e); }
  }

  // ===== 对外 API =====

  var StoreContext = {
    /** 当前门店 ID('' = 尚未确定) */
    getStoreId: function () { return state.storeId; },

    /** 当前用户可见的门店列表 */
    getStores: function () { return state.stores.slice(); },

    /** 是否总部账号(all_stores=true) */
    getAllStores: function () { return state.allStores; },

    /** bootstrap 是否完成 */
    isReady: function () { return state.ready; },

    /** 账号未分配门店(前端要显示空态,而不是一屏报错) */
    hasNoStore: function () { return state.noStore; },

    /** 门店 ID 合法性(与后端同一套口径) */
    isValidStoreId: isValidStoreId,

    /** 订阅变更。返回退订函数。cb(state, reason) */
    onChange: function (cb) {
      if (typeof cb !== 'function') return function () {};
      listeners.push(cb);
      return function () {
        var i = listeners.indexOf(cb);
        if (i >= 0) listeners.splice(i, 1);
      };
    },

    /**
     * 引导:取可见门店列表 + 后端默认店,决定当前该待在哪家店。
     *
     * 选店规则(优先级从高到低):
     *   1. localStorage 里记住的店 —— 但必须在可见列表里,否则作废
     *   2. 后端 /api/stores/current 给的默认店(按用户权限解析出来的)
     *   3. 都没有 → 当前店为空(账号未分配门店)
     */
    init: function (reason) {
      var self = this;
      return (async function () {
        var listRes = null, curRes = null, listErr = null, curErr = null;
        try { listRes = await Api.stores.list(); } catch (e) { listErr = e; }
        try { curRes = await Api.stores.current(); } catch (e) { curErr = e; }

        // 列表拿不到 → 可能是「账号未分配门店」(403),也可能后端挂了
        if (listErr || !listRes || listRes.ok === false) {
          var msg = (listErr && listErr.message) || (listRes && listRes.error) || '';
          state.stores = [];
          state.allStores = false;
          state.noStore = String(msg).indexOf('未分配门店') >= 0;
          state.storeId = '';
          _persist('');
          state.ready = true;
          _notify(state.noStore ? 'no-store' : (reason || 'init'));
          return '';
        }

        state.stores = listRes.stores || [];
        state.allStores = !!listRes.all_stores;
        state.noStore = state.stores.length === 0;

        var picked = '';
        var remembered = _readPersisted();
        if (isValidStoreId(remembered) && _hasStore(remembered)) {
          picked = remembered;
        } else if (curRes && curRes.ok !== false && isValidStoreId(String(curRes.store_id || ''))) {
          picked = String(curRes.store_id);
        }
        state.storeId = picked;
        _persist(picked);
        state.ready = true;
        _notify(reason || 'init');
        return picked;
      })();
    },

    /**
     * 切店。返回 false 表示拒绝(非法 ID / 不在可见列表里)。
     *
     * 只做「换店 + 清缓存 + 通知」;**不负责重新拉数据** ——
     * 数据刷新由 UI 层(切换器)订阅 onChange 后统一触发,
     * 避免这里和 UI 各刷一次。
     */
    switchTo: function (id) {
      var sid = String(id == null ? '' : id).trim();
      if (!isValidStoreId(sid)) return Promise.resolve(false);
      if (!_hasStore(sid)) return Promise.resolve(false);
      if (sid === state.storeId) return Promise.resolve(true);
      _persist(sid);
      state.storeId = sid;
      clearCaches();
      _notify('switch');
      return Promise.resolve(true);
    },

    /** 登出时清空本地状态(门店选择也清掉 —— 换人登录不该继承上一家店) */
    reset: function () {
      state.storeId = '';
      state.stores = [];
      state.allStores = false;
      state.ready = false;
      state.noStore = false;
      _persist('');
      _notify('reset');
    },

    /** 清缓存(对外暴露,便于测试与特殊场景) */
    clearCaches: clearCaches,

    /**
     * 门店失效恢复入口 —— 由 api.js 在收到 403/404 且文案指向门店时调用。
     *
     * 两种情况要分开处理:
     *   - 「无权访问门店」/「门店不存在」:当前选中的店没了或权限被收回了
     *     → 退回后端默认店,重新引导,重新拉数据。
     *   - 「未分配门店」:账号被管理员取消了门店,不是「切错店」
     *     → 置空态,不重试。
     */
    handleStoreError: function (status, text) {
      var msg = String(text || '');
      if (state.recovering) return;
      if (msg.indexOf('未分配门店') >= 0) {
        state.storeId = '';
        state.stores = [];
        state.allStores = false;
        state.noStore = true;
        state.ready = true;
        _persist('');
        _notify('no-store');
        return;
      }
      var storeBroken = (status === 404 && msg.indexOf('门店不存在') >= 0)
                    || (status === 403 && msg.indexOf('无权访问门店') >= 0);
      if (!storeBroken) return;
      state.recovering = true;
      state.storeId = '';
      _persist('');
      this.init('recovered').then(function () {
        state.recovering = false;
      }, function () {
        state.recovering = false;
      });
    },
  };

  window.StoreContext = StoreContext;
})();
```

> **注意**：`resetReportCaches()` 由 Task 2 的 Step 3 挂在 `state.js` 里（把 `_currentReport` / `_currentYearly` / `_currentUtilities` 清掉）。Step 3 里已通过 `State.reset()` 一并处理，因此 `clearCaches()` 里的 `resetReportCaches` 分支只是兜底 —— 两者都留着无害。

- [ ] **Step 6: 运行测试确认全绿**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_store_switch_frontend -v
```

Expected: 3 个用例全部 OK。

- [ ] **Step 7: 跑存量回归**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest discover -s tests -v 2>&1 | tail -5
```

Expected: `OK`（≥ 484 + 9 + 3）。

- [ ] **Step 8: 提交**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
git add MeterStats/js/core/storeContext.js MeterStats/js/core/state.js MeterStats/js/core/meterConfig.js tests/test_store_switch_frontend.py
git commit -m "feat(store): 新增门店上下文模块,切店时清空跨店缓存"
```

---

### Task 3: 前端 API 层 —— `store` 参数贯通

**Files:**
- Modify: `MeterStats/js/core/api.js`
- Modify: `MeterStats/js/shared/accessibility.js`
- Modify: `MeterStats/js/shared/image_settings.js`
- Modify: `MeterStats/js/helpers/utils.js`

**Interfaces:**
- Consumes: `window.StoreContext.getStoreId()`、`window.StoreContext.handleStoreError(status, text)`（Task 2 产出）。
- Produces: 每一个 `/api/*` 请求都带 `?store=<当前店>`，**除了** store-free 白名单里的端点。

- [ ] **Step 1: `api.js` —— 加 store 白名单与拼装函数**

修改 `MeterStats/js/core/api.js`。在 `var Api = (() => {` 之后、`function _request` 之前插入：

```javascript
    // ===== 门店参数 =====

    /**
     * 这些端点**不带** store 参数。理由各不相同,别随手往里加:
     *
     * - /api/health /api/version —— 公开端点,与门店无关。
     * - /api/auth/* —— 身份端点。带一个已失效的 store → 404 →
     *   /api/auth/me 失败 → 前端判定「会话过期」→ 把用户踢出登录,
     *   而真实原因只是当前门店被删了。
     * - /api/stores* —— 引导端点。必须能在「当前店已失效」时照常返回,
     *   否则用户锁死(连门店列表都拿不到 → 无从切店 → 永远出不来)。
     */
    function _isStoreFree(path) {
        var p = String(path || '').split('?')[0];
        if (p === '/api/health' || p === '/api/version') return true;
        if (p.indexOf('/api/auth/') === 0) return true;
        if (p === '/api/stores' || p.indexOf('/api/stores/') === 0) return true;
        return false;
    }

    /** 当前门店 ID。拿不到 / 不合法 → 空串(不带参数,让后端按用户范围默认)。 */
    function _currentStoreId() {
        try {
            if (typeof StoreContext === 'undefined' || !StoreContext) return '';
            var id = StoreContext.getStoreId();
            if (!id) return '';
            // 后端 registry.is_valid_store_id: \A[A-Za-z0-9_-]{1,32}\Z
            if (!/^[A-Za-z0-9_-]{1,32}$/.test(id)) return '';
            if (/[^A-Za-z0-9_-]/.test(id)) return '';
            return id;
        } catch (e) {
            return '';
        }
    }

    /** query 里是不是已经有 store 参数了(避免重复拼)。 */
    function _hasStoreParam(path) {
        var q = String(path || '').split('?')[1];
        if (!q) return false;
        var parts = q.split('&');
        for (var i = 0; i < parts.length; i++) {
            var kv = parts[i].split('=');
            var name = kv[0];
            try { name = decodeURIComponent(name); } catch (e) { /* 原样比 */ }
            if (name === 'store') return true;
        }
        return false;
    }

    /** 给请求路径拼上当前门店。 */
    function _appendStore(path) {
        if (_isStoreFree(path)) return path;
        if (_hasStoreParam(path)) return path;
        var store = _currentStoreId();
        if (!store) return path;
        var separator = path.indexOf('?') !== -1 ? '&' : '?';
        return path + separator + 'store=' + encodeURIComponent(store);
    }

    /** 统一取 token —— 只走 admin.js 的 currentAuthToken()(AGENTS.md 的约定)。 */
    function _authToken() {
        try {
            if (typeof currentAuthToken === 'function') {
                var t = currentAuthToken();
                if (t) return t;
            }
        } catch (e) { /* admin.js 还没加载 */ }
        try {
            if (typeof ADMIN_TOKEN !== 'undefined' && ADMIN_TOKEN) return ADMIN_TOKEN;
        } catch (e) { /* ignore */ }
        try { return localStorage.getItem('token') || ''; } catch (e) { return ''; }
    }
```

- [ ] **Step 2: `api.js` —— `_request()` 拼 store + 失效转交**

把 `_request` 改成：

```javascript
    function _request(method, path, body) {
        var opts = {
            method: method,
            headers: { 'Content-Type': 'application/json' }
        };
        if (body) opts.body = JSON.stringify(body);

        // token:只走 admin.js 的 currentAuthToken()(AGENTS.md 约定)
        var token = _authToken();
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;

        // 后端 auth_handler.py 从 query param 提取 token
        // 如果路径不含 token，追加 query param 以兼容后端
        if (token && path.indexOf('token=') === -1) {
            var separator = path.indexOf('?') !== -1 ? '&' : '?';
            path = path + separator + 'token=' + encodeURIComponent(token);
        }

        // 拼当前门店(store-free 端点除外)
        path = _appendStore(path);

        // path 已包含 '/api' 前缀（如 '/api/readings'），不能再拼一次，
        // 否则会请求 /api/api/xxx —— 后端无此路由，直接断开连接，
        // WKWebView/浏览器里表现为 "TypeError: Load failed"。
        return fetch(path, opts).then(function(res) {
            return res.json().then(function(data) {
                if (!res.ok) {
                    // 门店失效(被删 / 权限被收回)→ 交给门店上下文恢复。
                    // 不在这里处理:恢复要重新引导 + 重拉数据,得由上层统一做。
                    if (typeof StoreContext !== 'undefined' && StoreContext
                        && typeof StoreContext.handleStoreError === 'function') {
                        try {
                            StoreContext.handleStoreError(res.status, data && data.error);
                        } catch (e) { /* 恢复失败不掩盖原始错误 */ }
                    }
                    throw new Error(data.error || '请求失败');
                }
                return data;
            });
        });
    }
```

- [ ] **Step 3: `api.js` —— 合并重复的 `var backup` 并给裸 fetch 补 store**

`api.js` 里 `var backup` 声明了**两次**（约 127 行与 174 行），第二次赋值覆盖第一次 →
`Api.backup.doRestore` 实际是 `undefined`，`js/modules/backup.js:10` 的 `doRestore()` 一调就抛
`TypeError: Api.backup.doRestore is not a function`（目前 UI 没调用它，所以没爆）。
把**第一处** `backup` 整块删掉，把**第二处**改成下面这一份（两个方法都保留，名字都可用）：

```javascript
    // 备份/恢复 API —— 独立于 admin，数据管理页面用。
    //
    // ⚠️ 这里原来声明过两次 var backup,后者覆盖前者 → Api.backup.doRestore 是
    // undefined,js/modules/backup.js 的 doRestore() 一调就抛 TypeError。
    //   合并成一份,两个方法名都留着(doRestore / restore 是同一件事)。
    var backup = {
        doBackup: function() { return _request('POST', '/api/backup'); },
        doRestore: function(file) { return restoreUpload(file); },
        restore: function(file) { return restoreUpload(file); },
    };

    // 恢复要 FormData,不走 _request(那里只发 JSON)。
    // store 参数照样要带:恢复是「按门店写数据」的操作,后端门店闸靠它定作用域。
    function restoreUpload(file) {
        var formData = new FormData();
        formData.append('file', file);
        var opts = { method: 'POST', headers: {} };
        var token = _authToken();
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;
        var path = _appendStore('/api/restore');
        var sep = path.indexOf('?') !== -1 ? '&' : '?';
        if (token) path = path + sep + 'token=' + encodeURIComponent(token);
        return fetch(path, opts).then(function(res) { return res.json(); });
    }
```

其余 4 处裸 `fetch`（`duty.imageUpload` / `dataimport.import` / `upload.doUpload` /
`adminRestore.upload` / `adminImport.doImport`）逐个改成带 store：

```javascript
        imageUpload: function(id, file) {
            var formData = new FormData();
            formData.append('image', file);
            var opts = { method: 'POST', headers: {} };
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = _appendStore('/api/duty/' + id + '/image');
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            return fetch(path, opts).then(function(res) { return res.json(); });
        },
```

```javascript
        import: function(model, file) {
            var formData = new FormData();
            formData.append('model', model);
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = _appendStore('/api/import');
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            return fetch(path, opts).then(function(res) { return res.json(); });
        },
```

```javascript
        doUpload: function(file, category) {
            var formData = new FormData();
            formData.append('file', file);
            if (category) formData.append('category', category);
            var opts = { method: 'POST', headers: {} };
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = _appendStore('/api/upload');
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            return fetch(path, opts).then(function(res) { return res.json(); });
        },
```

```javascript
    var adminRestore = {
        upload: function(file) {
            var formData = new FormData();
            formData.append('zip_file', file);
            var opts = { method: 'POST', headers: {} };
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = _appendStore('/api/admin/restore-upload');
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            return fetch(path, opts).then(function(res) { return res.json(); });
        },
    };
```

```javascript
    var adminImport = {
        doImport: function(model, file) {
            var formData = new FormData();
            formData.append('model', model);
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = _appendStore('/api/import');
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            return fetch(path, opts).then(function(res) { return res.json(); });
        },
    };
```

- [ ] **Step 4: `accessibility.js` —— `api()` 辅助函数补 store**

`MeterStats/js/shared/accessibility.js` 的 `api()` 改成：

```javascript
// 异步加载数据 (通过 Api.* 封装,带 LocalStorage 缓存回退)
async function api(method, path, body) {
  const opts = { method, cache: 'no-store', headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const token = (typeof currentAuthToken === 'function')
    ? currentAuthToken()
    : ((typeof ADMIN_TOKEN !== 'undefined' && ADMIN_TOKEN) ? ADMIN_TOKEN : (localStorage.getItem('token') || ''));
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  if (token && path.indexOf('token=') === -1) {
    const separator = path.includes('?') ? '&' : '?';
    path = path + separator + 'token=' + encodeURIComponent(token);
  }
  // 拼当前门店 —— 与 js/core/api.js 的 _appendStore 同一套规则。
  // 这里不复用 api.js 的私有函数(它在 IIFE 里,外部拿不到),
  // 所以规则照抄一份;改一处就要改两处(测试会盯住)。
  if (!path.startsWith('/api/auth/') && !path.startsWith('/api/stores')
      && path.split('?')[0] !== '/api/health' && path.split('?')[0] !== '/api/version') {
    let store = '';
    try {
      if (typeof StoreContext !== 'undefined' && StoreContext) store = StoreContext.getStoreId() || '';
    } catch (e) { store = ''; }
    if (store && /^[A-Za-z0-9_-]{1,32}$/.test(store) && !/[^A-Za-z0-9_-]/.test(store)) {
      const separator = path.includes('?') ? '&' : '?';
      if (!path.includes('store=')) path = path + separator + 'store=' + encodeURIComponent(store);
    }
  }
  const res = await fetch(path, opts);
  if (!res.ok) { const txt = await res.text(); throw new Error(`HTTP ${res.status}: ${txt}`); }
  return res.json();
}
```

- [ ] **Step 5: `image_settings.js` —— 2 处裸 fetch 补 store**

`MeterStats/js/shared/image_settings.js`：把

```javascript
const IMAGE_API = '/api/admin/images';
```

改成

```javascript
const IMAGE_API = '/api/admin/images';

/** 给图片目录接口的 URL 拼上当前门店(与 api.js 同一套规则)。 */
function imageApiUrl() {
  const base = IMAGE_API + getAuthParam();
  let store = '';
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) store = StoreContext.getStoreId() || '';
  } catch (e) { store = ''; }
  if (!store) return base;
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(store) || /[^A-Za-z0-9_-]/.test(store)) return base;
  return base + (base.includes('?') ? '&' : '?') + 'store=' + encodeURIComponent(store);
}
```

再把两处 `fetch(IMAGE_API + getAuthParam())` / `fetch(IMAGE_API + getAuthParam(), {` 改成
`fetch(imageApiUrl())` / `fetch(imageApiUrl(), {`。

- [ ] **Step 6: `utils.js` —— `getDutyImageUrl()` 与 `uploadImages()` 补 store**

`MeterStats/js/helpers/utils.js`：

把

```javascript
window.getDutyImageUrl = function getDutyImageUrl(filename) {
  var base = `/api/duty/image/${filename}`;
  var t = (typeof currentAuthToken === 'function') ? currentAuthToken() : '';
  return t ? (base + '?token=' + encodeURIComponent(t)) : base;
};
```

改成

```javascript
window.getDutyImageUrl = function getDutyImageUrl(filename) {
  var base = `/api/duty/image/${filename}`;
  var t = (typeof currentAuthToken === 'function') ? currentAuthToken() : '';
  // ⚠️ store 参数必须带:图片目录是按门店分的
  // (stores/<store_id>/images/),不带就落到后端默认店 —— 总部账号切到分店后
  // 会看到总店的图,或者 404。
  var store = '';
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) store = StoreContext.getStoreId() || '';
  } catch (e) { store = ''; }
  var ok = store && /^[A-Za-z0-9_-]{1,32}$/.test(store) && !/[^A-Za-z0-9_-]/.test(store);
  var url = base;
  if (t) url += '?token=' + encodeURIComponent(t);
  if (ok) url += (url.indexOf('?') !== -1 ? '&' : '?') + 'store=' + encodeURIComponent(store);
  return url;
};
```

再把 `uploadImages` 里的

```javascript
  var suffix = token ? '?token=' + encodeURIComponent(token) : '';
```

改成

```javascript
  var suffix = token ? '?token=' + encodeURIComponent(token) : '';
  // 上传也是按门店落盘(stores/<store_id>/images/),必须带 store
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) {
      var st = StoreContext.getStoreId() || '';
      if (st && /^[A-Za-z0-9_-]{1,32}$/.test(st) && !/[^A-Za-z0-9_-]/.test(st)) {
        suffix += (suffix ? '&' : '?') + 'store=' + encodeURIComponent(st);
      }
    }
  } catch (e) { /* ignore */ }
```

- [ ] **Step 7: 加一条前端接线回归测试**

在 `tests/test_stores_frontend.py` 里**追加**（不要改已有用例）：

```python
    def test_api_js_appends_store_parameter(self) -> None:
        """api.js 必须给请求拼上当前门店,且引导端点除外。"""
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("_appendStore", src)
        self.assertIn("StoreContext.getStoreId()", src)
        # store-free 白名单:这三类端点不能带 store(否则会锁死 / 误踢登录)
        self.assertIn("/api/stores", src)
        self.assertIn("/api/auth/", src)

    def test_store_free_endpoints_are_not_given_store(self) -> None:
        """引导端点带 store 会锁死用户 —— 白名单必须真的生效。"""
        src = API_JS.read_text(encoding="utf-8")
        fn = re.search(r"function _isStoreFree\(path\)\s*\{[\s\S]*?\n    \}", src)
        self.assertIsNotNone(fn, "api.js 里找不到 _isStoreFree")
        body = fn.group(0)
        for guard in ("/api/health", "/api/version", "/api/auth/", "/api/stores"):
            self.assertIn(guard, body, f"_isStoreFree 少了 {guard}")

    def test_duty_image_url_carries_store(self) -> None:
        """图片按门店分目录 —— <img src> 必须带 store,否则串店。"""
        src = UTILS_JS.read_text(encoding="utf-8")
        fn = re.search(r"window\.getDutyImageUrl[\s\S]*?\n\};", src)
        self.assertIsNotNone(fn)
        self.assertIn("store=", fn.group(0))
```

- [ ] **Step 8: 运行测试**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_stores_frontend tests.test_store_switch_frontend -v
```

Expected: 全部 OK。

- [ ] **Step 9: 跑存量回归 + 静态检查**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest discover -s tests -v 2>&1 | tail -5
/private/tmp/lintvenv/bin/ruff check . 2>&1 | tail -3
```

Expected: `OK`；ruff ≤ 273。

- [ ] **Step 10: 提交**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
git add MeterStats/js/core/api.js MeterStats/js/shared/accessibility.js MeterStats/js/shared/image_settings.js MeterStats/js/helpers/utils.js tests/test_stores_frontend.py
git commit -m "feat(api): 所有请求贯通 store 参数,引导端点与身份端点除外"
```

---

### Task 4: 前端 UI —— 门店切换器

**Files:**
- Create: `MeterStats/js/modules/storeSwitcher.js`
- Modify: `MeterStats/index.html`（切换器 DOM + 两个新 `<script>`）
- Modify: `MeterStats/style.css`（切换器样式）
- Modify: `MeterStats/admin.js`（`setLoggedIn()` / `clearAuth()`）
- Test: `tests/test_store_switcher_ui.py`（新建）

**Interfaces:**
- Consumes: `window.StoreContext` 全部 API（Task 2）、`?store=` 贯通（Task 3）。
- Produces: 侧栏顶部的门店下拉；切换后自动重拉数据。

- [ ] **Step 1: 新建 `MeterStats/js/modules/storeSwitcher.js`**

```javascript
/**
 * 门店切换器(P1)—— 侧栏顶部下拉。
 *
 * 可见条件(与设计文档一致:仅总部/多店用户可见):
 *   - 总部账号(all_stores=true):即使只有 1 家店也要显示 ——
 *     它同时是「当前在哪家店」的指示器。
 *   - 可见门店 ≥ 2 家:多店员工/主管需要切。
 *   - 其它:单店用户没有可切的对象,不显示(不占地方也不误导)。
 *
 * 本文件只管 DOM。门店状态一律问 window.StoreContext,自己不要存一份。
 */

/** 当前可见门店列表里选中的那家 */
function currentStoreOptionId(stores) {
  var id = '';
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) id = StoreContext.getStoreId() || '';
  } catch (e) { id = ''; }
  for (var i = 0; i < stores.length; i++) {
    if (String(stores[i].id) === id) return id;
  }
  return stores.length ? String(stores[0].id) : '';
}

/** 渲染切换器(下拉内容 + 可见性) */
function renderStoreSwitcher(state) {
  var wrap = document.getElementById('store-switcher');
  var sel = document.getElementById('store-select');
  if (!wrap || !sel) return;

  var stores = (state && state.stores) || [];
  var allStores = !!(state && state.allStores);
  var visible = allStores || stores.length > 1;

  if (!visible || !stores.length) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = 'block';

  var selected = currentStoreOptionId(stores);
  var html = '';
  for (var i = 0; i < stores.length; i++) {
    var s = stores[i];
    var sid = String(s.id == null ? '' : s.id);
    var name = String(s.name || sid);
    html += '<option value="' + escapeAttr(sid) + '"'
          + (sid === selected ? ' selected' : '') + '>'
          + escapeHtml(name) + '</option>';
  }
  sel.innerHTML = html;
  sel.value = selected;
}

/** 切换门店:改状态 → 清缓存 → 重拉数据 → 提示 */
async function switchStoreTo(storeId) {
  var ok = false;
  try {
    ok = await StoreContext.switchTo(storeId);
  } catch (e) {
    ok = false;
  }
  if (!ok) {
    showAlert('切换门店失败:该门店不可访问', 'error');
    renderStoreSwitcher({
      stores: StoreContext.getStores(),
      allStores: StoreContext.getAllStores(),
    });
    return;
  }
  var name = storeId;
  var stores = StoreContext.getStores();
  for (var i = 0; i < stores.length; i++) {
    if (String(stores[i].id) === String(storeId)) name = stores[i].name || storeId;
  }
  showAlert('已切换到「' + name + '」', 'success');
}

/** 门店上下文变化 → 渲染切换器;需要重拉数据时统一重拉 */
function onStoreContextChanged(state, reason) {
  renderStoreSwitcher(state);
  if (reason === 'switch' || reason === 'recovered') {
    // 切店后要重新拉全量数据 + 重新加载电表配置 + 重画报表。
    // 门店上下文已经清过缓存,这里拉回来的就是新门店的数据。
    try {
      if (typeof window.loadAppData === 'function') window.loadAppData();
    } catch (e) {
      console.warn('切店后重新加载数据失败:', e);
    }
  }
  if (reason === 'no-store') {
    showAlert('账号未分配门店,请联系管理员', 'error');
  }
}

/** 绑定切换器事件(只绑一次) */
function bindStoreSwitcher() {
  var sel = document.getElementById('store-select');
  if (!sel || sel.dataset.storeBound === '1') return;
  sel.dataset.storeBound = '1';
  sel.addEventListener('change', function () {
    switchStoreTo(sel.value);
  });
}

/** 初始化:订阅门店上下文 + 首次渲染 */
function initStoreSwitcher() {
  bindStoreSwitcher();
  if (typeof StoreContext === 'undefined' || !StoreContext) return;
  StoreContext.onChange(onStoreContextChanged);
  renderStoreSwitcher({
    stores: StoreContext.getStores(),
    allStores: StoreContext.getAllStores(),
  });
}
```

- [ ] **Step 2: `index.html` —— 加切换器 DOM**

在 `MeterStats/index.html` 的 `<aside id="sidebar" class="sidebar">` 之后、`<nav class="sidebar-nav">` **之前**插入：

```html
    <!-- 门店切换器(P1):仅总部/多店用户可见,由 js/modules/storeSwitcher.js 渲染 -->
    <div class="store-switcher" id="store-switcher" style="display:none;">
      <label class="store-switcher-label" for="store-select">🏪 当前门店</label>
      <select id="store-select" class="store-select" title="切换门店"></select>
    </div>
```

- [ ] **Step 3: `index.html` —— 加两个 `<script>`**

在 `MeterStats/index.html` 的 `<script src="js/core/meterConfig.js"></script>` **之后**插入：

```html
  <script src="js/core/storeContext.js"></script>
```

（`storeContext.js` 必须在 `api.js` 之前 —— `api.js` 的 `_appendStore()` 会读
`StoreContext.getStoreId()`。虽然两者都只在运行时互相调用,但加载顺序上
把状态源放在前面更不容易出幺蛾子。）

在 `<script src="js/modules/stores.js"></script>` **之后**插入：

```html
  <script src="js/modules/storeSwitcher.js"></script>
```

- [ ] **Step 4: `style.css` —— 切换器样式**

在 `MeterStats/style.css` 末尾追加：

```css
/* ===== 门店切换器(P1) ===== */
.store-switcher {
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--border);
}
.store-switcher-label {
  display: block;
  font-size: 11px;
  font-weight: 510;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.store-select {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  font-size: 13px;
  color: var(--text);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
}
```

> **变量名以 `style.css` 里已有的为准**：已核实存在 `--bg-surface` / `--border` / `--text-muted` / `--text`。
> 焦点样式**不用自己写** —— `style.css:614` 已经有全局的 `select:focus` 规则，自定义一份只会打架。
> 强调色变量叫 **`--primary`**（不是 `--accent`，这个仓库里没有 `--accent`）。

- [ ] **Step 5: `admin.js` —— 登录后先引导门店，再拉数据**

把 `MeterStats/admin.js` 的 `setLoggedIn` 改成 **async**：

```javascript
// 验证通过后: 隐藏登录页, 显示主应用
async function setLoggedIn(user) {
  ADMIN_USER = user;
  document.getElementById('logout-btn').style.display = '';
  document.getElementById('login-page').style.display = 'none';
  // admin-user-info was in the removed popup modal
  // 鉴权通过才允许加载业务数据（后端 /api/* 已强制 token）
  // 按角色隐藏进不去的设置页(数据管理要主管以上、用户管理仅管理员)
  applyRoleVisibility();
  // ⚠️ 必须先引导门店上下文再拉数据:
  //    数据请求要带 ?store=,门店没定下来时后端会落到默认店 ——
  //    那样员工看到的就不是自己该看的那家店了。
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) {
      await StoreContext.init();
    }
  } catch (e) {
    console.warn('门店上下文引导失败:', e);
  }
  // 渲染门店切换器(可见性取决于 all_stores / 门店数量)
  try {
    if (typeof initStoreSwitcher === 'function') initStoreSwitcher();
  } catch (e) {
    console.warn('门店切换器初始化失败:', e);
  }
  if (typeof window.loadAppData === 'function') window.loadAppData();
}
```

`initAuth()` 里的调用点 `setLoggedIn(res.user);` 改成 `setLoggedIn(res.user).catch(...)`。

⚠️ **不要写成 `return setLoggedIn(res.user);`** —— 外层的 `.catch(function() { clearAuth(); })` 会把
`setLoggedIn` 内部的异常也接住 → 一次渲染异常就把用户踢出登录。要把两个 catch 分开：

```javascript
    Api.system.me().then(function(res) {
        if (res.user) {
          // ⚠️ 单独 catch:不要 return 给外层的 catch(那会把用户踢出登录)
          setLoggedIn(res.user).catch(function(e) {
            console.warn('登录后初始化失败:', e);
          });
        } else {
          clearAuth();
        }
      }).catch(function() { clearAuth(); });
```

`doLogin()` 里的 `setLoggedIn(res.user);` 改成（`doLogin` 本身已经是 async）：

```javascript
    try {
      await setLoggedIn(res.user);  // 内部会触发 loadAppData，不要再 renderAll() 一次
    } catch (e) {
      console.warn('登录后初始化失败:', e);
    }
```

- [ ] **Step 6: `admin.js` —— 登出时重置门店上下文**

把 `clearAuth` 改成：

```javascript
// 无权限时: 显示登录页
function clearAuth() {
  ADMIN_TOKEN = null;
  ADMIN_USER = null;
  // 'token' 才是登录后实际写入的键，之前只删了死键 meter_admin_token，
  // 导致登出后 api.js 仍能读到旧 token。三个键一律清掉。
  localStorage.removeItem('token');
  localStorage.removeItem('meter_admin_token');
  localStorage.removeItem('meter_token');
  // 门店上下文也要清:换人登录不该继承上一个人选的门店。
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) StoreContext.reset();
  } catch (e) { /* ignore */ }
  document.getElementById('logout-btn').style.display = 'none';
  document.getElementById('login-page').style.display = 'flex';
  // 登出后管理类入口一律藏起来(不等下次登录)
  applyRoleVisibility();
}
```

- [ ] **Step 7: 加一条前端接线回归测试**

新建 `tests/test_store_switcher_ui.py`（**不要追加到 `tests/test_stores_frontend.py`** —— 那个文件归 Task 3）：

```python
"""门店切换器接线回归测试(标准库 unittest,零依赖)。

只做静态接线检查(与 tests/test_stores_frontend.py 同风格):
- index.html 有切换器 DOM,并引入了两个新脚本
- storeSwitcher.js 订阅了 StoreContext 变化、调用了 switchTo、切换后重拉数据
- admin.js 先引导门店上下文再 loadAppData(顺序反了 → 第一个请求落到后端默认店)

运行:
    python3 -m unittest tests.test_store_switcher_ui -v
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
INDEX_HTML = METERSTATS / "index.html"
STORE_SWITCHER_JS = METERSTATS / "js" / "modules" / "storeSwitcher.js"
ADMIN_JS = METERSTATS / "admin.js"


class TestStoreSwitcherWiring(unittest.TestCase):

    def test_index_has_store_switcher(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="store-switcher"', html)
        self.assertIn('id="store-select"', html)
        self.assertIn("js/core/storeContext.js", html)
        self.assertIn("js/modules/storeSwitcher.js", html)

    def test_store_switcher_js_is_wired(self) -> None:
        src = STORE_SWITCHER_JS.read_text(encoding="utf-8")
        self.assertIn("StoreContext.onChange", src)
        self.assertIn("StoreContext.switchTo", src)
        self.assertIn("loadAppData", src)

    def test_admin_js_awaits_store_context_before_loading_data(self) -> None:
        """必须先引导门店上下文再拉数据 —— 否则第一个请求落到后端默认店。"""
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("StoreContext.init()", src)
        idx_init = src.find("StoreContext.init()")
        idx_load = src.find("loadAppData", idx_init)
        self.assertTrue(idx_init >= 0 and idx_load > idx_init,
                        "loadAppData 必须排在 StoreContext.init() 之后")

    def test_logout_resets_store_context(self) -> None:
        """登出要清门店上下文 —— 换人登录不该继承上一个人选的门店。"""
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("StoreContext.reset()", src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8: 运行测试**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_store_switcher_ui tests.test_stores_frontend tests.test_store_switch_frontend -v
python3 -m unittest discover -s tests -v 2>&1 | tail -5
```

Expected: 全部 OK。

- [ ] **Step 9: 提交**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
git add MeterStats/js/modules/storeSwitcher.js MeterStats/index.html MeterStats/style.css MeterStats/admin.js tests/test_store_switcher_ui.py
git commit -m "feat(ui): 侧栏门店切换器,切店后自动重拉数据"
```

---

## 收尾验收（控制器执行，不派 worker）

- [x] **Step A: 全量测试** ✅ 549 项全绿(要求 ≥503)

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest discover -s tests -v 2>&1 | tail -5
```

Expected: `OK`，用例数 ≥ 484 + 9（Task 1）+ 3（Task 2）+ 3（Task 3 接线）+ 4（Task 4 接线）= **≥ 503**。

- [x] **Step B: 静态检查** ✅ ruff 273 / mypy 793,与 P0 收尾基线持平,新增文件零错误

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
/private/tmp/lintvenv/bin/ruff check . 2>&1 | tail -3
/private/tmp/lintvenv/bin/mypy . --exclude 'data/' 2>&1 | tail -3
```

Expected: ruff ≤ 273；mypy ≤ 793，**新增文件零错误**。

- [x] **Step C: 口径回归** ✅ 71226.1 度断言通过(18 项)

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_monthly_report -v 2>&1 | tail -5
```

Expected: `71226.1 度` 断言通过（`tests/test_monthly_report.py:313`）。**P1 不许动任何计算口径。**

- [x] **Step D: 真实会话端到端验证** ✅ 5/5 通过

> ⚠️ **实操修正**:上面那条 `METER_DATA_DIR=... ./MeterStats/run.sh start` **不生效** ——
> `run.sh` 里 `DATA_DIR="$SCRIPT_DIR/.data"` 是写死的,并在启动时用
> `METER_DATA_DIR="$DATA_DIR"` 覆盖掉外部传入的值,会跑在开发数据目录上。
> 正确的做法是直接起 `server.py`:
> ```bash
> cd MeterStats && METER_PORT=8767 METER_DATA_DIR=/tmp/meter-p1-test \
>   METER_BIND=127.0.0.1 METER_INITIAL_PASS=admin123 python3 server.py
> ```
> 验证结果:① `GET /api/stores` 与 `/api/stores/current` 均带 `all_stores: true` 与门店列表;
> ② 两店各写一条抄表后,`?store=main` / `?store=s002` 各自只看到自己的行,不带参数落到默认店;
> ③ `?store=nope999` → 404「门店不存在」;
> ④ 仅属 s002 的员工 `?store=main` → 403「无权访问门店: main」,`?store=s002` → 200,
>    不带参数落到 s002,且 `/api/stores` 返回 `all_stores: false`。
>
> ⚠️ **收尾清理注意**:`kill`(SIGTERM)后进程会**卡住不退出**(见下方已知问题),
> 必须 `kill -9`。

起一个临时实例（**不要用生产数据目录**）：

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
METER_PORT=8767 METER_DATA_DIR=/tmp/meter-p1-test ./MeterStats/run.sh start
```

用 admin 登录后：
1. `GET /api/stores` → 含 `all_stores: true` 与两个门店
2. `GET /api/stores/current` → `{store_id, store, all_stores}`
3. `GET /api/readings?store=s002` → 只返回 s002 的抄表（与不带参数时不同）
4. `GET /api/readings?store=<不存在的ID>` → 404
5. 用只属于 s002 的员工账号 `GET /api/readings?store=main` → 403

验证完清理：`./MeterStats/run.sh stop` + `rm -rf /tmp/meter-p1-test`。

- [x] **Step E: 更新 CHANGELOG** ✅

在 `CHANGELOG.md` 的 **0.5.0** 章节里补一条 P1 小节（不递增版本号 —— 0.5.0 尚未发布到 GitHub）：

```markdown
### P1 门店切换器(0.5.0 内补齐)

- 侧栏顶部新增门店切换器:总部账号与多店用户可见
- 所有 `/api/*` 请求贯通 `?store=` 参数,前端不再出现「切了店还是上一个店的数据」
- 切店时清空 State / 报表缓存 / 离线缓存,杜绝跨店串数据
- `GET /api/stores` 与 `GET /api/stores/current` 新增 `all_stores` 标记
- 已知问题:`/api/admin/dir-listing` 前端传的是 `?dir=`,后端读的是 `?path=` —— 目录列举功能是坏的(P1 未修,与分店无关)
```

- [x] **Step F: 提交** ✅

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
git add CHANGELOG.md
git commit -m "docs: 0.5.0 补 P1 门店切换器更新日志"
```

---

## 不在本期范围

- 表计自定义（每店自己的表数量与倍率）→ **P2**
- 总部总表 / 门店总览页 → **P3**
- `X-Store` 头兜底 → 本期只走 query（D1）
- `admin.js` 的备份下载/删除带 `store` → 全局操作，不按店过滤（D6）
- `/api/admin/dir-listing` 的 `?dir=` vs `?path=` 参数不一致 → **P1 只记录不修**，与分店无关
- ~~`escapeHtml` 重复定义（admin.js 弱版本覆盖 utils.js 强版本）~~ → **P1 收尾轮已修**（删除 admin.js 弱版）
- ~~`modules/_base.py` 缓存别名地雷~~ → **P1 收尾轮已修**（失效挪进 `finally`）
- SIGTERM 死锁（`_shutdown` 在主线程调 `server.shutdown()`，与 `serve_forever()` 互锁）→ 既存问题，列 P2
