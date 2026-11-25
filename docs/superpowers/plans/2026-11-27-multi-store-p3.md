# 分店功能 P3 实施计划 —— 总部总表（门店总览页）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让总部账号在**一个页面**上看清所有门店当月的用电与费用，并能横向对比；分店员工看到的是自己那家店。

**Architecture:** P2 已经把「每店自己的表集合 + 电价」做完了（`get_store_meters()` / `get_store_prices()` / `calculate_monthly_report(tables=..., price=...)`）。P3 不碰数据隔离与计算口径，只做**横向聚合**：新增 `GET /api/stores/overview?month=YYYY-MM`，遍历调用方有权限的门店，逐店用**它自己的**表集合与电价跑一遍月报，再把结果并起来；前端加一个「门店总览」页展示成表格 + 柱状图。

**Tech Stack:** Python 3.9+（零外部依赖，仅标准库）、纯 HTML/CSS/JS（无构建步骤）、`unittest`（存量 **650** 用例）+ node 行为验证。

---

## Global Constraints

- **Python 3.9+**：新模块首行 `from __future__ import annotations`；**零外部依赖**。
- **存储读写**统一走 `storage.load_json` / `save_json`；门店配置走 `modules/stores/config.py`。
- **鉴权与门店闸**统一在 `routing._route()`；**新增接口默认就带鉴权 + 门店闸**，不要单独加。
- **存量回归**：现有 **650** 个用例必须全绿（`python3 -m unittest discover -s tests`）。
- **口径不许变**：2026 年 6 月 **71226.1 度**。P3 只读不写，**不得修改 `report.py` 的计算逻辑**。
- **ruff ≤ 267 条、mypy ≤ 793 条**（当前基线；`/private/tmp/lintvenv/bin/{ruff,mypy}`，mypy 要带 `--exclude 'data/'`），**新文件必须 0 错**。
- **禁止手动编辑数据目录下的 JSON**；**`build-app.sh release --install` 不许跑**。
- **提交用约定式提交**，`git add` 只写明确路径。

---

## 本期的关键设计决策（实现时不要自行改口径）

| # | 决策 | 理由 |
|---|---|---|
| D1 | **逐店切换门店上下文**（`context.store_scope()`）再跑现有月报，而不是自己重算 | `report._report_cache_key()` 用的是**当前门店** —— 不切上下文就逐店计算，两家表集合相同的店会命中同一份缓存，直接把 A 店的数字当成 B 店的。切换必须在 `try/finally` 里，异常也要恢复，否则本请求后续的读会串店 |
| D2 | **权限 = 任意登录用户，但只聚合调用方有权限的门店** | 这些数据本来就在他的可见范围内（员工看自己店、总部看全部）。**不**加主管闸：分店员工看自己一家店的月度汇总没有任何越权 |
| D3 | **各店用自己的 `tables` / `price`**；汇总只加总 `total_kwh` / `total_cost` | 不同店的表 key 可能完全不同（`m1`/`m2` vs `hall`…），把 `by_meter` 横向合并会产生一个四不像的键集合。细则见下 |
| D4 | **单店失败不影响整体**：该店返回 `{id, name, error}`，其余照常 | 一家店的数据文件损坏就让整个总览 500，等于「一家店坏了，总部什么都看不到」 |
| D5 | **水电用量按店取**（复用 `calc_month_utilities`） | 总表/分表/水表是另一套口径（`readings_water.json`），但总部要看的正是「哪家店用电多、用水多」 |
| D6 | **前端入口可见条件与门店切换器一致**：`all_stores === true` 或可见门店 ≥ 2 | 单店用户看「总览」只有一行，没有信息量 |

### 锁死链路（Task 1 的核心约束）

```
逐店算月报 → 忘了切换门店上下文
  → _report_cache_key() 用调用方当前门店(比如 main)
  → 两家店表集合相同时(比如都还没配过,都是默认 4 表 + 同倍率)
  → 缓存键完全相同 → 第二家店直接拿到第一家店的结果
  → 总览上两家店数字一模一样,而且**不报错**
```

这条与 P2 那个「同店同月不同表集合」的缓存坑是同一类，必须靠「进店 → 算 → 恢复」的
上下文管理来保证，而不是靠缓存键凑巧不同。

---

## 文件地图

| 文件 | 归属 Task | 职责 |
|---|---|---|
| `MeterStats/modules/stores/context.py` | 1 | 新增 `store_scope(store_id)` 上下文管理器（保存/恢复**原始** thread-local 值） |
| `MeterStats/modules/stores/handler.py` | 1 | 新增 `handle_get_stores_overview` |
| `MeterStats/routing.py` | 1 | 注册 `GET /api/stores/overview` |
| `tests/test_store_overview.py` | 1 | **新建**：聚合口径、权限范围、单店失败、缓存不串 |
| `MeterStats/index.html` | 2 | 侧栏「门店总览」入口 + `section-settings-overview` + 引入 `overview.js` |
| `MeterStats/js/modules/overview.js` | 2 | **新建**：月份选择、表格渲染、合计行、柱状图 |
| `MeterStats/js/core/api.js` | 2 | 加 `Api.stores.overview(month)` |
| `MeterStats/admin.js` 或 `navigation.js` | 2 | 打开页面时按需加载；入口可见性按 D6 |
| `tests/test_overview_frontend.py` | 2 | **新建**：静态接线 + node 行为（2 店 2 行、合计、错误行） |

**并行约束**：Task 1 必须先（Task 2 依赖接口形状）；Task 2 内部分两步（接线 → 渲染）可作两个提交。

---

### Task 1: 后端 —— `GET /api/stores/overview`

**Files:**
- Modify: `MeterStats/modules/stores/context.py`
- Modify: `MeterStats/modules/stores/handler.py`
- Modify: `MeterStats/routing.py`
- Create: `tests/test_store_overview.py`

- [ ] **Step 1: 先加 `store_scope` 上下文管理器**

```python
@contextlib.contextmanager
def store_scope(store_id: str):
    """临时切到某门店，退出时**恢复原始值**（含"从未设置过"这个状态）。

    为什么不用 set/get 手写:
      get_current_store() 在未设置时返回 DEFAULT_STORE_ID("main") ——
      拿它当"原值"恢复,会把「原本未设置」悄悄改成「已设为 main」,
      掩盖真正的初始化缺失。

    为什么必须 finally:
      遍历多店时任何一家抛异常,上下文没恢复 → 本请求后续的读全部落到那家店上,
      表现为「总览算完之后,页面上的抄表数据变成了别家店的」。
    """
```
实现要点：保存 `getattr(_ctx, "store_id", None)`，`finally` 里**有值才 set、没值就 del**。

- [ ] **Step 2: 先写失败测试**

`tests/test_store_overview.py`（沿用 `tests/test_store_api.py` 的 `StoreApiTestBase`），覆盖：

1. **两家店各自的口径**：`main` 4 表（电价 0.9）、`s002` 2 表（电价 1.5），各录一组抄表 →
   总览里两行的 `total_kwh` / `total_cost` / `by_meter` 各按自己的表集合与电价算。
2. **缓存不串（锁死链路）**：两家店**表集合完全相同**（都为默认 4 表、同倍率），
   但抄表数据不同 → 两次的数字必须不同。这条专门抓「忘记切上下文」。
3. **合计**：`total.total_kwh` = 各行之和；`total.total_cost` = 各行之和。
4. **权限**：s002 员工只看到 `s002` 一行；admin(`all_stores`)看到两行。
5. **单店失败不影响整体**：把 s002 的 `readings.json` 写成坏 JSON →
   s002 那行带 `error`，`main` 那行照常，接口仍 200。
6. **月份校验**：`month=2026-13` / `2026-1` → 400。
7. **上下文恢复**：调用结束后 `context.get_current_store()` 应回到调用前的值。

- [ ] **Step 3: 实现 handler**

```python
def handle_get_stores_overview(handler: Any) -> None:
    """GET /api/stores/overview?month=YYYY-MM → 各店月度汇总 + 合计。

    逐店用**自己的**表集合与电价跑一遍月报(P2 已参数化),再横向合并。
    整个过程在 store_scope 里切换门店上下文 —— 报表缓存键带门店维度,
    不切就会把上一家店的数字当成这一家的。
    """
```
实现要点：
- 月份正则 `^\d{4}-(0[1-9]|1[0-2])$`（注意**不是** `\d{2}`：`2026-13` 必须拒）。
- 可见门店：`registry.list_stores()` 与调用方 `_user_store_scope()` 取交集（复用 routing 里已有的口径，不要另写一套）。
- 每店：`with context.store_scope(sid):` → `get_report_tables()` / `get_store_prices()` →
  读该店 readings/charges → `calculate_monthly_report(...)` → `calc_month_utilities`。
- 单店异常 → `except Exception as e:` 记录 `{"id", "name", "error": str(e)}`，`log()` 一条，继续下一家。
- 响应形状**严格按规格 §3.5**，额外字段只加 `error`。

- [ ] **Step 4: 注册路由**

放在 `/api/stores/current` 与 `/api/stores` **之前**（前缀匹配：`/api/stores/overview` 会命中 `/api/stores`）。

- [ ] **Step 5: 运行测试**

```bash
python3 -m unittest tests.test_store_overview -v
python3 -m unittest discover -s tests 2>&1 | tail -3
```

- [ ] **Step 6: 提交**

```bash
git add MeterStats/modules/stores/context.py MeterStats/modules/stores/handler.py \
        MeterStats/routing.py tests/test_store_overview.py
git commit -m "feat(api): 门店总览接口,逐店按自己的表集合与电价汇总"
```

---

### Task 2: 前端 —— 门店总览页

**Files:**
- Modify: `MeterStats/index.html`
- Modify: `MeterStats/js/core/api.js`
- Create: `MeterStats/js/modules/overview.js`
- Create: `tests/test_overview_frontend.py`

- [ ] **Step 1: 先写失败测试**

静态：侧栏有入口、有 `section-settings-overview`、引入了 `overview.js`、`api.js` 有 `overview` 封装。
node 行为：喂 2 店 + 1 错误店的响应 → 表格 3 行（错误店那行显示原因）、合计行等于两店之和、
列名是「门店 / 用电 / 电费 / 抄表天数 / 水电」而**不是**某一家店的表名。

> ⚠️ 总览表**不能**按 `METER_KEYS` 出列 —— 每家店的表不一样，横向比较的是
> 「总用电 / 电费」这类**跨店同构**指标。`by_meter` 只在单店展开时看（P2 的月报页）。

- [ ] **Step 2: 接线 + 渲染**

- 侧栏入口：`<button class="sidebar-item" data-section="settings-overview" ...>🏬 门店总览</button>`
- 可见性：`all_stores === true` 或 `StoreContext.getStores().length >= 2`（与切换器同条件，D6）
- `overview.js`：`loadStoresOverview()` 取当月 → 表格 + 合计行 + 柱状图（复用 Chart.js）
- 切门店/切月份都要重新拉（切门店对总览其实无影响，但**切换月份必须重拉**）
- XSS：门店名是自由文本，进 `innerHTML` 必须 `escapeHtml`

- [ ] **Step 3: 人工核对**

起临时实例（**直接 `python3 server.py`**，`run.sh` 的 `DATA_DIR` 是写死的），
两店各录数据，打开总览页确认：行数、合计、错误行提示、月份切换。

- [ ] **Step 4: 提交**

```bash
git add MeterStats/index.html MeterStats/js/core/api.js MeterStats/js/modules/overview.js \
        tests/test_overview_frontend.py
git commit -m "feat(ui): 门店总览页,横向对比各店用电与费用"
```

---

## 收尾验收（控制器执行，不派 worker）

- [ ] **Step A: 全量测试** —— `python3 -m unittest discover -s tests`，Expected `OK`，用例数 ≥ 650 + 新增
- [ ] **Step B: 静态检查** —— ruff ≤ 267；mypy ≤ 793，新文件 0 错
- [ ] **Step C: 口径回归** —— `tests.test_monthly_report` 的 **71226.1** 通过（P3 只读不写，这条用来证明没被带歪）
- [ ] **Step D: 端到端** —— 临时实例：两店各录数据 → 总览两行数字各自对得上单店月报；
  合计 = 两行之和；s002 员工只看到一行；坏数据店不拖垮整体
- [ ] **Step E: 更新 CHANGELOG** 0.5.0 补 P3 小节
- [ ] **Step F: 提交**

---

## 不在本期范围

- **跨店合计的「表维度」对比**（同一块表在各店之间的对比）：各店表 key 不通用，需要先有「表身份」概念
- **时间序列对比**（各店近 12 个月趋势）→ 后续
- **导出总览为 Excel/CSV** → 后续
- 迁店工具、多租户计费、移动端、报表 PDF 导出（规格 §6 已排除）
- `dataimport` 之外的历史遗留见 CHANGELOG「已知问题」（值班照片无自动备份、
  `rglob` 深度与恢复白名单不一致、multipart ZIP 不校验、文件系统大小写不敏感、
  `dir-listing` 参数不一致）
