# 分店功能 P0 — 实施计划（门店底座）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有单店使用行为的前提下，把数据底座改造成「每店独立数据目录」的多门店结构，并建立门店注册表、门店上下文、按门店的数据读写与门店级越权防护。

**Architecture:** 新增 `modules/stores/` 包承载门店注册表（`settings.json` 的 `stores[]`）、门店配置（`stores/<id>/store.json`）、thread-local 门店上下文与幂等迁移。路径解析以 `app_handler.DATA_PATHS` 为基准推导（**不**直接用 `get_data_dir()`），单店布局下原样返回 `DATA_PATHS`，多店布局下返回 `stores/<id>/<file>`。门店鉴权闸挂在 `routing._route()` 唯一入口，紧随 `_auth_gate()` 之后，覆盖所有 `/api/*` 接口。

**Tech Stack:** Python 3.9+（`from __future__ import annotations`）、标准库 `unittest`（零 pip 依赖）、`http.server.ThreadingHTTPServer`、纯 HTML/CSS/JS 前端（无构建步骤）。

**设计规格：** `docs/superpowers/specs/2026-11-25-multi-store-design.md`

---

## Global Constraints

以下约束对每个 Task 都生效，不得违反：

- **Python 3.9+**，所有新模块首行写 `from __future__ import annotations`。
- **零外部依赖**：只用标准库。禁止 `requests` / `pydantic` 等。
- **存储读写**统一走 `storage.load_json(path, default)` / `storage.save_json(path, data)`（原子写 + LRU 缓存），写操作用 `storage.get_lock(model)` 加行级锁。
- **HTTP 响应**统一 `utils.send_json(handler, status, payload)`；读请求体用 `utils.read_body(handler)`。
- **鉴权与门店闸统一在 `routing._route()` 拦截**，新接口默认就带鉴权 + 门店隔离，不要在业务 handler 里另写一套。
- **数据目录基准**：`app_handler.DATA_PATHS` 永远是**顶层**数据目录的映射，**不随门店改变**。`settings.json` 始终位于顶层数据目录（全局配置，不分店）。门店数据位于 `stores/<store_id>/`。
- **存量回归**：现有 169 个单元测试必须**全部继续通过**。`tests/` 下已有测试直接把 `app_handler.DATA_PATHS` 指向临时目录 —— 新代码解析路径时**必须**以 `DATA_PATHS` 为基准，绕开 `DATA_PATHS` 自行推导目录会让存量测试全部读不到数据。
- **口径不变**：本计划**不改动**充值归属 / 用电计算口径。`report.py` 的表定义参数化属于 P2，不在本计划范围。
- **代码风格**：`ruff check .`（line-length 100，ignore E501）+ `mypy .`（strict，py39）无新增告警。
- **提交规范**：约定式提交（`feat`/`fix`/`refactor`/`docs`/`test`/`chore`）。**本计划全程不递增 `MeterStats/VERSION`** —— 版本号只在推送前敲定一次。
- **禁止手动编辑 `MeterStats/.data/` 或 `~/Library/Application Support/com.meter.stats/` 下的 JSON**：那是生产数据，迁移由代码执行。
- **禁止在本计划期间运行 `./build-app.sh`**：它会 `rm -rf ~/Library/Application Support/com.meter.stats/`（含真实生产数据）。

**测试命令：** `python3 -m unittest discover -s tests -v`（全量）
**单文件：** `python3 -m unittest tests.test_stores -v`

---

## File Structure

| 文件 | 职责 | Task |
|---|---|---|
| `MeterStats/modules/stores/__init__.py` | 包声明 | 1 |
| `MeterStats/modules/stores/context.py` | thread-local 门店上下文、按门店路径解析 | 1 |
| `MeterStats/modules/stores/registry.py` | 门店注册表 CRUD（`settings.json` 的 `stores[]`） | 2 |
| `MeterStats/modules/stores/config.py` | 门店配置 `store.json` 读写（表定义 + 价格） | 2 |
| `MeterStats/modules/stores/migration.py` | 顶层数据 → `stores/main/` 幂等迁移 | 3 |
| `MeterStats/modules/stores/handler.py` | 门店管理 HTTP API | 5 |
| `MeterStats/modules/_base.py` | `get_data_paths()` 改为按当前门店解析 | 1 |
| `MeterStats/modules/_storage.py` | `ModuleStorage._get_filepath()` 改为按当前门店解析 | 1 |
| `MeterStats/modules/system/settings_handler.py` | `add_user`/`update_user` 支持门店字段；`_get_current_dir()` 用基准目录 | 1、6 |
| `MeterStats/modules/system/users_handler.py` | 用户 CRUD 透传门店字段 | 6 |
| `MeterStats/modules/system/auth_handler.py` | `create_session` 记录门店范围；登录返回门店范围 | 6 |
| `MeterStats/routing.py` | `_auth_gate` 返回 session；新增 `_store_gate`；门店路由表 | 4、5 |
| `MeterStats/storage.py` | `backup_data()` 覆盖 `stores/` 子树 | 7 |
| `MeterStats/modules/backup/handler.py` | 备份/恢复/上传改用基准目录 + 支持 `stores/` 子路径 | 7 |
| `MeterStats/modules/backup/admin_handler.py` | 备份下载/删除/恢复上传/NAS 同步支持 `stores/` 子路径 | 7 |
| `MeterStats/modules/duty/handler.py` | 图片目录按门店隔离 | 7 |
| `MeterStats/js/core/api.js` | 新增 `Api.stores` 封装 | 8 |
| `MeterStats/js/modules/stores.js` | 门店管理页（列表 + 增删改） | 8 |
| `MeterStats/index.html` | 侧栏「门店管理」入口 + 引入 `stores.js` | 8 |
| `MeterStats/admin.js` | 用户管理表单加「可访问门店」多选 | 8 |
| `tests/test_stores.py` | 分店功能全部单测 | 1–7 |
| `tests/test_stores_frontend.py` | 前端静态接线回归 | 8 |

---

### Task 1: 门店上下文与按门店路径解析

**Files:**
- Create: `MeterStats/modules/stores/__init__.py`
- Create: `MeterStats/modules/stores/context.py`
- Modify: `MeterStats/modules/_base.py:28-31`（`get_data_paths`）、`:79-83`（`_get_data_paths`）
- Modify: `MeterStats/modules/_storage.py:34-44`（`_get_filepath`）
- Modify: `MeterStats/modules/system/settings_handler.py:33-35`（`_get_current_dir`）
- Test: `tests/test_stores.py`

**Interfaces:**
- Consumes: `storage.DATA_FILES`（`{model: filename}`）、`app_handler.DATA_PATHS`（`{model: Path}`）
- Produces（后续 Task 全部依赖这些名字，签名必须一致）：
  - `context.DEFAULT_STORE_ID: str = "main"`
  - `context.set_current_store(store_id: str) -> None`
  - `context.get_current_store() -> str`
  - `context.clear_current_store() -> None`
  - `context.base_data_dir() -> Path` —— 顶层数据目录（`DATA_PATHS["readings"].parent`）
  - `context.stores_root() -> Path` —— `<base>/stores`
  - `context.store_dir(store_id: str) -> Path` —— `<base>/stores/<id>`
  - `context.multi_store_layout() -> bool` —— `stores/` 目录是否存在
  - `context.resolve_store_path(model: str, store_id: str, filename: str) -> Path`
  - `context.current_store_paths() -> dict` —— `{model: Path}`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_stores.py`：

```python
"""分店功能回归测试(标准库 unittest,零依赖)。

覆盖:
- 门店上下文:当前门店读写、线程隔离
- 按门店路径解析:单店布局原样返回 DATA_PATHS;多店布局指向 stores/<id>/
- 默认店在迁移前可回退顶层旧文件;分店不回退(否则会读到总店数据)
"""
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

import app_handler  # noqa: E402
import routing  # noqa: E402
from storage import DATA_FILES  # noqa: E402
from modules.stores import context  # noqa: E402


class StoreTestBase(unittest.TestCase):
    """基类:独立临时数据目录 + 关闭鉴权开关(业务回归用)。"""

    def setUp(self):
        self._prev_enforce = routing.ENFORCE_AUTH
        routing.ENFORCE_AUTH = False
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.paths = {m: self.data_dir / fn for m, fn in DATA_FILES.items()}
        app_handler.DATA_PATHS = self.paths
        for p in self.paths.values():
            p.write_text("[]", encoding="utf-8")
        context.clear_current_store()

    def tearDown(self):
        routing.ENFORCE_AUTH = self._prev_enforce
        context.clear_current_store()
        self.tmp.cleanup()


class TestStoreContext(StoreTestBase):
    """门店上下文本身。"""

    def test_default_store_id_is_main(self):
        self.assertEqual(context.DEFAULT_STORE_ID, "main")

    def test_set_and_get_current_store(self):
        context.set_current_store("s002")
        self.assertEqual(context.get_current_store(), "s002")

    def test_get_current_store_defaults_to_main(self):
        context.clear_current_store()
        self.assertEqual(context.get_current_store(), "main")

    def test_current_store_is_thread_local(self):
        context.set_current_store("s002")
        seen = {}

        def worker():
            seen["value"] = context.get_current_store()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        # 子线程没有继承当前门店 → 回到默认店
        self.assertEqual(seen["value"], "main")
        # 主线程不受影响
        self.assertEqual(context.get_current_store(), "s002")

    def test_base_data_dir_follows_data_paths(self):
        self.assertEqual(context.base_data_dir(), self.data_dir)

    def test_store_dir_is_under_stores_root(self):
        self.assertEqual(
            context.store_dir("s002"),
            self.data_dir / "stores" / "s002",
        )


class TestStorePaths(StoreTestBase):
    """按门店解析数据路径。"""

    def test_single_store_layout_returns_data_paths_unchanged(self):
        """单店布局(没有 stores/ 目录)→ 原样返回 DATA_PATHS。

        这是 169 个存量测试能继续通过的关键。
        """
        paths = context.current_store_paths()
        self.assertEqual(paths["readings"], self.data_dir / "readings.json")
        self.assertEqual(paths["charges"], self.data_dir / "charges.json")

    def test_multi_store_layout_points_into_store_dir(self):
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        context.set_current_store("s002")
        paths = context.current_store_paths()
        self.assertEqual(
            paths["readings"],
            self.data_dir / "stores" / "s002" / "readings.json",
        )

    def test_default_store_falls_back_to_legacy_top_level_file(self):
        """迁移前 / 迁移失败:默认店可回退顶层旧文件(读双写单)。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        paths = context.current_store_paths()
        self.assertEqual(paths["readings"], self.data_dir / "readings.json")

    def test_branch_store_never_falls_back_to_top_level(self):
        """分店不回退顶层 —— 否则分店会读到总店数据。"""
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        context.set_current_store("s002")
        paths = context.current_store_paths()
        self.assertEqual(
            paths["readings"],
            self.data_dir / "stores" / "s002" / "readings.json",
        )

    def test_resolve_store_path_is_scoped_by_store(self):
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        p = context.resolve_store_path("readings", "s002", "readings.json")
        self.assertEqual(p, self.data_dir / "stores" / "s002" / "readings.json")


class TestHandlerStoreScoping(StoreTestBase):
    """CRUD handler 自动按当前门店读写(不改任何业务 handler)。"""

    def test_readings_written_to_current_store(self):
        from modules._base import get_data_paths
        from storage import load_json

        (self.data_dir / "stores" / "main").mkdir(parents=True)
        (self.data_dir / "stores" / "s002").mkdir(parents=True)
        context.set_current_store("s002")

        paths = get_data_paths()
        self.assertEqual(
            paths["readings"],
            self.data_dir / "stores" / "s002" / "readings.json",
        )
        # 直接写一次,验证落到分店目录
        from storage import save_json
        save_json(paths["readings"], [{"date": "2026-11-25", "hall": 1.0}])
        saved = load_json(self.data_dir / "stores" / "s002" / "readings.json")
        self.assertEqual(len(saved), 1)
        # 总店目录不应被创建
        self.assertFalse((self.data_dir / "stores" / "main" / "readings.json").exists())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'modules.stores'`

- [ ] **Step 3: 创建 `modules/stores/__init__.py`**

```python
"""门店模块 — 注册表、上下文、门店配置、数据迁移、HTTP API。

分店功能的核心:一个实例管多家店,每家店的数据放在独立的目录里,
彼此物理隔离,不会因为某个查询漏了过滤条件而串店。
"""
from __future__ import annotations
```

- [ ] **Step 4: 创建 `modules/stores/context.py`**

```python
"""门店上下文 — 当前门店(thread-local)与按门店的数据路径解析。

为什么用 thread-local:
    ThreadingHTTPServer 每个请求一个线程,把当前门店放在 threading.local 里,
    天然做到「请求之间不串店」,不需要给每个 handler 函数加参数。

为什么路径以 app_handler.DATA_PATHS 为基准:
    单元测试直接把 app_handler.DATA_PATHS 指向临时目录(见 tests/test_handlers.py),
    若绕开 DATA_PATHS 自行调 get_data_dir() 推导目录,存量测试会全部读不到数据。
    DATA_PATHS 永远指向**顶层**数据目录,迁移后也不改变 —— 否则 stores_root()
    会被算成 stores/main/stores/,路径全错。

单店兼容:
    未启用 stores/ 布局时,current_store_paths() 原样返回 DATA_PATHS,
    行为与分店改造前完全一致。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict

# 默认店(总店)的 ID。历史数据迁移后落到这个名字下。
DEFAULT_STORE_ID = "main"

_ctx = threading.local()


def set_current_store(store_id: str) -> None:
    """设置当前门店(仅本请求线程可见)。"""
    _ctx.store_id = store_id


def get_current_store() -> str:
    """当前门店 ID。未设置时返回默认店。"""
    return getattr(_ctx, "store_id", None) or DEFAULT_STORE_ID


def clear_current_store() -> None:
    """清空当前门店(单元测试用)。"""
    _ctx.store_id = None


def base_data_dir() -> Path:
    """顶层数据目录 —— settings.json 所在处,全局唯一。

    取 app_handler.DATA_PATHS["readings"] 的父目录;DATA_PATHS 为空时回退
    storage.get_data_dir()(服务尚未启动完时的兜底)。
    """
    paths = getattr(app_handler_module(), "DATA_PATHS", None) or {}
    ref = paths.get("readings")
    if ref:
        return Path(ref).parent
    from storage import get_data_dir
    return Path(get_data_dir())


def app_handler_module():
    """延迟 import app_handler —— 避免模块级循环依赖。"""
    import app_handler as _h
    return _h


def stores_root() -> Path:
    """stores/ 根目录。"""
    return base_data_dir() / "stores"


def store_dir(store_id: str) -> Path:
    """某门店的数据目录(可能尚不存在)。"""
    return stores_root() / store_id


def multi_store_layout() -> bool:
    """是否已启用多门店布局(stores/ 目录存在)。

    单店布局下门店闸门整体放行 —— 此时只有一家店,无从越权。
    """
    return stores_root().is_dir()


def resolve_store_path(model: str, store_id: str, filename: str) -> Path:
    """解析某门店某模型的数据文件路径。

    - 单店布局 → 顶层目录(与改造前一致)
    - 多店布局 → stores/<store_id>/<filename>>
    - 默认店 main 且该文件不存在、顶层旧文件存在 → 回退顶层旧文件
      (迁移前 / 迁移失败时的「读双写单」)
    - 分店**不回退**顶层:否则分店会读到总店数据
    """
    base = base_data_dir()
    if not multi_store_layout():
        return base / filename
    target = store_dir(store_id) / filename
    if not target.exists() and store_id == DEFAULT_STORE_ID:
        legacy = base / filename
        if legacy.exists():
            return legacy
    return target


def current_store_paths() -> Dict[str, Path]:
    """当前门店的 {model: Path} 映射。

    单店布局 → 原样返回 app_handler.DATA_PATHS;
    多店布局 → 按当前门店解析。
    """
    if not multi_store_layout():
        return dict(getattr(app_handler_module(), "DATA_PATHS", None) or {})
    from storage import DATA_FILES
    store_id = get_current_store()
    return {m: resolve_store_path(m, store_id, fn) for m, fn in DATA_FILES.items()}
```

- [ ] **Step 5: 改 `modules/_base.py` 的路径获取**

把 `modules/_base.py:28-31` 的 `get_data_paths()` 整段替换为：

```python
def get_data_paths() -> dict:
    """全局获取当前门店的 DATA_PATHS 映射。

    多门店布局下按当前门店解析;单店布局下原样返回 app_handler.DATA_PATHS。
    """
    from modules.stores.context import current_store_paths
    return current_store_paths()
```

把 `modules/_base.py:79-83` 的 `_get_data_paths()` 静态方法整段替换为：

```python
    @staticmethod
    def _get_data_paths() -> dict:
        """从 context 模块读取当前门店的数据路径映射。"""
        return get_data_paths()
```

- [ ] **Step 6: 改 `modules/_storage.py` 的文件路径获取**

把 `modules/_storage.py:34-44` 的 `_get_filepath()` 整段替换为：

```python
    def _get_filepath(self) -> Path:
        """获取数据文件路径 (动态按当前门店解析)。"""
        try:
            from modules.stores.context import current_store_paths
            path = current_store_paths().get(self.name)
            if path:
                return Path(path)
        except (ImportError, AttributeError):
            pass
        # 回退到默认路径
        return Path(self.name + '.json')
```

- [ ] **Step 7: 改 `settings_handler._get_current_dir()`**

把 `MeterStats/modules/system/settings_handler.py:33-35` 整段替换为：

```python
def _get_current_dir() -> Path:
    """顶层数据目录 —— settings.json 是全局配置,不随门店变化。

    注意:不要在这里返回门店目录。settings.json 存放用户表、门店注册表和部署配置,
    是所有门店共享的;门店自己的表定义/价格在 stores/<id>/store.json。
    """
    from modules.stores.context import base_data_dir
    return base_data_dir()
```

- [ ] **Step 8: 运行测试确认通过**

Run: `python3 -m unittest tests.test_stores -v`
Expected: PASS —— 全部用例通过

- [ ] **Step 9: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 个存量用例 + 本文件新用例全部通过

若存量用例失败,几乎一定是路径解析基准出了问题:确认 `current_store_paths()` 在单店布局下原样返回 `app_handler.DATA_PATHS`,且 `base_data_dir()` 取的是 `DATA_PATHS["readings"].parent`。

- [ ] **Step 10: 提交**

```bash
git add MeterStats/modules/stores/ MeterStats/modules/_base.py MeterStats/modules/_storage.py \
        MeterStats/modules/system/settings_handler.py tests/test_stores.py
git commit -m "feat(stores): 门店上下文与按门店路径解析"
```

---

### Task 2: 门店注册表与门店配置

**Files:**
- Create: `MeterStats/modules/stores/registry.py`
- Create: `MeterStats/modules/stores/config.py`
- Test: `tests/test_stores.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `context.store_dir()` / `context.get_current_store()`；`settings_handler.get_settings()` / `save_settings()`
- Produces:
  - `registry.DEFAULT_STORE_ID: str = "main"`
  - `registry.DEFAULT_STORE_NAME: str = "总店"`
  - `registry.list_stores(settings: dict | None = None) -> list[dict]`
  - `registry.get_store(store_id: str, settings: dict | None = None) -> dict | None`
  - `registry.add_store(store_id: str, name: str, code: str = "", address: str = "", settings: dict | None = None) -> dict`
  - `registry.update_store(store_id: str, fields: dict, settings: dict | None = None) -> dict`
  - `registry.delete_store(store_id: str, settings: dict | None = None) -> bool`
  - `registry.ensure_default_store(settings: dict) -> dict`
  - `registry.user_store_scope(user_id: int, settings: dict | None = None) -> tuple[bool, list[str]] | None`
  - `registry.is_valid_store_id(store_id: str) -> bool` —— 只允许 `[A-Za-z0-9_-]{1,32}`
  - `config.DEFAULT_METERS: list[dict]`
  - `config.store_config_path(store_id: str) -> Path`
  - `config.read_store_config(store_id: str) -> dict`
  - `config.write_store_config(store_id: str, cfg: dict) -> None`
  - `config.get_store_settings() -> dict` —— 当前门店配置
  - `config.get_store_meters() -> list[dict]`
  - `config.get_store_prices() -> dict`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_stores.py` 末尾）

```python
class TestStoreRegistry(StoreTestBase):
    """门店注册表。"""

    def _settings(self):
        from modules.system.settings_handler import get_settings, init_settings
        init_settings(self.data_dir)
        return get_settings()

    def test_ensure_default_store_creates_main(self):
        settings = self._settings()
        store = registry.ensure_default_store(settings)
        self.assertEqual(store["id"], "main")
        self.assertEqual(store["name"], "总店")
        self.assertEqual(len(registry.list_stores(settings)), 1)

    def test_ensure_default_store_is_idempotent(self):
        settings = self._settings()
        registry.ensure_default_store(settings)
        registry.ensure_default_store(settings)
        self.assertEqual(len(registry.list_stores(settings)), 1)

    def test_add_store_registers_and_creates_directory(self):
        settings = self._settings()
        store = registry.add_store("s002", "国贸店", code="B002", settings=settings)
        self.assertEqual(store["name"], "国贸店")
        self.assertTrue((self.data_dir / "stores" / "s002").is_dir())
        self.assertEqual(len(registry.list_stores(settings)), 2)

    def test_add_store_rejects_duplicate_id(self):
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        with self.assertRaises(ValueError):
            registry.add_store("s002", "重复店", settings=settings)

    def test_add_store_rejects_invalid_id(self):
        settings = self._settings()
        with self.assertRaises(ValueError):
            registry.add_store("../evil", "越权店", settings=settings)

    def test_delete_store_cannot_delete_default(self):
        settings = self._settings()
        registry.ensure_default_store(settings)
        self.assertFalse(registry.delete_store("main", settings=settings))
        self.assertIsNotNone(registry.get_store("main", settings=settings))

    def test_delete_store_removes_branch(self):
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        self.assertTrue(registry.delete_store("s002", settings=settings))
        self.assertIsNone(registry.get_store("s002", settings=settings))

    def test_update_store_changes_name(self):
        settings = self._settings()
        registry.add_store("s002", "国贸店", settings=settings)
        updated = registry.update_store("s002", {"name": "国贸分店"}, settings=settings)
        self.assertEqual(updated["name"], "国贸分店")

    def test_user_store_scope_reads_all_stores_flag(self):
        settings = self._settings()
        users = settings.get("users", [])
        users[0]["all_stores"] = True
        scope = registry.user_store_scope(users[0]["id"], settings=settings)
        self.assertIsNotNone(scope)
        self.assertTrue(scope[0])

    def test_user_store_scope_returns_none_for_unknown_user(self):
        settings = self._settings()
        self.assertIsNone(registry.user_store_scope(999999, settings=settings))


class TestStoreConfig(StoreTestBase):
    """门店配置 store.json。"""

    def test_default_meters_are_four_tables(self):
        self.assertEqual(len(config.DEFAULT_METERS), 4)
        self.assertEqual(config.DEFAULT_METERS[0]["key"], "hall")

    def test_write_and_read_store_config(self):
        cfg = {"id": "s002", "name": "国贸店", "meters": config.DEFAULT_METERS, "config": {}}
        config.write_store_config("s002", cfg)
        read = config.read_store_config("s002")
        self.assertEqual(read["name"], "国贸店")
        self.assertEqual(len(read["meters"]), 4)

    def test_get_store_settings_falls_back_to_defaults(self):
        """门店还没有 store.json 时返回默认表定义,不抛异常。"""
        cfg = config.get_store_settings()
        self.assertEqual(len(cfg.get("meters", [])), 4)

    def test_get_store_meters_returns_list(self):
        self.assertIsInstance(config.get_store_meters(), list)
```

并在文件顶部补上 import：

```python
from modules.stores import config, registry  # noqa: E402
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores -v`
Expected: FAIL —— `ImportError: cannot import name 'registry' from 'modules.stores'`

- [ ] **Step 3: 创建 `modules/stores/registry.py`**

```python
"""门店注册表 —— settings.json 里的 stores[] 分区。

门店注册表是全局的(所有门店共用一份 settings.json),只存门店的元信息:
ID、名称、编号、地址、是否启用。门店自己的数据在 stores/<id>/ 目录下。

门店 ID 规则:只允许字母、数字、下划线、连字符,长度 1-32。
ID 会拼进文件路径,必须挡住路径穿越("../" 等)。
"""
from __future__ import annotations

import re
from typing import Optional

DEFAULT_STORE_ID = "main"
DEFAULT_STORE_NAME = "总店"

_STORE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def is_valid_store_id(store_id: str) -> bool:
    """门店 ID 是否合法(可安全用作目录名)。"""
    if not store_id or not isinstance(store_id, str):
        return False
    return bool(_STORE_ID_RE.match(store_id))


def _load_settings(settings: Optional[dict]) -> dict:
    """拿到可写的 settings dict。传入了就用传入的,否则读全局 settings.json。"""
    if settings is not None:
        return settings
    from modules.system.settings_handler import get_settings
    return get_settings()


def _persist(settings: dict) -> None:
    """把改动写回 settings.json。"""
    from modules.system.settings_handler import save_settings
    save_settings(settings)


def list_stores(settings: Optional[dict] = None) -> list:
    """全部门店(按创建顺序)。"""
    st = _load_settings(settings)
    stores = st.get("stores")
    return list(stores) if isinstance(stores, list) else []


def get_store(store_id: str, settings: Optional[dict] = None) -> Optional[dict]:
    """按 ID 查门店;不存在返回 None。"""
    for s in list_stores(settings):
        if s.get("id") == store_id:
            return s
    return None


def ensure_default_store(settings: dict) -> dict:
    """确保注册表里有默认店(总店)。已存在则原样返回。"""
    stores = settings.setdefault("stores", [])
    if not isinstance(stores, list):
        stores = []
        settings["stores"] = stores
    for s in stores:
        if isinstance(s, dict) and s.get("id") == DEFAULT_STORE_ID:
            return s
    store = {
        "id": DEFAULT_STORE_ID,
        "name": DEFAULT_STORE_NAME,
        "code": "",
        "address": "",
        "active": True,
        "created_at": _now(),
    }
    stores.append(store)
    return store


def add_store(store_id: str, name: str, code: str = "", address: str = "",
              settings: Optional[dict] = None) -> dict:
    """新增门店。ID 非法或重复时抛 ValueError。

    同时创建 stores/<id>/ 目录和空的 6 个数据文件 —— 分店建好就能直接用。
    """
    if not is_valid_store_id(store_id):
        raise ValueError(f"门店 ID 非法(只允许字母/数字/下划线/连字符,1-32 位): {store_id}")
    if not name or not str(name).strip():
        raise ValueError("门店名称不能为空")
    st = _load_settings(settings)
    if get_store(store_id, settings=st) is not None:
        raise ValueError(f"门店已存在: {store_id}")
    store = {
        "id": store_id,
        "name": str(name).strip(),
        "code": (code or "").strip(),
        "address": (address or "").strip(),
        "active": True,
        "created_at": _now(),
    }
    st.setdefault("stores", []).append(store)
    if settings is None:
        _persist(st)
    _create_store_files(store_id)
    return store


def update_store(store_id: str, fields: dict, settings: Optional[dict] = None) -> dict:
    """修改门店元信息。可改字段: name / code / address / active。"""
    st = _load_settings(settings)
    store = get_store(store_id, settings=st)
    if store is None:
        raise ValueError(f"门店不存在: {store_id}")
    for k in ("name", "code", "address", "active"):
        if k in fields:
            store[k] = fields[k]
    if settings is None:
        _persist(st)
    return store


def delete_store(store_id: str, settings: Optional[dict] = None) -> bool:
    """删除门店(默认店不可删)。只删注册表条目,不删数据目录。

    返回 True = 已删除。
    """
    if store_id == DEFAULT_STORE_ID:
        return False
    st = _load_settings(settings)
    stores = st.get("stores") or []
    new_list = [s for s in stores if not (isinstance(s, dict) and s.get("id") == store_id)]
    if len(new_list) == len(stores):
        return False
    st["stores"] = new_list
    if settings is None:
        _persist(st)
    return True


def user_store_scope(user_id: int, settings: Optional[dict] = None) -> Optional[tuple]:
    """查用户的门店范围。

    返回 (all_stores, store_ids);用户不存在返回 None。
    all_stores 为 True 表示总部账号,可访问全部门店。
    """
    st = _load_settings(settings)
    for u in st.get("users") or []:
        if not isinstance(u, dict):
            continue
        if u.get("id") != user_id:
            continue
        role = u.get("role", "employee")
        all_stores = bool(u.get("all_stores", role == "admin"))
        ids = u.get("store_ids")
        store_ids = [str(x) for x in ids] if isinstance(ids, list) else []
        return (all_stores, store_ids)
    return None


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


def _create_store_files(store_id: str) -> None:
    """创建门店目录 + 空的 6 个数据文件 + 默认 store.json。"""
    from storage import DATA_FILES, save_json
    from modules.stores import config
    d = context_store_dir(store_id)
    d.mkdir(parents=True, exist_ok=True)
    for fname in DATA_FILES.values():
        p = d / fname
        if not p.exists():
            save_json(p, [])
    cfg_path = config.store_config_path(store_id)
    if not cfg_path.exists():
        config.write_store_config(store_id, {
            "id": store_id,
            "name": "",
            "meters": [dict(m) for m in config.DEFAULT_METERS],
            "config": {},
        })


def context_store_dir(store_id: str):
    """薄封装,避免 registry 直接 import context 造成循环依赖。"""
    from modules.stores.context import store_dir
    return store_dir(store_id)
```

- [ ] **Step 4: 创建 `modules/stores/config.py`**

```python
"""门店配置 store.json —— 该店自己的表定义与价格/倍率。

每店一个文件:stores/<store_id>/store.json
{
  "id": "s002",
  "name": "国贸店",
  "meters": [ {"key": "hall", "label": "大厅", "icon": "🎤",
               "multiplier": 160, "color": "#2563eb"}, ... ],
  "config": {"electricity_price": 0.9, "water_price": 4.5,
             "main_mult": 50, "sub_mult": 40}
}

P0 阶段:每店先复制一份默认表定义(与总店一致),P2 再开放自定义编辑。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# 默认表定义 —— 与 constants.METER_MULTIPLIERS / settings.json 的 meter 字段一致。
# P2 之前,所有门店都用这一份;P2 起各店可独立配置。
DEFAULT_METERS: list = [
    {"key": "hall", "label": "大厅", "icon": "🎤", "multiplier": 160, "color": "#2563eb"},
    {"key": "fire", "label": "消防", "icon": "🧯", "multiplier": 1, "color": "#dc2626"},
    {"key": "private_room", "label": "包厢", "icon": "🛋️", "multiplier": 160, "color": "#059669"},
    {"key": "ac", "label": "空调", "icon": "❄️", "multiplier": 160, "color": "#d97706"},
]

DEFAULT_CONFIG: dict = {
    "electricity_price": 0.9,
    "water_price": 4.5,
    "main_mult": 50,
    "sub_mult": 40,
}


def store_config_path(store_id: str) -> Path:
    """门店配置文件路径 stores/<store_id>/store.json。"""
    from modules.stores.context import store_dir
    return store_dir(store_id) / "store.json"


def read_store_config(store_id: str) -> dict:
    """读取门店配置。文件不存在或损坏时返回默认配置(不抛异常)。"""
    path = store_config_path(store_id)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {"id": store_id, "name": "", "meters": [dict(m) for m in DEFAULT_METERS],
            "config": dict(DEFAULT_CONFIG)}


def write_store_config(store_id: str, cfg: dict) -> None:
    """原子写入门店配置。"""
    path = store_config_path(store_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_store_settings() -> dict:
    """当前门店的配置(表定义 + 价格)。"""
    from modules.stores.context import get_current_store
    return read_store_config(get_current_store())


def get_store_meters() -> list:
    """当前门店的表定义列表。"""
    meters = get_store_settings().get("meters")
    if isinstance(meters, list) and meters:
        return meters
    return [dict(m) for m in DEFAULT_METERS]


def get_store_prices() -> dict:
    """当前门店的价格/倍率配置(缺失项用默认值补齐)。"""
    cfg = get_store_settings().get("config")
    out = dict(DEFAULT_CONFIG)
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            out[k] = v
    return out
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m unittest tests.test_stores -v`
Expected: PASS

- [ ] **Step 6: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 + 新增全部通过

- [ ] **Step 7: 提交**

```bash
git add MeterStats/modules/stores/registry.py MeterStats/modules/stores/config.py tests/test_stores.py
git commit -m "feat(stores): 门店注册表与门店配置"
```

---

### Task 3: 顶层数据 → `stores/main/` 幂等迁移

**Files:**
- Create: `MeterStats/modules/stores/migration.py`
- Modify: `MeterStats/server.py`（`main()` 里调用迁移）
- Test: `tests/test_stores.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `context.store_dir()` / `base_data_dir()`；Task 2 的 `registry.ensure_default_store()`；`storage.backup_data()`
- Produces:
  - `migration.migrate_to_stores(data_dir: Path) -> dict` —— 返回 `{"migrated": bool, "created": bool, "backup": str | None, "stores": int}`
  - `migration.migrate_settings_stores(data_dir: Path) -> dict` —— 只补注册表与用户门店归属(不搬文件)

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_stores.py`）

```python
class TestStoreMigration(StoreTestBase):
    """幂等迁移。"""

    def _seed_legacy(self):
        """造一份"迁移前"的数据:顶层 6 个 json + settings.json。"""
        (self.data_dir / "readings.json").write_text(
            '[{"date": "2026-11-01", "hall": 10.0}]', encoding="utf-8")
        (self.data_dir / "charges.json").write_text(
            '[{"id": "c1", "date": "2026-11-01", "hall": 5.0}]', encoding="utf-8")
        from modules.system.settings_handler import init_settings
        init_settings(self.data_dir)

    def test_migration_moves_files_into_main_store(self):
        self._seed_legacy()
        result = migration.migrate_to_stores(self.data_dir)
        self.assertTrue(result["migrated"])
        main = self.data_dir / "stores" / "main"
        self.assertTrue((main / "readings.json").exists())
        self.assertTrue((main / "charges.json").exists())
        # 内容完整
        import json as _json
        data = _json.loads((main / "readings.json").read_text(encoding="utf-8"))
        self.assertEqual(data[0]["date"], "2026-11-01")

    def test_migration_keeps_legacy_files_for_rollback(self):
        self._seed_legacy()
        migration.migrate_to_stores(self.data_dir)
        # 顶层旧文件保留(可回滚),不删除
        self.assertTrue((self.data_dir / "readings.json").exists())

    def test_migration_is_idempotent(self):
        self._seed_legacy()
        migration.migrate_to_stores(self.data_dir)
        result2 = migration.migrate_to_stores(self.data_dir)
        self.assertFalse(result2["migrated"])
        import json as _json
        data = _json.loads(
            (self.data_dir / "stores" / "main" / "readings.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)

    def test_migration_creates_store_json_with_meters(self):
        self._seed_legacy()
        migration.migrate_to_stores(self.data_dir)
        cfg = config.read_store_config("main")
        self.assertEqual(len(cfg["meters"]), 4)

    def test_migration_registers_default_store(self):
        self._seed_legacy()
        migration.migrate_to_stores(self.data_dir)
        from modules.system.settings_handler import get_settings
        stores = get_settings().get("stores") or []
        self.assertEqual(len(stores), 1)
        self.assertEqual(stores[0]["id"], "main")

    def test_migration_assigns_existing_users_to_default_store(self):
        self._seed_legacy()
        migration.migrate_to_stores(self.data_dir)
        from modules.system.settings_handler import get_settings
        users = get_settings().get("users") or []
        self.assertTrue(users)
        for u in users:
            if u.get("role") == "admin":
                self.assertTrue(u.get("all_stores"))
            else:
                self.assertEqual(u.get("store_ids"), ["main"])

    def test_fresh_install_creates_empty_main_store(self):
        """全新安装(没有任何顶层数据)→ 建好默认店,不报错。"""
        from modules.system.settings_handler import init_settings
        init_settings(self.data_dir)
        result = migration.migrate_to_stores(self.data_dir)
        self.assertFalse(result["migrated"])
        self.assertTrue((self.data_dir / "stores" / "main" / "readings.json").exists())
```

并在文件顶部补上 import：

```python
from modules.stores import migration  # noqa: E402
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores -v`
Expected: FAIL —— `ImportError: cannot import name 'migration' from 'modules.stores'`

- [ ] **Step 3: 创建 `modules/stores/migration.py`**

```python
"""数据迁移 —— 顶层数据文件 → stores/<store_id>/。

做一次,幂等。触发时机:server 启动时(server.py 调用)。

原则:
1. **先备份,再动数据。** 迁移前必须打一份完整备份,备份失败就不迁。
2. **顶层旧文件不删。** 搬完保留在原地,作为可回滚副本。
3. **失败不阻塞启动。** 迁移异常只记日志,服务照常起(此时是单店布局,
   门店闸门整体放行,行为与改造前一致)。

迁移后:
- stores/main/  ← 原顶层 6 个数据文件
- stores/main/store.json  ← 由 settings.json 的 meter/config 合成
- settings.json 增加 stores[] 注册表,现有用户补上门店归属
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from storage import DATA_FILES, log


def migrate_to_stores(data_dir: Path) -> dict:
    """把顶层数据迁移到默认店目录。返回执行结果统计。

    返回 {"migrated": bool, "created": bool, "backup": str|None, "stores": int}
    """
    result = {"migrated": False, "created": False, "backup": None, "stores": 0}
    stores_root = Path(data_dir) / "stores"
    main_dir = stores_root / "main"

    # 已迁移过 → 只补注册表(幂等)
    if (main_dir / "readings.json").exists():
        result["stores"] = _ensure_registry(data_dir)
        return result

    legacy_present = any(_file_has_records(Path(data_dir) / fn) for fn in DATA_FILES.values())

    if legacy_present:
        # 1. 先备份 —— 备份失败就不迁
        backup_path = _backup_before_migration(data_dir)
        if not backup_path:
            log("[MIGRATE] 备份失败,放弃迁移(保持单店布局继续运行)")
            return result
        result["backup"] = str(backup_path)
        # 2. 搬文件
        try:
            main_dir.mkdir(parents=True, exist_ok=True)
            for fname in DATA_FILES.values():
                src = Path(data_dir) / fname
                if src.exists():
                    shutil.copy2(src, main_dir / fname)
                    log(f"[MIGRATE] {fname} → stores/main/{fname}")
        except Exception as e:
            log(f"[MIGRATE] 迁移失败: {e} —— 保持单店布局继续运行")
            return result
        result["migrated"] = True
    else:
        # 全新安装:直接建好默认店
        main_dir.mkdir(parents=True, exist_ok=True)
        for fname in DATA_FILES.values():
            p = main_dir / fname
            if not p.exists():
                p.write_text("[]", encoding="utf-8")
        result["created"] = True

    # 3. 门店配置 store.json(从 settings.json 的 meter/config 合成)
    _write_default_store_json(data_dir)

    # 4. 注册表 + 用户门店归属
    result["stores"] = _ensure_registry(data_dir)

    log(f"[MIGRATE] 多门店布局就绪: stores/main/ (迁移={result['migrated']}, "
        f"新建={result['created']}, 门店数={result['stores']})")
    return result


def migrate_settings_stores(data_dir: Path) -> dict:
    """只补注册表与用户门店归属,不搬数据文件。"""
    return {"stores": _ensure_registry(data_dir)}


def _file_has_records(path: Path) -> bool:
    """JSON 文件里是否有实际记录。

    用来区分「老部署的遗留数据」和「全新安装」:
    init_data_files() 会先创建 6 个空的顶层 JSON 文件(内容是 [])，
    只看文件存在会把全新安装误判成迁移场景,多打一次备份。
    """
    try:
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(data, list) and len(data) > 0
    except (OSError, ValueError):
        return False


def _backup_before_migration(data_dir: Path) -> Optional[Path]:
    """迁移前打一份完整备份。失败返回 None。"""
    try:
        from storage import backup_data
        p = backup_data(Path(data_dir), force=True)
        return Path(p) if p else None
    except Exception as e:
        log(f"[MIGRATE] 迁移前备份失败: {e}")
        return None


def _write_default_store_json(data_dir: Path) -> None:
    """用 settings.json 的 meter/config 合成默认店的 store.json。"""
    from modules.stores import config
    path = config.store_config_path("main")
    if path.exists():
        return
    meters = None
    prices = None
    try:
        settings_path = Path(data_dir) / "settings.json"
        if settings_path.exists():
            st = json.loads(settings_path.read_text(encoding="utf-8"))
            meters = st.get("meter")
            prices = st.get("config")
    except (OSError, ValueError) as e:
        log(f"[MIGRATE] 读取 settings.json 失败,用默认表定义: {e}")

    meter_list = []
    if isinstance(meters, dict):
        # settings.json 的 meter 是 {key: {label, icon, multiplier, color}}
        for key, val in meters.items():
            if not isinstance(val, dict):
                continue
            meter_list.append({
                "key": key,
                "label": val.get("label", key),
                "icon": val.get("icon", ""),
                "multiplier": val.get("multiplier", 1),
                "color": val.get("color", "#888888"),
            })
    if not meter_list:
        meter_list = [dict(m) for m in config.DEFAULT_METERS]

    price_cfg = dict(config.DEFAULT_CONFIG)
    if isinstance(prices, dict):
        for k, v in prices.items():
            price_cfg[k] = v

    try:
        config.write_store_config("main", {
            "id": "main",
            "name": "总店",
            "meters": meter_list,
            "config": price_cfg,
        })
    except Exception as e:
        log(f"[MIGRATE] 写入 store.json 失败: {e}")


def _ensure_registry(data_dir: Path) -> int:
    """确保 settings.json 有门店注册表,且现有用户都有门店归属。返回门店数。"""
    from modules.stores import registry
    from modules.system.settings_handler import get_settings, save_settings

    try:
        settings = get_settings()
    except Exception as e:
        log(f"[MIGRATE] 读取 settings.json 失败,跳过注册表: {e}")
        return 0

    changed = False
    registry.ensure_default_store(settings)
    if "stores" not in settings:
        changed = True

    stores = settings.get("stores") or []
    default_id = registry.DEFAULT_STORE_ID

    for u in settings.get("users") or []:
        if not isinstance(u, dict):
            continue
        role = u.get("role", "employee")
        if role == "admin":
            # 总部账号:可跨店
            if not u.get("all_stores"):
                u["all_stores"] = True
                changed = True
        else:
            # 分店员工:未分配时先归到默认店,避免迁移后所有人被挡在门外
            if "store_ids" not in u:
                u["store_ids"] = [default_id]
                changed = True
            elif not isinstance(u.get("store_ids"), list):
                u["store_ids"] = [default_id]
                changed = True

    if changed:
        try:
            save_settings(settings)
        except Exception as e:
            log(f"[MIGRATE] 保存 settings.json 失败: {e}")

    return len(stores)
```

- [ ] **Step 4: 在 `server.py` 启动流程里调用迁移**

⚠️ **调用位置很重要**:必须放在 `app_handler._sync_data_paths()` **之后**。
`_sync_data_paths()` 才会调用 `init_settings(data_dir)` 创建 `settings.json` ——
而迁移要往 settings.json 里写门店注册表、给用户补 `all_stores` / `store_ids`,
settings.json 不存在时这些都做不了。

在 `MeterStats/server.py` 的 `main()` 中,把现有的

```python
    app_handler.DATA_PATHS = data_paths
    app_handler._sync_data_paths()  # 初始化 settings.json
```

替换为:

```python
    app_handler.DATA_PATHS = data_paths
    app_handler._sync_data_paths()  # 初始化 settings.json

    # 分店迁移:顶层数据 → stores/main/(幂等;失败不阻塞启动)
    # ⚠️ 必须放在 _sync_data_paths() 之后 —— 迁移要写 settings.json
    #    (门店注册表 + 用户门店归属),settings.json 不存在时做不了。
    from modules.stores.migration import migrate_to_stores as _migrate_to_stores
    try:
        _migrate_to_stores(data_dir)
    except Exception as e:
        log(f"  [MIGRATE] 多门店布局迁移异常(继续以单店模式运行): {e}")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m unittest tests.test_stores -v`
Expected: PASS

- [ ] **Step 6: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 + 新增全部通过

- [ ] **Step 7: 提交**

```bash
git add MeterStats/modules/stores/migration.py MeterStats/server.py tests/test_stores.py
git commit -m "feat(stores): 顶层数据到 stores/main/ 的幂等迁移"
```

---

### Task 4: 门店鉴权闸（越权防护）

**Files:**
- Modify: `MeterStats/routing.py:106-139`（`_auth_gate`）、`:240-268`（`_route`）
- Test: `tests/test_stores.py`（追加用例）、`tests/test_auth_enforcement.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `context.multi_store_layout()` / `set_current_store()`；Task 2 的 `registry.user_store_scope()` / `registry.get_store()`
- Produces:
  - `routing._auth_gate(method: str, path_clean: str, handler) -> dict | None` —— **返回 session dict 表示放行;返回 None 表示已发 401/403**（签名从 `-> bool` 改为 `-> dict | None`）
  - `routing._store_gate(sess: dict, handler) -> bool` —— True 放行;False 已发 403/404

> ⚠️ `_auth_gate` 的返回类型从 `bool` 改成 `dict | None`,是为了把 session 传给 `_store_gate`,避免重复查会话(也避免重复 `_touch_session`)。`_route()` 是唯一调用方,同步改即可。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_stores.py`）

```python
class TestStoreGate(StoreTestBase):
    """门店鉴权闸。"""

    def _enable_multi_store(self):
        """造出多门店布局 + 一个 admin、一个分店员工。"""
        from modules.system.settings_handler import init_settings, get_settings, save_settings
        init_settings(self.data_dir)
        settings = get_settings()
        settings["stores"] = [
            {"id": "main", "name": "总店", "active": True},
            {"id": "s002", "name": "国贸店", "active": True},
        ]
        users = settings["users"]
        users[0]["all_stores"] = True          # admin
        users[0]["store_ids"] = []
        settings["users"].append({
            "id": 99, "username": "branch", "password": "x", "role": "employee",
            "name": "分店员工", "enabled": True, "store_ids": ["s002"], "all_stores": False,
        })
        save_settings(settings)
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        (self.data_dir / "stores" / "s002").mkdir(parents=True)

    def _session(self, user_id, role="employee", all_stores=False, store_ids=None):
        return {"user_id": user_id, "username": "u", "role": role, "name": "u",
                "all_stores": all_stores, "store_ids": store_ids or []}

    def test_gate_is_noop_in_single_store_layout(self):
        """单店布局 → 门店闸整体放行(存量测试行为不变)。"""
        from routing import _store_gate
        self.assertTrue(_store_gate(self._session(1, "admin", True), _FakeHandler()))

    def test_gate_allows_assigned_store(self):
        self._enable_multi_store()
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=s002")
        self.assertTrue(_store_gate(self._session(99, store_ids=["s002"]), h))
        from modules.stores.context import get_current_store
        self.assertEqual(get_current_store(), "s002")

    def test_gate_blocks_unassigned_store(self):
        self._enable_multi_store()
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=main")
        self.assertFalse(_store_gate(self._session(99, store_ids=["s002"]), h))
        self.assertEqual(h.response_status, 403)

    def test_gate_allows_all_stores_user_any_store(self):
        self._enable_multi_store()
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=s002")
        self.assertTrue(_store_gate(self._session(1, "admin", True), h))

    def test_gate_defaults_to_first_assigned_store(self):
        self._enable_multi_store()
        from routing import _store_gate
        h = _FakeHandler("/api/readings")
        self.assertTrue(_store_gate(self._session(99, store_ids=["s002"]), h))
        from modules.stores.context import get_current_store
        self.assertEqual(get_current_store(), "s002")

    def test_gate_rejects_unknown_store(self):
        self._enable_multi_store()
        from routing import _store_gate
        h = _FakeHandler("/api/readings?store=nope")
        self.assertFalse(_store_gate(self._session(1, "admin", True), h))
        self.assertEqual(h.response_status, 404)
```

在 `tests/test_stores.py` 顶部加一个最小 handler 桩：

```python
class _FakeHandler:
    """最小 HTTP handler 桩 —— 只供门店闸测试用。"""

    def __init__(self, path: str):
        self.path = path
        self.response_status = None
        self.response_headers = {}
        self.wfile = io.BytesIO()
        self.headers = {"Content-Length": "0"}

    def send_response(self, status):
        self.response_status = status

    def send_header(self, k, v):
        self.response_headers[k] = v

    def end_headers(self):
        pass
```

并在文件顶部补 `import io`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores -v`
Expected: FAIL —— `ImportError: cannot import name '_store_gate' from 'routing'`

- [ ] **Step 3: 改 `routing._auth_gate` 返回 session**

把 `MeterStats/routing.py:106-139` 的 `_auth_gate` 整段替换为：

```python
def _auth_gate(method: str, path_clean: str, handler) -> "dict | None":
    """统一鉴权入口。返回 session dict 表示放行;返回 None 表示已发出 401/403。

    token 由 _get_token 依次尝试 Cookie / ?token= / Authorization 头,
    所以 <img src> 与 <a href> 这类带不了请求头的请求也能用 query 通过校验。
    """
    if not ENFORCE_AUTH:
        # 业务回归测试关闭了鉴权 —— 合成一个管理员会话,
        # 让下游的门店闸也能正常工作。
        return {"user_id": 0, "username": "test", "role": "admin", "name": "test",
                "all_stores": True, "store_ids": []}
    if path_clean in PUBLIC_API_PATHS:
        return {}  # 匿名放行(白名单端点)

    from modules.system.permissions_handler import _get_token
    from modules.system.auth_handler import get_session, _touch_session

    token = _get_token(handler)
    sess = get_session(token) if token else None
    if not sess:
        send_json(handler, 401, {"error": "未登录或会话已过期,请重新登录"})
        return None

    _touch_session(token)  # 有活动就续期,与 check_permission 装饰器行为一致
    role = sess.get("role", "employee")

    if method == "DELETE" and role not in DELETE_ROLES:
        send_json(handler, 403, {"error": "权限不足: 删除需要主管或管理员权限"})
        return None

    if path_clean.startswith(ADMIN_ONLY_PREFIXES) and role != "admin":
        send_json(handler, 403, {"error": "权限不足: 用户管理需要管理员权限"})
        return None

    if path_clean.startswith(MANAGER_ONLY_PREFIXES) and role not in MANAGER_ROLES:
        send_json(handler, 403, {"error": "权限不足: 该操作需要主管或管理员权限"})
        return None

    return sess
```

- [ ] **Step 4: 新增 `_store_gate`**

在 `MeterStats/routing.py` 的 `_auth_gate` 函数之后插入：

```python
def _store_gate(sess: dict, handler) -> bool:
    """解析并校验当前门店。返回 False 表示已发出 403/404。

    规则:
    - **单店布局**(未启用 stores/)→ 整体放行,使用默认店。此时只有一家店,
      无从越权;也让 169 个存量测试的行为完全不变。
    - **多店布局** → 严格执行:
        - all_stores=True(总部账号)→ 允许任意已注册门店
        - 否则请求的门店必须在该用户的 store_ids 里
        - 不带 store 参数时,取该用户第一个 store_ids;都没有则取默认店并 403
    """
    from modules.stores.context import (
        DEFAULT_STORE_ID, multi_store_layout, set_current_store,
    )
    from modules.stores import registry

    if not multi_store_layout():
        set_current_store(DEFAULT_STORE_ID)
        return True

    # 门店范围优先取 settings.json 里的最新用户记录(改权限即时生效,不用重登);
    # 用户记录查不到(测试用的合成会话)才回退会话里的值。
    scope = registry.user_store_scope(sess.get("user_id"))
    if scope is None:
        all_stores = bool(sess.get("all_stores", True))
        store_ids = list(sess.get("store_ids") or [])
    else:
        all_stores, store_ids = scope

    # 请求里指定的门店
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    requested = (qs.get("store") or [""])[0].strip()

    if not requested:
        requested = store_ids[0] if store_ids else DEFAULT_STORE_ID

    if not all_stores and requested not in store_ids:
        if not store_ids:
            send_json(handler, 403, {"error": "账号未分配门店,请联系管理员"})
        else:
            send_json(handler, 403, {"error": f"无权访问门店: {requested}"})
        return False

    if registry.get_store(requested) is None:
        send_json(handler, 404, {"error": f"门店不存在: {requested}"})
        return False

    set_current_store(requested)
    return True
```

- [ ] **Step 5: 改 `_route` 调用闸门**

把 `MeterStats/routing.py:266-268` 的

```python
    # GET: 精确匹配 + 前缀匹配
    if not _auth_gate(method, path_clean, handler):
        return True  # 已经发了 401/403,不再往下分发
```

替换为：

```python
    # GET: 精确匹配 + 前缀匹配
    sess = _auth_gate(method, path_clean, handler)
    if sess is None:
        return True  # 已经发了 401/403,不再往下分发

    # 门店闸:解析并校验当前门店,失败直接 403/404。
    # 挂在 _route() 这个唯一入口上 → 新增接口默认就带门店隔离。
    if not _store_gate(sess, handler):
        return True
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python3 -m unittest tests.test_stores -v`
Expected: PASS

- [ ] **Step 7: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 + 新增全部通过

- [ ] **Step 8: 在 `tests/test_auth_enforcement.py` 补越权用例**

在该文件的 `AuthBase` 之后追加一个新测试类:

```python
class TestStoreScope(AuthBase):
    """门店越权防护(多门店布局下)。"""

    def _enable_multi_store(self):
        (self.data_dir / "stores" / "main").mkdir(parents=True)
        (self.data_dir / "stores" / "s002").mkdir(parents=True)
        from modules.system.settings_handler import get_settings, save_settings
        settings = get_settings()
        settings["stores"] = [
            {"id": "main", "name": "总店", "active": True},
            {"id": "s002", "name": "国贸店", "active": True},
        ]
        settings["users"][0]["all_stores"] = True
        save_settings(settings)

    def test_employee_cannot_read_other_store(self):
        self._enable_multi_store()
        from modules.system.settings_handler import get_settings, save_settings
        settings = get_settings()
        settings["users"].append({
            "id": 99, "username": "branch", "password": "x", "role": "employee",
            "name": "分店员工", "enabled": True, "store_ids": ["s002"], "all_stores": False,
        })
        save_settings(settings)
        tok = create_session({
            "id": 99, "username": "branch", "role": "employee", "name": "分店员工",
        })
        h = self.call("GET", "/api/readings?store=main", token=tok)
        self.assertEqual(h.response_status, 403)
```

- [ ] **Step 9: 运行鉴权测试**

Run: `python3 -m unittest tests.test_auth_enforcement -v`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add MeterStats/routing.py tests/test_stores.py tests/test_auth_enforcement.py
git commit -m "feat(stores): 门店鉴权闸,拦截跨店越权访问"
```

---

### Task 5: 门店管理 HTTP API

**Files:**
- Create: `MeterStats/modules/stores/handler.py`
- Modify: `MeterStats/routing.py`（路由表）
- Test: `tests/test_stores.py`（追加用例）

**Interfaces:**
- Consumes: Task 2 的 `registry` / `config`；Task 4 的 `_store_gate`
- Produces（HTTP 契约）:
  - `GET /api/stores` → `{"ok": true, "stores": [{id, name, code, address, active, created_at, record_counts?}]}`
  - `POST /api/stores` body `{id, name, code?, address?}` → `{"ok": true, "store": {...}}` 或 `{"ok": false, "error": "..."}`
  - `PUT /api/stores/<id>` body `{name?, code?, address?, active?}` → `{"ok": true, "store": {...}}`
  - `DELETE /api/stores/<id>` → `{"ok": true}`
  - `GET /api/stores/current` → `{"ok": true, "store": {...}, "store_id": "..."}`

> 权限:`/api/stores` 的**读**任何登录用户可读(但只返回自己有权限的门店);**增删改仅 admin**。
> 在 `routing.py` 里把 `/api/stores` 加进 `ADMIN_ONLY_PREFIXES` 之前需要分开处理 ——
> 所以实现为:路由表里注册**精确路径** `GET /api/stores` 走普通读权限,
> 而 `POST /api/stores`、`PUT /api/stores/*`、`DELETE /api/stores/*` 在 handler 内部
> 自行校验 `role == "admin"`,不依赖前缀黑名单(前缀黑名单会把 GET 一起拦掉)。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_stores.py`）

```python
class TestStoreApi(StoreTestBase):
    """门店管理 API。"""

    def _call(self, method, path, body=None, token=""):
        from app_handler import _do_api
        h = _ApiHandler(path, body, method, token=token)
        _do_api(method, h, h.path)
        return h

    def _setup_admin(self):
        from modules.system.settings_handler import init_settings, get_settings, save_settings
        init_settings(self.data_dir)
        settings = get_settings()
        settings["users"][0]["all_stores"] = True
        # 必须注册门店:多门店布局下门店闸会校验门店是否在注册表里,
        # 没注册会直接 404,后面的断言全部落空。
        settings["stores"] = [{"id": "main", "name": "总店", "active": True}]
        save_settings(settings)
        (self.data_dir / "stores" / "main").mkdir(parents=True)

    def test_get_stores_returns_list(self):
        self._setup_admin()
        h = self._call("GET", "/api/stores")
        self.assertEqual(h.response_status, 200)
        self.assertTrue(h.parsed["ok"])
        self.assertIsInstance(h.parsed["stores"], list)

    def test_post_store_creates_store(self):
        self._setup_admin()
        h = self._call("POST", "/api/stores", {"id": "s002", "name": "国贸店"})
        self.assertTrue(h.parsed["ok"], h.parsed)
        self.assertEqual(h.parsed["store"]["name"], "国贸店")

    def test_post_store_rejects_invalid_id(self):
        self._setup_admin()
        h = self._call("POST", "/api/stores", {"id": "../evil", "name": "越权店"})
        self.assertFalse(h.parsed["ok"])
        self.assertIn("ID", h.parsed["error"])

    def test_delete_default_store_forbidden(self):
        self._setup_admin()
        h = self._call("DELETE", "/api/stores/main")
        self.assertFalse(h.parsed["ok"])

    def test_non_admin_cannot_create_store(self):
        self._setup_admin()
        from modules.system.auth_handler import create_session
        tok = create_session({"id": 77, "username": "emp", "role": "employee", "name": "员工"})
        h = self._call("POST", "/api/stores", {"id": "s003", "name": "越权店"}, token=tok)
        self.assertFalse(h.parsed["ok"])
```

在 `tests/test_stores.py` 顶部加 API 桩:

```python
class _ApiHandler:
    """最小 HTTP handler 桩 —— 供门店 API 测试用。"""

    def __init__(self, path: str, body=None, method: str = "GET", token: str = ""):
        self.path = path
        self.command = method
        self.response_status = None
        self.response_headers = {}
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

    def send_response(self, status):
        self.response_status = status

    def send_header(self, k, v):
        self.response_headers[k] = v

    def end_headers(self):
        pass

    @property
    def parsed(self):
        body = self.wfile.getvalue()
        return json.loads(body) if body else None
```

并在文件顶部补 `import json`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores -v`
Expected: FAIL —— 404 未知接口

- [ ] **Step 3: 创建 `modules/stores/handler.py`**

```python
"""门店管理 HTTP API。

权限:
- 读(GET)  → 任何登录用户,但只返回自己有权限的门店
- 增删改   → 仅管理员
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from modules.stores import registry, config
from modules.stores.context import get_current_store


def _current_session(handler) -> dict:
    """取当前会话(鉴权已在 routing._auth_gate 完成,这里只读不校验)。"""
    from modules.system.permissions_handler import _get_token
    from modules.system.auth_handler import get_session
    token = _get_token(handler)
    sess = get_session(token) if token else None
    return sess or {}


def _is_admin(sess: dict) -> bool:
    return sess.get("role") == "admin"


def _visible_store_ids(sess: dict) -> tuple:
    """返回 (all_stores, store_ids) —— 与门店闸同源。"""
    scope = registry.user_store_scope(sess.get("user_id"))
    if scope is None:
        return (bool(sess.get("all_stores", True)), list(sess.get("store_ids") or []))
    return scope


def handle_get_stores(handler):
    """GET /api/stores → { ok, stores }"""
    sess = _current_session(handler)
    all_stores, store_ids = _visible_store_ids(sess)
    stores = registry.list_stores()
    if not all_stores:
        stores = [s for s in stores if s.get("id") in store_ids]
    send_json(handler, 200, {"ok": True, "stores": stores})


def handle_get_current_store(handler):
    """GET /api/stores/current → { ok, store_id, store }"""
    store_id = get_current_store()
    store = registry.get_store(store_id) or {"id": store_id, "name": store_id}
    send_json(handler, 200, {"ok": True, "store_id": store_id, "store": store})


def handle_post_store(handler):
    """POST /api/stores { id, name, code?, address? } → { ok, store }"""
    sess = _current_session(handler)
    if not _is_admin(sess):
        send_json(handler, 200, {"ok": False, "error": "仅管理员可新增门店"})
        return
    body = read_body(handler) or {}
    store_id = str(body.get("id") or "").strip()
    name = str(body.get("name") or "").strip()
    try:
        store = registry.add_store(
            store_id, name,
            code=str(body.get("code") or ""),
            address=str(body.get("address") or ""),
        )
    except ValueError as e:
        send_json(handler, 200, {"ok": False, "error": str(e)})
        return
    send_json(handler, 200, {"ok": True, "store": store})


def handle_put_store(handler, path_clean: str):
    """PUT /api/stores/<id> { name?, code?, address?, active? } → { ok, store }"""
    sess = _current_session(handler)
    if not _is_admin(sess):
        send_json(handler, 200, {"ok": False, "error": "仅管理员可修改门店"})
        return
    store_id = path_clean.split("/")[3] if len(path_clean.split("/")) >= 4 else ""
    body = read_body(handler) or {}
    try:
        store = registry.update_store(store_id, body)
    except ValueError as e:
        send_json(handler, 200, {"ok": False, "error": str(e)})
        return
    send_json(handler, 200, {"ok": True, "store": store})


def handle_delete_store(handler, path_clean: str):
    """DELETE /api/stores/<id> → { ok }"""
    sess = _current_session(handler)
    if not _is_admin(sess):
        send_json(handler, 200, {"ok": False, "error": "仅管理员可删除门店"})
        return
    store_id = path_clean.split("/")[3] if len(path_clean.split("/")) >= 4 else ""
    if not registry.delete_store(store_id):
        send_json(handler, 200, {"ok": False, "error": f"门店不存在或不可删除: {store_id}"})
        return
    send_json(handler, 200, {"ok": True})
```

- [ ] **Step 4: 注册路由**

在 `MeterStats/routing.py` 的 import 区加入：

```python
from modules.stores.handler import (
    handle_get_stores, handle_get_current_store,
    handle_post_store, handle_put_store, handle_delete_store,
)
```

在 `_GET_ROUTES` 里加入（注意放在 `/api/stores/current` 之前，避免被前缀匹配吃掉）：

```python
    "/api/stores/current": handle_get_current_store,
    "/api/stores": handle_get_stores,
```

在 `_POST_PREFIX` 里加入：

```python
    "/api/stores": handle_post_store,
```

在 `_PUT_PREFIX` 里加入：

```python
    "/api/stores": handle_put_store,
```

在 `_DELETE_PREFIX` 里加入：

```python
    "/api/stores": handle_delete_store,
```

> ⚠️ GET 路由匹配顺序:`_route()` 先做**精确匹配**(`path_clean in _GET_ROUTES`),
> 精确匹配不到才做前缀匹配。所以 `/api/stores/current` 和 `/api/stores` 都放进
> `_GET_ROUTES` 即可,字典顺序无所谓。但**前缀匹配**(`_match_prefix`)对
> `/api/stores/xxx` 会命中 `/api/stores` —— 所以 `GET /api/stores/current`
> 必须**精确登记**在 `_GET_ROUTES` 里,否则会被当成 `/api/stores/<id>` 处理。

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m unittest tests.test_stores -v`
Expected: PASS

- [ ] **Step 6: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 + 新增全部通过

- [ ] **Step 7: 提交**

```bash
git add MeterStats/modules/stores/handler.py MeterStats/routing.py tests/test_stores.py
git commit -m "feat(stores): 门店管理 API"
```

---

### Task 6: 用户门店归属

**Files:**
- Modify: `MeterStats/modules/system/settings_handler.py:223-247`（`add_user` / `update_user`）
- Modify: `MeterStats/modules/system/users_handler.py:23-91`（`handle_post_users` / `handle_put_users` / `handle_get_users`）
- Modify: `MeterStats/modules/system/auth_handler.py:148-162`（`create_session`）、`:223-241`（登录返回）
- Test: `tests/test_stores.py`（追加用例）

**Interfaces:**
- Consumes: Task 2 的 `registry.user_store_scope()`；Task 4 的 `_store_gate`
- Produces:
  - `settings_handler.add_user(users, username, password, name, role, store_ids=None, all_stores=None) -> dict | None`
  - `settings_handler.update_user(users, uid, fields) -> dict | None` —— 支持 `store_ids` / `all_stores` 字段
  - 用户记录新增字段:`store_ids: list[str]`、`all_stores: bool`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_stores.py`）

```python
class TestUserStoreScope(StoreTestBase):
    """用户的门店归属。"""

    def _settings(self):
        from modules.system.settings_handler import init_settings, get_settings
        init_settings(self.data_dir)
        return get_settings()

    def test_add_user_defaults_to_admin_all_stores(self):
        from modules.system.settings_handler import add_user
        users = []
        u = add_user(users, "boss", "pw123456", "老板", "admin")
        self.assertTrue(u["all_stores"])

    def test_add_user_employee_gets_empty_store_ids(self):
        from modules.system.settings_handler import add_user
        users = []
        u = add_user(users, "emp", "pw123456", "员工", "employee")
        self.assertEqual(u["store_ids"], [])
        self.assertFalse(u["all_stores"])

    def test_add_user_accepts_store_ids(self):
        from modules.system.settings_handler import add_user
        users = []
        u = add_user(users, "emp2", "pw123456", "员工2", "employee", store_ids=["s002"])
        self.assertEqual(u["store_ids"], ["s002"])

    def test_update_user_changes_store_ids(self):
        from modules.system.settings_handler import add_user, update_user
        users = []
        u = add_user(users, "emp3", "pw123456", "员工3", "employee")
        updated = update_user(users, u["id"], {"store_ids": ["s002", "s003"]})
        self.assertEqual(updated["store_ids"], ["s002", "s003"])

    def test_update_user_changes_all_stores(self):
        from modules.system.settings_handler import add_user, update_user
        users = []
        u = add_user(users, "boss2", "pw123456", "老板2", "admin")
        updated = update_user(users, u["id"], {"all_stores": False})
        self.assertFalse(updated["all_stores"])

    def test_user_store_scope_reflects_update(self):
        from modules.system.settings_handler import add_user, update_user
        users = []
        u = add_user(users, "emp4", "pw123456", "员工4", "employee")
        self.assertEqual(registry.user_store_scope(u["id"], settings={"users": users}),
                         (False, []))
        update_user(users, u["id"], {"store_ids": ["s002"]})
        self.assertEqual(registry.user_store_scope(u["id"], settings={"users": users}),
                         (False, ["s002"]))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores -v`
Expected: FAIL —— `TypeError: add_user() got an unexpected keyword argument 'store_ids'`

- [ ] **Step 3: 改 `settings_handler.add_user` / `update_user`**

把 `MeterStats/modules/system/settings_handler.py:223-247` 整段替换为：

```python
def add_user(users: List[dict], username: str, password: str, name: str, role: str,
             store_ids: Optional[List[str]] = None,
             all_stores: Optional[bool] = None) -> Optional[dict]:
    """新增用户。

    门店归属:
    - all_stores 省略时,admin 默认 True(总部账号可跨店),其它角色默认 False
    - store_ids 是该用户可访问的门店 ID 列表;非总部账号必须有值才能看到数据
    """
    if any(u["username"] == username for u in users):
        return {"error": "用户名已存在"}
    users.append({
        "id": get_next_user_id(users),
        "username": username,
        "password": _hash_pass(password),
        "role": role,
        "name": name,
        "enabled": True,
        "all_stores": (role == ROLE_ADMIN) if all_stores is None else bool(all_stores),
        "store_ids": list(store_ids) if isinstance(store_ids, list) else [],
        "created_at": datetime.now().isoformat(),
    })
    return users[-1]


def update_user(users: List[dict], uid: int, fields: dict) -> Optional[dict]:
    """更新用户。门店归属字段:store_ids / all_stores。"""
    for u in users:
        if u["id"] == uid:
            for k in ("username", "name", "role", "enabled"):
                if k in fields:
                    u[k] = fields[k]
            if "all_stores" in fields:
                u["all_stores"] = bool(fields["all_stores"])
            if "store_ids" in fields:
                v = fields["store_ids"]
                u["store_ids"] = [str(x) for x in v] if isinstance(v, list) else []
            if "password" in fields and fields["password"]:
                u["password"] = _hash_pass(fields["password"])
            return u
    return None
```

- [ ] **Step 4: 改 `users_handler` 透传门店字段**

把 `MeterStats/modules/system/users_handler.py:23-48` 的 `handle_post_users` 整段替换为：

```python
def handle_post_users(handler):
    """POST /api/admin/users {username, password, name, role, store_ids?, all_stores?} → {ok, user}"""
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    users = settings.get("users", [])
    username = (body or {}).get("username", "")
    password = (body or {}).get("password", "")
    name = (body or {}).get("name", username)
    role = (body or {}).get("role", "employee")
    store_ids = (body or {}).get("store_ids")
    all_stores = (body or {}).get("all_stores")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    result = add_user(users, username, password, name, role,
                      store_ids=store_ids if isinstance(store_ids, list) else None,
                      all_stores=all_stores if isinstance(all_stores, bool) else None)
    if isinstance(result, dict) and "error" in result:
        send_json(handler, 200, {"ok": False, "error": result["error"]})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "user": result})
```

`handle_put_users` 不用改 —— 它把整个 body 交给 `update_user(users, uid, body)`,而 `update_user` 已经支持新字段。

把 `handle_get_users` 的返回值补上门店字段(其实密码以外的字段本来就全返回了,这里只需确认不泄露密码 —— 已满足,无需改动)。

- [ ] **Step 5: 改 `auth_handler.create_session` 与登录返回**

把 `MeterStats/modules/system/auth_handler.py:148-162` 的 `create_session` 整段替换为：

```python
def create_session(user: dict) -> str:
    """创建新会话,返回 token。

    会话里带上门店范围(all_stores / store_ids)作为兜底 ——
    门店闸优先读 settings.json 里的最新用户记录,读不到时才用这里的值。
    """
    _cleanup_expired_sessions()
    token = secrets.token_hex(32)
    now = time.time()
    role = user.get("role", "employee")
    store_ids = user.get("store_ids")
    with _SESSIONS_LOCK:
        _SESSIONS[token] = {
            "user_id": user["id"],
            "username": user["username"],
            "role": role,
            "name": user["name"],
            "all_stores": bool(user.get("all_stores", role == "admin")),
            "store_ids": [str(x) for x in store_ids] if isinstance(store_ids, list) else [],
            "created_at": datetime.datetime.fromtimestamp(now).isoformat(),
            "_access_time": now,
        }
    return token
```

把 `handle_post_login` 里的 `user_info` 与返回值补上门店范围 —— 把

```python
    # 创建新会话(含 TTL)
    user_info = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "name": user["name"],
    }
    token = create_session(user_info)
```

替换为：

```python
    # 创建新会话(含 TTL)
    user_info = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "name": user["name"],
        "all_stores": bool(user.get("all_stores", user.get("role") == "admin")),
        "store_ids": user.get("store_ids") if isinstance(user.get("store_ids"), list) else [],
    }
    token = create_session(user_info)
```

并把返回的 `user` 字典补上门店字段:

```python
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
            "all_stores": user_info["all_stores"],
            "store_ids": user_info["store_ids"],
        },
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python3 -m unittest tests.test_stores -v`
Expected: PASS

- [ ] **Step 7: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 + 新增全部通过

- [ ] **Step 8: 提交**

```bash
git add MeterStats/modules/system/settings_handler.py MeterStats/modules/system/users_handler.py \
        MeterStats/modules/system/auth_handler.py tests/test_stores.py
git commit -m "feat(stores): 用户门店归属(分店员工绑单店,总部账号可跨店)"
```

---

### Task 7: 备份 / 恢复 / NAS 同步 / 图片 覆盖 `stores/` 子树

**Files:**
- Modify: `MeterStats/storage.py:211-341`（`backup_data`）
- Modify: `MeterStats/modules/backup/handler.py:75-97`（`handle_get_data_files`）、`:149-229`（`handle_post_backup`）、`:232-300`（`handle_post_restore`）、`:303-463`（`handle_post_upload`）
- Modify: `MeterStats/modules/backup/admin_handler.py`（`handle_post_backup_download` / `handle_post_backup_delete` / `handle_post_restore_upload` / `handle_post_sync_from_nas`）
- Modify: `MeterStats/modules/duty/handler.py:150-175`（`_get_images_dir`）
- Test: `tests/test_stores.py`（追加用例）

> ⚠️ **本 Task 的关键陷阱**:现有备份/恢复代码全部用
> `data_dir = get_data_paths().get("readings")` 再取 `data_dir.parent` 当作数据根目录。
> 多门店布局下 `get_data_paths()` 返回的是**当前门店**的路径,`.parent` 就是
> `stores/<当前店>/` —— 备份会只抓到一个门店的目录,严重不完整。
> **必须全部改用 `context.base_data_dir()`**。

**Interfaces:**
- Consumes: Task 1 的 `context.base_data_dir()` / `context.store_dir()` / `context.get_current_store()`
- Produces:
  - `storage.backup_data(data_dir, force=False, target_parent=None)` —— 备份包内额外包含 `stores/<id>/<file>` 条目
  - `modules/backup/handler.py` 新增内部函数 `_iter_store_files(base_dir) -> list[tuple[str, Path]]` —— 返回 `(相对路径, 绝对路径)` 列表
  - `modules/backup/handler.py` 新增内部函数 `_safe_rel_target(base_dir, rel) -> Path | None` —— 解析备份包内的相对路径,**挡路径穿越**

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_stores.py`）

```python
class TestStoreBackup(StoreTestBase):
    """备份 / 恢复 必须覆盖 stores/ 子树。"""

    def _setup_stores(self):
        from modules.system.settings_handler import init_settings
        init_settings(self.data_dir)
        main = self.data_dir / "stores" / "main"
        s002 = self.data_dir / "stores" / "s002"
        main.mkdir(parents=True)
        s002.mkdir(parents=True)
        (main / "readings.json").write_text(
            '[{"date": "2026-11-01", "hall": 1.0}]', encoding="utf-8")
        (s002 / "readings.json").write_text(
            '[{"date": "2026-11-02", "hall": 2.0}]', encoding="utf-8")

    def test_backup_zip_contains_all_stores(self):
        self._setup_stores()
        from storage import backup_data
        zip_path = backup_data(self.data_dir, force=True)
        self.assertIsNotNone(zip_path)
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("stores/main/readings.json", names)
        self.assertIn("stores/s002/readings.json", names)

    def test_backup_contains_settings_json(self):
        self._setup_stores()
        from storage import backup_data
        zip_path = backup_data(self.data_dir, force=True)
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("settings.json", names)

    def test_safe_rel_target_rejects_traversal(self):
        from modules.backup.handler import _safe_rel_target
        self.assertIsNone(_safe_rel_target(self.data_dir, "../../etc/passwd"))
        self.assertIsNone(_safe_rel_target(self.data_dir, "stores/../../evil.json"))

    def test_safe_rel_target_accepts_store_path(self):
        from modules.backup.handler import _safe_rel_target
        p = _safe_rel_target(self.data_dir, "stores/s002/readings.json")
        self.assertIsNotNone(p)
        self.assertEqual(p, self.data_dir / "stores" / "s002" / "readings.json")

    def test_data_files_endpoint_includes_store_files(self):
        self._setup_stores()
        from modules.backup.handler import handle_get_data_files
        h = _ApiHandler("/api/admin/data-files", method="GET")
        handle_get_data_files(h)
        files = h.parsed["files"]
        self.assertIn("stores/main/readings.json", files)
        self.assertIn("stores/s002/readings.json", files)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores -v`
Expected: FAIL —— `ImportError: cannot import name '_safe_rel_target'`

- [ ] **Step 3: 改 `storage.backup_data` 覆盖 `stores/` 子树**

在 `MeterStats/storage.py` 的 `backup_data()` 中,把

```python
    # 自动备份也包含 settings.json（与手动备份一致）
    settings_src = data_dir / "settings.json"
```

这一段之前,插入:

```python
    # 多门店布局:stores/ 整个子树也要进备份。
    # P0 之后数据都在 stores/<store_id>/ 下,不复制的话备份包是空的。
    stores_dir = data_dir / "stores"
    if stores_dir.is_dir():
        for src in sorted(stores_dir.rglob("*")):
            if not src.is_file():
                continue
            if src.suffix not in (".json", ".tmp"):
                continue
            rel = src.relative_to(data_dir)
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dest)
                log(f"[BACKUP] 已复制 {rel} → {backup_dir}")
            except OSError as e:
                log(f"[BACKUP] 复制 {rel} 失败: {e}")
                raise
```

> 注意:`.tmp` 是原子写的临时文件,正常不会残留,但保留复制以防万一;`.tmp` 文件在恢复时会被路径白名单挡掉(见 Step 4)。

同时**必须改 ZIP 打包那一段** —— 现有代码只遍历 `backup_dir.iterdir()`,
拿到的是**顶层条目**,`stores/` 是目录会被跳过,备份包里就不会有门店数据。
把 `MeterStats/storage.py` 里的

```python
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 只打包数据文件,跳过 zip_path 自身(避免 zip 包含自身 0 字节空文件)
            for f in sorted(backup_dir.iterdir()):
                if f.is_file() and f != zip_path:
                    zf.write(f, f.name)
```

替换为:

```python
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 递归打包(含 stores/ 子树),跳过 zip_path 自身
            # ⚠️ 必须用 rglob:iterdir() 只拿到顶层条目,stores/ 是目录会被跳过
            for f in sorted(backup_dir.rglob("*")):
                if f.is_file() and f != zip_path:
                    zf.write(f, str(f.relative_to(backup_dir)))
```

- [ ] **Step 4: 在 `modules/backup/handler.py` 加路径工具并改造备份/恢复**

在 `MeterStats/modules/backup/handler.py` 的 `_filter_settings_for_backup` 之前插入:

```python
def _iter_store_files(base_dir: Path) -> list:
    """列出 stores/ 子树下的数据文件。

    返回 [(相对路径, 绝对路径)],相对路径形如 "stores/s002/readings.json"。
    """
    out = []
    stores_dir = base_dir / "stores"
    if not stores_dir.is_dir():
        return out
    for src in sorted(stores_dir.rglob("*.json")):
        if not src.is_file():
            continue
        out.append((str(src.relative_to(base_dir)).replace("\\", "/"), src))
    return out


def _safe_rel_target(base_dir: Path, rel: str) -> "Path | None":
    """把备份包里的相对路径解析成目标路径,挡掉路径穿越。

    允许的两种形态:
    - 顶层数据文件:readings.json / settings.json 等
    - 门店子文件:stores/<safe_id>/<safe_name>.json

    其它一律拒绝(返回 None)。特别是 ".." 和绝对路径。
    """
    if not rel or rel.startswith("/") or "\\" in rel:
        return None
    parts = rel.split("/")
    if len(parts) == 1:
        if parts[0] in set(DATA_FILES.values()) | {"settings.json"}:
            return base_dir / parts[0]
        return None
    if len(parts) == 3 and parts[0] == "stores":
        from modules.stores.registry import is_valid_store_id
        if not is_valid_store_id(parts[1]):
            return None
        if parts[2] not in set(DATA_FILES.values()) | {"store.json"}:
            return None
        return base_dir / "stores" / parts[1] / parts[2]
    return None
```

把 `handle_get_data_files` 整段替换为:

```python
def handle_get_data_files(handler):
    """GET /api/admin/data-files — 浏览器备份: 获取所有数据文件的当前内容。

    返回 { ok: true, files: { "readings.json": "<JSON字符串>", ... } }
    多门店布局下额外包含 "stores/<id>/<name>.json" 形式的条目。
    """
    from modules.stores.context import base_data_dir
    target_dir = base_data_dir()
    files = {}
    data_file_names = set(DATA_FILES.values()) | {"settings.json"}

    for f in target_dir.iterdir():
        if f.is_file() and f.suffix == '.json' and f.name in data_file_names:
            try:
                files[f.name] = f.read_text(encoding="utf-8")
            except OSError as e:
                log(f"[WARN] 读取 {f.name} 失败: {e}")

    for rel, path in _iter_store_files(target_dir):
        try:
            files[rel] = path.read_text(encoding="utf-8")
        except OSError as e:
            log(f"[WARN] 读取 {rel} 失败: {e}")

    send_json(handler, 200, {"ok": True, "files": files})
```

把 `handle_post_backup` 中的

```python
    data_dir = get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    source_dir = data_dir.parent
```

替换为:

```python
    from modules.stores.context import base_data_dir
    source_dir = base_data_dir()
```

并在打包 ZIP 之前(复制完 settings.json 之后),插入 stores 子树的复制:

```python
        # 多门店布局:复制 stores/ 子树(保持相对路径)
        for rel, src in _iter_store_files(source_dir):
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
```

把 ZIP 打包那段

```python
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(backup_dir.iterdir()):
                # 只打包数据文件和剥离后的 settings.json,跳过 zip_path 自身
                if f.is_file() and f != zip_path:
                    zf.write(f, f.name)
```

替换为:

```python
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(backup_dir.rglob("*")):
                # 打包全部文件(含 stores/ 子树),跳过 zip_path 自身
                if f.is_file() and f != zip_path:
                    zf.write(f, str(f.relative_to(backup_dir)))
```

把 `handle_post_restore` 中的

```python
    # 恢复前自动备份当前数据(可回滚)
    pre_backup = backup_data(data_dir.parent, force=True) if (data_dir := get_data_paths().get("readings")) else None
```

替换为:

```python
    from modules.stores.context import base_data_dir
    target_dir = base_data_dir()

    # 恢复前自动备份当前数据(可回滚)
    pre_backup = backup_data(target_dir, force=True)
```

并把该函数里

```python
            target_dir = (data_dir.parent if data_dir else Path("/data"))

            # 找到解压出的数据目录（可能是 YYYYMMDD_HHMMSS/ 子目录或根目录）
            extract_dir = Path(tmp_dir)
            children = list(extract_dir.iterdir())
            if len(children) == 1 and children[0].is_dir():
                extract_dir = children[0]

            # 恢复数据文件
            restored = []
            for name in DATA_FILES.values():
                src_file = extract_dir / name
                if src_file.exists():
                    shutil.copy2(src_file, target_dir / name)
                    restored.append(name)
                    log(f"  恢复 {name} <- {src_file}")
```

替换为:

```python
            # 找到解压出的数据目录（可能是 YYYYMMDD_HHMMSS/ 子目录或根目录）
            extract_dir = Path(tmp_dir)
            children = list(extract_dir.iterdir())
            if len(children) == 1 and children[0].is_dir():
                extract_dir = children[0]

            # 恢复数据文件 —— 顶层 + stores/ 子树
            restored = []
            for name in DATA_FILES.values():
                src_file = extract_dir / name
                if src_file.exists():
                    shutil.copy2(src_file, target_dir / name)
                    restored.append(name)
                    log(f"  恢复 {name} <- {src_file}")

            for rel, src_path in _iter_store_files(extract_dir):
                dest = _safe_rel_target(target_dir, rel)
                if dest is None:
                    log(f"  [WARN] 跳过非法备份路径: {rel}")
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest)
                restored.append(rel)
                log(f"  恢复 {rel} <- {src_path}")
```

把 `handle_post_upload` 中的

```python
    data_dir = get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    target_dir = data_dir.parent
```

替换为:

```python
    from modules.stores.context import base_data_dir
    target_dir = base_data_dir()
```

并把 `_extract_zip_to_target` 里的

```python
        for name in DATA_FILES.values():
            src = extract_dir / name
            if src.exists():
                shutil.copy2(src, target_dir / name)
                names.append(name)
                log(f"  恢复 {name} <- {src}")
```

替换为:

```python
        for name in DATA_FILES.values():
            src = extract_dir / name
            if src.exists():
                shutil.copy2(src, target_dir / name)
                names.append(name)
                log(f"  恢复 {name} <- {src}")
        # 恢复 stores/ 子树
        for rel, src_path in _iter_store_files(extract_dir):
            dest = _safe_rel_target(target_dir, rel)
            if dest is None:
                log(f"  [WARN] 跳过非法备份路径: {rel}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)
            names.append(rel)
            log(f"  恢复 {rel} <- {src_path}")
```

并把 JSON body 分支里的文件名白名单判断

```python
                elif fname in DATA_FILES.values() or fname == "settings.json":
```

改成同时接受门店子路径:

```python
                elif fname in DATA_FILES.values() or fname == "settings.json" \
                        or _safe_rel_target(target_dir, fname) is not None:
```

> ⚠️ 注意 multipart 分支也有同样的一行 `elif fname in DATA_FILES.values() or fname == "settings.json":`,两处都要改。

- [ ] **Step 5: 改 `modules/backup/admin_handler.py` 的四处**

`handle_post_backup_download` / `handle_post_backup_delete` 用的是备份目录下的 ZIP 文件名,不涉及数据目录,无需改路径 —— **但** `handle_post_restore_upload` 和 `handle_post_sync_from_nas` 需要改。

把 `handle_post_sync_from_nas` 里的

```python
    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    target_dir = data_dir.parent
```

替换为:

```python
    from modules.stores.context import base_data_dir
    target_dir = base_data_dir()
```

并把写入循环里的

```python
        if name in DATA_FILES.values() or name == "settings.json":
```

替换为:

```python
        from modules.backup.handler import _safe_rel_target
        rel_target = _safe_rel_target(target_dir, name)
        if rel_target is not None:
```

并把该分支体改成用 `rel_target` 而不是 `target_dir / name`:

```python
            try:
                if name == "settings.json":
                    # ⚠️ settings.json 必须"合并"而不是"覆盖" —— 远端实例并不知道
                    # 本机的部署字段(nas_sync_user/nas_sync_pass/nas_sync_url/backup_dir)。
                    # 直接覆盖会导致:同步一次 → 本机 NAS 凭据被清空 → 下次同步直接失败。
                    import json as _json
                    try:
                        src_settings = _json.loads(content)
                    except ValueError as e:
                        errors.append(f"跳过 settings.json: 不是合法 JSON ({e})")
                        continue
                    if not isinstance(src_settings, dict):
                        errors.append("跳过 settings.json: 不是对象结构")
                        continue
                    _merge_settings_after_restore(target_dir, src_settings)
                else:
                    rel_target.parent.mkdir(parents=True, exist_ok=True)
                    rel_target.write_text(content, encoding="utf-8")
                restored.append(name)
                log(f"  同步写入 {name}")
            except Exception as e:
                errors.append(f"{name}: {e}")
```

把 `handle_post_restore_upload` 里的目标目录解析同样改成 `base_data_dir()`,并把其中的文件白名单判断替换为 `_safe_rel_target`。

- [ ] **Step 6: 改 `modules/duty/handler.py` 的图片目录按门店隔离**

把 `MeterStats/modules/duty/handler.py:150-175` 的 `_get_images_dir()` 整段替换为:

```python
def _get_images_dir():
    """获取图片目录(按门店隔离)。

    优先用设置里的 image_dir(数据管理页可配置),但这个值可能是从 Docker
    部署带过来的绝对路径(例如 /data/images)—— 在 macOS 上既不存在也创建
    不了(Read-only file system),直接 mkdir 会让整个上传接口 500。
    所以创建失败时回退到「当前门店目录/images」,保证上传永远有地方落盘。

    多门店布局下,图片落在 stores/<store_id>/images/,不同门店互不干扰。
    """
    from modules.stores.context import multi_store_layout, store_dir, get_current_store
    from storage import get_data_dir

    settings = _get_settings()

    if multi_store_layout():
        base = store_dir(get_current_store())
        fallback = base / "images"
        configured = (settings.get("image_dir") or "").strip()
        if configured:
            try:
                d = Path(configured)
                d.mkdir(parents=True, exist_ok=True)
                return d
            except OSError:
                pass
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    data_dir = get_data_dir()
    fallback = Path(data_dir) / "images"
    configured = (settings.get("image_dir") or "").strip()
    if configured:
        try:
            d = Path(configured)
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            pass
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback
```

- [ ] **Step 7: 运行测试确认通过**

Run: `python3 -m unittest tests.test_stores -v`
Expected: PASS

- [ ] **Step 8: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 + 新增全部通过

若 `test_handlers.py` 里的备份用例失败,检查 `handle_post_backup` 是否已改用 `base_data_dir()` —— 用 `get_data_paths()` 会导致备份目录算错。

- [ ] **Step 9: 提交**

```bash
git add MeterStats/storage.py MeterStats/modules/backup/handler.py \
        MeterStats/modules/backup/admin_handler.py MeterStats/modules/duty/handler.py \
        tests/test_stores.py
git commit -m "fix(stores): 备份/恢复/NAS 同步覆盖 stores/ 子树,图片按店隔离"
```

---

### Task 8: 前端 — 门店管理页与用户门店分配

**Files:**
- Create: `MeterStats/js/modules/stores.js`
- Create: `tests/test_stores_frontend.py`
- Modify: `MeterStats/js/core/api.js`（新增 `Api.stores`）
- Modify: `MeterStats/index.html`（侧栏入口 + 引入 `stores.js`）
- Modify: `MeterStats/admin.js`（用户管理表单加门店多选）

**Interfaces:**
- Consumes: Task 5 的 HTTP 契约；Task 6 的用户字段 `store_ids` / `all_stores`
- Produces:
  - `Api.stores.list()` → `GET /api/stores`
  - `Api.stores.current()` → `GET /api/stores/current`
  - `Api.stores.create(data)` → `POST /api/stores`
  - `Api.stores.update(id, data)` → `PUT /api/stores/<id>`
  - `Api.stores.remove(id)` → `DELETE /api/stores/<id>`
  - 全局函数 `renderStoresPage()` —— 渲染门店管理页
  - 全局函数 `switchSettingsPage('stores')` 支持 `'stores'` 分支

- [ ] **Step 1: 写失败测试**（创建 `tests/test_stores_frontend.py`）

```python
"""分店前端接线回归测试(标准库 unittest,零依赖)。

只做静态接线检查(与 tests/test_frontend_refresh.py 同风格):
- index.html 引入了 stores.js,侧栏有「门店管理」入口
- api.js 有 Api.stores 封装
- stores.js 渲染门店列表并调用 Api.stores.create / update / remove
- admin.js 的用户表单带门店多选
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
INDEX_HTML = METERSTATS / "index.html"
API_JS = METERSTATS / "js" / "core" / "api.js"
STORES_JS = METERSTATS / "js" / "modules" / "stores.js"
ADMIN_JS = METERSTATS / "admin.js"


class TestStoresFrontendWiring(unittest.TestCase):

    def test_stores_js_is_loaded_by_index(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn("js/modules/stores.js", html)

    def test_sidebar_has_stores_entry(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn("switchSettingsPage('stores')", html)
        self.assertIn("门店管理", html)

    def test_index_has_stores_section(self):
        """switchSettingsPage 靠 section-settings-<page> 找容器,id 必须对。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="section-settings-stores"', html)

    def test_api_exposes_stores_endpoints(self):
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("var stores = {", src)
        for call in ("/api/stores", "create:", "update:", "remove:"):
            self.assertIn(call, src)

    def test_api_returns_stores_in_public_surface(self):
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("stores: stores", src)

    def test_stores_js_renders_list_and_calls_api(self):
        src = STORES_JS.read_text(encoding="utf-8")
        self.assertIn("function renderStoresPage", src)
        self.assertIn("Api.stores.list()", src)
        self.assertIn("Api.stores.create", src)
        self.assertIn("Api.stores.update", src)
        self.assertIn("Api.stores.remove", src)

    def test_admin_js_has_store_multi_select(self):
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("store_ids", src)
        self.assertIn("all_stores", src)

    def test_user_form_renders_store_checkboxes(self):
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertRegex(src, r"store_ids")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_stores_frontend -v`
Expected: FAIL —— `js/modules/stores.js` 不存在

- [ ] **Step 3: 在 `js/core/api.js` 加 `Api.stores`**

在 `js/core/api.js` 的 `var migrate = {` 之前插入:

```javascript
    // 分店模块 API (5个端点) — 门店管理页用
    var stores = {
        list: function() { return _request('GET', '/api/stores'); },
        current: function() { return _request('GET', '/api/stores/current'); },
        create: function(data) { return _request('POST', '/api/stores', data); },
        update: function(id, data) { return _request('PUT', '/api/stores/' + id, data); },
        remove: function(id) { return _request('DELETE', '/api/stores/' + id); },
    };
```

并把文件末尾的 return 语句改成:

```javascript
    return { 
        readings: readings, charges: charges, utilities: utilities, 
        items: items, purchases: purchases, duty: duty, 
        reports: reports, system: system,
        admin: admin, backup: backup, dataimport: dataimport,
        upload: upload, proxy: proxy, images: images, migrate: migrate,
        adminRestore: adminRestore, adminImport: adminImport,
        stores: stores
    };
```

- [ ] **Step 4: 创建 `js/modules/stores.js`**

```javascript
/**
 * 门店管理页 — 管理员维护分店。
 *
 * P0 范围:门店的增删改查 + 每店记录数展示。
 * P1 会在这里接入门店切换器(总部账号在侧栏顶部切店)。
 */

// ===== 门店状态 =====
var STORE_LIST = [];          // 当前用户可见的门店
var STORE_EDITING_ID = null;  // 正在编辑的门店 ID(null = 新增)

// ===== 渲染 =====

/** 渲染门店管理页主体 */
function renderStoresPage() {
    var host = document.getElementById('stores-page');
    if (!host) return;

    var rows = STORE_LIST.map(function(s) {
        var counts = s.record_counts || {};
        var total = Object.keys(counts).reduce(function(a, k) { return a + (counts[k] || 0); }, 0);
        return '<tr>' +
            '<td><strong>' + escapeHtml(s.name || s.id) + '</strong></td>' +
            '<td><code>' + escapeHtml(s.id) + '</code></td>' +
            '<td>' + escapeHtml(s.code || '—') + '</td>' +
            '<td>' + escapeHtml(s.address || '—') + '</td>' +
            '<td>' + (s.active === false ? '停用' : '启用') + '</td>' +
            '<td>' + total + '</td>' +
            '<td>' +
                '<button type="button" class="btn btn-secondary btn-sm" onclick="editStore(\'' + s.id + '\')">编辑</button> ' +
                '<button type="button" class="btn btn-danger btn-sm" onclick="removeStore(\'' + s.id + '\')">删除</button>' +
            '</td>' +
        '</tr>';
    }).join('');

    if (!rows) {
        rows = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:20px;">暂无门店</td></tr>';
    }

    host.innerHTML =
        '<div class="card">' +
            '<div class="card-header"><h3>🏪 门店管理</h3>' +
            '<button type="button" class="btn btn-primary btn-sm" onclick="resetStoreForm()">+ 新增门店</button></div>' +
            '<div style="overflow-x:auto;">' +
            '<table class="settings-table"><thead><tr>' +
                '<th>门店名称</th><th>门店 ID</th><th>编号</th><th>地址</th><th>状态</th><th>记录数</th><th class="ta-right">操作</th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>' +
            '</div>' +
        '</div>' +
        '<div class="card" id="store-form-card" style="display:none;">' +
            '<div class="card-header"><h3 id="store-form-title">新增门店</h3></div>' +
            '<form id="store-form" onsubmit="return saveStore(event)">' +
                '<input type="hidden" id="store-id" />' +
                '<div class="form-row">' +
                    '<label>门店 ID<code style="color:var(--text-muted);">(字母/数字/下划线,创建后不可改)</code></label>' +
                    '<input type="text" id="store-name-input" required placeholder="例如 s002" ' +
                        'pattern="[A-Za-z0-9_-]{1,32}" />' +
                '</div>' +
                '<div class="form-row">' +
                    '<label>门店名称</label>' +
                    '<input type="text" id="store-name" required placeholder="例如 国贸店" />' +
                '</div>' +
                '<div class="form-row">' +
                    '<label>编号</label>' +
                    '<input type="text" id="store-code" placeholder="例如 B002" />' +
                '</div>' +
                '<div class="form-row">' +
                    '<label>地址</label>' +
                    '<input type="text" id="store-address" placeholder="选填" />' +
                '</div>' +
                '<div class="form-actions">' +
                    '<button type="submit" class="btn btn-primary" id="store-submit">保存</button>' +
                    '<button type="button" class="btn btn-secondary" onclick="resetStoreForm()">取消</button>' +
                '</div>' +
            '</form>' +
        '</div>';
}

/** 加载门店列表 */
async function loadStores() {
    try {
        var res = await Api.stores.list();
        STORE_LIST = (res && res.stores) || [];
    } catch (e) {
        STORE_LIST = [];
        showAlert('加载门店列表失败: ' + e, 'error');
    }
    renderStoresPage();
}

// ===== 操作 =====

/** 开始新增门店 */
function resetStoreForm() {
    STORE_EDITING_ID = null;
    var card = document.getElementById('store-form-card');
    var title = document.getElementById('store-form-title');
    var idInput = document.getElementById('store-id');
    var nameInput = document.getElementById('store-name-input');
    if (card) card.style.display = 'block';
    if (title) title.textContent = '新增门店';
    if (idInput) { idInput.value = ''; idInput.disabled = false; }
    if (nameInput) nameInput.value = '';
    var s = document.getElementById('store-name');
    if (s) s.value = '';
    var c = document.getElementById('store-code');
    if (c) c.value = '';
    var a = document.getElementById('store-address');
    if (a) a.value = '';
}

/** 开始编辑门店 */
function editStore(id) {
    var s = STORE_LIST.find(function(x) { return x.id === id; });
    if (!s) return;
    STORE_EDITING_ID = id;
    var card = document.getElementById('store-form-card');
    var title = document.getElementById('store-form-title');
    var idInput = document.getElementById('store-id');
    if (card) card.style.display = 'block';
    if (title) title.textContent = '编辑门店: ' + (s.name || s.id);
    if (idInput) { idInput.value = id; idInput.disabled = true; }
    var n = document.getElementById('store-name');
    if (n) n.value = s.name || '';
    var c = document.getElementById('store-code');
    if (c) c.value = s.code || '';
    var a = document.getElementById('store-address');
    if (a) a.value = s.address || '';
}

/** 保存门店(新增或编辑) */
async function saveStore(ev) {
    if (ev) ev.preventDefault();
    var id = (document.getElementById('store-id') || {}).value || '';
    var name = (document.getElementById('store-name') || {}).value || '';
    var code = (document.getElementById('store-code') || {}).value || '';
    var address = (document.getElementById('store-address') || {}).value || '';
    if (!id || !name.trim()) {
        showAlert('门店 ID 和名称不能为空', 'error');
        return false;
    }
    var payload = { name: name.trim(), code: code, address: address };
    try {
        var res;
        if (STORE_EDITING_ID) {
            res = await Api.stores.update(STORE_EDITING_ID, payload);
        } else {
            payload.id = id.trim();
            res = await Api.stores.create(payload);
        }
        if (res && res.ok === false) {
            showAlert(res.error || '保存失败', 'error');
            return false;
        }
        showAlert(STORE_EDITING_ID ? '门店已更新' : '门店已创建', 'success');
        resetStoreForm();
        await loadStores();
    } catch (e) {
        showAlert('保存失败: ' + e, 'error');
    }
    return false;
}

/** 删除门店 */
async function removeStore(id) {
    var s = STORE_LIST.find(function(x) { return x.id === id; });
    var name = s ? (s.name || s.id) : id;
    if (!confirm('确定删除门店「' + name + '」?\n\n注意:只删除门店登记信息,数据目录不会被删除。')) return;
    try {
        var res = await Api.stores.remove(id);
        if (res && res.ok === false) {
            showAlert(res.error || '删除失败', 'error');
            return;
        }
        showAlert('门店已删除', 'success');
        await loadStores();
    } catch (e) {
        showAlert('删除失败: ' + e, 'error');
    }
}

// ===== 页面挂载 =====

// 用户管理页的门店多选需要门店列表,提前拉一次并缓存
window.loadStores = loadStores;
```

> `escapeHtml` **已经存在** —— `js/helpers/utils.js:12` 定义了 `window.escapeHtml`,
> 全项目共用。直接调用,不要在本文件重复定义。

- [ ] **Step 5: 在 `index.html` 加侧栏入口并引入脚本**

在 `index.html` 的侧栏设置分组里,把

```html
        <button class="sidebar-item" data-section="settings-users" onclick="switchSettingsPage('users')"><span class="item-icon">👥</span><span class="item-label">用户管理</span></button>
```

改成(新增一行「门店管理」放在用户管理之前):

```html
        <button class="sidebar-item" data-section="settings-stores" onclick="switchSettingsPage('stores')"><span class="item-icon">🏪</span><span class="item-label">门店管理</span></button>
        <button class="sidebar-item" data-section="settings-users" onclick="switchSettingsPage('users')"><span class="item-icon">👥</span><span class="item-label">用户管理</span></button>
```

在 `index.html` 的 `<script>` 引入区加入 —— 放在 `js/modules/backup.js` 那一行**之后**
(与其它 `js/modules/*.js` 排在一起,模块分组更整齐):

```html
  <script src="js/modules/stores.js"></script>
```

> 加载顺序说明:`api.js`(1546 行)在 `js/modules/*.js` 之前,`modals.js`(1552 行)也在前面,
> 所以 `stores.js` 里用到的 `Api.stores.*` / `showModal` / `showAlert` 在定义时都已就绪。
> `admin.js`(1569 行)在 `stores.js` 之后 —— 它要用到 `ensureStoreList()`,
> 而 `ensureStoreList` 定义在 `admin.js` 自己内部,不依赖 `stores.js`,没有时序问题。

并在 `section-settings-users` **之前**插入门店管理页容器:

```html
  <!-- ===== 门店管理（独立页面） ===== -->
  <section id="section-settings-stores" class="content-section" style="display:none;">
    <div id="stores-page"></div>
  </section>
```

> ⚠️ `switchSettingsPage` 靠 `section-settings-<page>` 这个 id 找容器
> (`navigation.js:147`),所以 section 的 id **必须**是 `section-settings-stores`。
> `stores.js` 里的 `renderStoresPage()` 渲染到 section 内部的 `#stores-page`。

- [ ] **Step 6: 在 `js/core/navigation.js` 的 `switchSettingsPage` 加 `stores` 分支**

`switchSettingsPage` 靠 `section-settings-<page>` 这个 id 找容器(见 `navigation.js:147`),
所以只要 index.html 里有 `<section id="section-settings-stores">` 就自动能切。

把 `MeterStats/js/core/navigation.js:177` 的

```javascript
  if (page === 'roles' && typeof loadRolesInfo === 'function') loadRolesInfo();
}
```

替换为:

```javascript
  if (page === 'roles' && typeof loadRolesInfo === 'function') loadRolesInfo();
  // 门店管理:拉一次门店列表再渲染
  if (page === 'stores' && typeof loadStores === 'function') loadStores();
}
```

- [ ] **Step 7: 在 `admin.js` 的用户管理加门店多选**

现有结构(`admin.js:157-244`):
- `loadAdminUsers()` 渲染表格到 `#users-table-body`
- `addAdminUser()` 读 `#new-username` / `#new-password` / `#new-name` / `#new-role` 后提交
- `editAdminUser(uid, oldUsername)` 用 `prompt()` 逐项改显示名/角色/密码

**改动 1 —— 表格加「门店」列。** 把 `admin.js:179-192` 的 `tbody.innerHTML = usersList.map(u => \`` 那一整段模板替换为:

```javascript
    tbody.innerHTML = usersList.map(u => `
        <tr>
          <td>${u.username}</td>
          <td>${u.name}</td>
          <td><span class="role-badge role-${u.role}">${ROLE_NAMES[u.role] || u.role}</span></td>
          <td>${u.enabled
              ? '<span class="status-dot on"></span>启用'
              : '<span class="status-dot off"></span>禁用'}</td>
          <td>${userStoreScopeText(u)}</td>
          <td class="ta-right">
            <button class="btn btn-primary btn-xs" onclick="editAdminUser(${u.id},'${u.username}')">编辑</button>
            <button class="btn btn-secondary btn-xs" onclick="editUserStores(${u.id})">门店</button>
            ${ADMIN_DELETE_ROLES.has(ADMIN_USER?.role) && u.id !== ADMIN_USER?.id ? `<button class="btn btn-danger btn-xs" onclick="deleteAdminUser(${u.id})">删除</button>` : ''}
          </td>
        </tr>
      `).join('');
```

**改动 2 —— 加两个辅助函数。** 在 `admin.js` 的 `// ===== 用户管理 =====` 注释下面(`loadAdminUsers` 之前)插入:

```javascript
/** 用户的门店范围摘要(表格里显示)。 */
function userStoreScopeText(u) {
  if (u.all_stores) return '<span class="role-badge role-admin">全部门店</span>';
  var ids = u.store_ids || [];
  if (!ids.length) return '<span style="color:var(--text-muted);">未分配</span>';
  var names = ids.map(function(id) {
    var s = (window.STORE_LIST || []).find(function(x) { return x.id === id; });
    return s ? (s.name || s.id) : id;
  });
  return names.map(function(n) {
    return '<span class="role-badge">' + escapeHtml(n) + '</span>';
  }).join(' ');
}

/** 拉门店列表并缓存到 window.STORE_LIST(用户表格要显示门店名)。 */
function ensureStoreList() {
  if (window.STORE_LIST && window.STORE_LIST.length) return Promise.resolve(window.STORE_LIST);
  return Api.stores.list().then(function(res) {
    window.STORE_LIST = (res && res.stores) || [];
    return window.STORE_LIST;
  }).catch(function() {
    window.STORE_LIST = [];
    return window.STORE_LIST;
  });
}

/** 编辑某个用户的门店权限(弹窗多选)。 */
function editUserStores(uid) {
  Promise.all([Api.admin.users(), ensureStoreList()]).then(function(results) {
    var users = results[0] || [];
    var stores = results[1] || [];
    var u = users.find(function(x) { return x.id == uid; });
    if (!u) { showAlert('用户不存在', 'error'); return; }

    var boxes = stores.map(function(s) {
      var checked = (u.store_ids || []).indexOf(s.id) >= 0 ? ' checked' : '';
      return '<label style="display:inline-flex;align-items:center;gap:6px;margin:4px 12px 4px 0;">' +
        '<input type="checkbox" name="edit-store-ids" value="' + escapeHtml(s.id) + '"' + checked + ' />' +
        escapeHtml(s.name || s.id) + '</label>';
    }).join('') || '<div style="color:var(--text-muted);">还没有门店,请先到「门店管理」创建</div>';

    var allChecked = u.all_stores ? ' checked' : '';
    showModal({
      title: '门店权限: ' + (u.name || u.username),
      icon: '🏪', iconKind: 'info',
      body: '<div style="margin-bottom:10px;">' +
              '<label style="display:inline-flex;align-items:center;gap:6px;">' +
                '<input type="checkbox" id="edit-all-stores"' + allChecked + ' /> 全部门店(总部账号)</label>' +
            '</div>' +
            '<div>' + boxes + '</div>',
      confirmText: '保存', confirmKind: 'primary'
    }).then(function(ok) {
      if (!ok) return;
      var picked = Array.prototype.slice.call(
        document.querySelectorAll('input[name="edit-store-ids"]:checked')
      ).map(function(el) { return el.value; });
      var all = (document.getElementById('edit-all-stores') || {}).checked || false;
      Api.admin.updateUser(uid, { store_ids: picked, all_stores: all }).then(function(res2) {
        if (!res2.ok) { showAlert('保存失败: ' + (res2.error || '未知错误'), 'error'); return; }
        showAlert('门店权限已更新', 'success');
        loadAdminUsers();
      }).catch(function(e) { showAlert('网络错误: ' + e.message, 'error'); });
    });
  }).catch(function(e) { showAlert('加载失败: ' + e.message, 'error'); });
}
```

**改动 3 —— 新增用户时带上门店。** 把 `admin.js:205` 的

```javascript
  Api.admin.createUser({ username: username, password: password, name: name, role: role }).then(function(res) {
```

替换为:

```javascript
  ensureStoreList().then(function(stores) {
    var storeIds = Array.prototype.slice.call(
      document.querySelectorAll('input[name="new-store-ids"]:checked')
    ).map(function(el) { return el.value; });
    var allStores = (document.getElementById('new-all-stores') || {}).checked || false;
    Api.admin.createUser({
      username: username, password: password, name: name, role: role,
      store_ids: storeIds, all_stores: allStores
    }).then(function(res) {
      if (!res.ok) { showAlert('添加失败: ' + (res.error || '未知错误'), 'error'); return; }
      showAlert('用户已添加: ' + username, 'success');
      document.getElementById('new-username').value = '';
      document.getElementById('new-password').value = '';
      document.getElementById('new-name').value = '';
      loadAdminUsers();
    }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
  });
```

同时把 `addAdminUser()` 里原来那行

```javascript
  Api.admin.createUser({...}).then(function(res) {
    if (!res.ok) { ... }
    showAlert('用户已添加: ' + username, 'success');
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-name').value = '';
    loadAdminUsers();
  }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
}
```

**整段删掉**(已被上面的 `ensureStoreList().then(...)` 包裹版本取代),只保留函数结尾的 `}`。

**改动 4 —— index.html 的用户管理区加门店多选控件。**

把 `index.html` 里 `section-settings-users` 的

```html
        <select id="new-role" class="field-control">
          <option value="employee">员工</option>
          <option value="supervisor">主管</option>
          <option value="admin">管理员</option>
        </select>
        <button class="btn btn-primary btn-sm" onclick="addAdminUser()">➕ 添加</button>
      </div>
```

替换为:

```html
        <select id="new-role" class="field-control">
          <option value="employee">员工</option>
          <option value="supervisor">主管</option>
          <option value="admin">管理员</option>
        </select>
        <label style="display:inline-flex;align-items:center;gap:4px;white-space:nowrap;">
          <input type="checkbox" id="new-all-stores"> 全部门店
        </label>
        <span id="new-store-ids-box" style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;"></span>
        <button class="btn btn-primary btn-sm" onclick="addAdminUser()">➕ 添加</button>
      </div>
```

并把用户表格的表头加一列 —— 把

```html
              <th>状态</th>
              <th class="ta-right">操作</th>
```

替换为:

```html
              <th>状态</th>
              <th>门店</th>
              <th class="ta-right">操作</th>
```

**改动 5 —— 渲染「新增用户」的门店勾选框。** 在 `admin.js` 的 `loadAdminUsers()` 末尾(`.catch(...)` 之前)插入:

```javascript
    // 新增用户时的门店勾选框
    ensureStoreList().then(function(stores) {
      var box = document.getElementById('new-store-ids-box');
      if (!box) return;
      box.innerHTML = stores.map(function(s) {
        return '<label style="display:inline-flex;align-items:center;gap:4px;white-space:nowrap;">' +
          '<input type="checkbox" name="new-store-ids" value="' + escapeHtml(s.id) + '" />' +
          escapeHtml(s.name || s.id) + '</label>';
      }).join('');
    });
```

> `loadAdminUsers()` 里 `Api.admin.users().then(function(users) { ... })` 的最后一行是
> `}).catch(e => showAlert('加载用户失败: ' + e.message, 'error'));` ——
> 把上面这段插在 `}).catch(...)` **之前**的 `});` 里面。

- [ ] **Step 8: 运行前端接线测试**

Run: `python3 -m unittest tests.test_stores_frontend -v`
Expected: PASS

- [ ] **Step 9: 运行全量回归**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS —— 169 + 分店后端用例 + 前端接线用例全部通过

- [ ] **Step 10: 静态检查**

Run: `ruff check .` → Expected: 无新增告警
Run: `mypy .` → Expected: 无新增告警

若 `mypy` 报 `escapeHtml` 重复定义,把该函数统一移到 `js/helpers/utils.js` 再引用。

- [ ] **Step 11: 提交**

```bash
git add MeterStats/js/modules/stores.js MeterStats/js/core/api.js MeterStats/index.html \
        MeterStats/js/core/navigation.js MeterStats/admin.js tests/test_stores_frontend.py
git commit -m "feat(stores): 门店管理页与用户门店分配"
```

---

## 验收清单（P0 完成时逐条核对）

- [ ] `python3 -m unittest discover -s tests -v` 全绿,**169 个存量用例一个不少**
- [ ] `ruff check .` 与 `mypy .` 无新增告警
- [ ] 新建一台干净数据目录启动服务 → 自动建出 `stores/main/`,服务可正常登录、录抄表、看报表
- [ ] 用旧数据目录启动服务 → 顶层数据自动搬进 `stores/main/`,顶层旧文件仍在(可回滚),备份目录里有迁移前的快照
- [ ] 手动备份产出的 ZIP 内含 `stores/main/readings.json` 与 `settings.json`
- [ ] 新建一个分店 → `stores/<id>/` 目录自动建好,6 个空数据文件就位
- [ ] 分店员工账号只勾了一个门店 → 登录后请求别的门店返回 403
- [ ] 总部账号(admin)可访问全部门店
- [ ] **口径未变**:用 2026 年 6 月 Excel 核对值 **71226.1 度** 复验通过(本计划不动 `report.py` 的计算口径,但报表缓存键在 P2 才加门店维度,P0 期间单店行为必须与改造前完全一致)
- [ ] `MeterStats/VERSION` **未改动**

## 交付后仍需人工确认的事项

1. **生产数据迁移**：本计划的迁移代码会在下次启动服务时自动执行。**执行前务必先手工备份** `~/Library/Application Support/com.meter.stats/`(或 Docker 的 `meter-data` 卷),并在迁移后逐文件比对 `stores/main/` 与备份内容。
2. **迁移回滚**：如迁移结果不对,停服 → 删掉 `stores/` 目录 → 把备份里的顶层文件拷回 → 启动服务(此时回到单店布局,门店闸整体放行,系统照常可用)。
3. **`build-app.sh` 暂缓**：该脚本会清空 Application Support,本次改造期间不要运行。

## 下一期预告（P1，不在本计划范围）

- 侧栏顶部门店切换器(总部账号可见),切换即换 `?store=` 参数重拉数据
- `Api._request` 统一带 `store` 参数
- `/api/snapshot` 按当前门店返回
- 登录后展示当前门店名
