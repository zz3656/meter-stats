# 分店功能 P2 实施计划 —— 表计自定义（每店自己的表数量与倍率）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让**每家门店拥有自己的表集合**（数量 / 名称 / 图标 / 倍率 / 颜色），并且抄表、充值、报表、图表全部按当前店的表集合工作 —— 同时保证总店（沿用 4 表）的数字与今天完全一致。

**Architecture:** P0 已经把每店的 `meters` / `config` 落在 `stores/<id>/store.json`（`modules/stores/config.py` 的 `DEFAULT_METERS` / `get_store_meters()` / `get_store_prices()` 均已就绪，注释里明写「P0 阶段每店先复制一份默认表定义，P2 再开放自定义编辑」）。P2 不动数据隔离与门店闸，只做三件事：
1. **后端把「表定义」从全局常量改成参数**——`report.py` 不再读模块级 `TABLES`，改由调用方按当前店传入；新增统一读取器 `row_values()`。
2. **配置接口从全局 `settings.json` 改到每店 `store.json`**——`/api/meters` 与 `PUT /api/admin/meter` 目前读写的都是**全局** settings，多店下这是错的（一家店改表名，全部门店跟着变）。
3. **前端把 4 表硬编码改成按当前店的表集合渲染**——`METER_KEYS` / `CHARGE_METERS` 由 `loadMeterConfig()` 重建，表单与报表遍历该集合。

**Tech Stack:** Python 3.9+（零外部依赖，仅标准库）、纯 HTML/CSS/JS（无构建步骤）、`unittest`（存量 **549** 用例）+ node 行为验证（沿用 `tests/test_stores_frontend.py` 的 vm 沙箱范式）。

---

## Global Constraints

这些约束适用于**每一个** Task，不需要在 Task 里重复：

- **Python 3.9+**：新模块首行 `from __future__ import annotations`；**零外部依赖**（仅标准库）。
- **存储读写**统一走 `storage.load_json` / `storage.save_json`；写操作用 `storage.get_lock(model)`。
- **HTTP 响应**统一 `utils.send_json(handler, status, payload)`；读体 `utils.read_body(handler)`。
- **鉴权与门店闸**统一在 `routing._route()` 拦截；**新增接口默认就带鉴权 + 门店隔离**，不需要单独加。
- **门店配置读写一律走 `modules/stores/config.py`**（`read_store_config` / `write_store_config` / `get_store_meters` / `get_store_prices`）。它们返回**深拷贝**，不要绕过它们直接 `load_json` —— 直接读会拿到存储层缓存对象本体，改嵌套结构就是在改缓存（那条坑 2026-11-26 已在 `storage.py` 侧加了 `finally` 失效兜底，但**不要**因此放松）。
- **前端 token 只从 `admin.js` 的 `currentAuthToken()` 取**；`meter_admin_token` / `meter_token` 是死键。
- **存量回归**：现有 **549** 个单元测试必须全部通过（`python3 -m unittest discover -s tests`）。
- **口径不许变**：2026 年 6 月核对值 **71226.1 度**是自动化断言（`tests/test_monthly_report.py:168/228/313`）。P2 动了 `report.py` 的表遍历 —— **每一轮都必须重跑这条**。默认 4 表下的所有数字必须与改造前逐位相同。
- **ruff ≤ 273 条、mypy ≤ 793 条**（基线，仓库本身不干净；`/private/tmp/lintvenv/bin/{ruff,mypy}`，PATH 里没有），**新文件必须 0 错**。mypy 正确口径是 `mypy . --exclude 'data/'`。
- **禁止手动编辑 `MeterStats/.data/` 或 `~/Library/Application Support/com.meter.stats/` 下的 JSON**。
- **提交用约定式提交**，**`git add` 只写明确路径，禁用 `-A` / `.`**。
- **`MeterStats/VERSION` 本期不动**（0.5.0 同一版本内补齐）。
- **`build-app.sh release --install` 本期不许跑** —— 它会 `rm -rf ~/Library/Application Support/com.meter.stats/`（真实生产数据），自带备份带 `2>/dev/null`、静默失败照删。真要跑必须先另做独立备份并事后逐文件比对。

---

## 本期的关键设计决策（实现时不要自行改口径）

| # | 决策 | 理由 |
|---|---|---|
| D1 | **旧 4 表（`hall`/`fire`/`private_room`/`ac`）继续用记录顶层字段，永不迁移、不改键名** | 历史数据 100% 兼容，零迁移。改键名会让所有历史报表对不上。 |
| D2 | **门店自定义的新表写进记录的 `meters` 字典**（`{"meters": {"m1": 12.3}}`） | 与顶层字段并存不打架；`row_values()` 先查 `meters[key]`、缺失 fallback 顶层 `row[key]`，于是「旧 4 表」和「新表」用同一套读法。 |
| D3 | **新表的 key 禁止与旧 4 表重名** | 若允许重名，`meters` 里一份、顶层一份，`row_values()` 的优先级就成了隐藏口径（导入/迁移时极易写出两处不一致的数据）。旧 4 表 key 固定占位，新增表只能用新 key。 |
| D4 | **删表不删数据** | 删掉一块表后，历史 JSON 里那些值仍在（只是不再显示/计算）。真要清理再单独做工具 —— 删表顺手删数据是不可逆的。 |
| D5 | **每店至少 1 块表；倍率必须是正整数** | 0 块表的门店会让报表、图表、表单全部落入「无表」分支，收益为零而分支成本很高。倍率 0 会让该表用电恒为 0，属于静默错数据。 |
| D6 | **电价 / 水价 / 总表倍率 / 分表倍率也按店**（`store.json` 的 `config`） | 规格 §3.3 已定。`get_store_prices()` 已就绪，P2 只把 `modules/reports/handler.py` 里的常量引用换掉。 |
| D7 | **`/api/meters` 按**当前店**返回**；前端**切店后必须重新 `loadMeterConfig()`** | 不重载 = 切到 B 店还显示 A 店的表名与倍率，抄进去的就是错数据。这是本期最容易漏的一条，与 P1 的「切店清缓存」是同一类问题。 |
| D8 | **报表缓存键沿用 P0 的 `f"{store_id}:{key}"`，本期不动** | 门店维度已经在里面了（`report.py::_report_cache_key`）。但 P2 改了表集合 —— **配置变更时必须主动失效报表缓存**，否则改完备率看到的还是旧数字。 |
| D9 | **自定义表不参与水电总表计算** | 总表 / 分表 / 水表是另一套（`readings_water.json`），有独立的倍率与口径，与用电表无关。 |
| D10 | **默认 4 表 = 现状**（`DEFAULT_METERS`），缺配置的门店自动拿默认 | 老店升级后行为零变化；`read_store_config()` 在文件缺失时已经回落 `DEFAULT_METERS`。 |
| D11 | **三个配置端点同批改完**：`GET /api/meters`、`GET /api/admin/meter`、`PUT /api/admin/meter`，响应统一「`meters` 数组 + 兼容的 `meter` 字典」 | 现在三个都读写**全局** settings，且字段名一个叫 `meter` 一个叫 `meters`。只改其中一两个 → 「写进本店、读的是全局」= 保存成功但刷新变回去；或者设置页与别的页面显示不同的表。过渡期两种形状都返回，前端可分批改。 |

### 锁死链路（Task 1 / Task 2 / Task 4 的核心约束）

```
门店 A 自定义成 2 块表（m1/m2），报表按 2 表算
  但 report.py 里 `r.get("hall") is not None` 还在用它判断「这行有没有电表读数」
  → A 店的抄表行没有 hall 字段 → 整月读数被当成「只录了水电的行」跳过
  → 月报 total_kwh = 0，而且不报错
```

同理，只要**任何一处**仍然引用全局 `TABLES` / `METER_KEYS` / `CHARGE_METERS`，
在该店就会表现为「少一块表」或「多一块不存在的表」，而且**不会抛异常**。
所以 Task 1 的验收方式不是「跑通」，而是**用 2 表的门店跑一遍，断言报表 / 表单 / 图表
都只出现这 2 块表**（Task 1、3、4、5 各自带这样一条断言）。

---

## 文件地图

| 文件 | 归属 Task | 职责 |
|---|---|---|
| `MeterStats/modules/stores/meters.py` | 1 | **新建**：`row_values()` 统一读取器 + 表 key 校验 + 表定义归一化 |
| `MeterStats/constants.py` | 1 | 加 `DEFAULT_TABLES`；`METER_MULTIPLIERS` 保留为兼容别名 |
| `MeterStats/report.py` | 1 | `TABLES` 全局 → `tables` 参数；`PRICE` → `price` 参数；修 `r.get("hall")` 硬编码 |
| `tests/test_meter_tables.py` | 1 | **新建**：参数化回归（默认 4 表 = 现状 + 2 表门店正确计算 + 跨表不串） |
| `MeterStats/modules/system/users_handler.py` | 2 | **三个**端点改按店：`GET /api/meters`(221)、`GET /api/admin/meter`(212)、`PUT /api/admin/meter`(230)；统一返回 `meters` 数组 + 兼容旧 `meter` 字典 |
| `MeterStats/modules/readings/handler.py` | 2 | 接 `meters` 字典；四表字段改为按当前店表集合校验 |
| `MeterStats/modules/charges/handler.py` | 2 | 同上；充值一致性校验传 `tables` |
| `MeterStats/modules/reports/handler.py` | 2 | 价格改读 `get_store_prices()`；报表调用传 `tables`/`price` |
| `MeterStats/modules/dataimport/handler.py` | 2 | 导入时按当前店表集合校验列 |
| `tests/test_meter_config_api.py` | 2 | **新建**：按店配置接口 + 增删表校验 + 越权 |
| `MeterStats/js/core/meterConfig.js` | 3 | `loadMeterConfig()` 重建 `METER_CONFIG`/`METER_KEYS`/`CHARGE_METERS`；加 `resetMeterConfig()` |
| `MeterStats/js/core/storeContext.js` | 3 | 切店清缓存时加一项 `resetMeterConfig()` |
| `tests/test_meter_config_frontend.py` | 3 | **新建**：node 沙箱验证「2 表门店 → METER_KEYS 只有 2 个」+ 切店重载 |
| `MeterStats/index.html` | 4 | 4 组静态表单项 → 容器 + 动态生成 |
| `MeterStats/js/modules/readings.js` | 4 | 抄表表格与表单按 `METER_KEYS` 渲染/收集 |
| `MeterStats/js/modules/charges.js` | 4 | 充值表单按 `CHARGE_METERS` 渲染/收集 |
| `tests/test_dynamic_forms.py` | 4 | **新建**：node 沙箱验证表单随表集合变化 |
| `MeterStats/js/modules/reports.js` | 5 | 报表表格/合计按表集合遍历 |
| `MeterStats/js/modules/render_charts.js` / `render_pie_charts.js` / `render_weekly.js` / `render_weekly_trend.js` / `alerts.js` | 5 | 图表与告警按表集合遍历 |
| `tests/test_dynamic_render.py` | 5 | **新建**：node 沙箱验证图表/告警不出现硬编码表 |
| `MeterStats/admin.js` | 6 | 电表设置页：增删表 / 排序 / 按店保存 |
| `MeterStats/index.html` | 6 | 电表设置页 DOM 调整（加「新增表」「删除」按钮） |
| `tests/test_meter_settings_ui.py` | 6 | **新建**：设置页接线回归 |

**并行约束**：
- **Task 1 必须最先**（它定义 `row_values` 与参数化签名，Task 2 要调用）。
- **Task 2 依赖 Task 1**；**Task 3 依赖 Task 2**（前端要读新的 `/api/meters` 响应形状）。
- **Task 4 依赖 Task 3**（表单渲染要 `METER_KEYS`）；**Task 5 依赖 Task 1**（报表字段）**和 Task 3**。
- **Task 6 依赖 Task 2**（写接口），与 Task 4/5 可并行（文件不重叠）。
- 每个 Task 的测试写进**自己的新文件**，不要追加到别的 Task 的文件里（并行写会撞 git 冲突）。

---

### Task 1: 后端 —— 表定义参数化 + 统一读取器

**Files:**
- Create: `MeterStats/modules/stores/meters.py`
- Modify: `MeterStats/constants.py`
- Modify: `MeterStats/report.py`
- Create: `tests/test_meter_tables.py`

- [ ] **Step 1: 先写失败测试**

新建 `tests/test_meter_tables.py`，覆盖四件事：

1. **默认 4 表口径不变**：用现有 `tests/test_monthly_report.py` 的 2026-06 夹具跑 `calculate_monthly_report(readings, charges, "2026-06")`（不传 `tables`），断言 `total_kwh == 71226.1`。
2. **显式传默认表也一致**：传 `tables=DEFAULT_TABLES`，结果与第 1 条逐键相等。
3. **2 表门店能算**：造一组只有 `m1`/`m2` 的抄表（值写进 `meters` 字典），传 `tables=[m1, m2]`，断言 `by_meter` 只有这两个键、`total_kwh` 等于手算值。
4. **`row_values` 读取器**：`{"hall": 5, "meters": {"m1": 7}}` → `row_values(row, "hall") == 5`、`row_values(row, "m1") == 7`、`row_values(row, "nope") is None`；再验证**同 key 同时存在时 `meters` 优先**（这条是 D2 的口径，必须锁死）。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/ceasar/Documents/GitHub/meter-stats
python3 -m unittest tests.test_meter_tables -v
```
Expected: FAIL（`modules.stores.meters` 不存在 / 签名不收 `tables`）。

- [ ] **Step 3: 新建 `modules/stores/meters.py`**

```python
"""表定义与表值读取 —— 每店表集合的唯一入口。

记录格式(向后兼容,见 P2 计划 D1/D2):
    {"date": "...", "hall": 65.3, "ac": 52.1,
     "meters": {"m1": 12.3}, "note": ""}

旧 4 表在顶层,自定义表在 meters 字典。row_values() 把两种读法收成一个。
"""
from __future__ import annotations

import re
from typing import Any

# 旧 4 表 —— 固定在顶层,新表禁止复用这些 key(P2 计划 D3)
LEGACY_KEYS: tuple[str, ...] = ("hall", "fire", "private_room", "ac")

# 新表 key 规则:小写字母开头,只含小写字母/数字/下划线,2~32 位
_KEY_RE = re.compile(r"\A[a-z][a-z0-9_]{1,31}\Z")


def row_values(row: dict[str, Any], key: str) -> Any:
    """读一行的某个表值:先查 meters 字典,缺失再 fallback 顶层字段。"""
    meters = row.get("meters")
    if isinstance(meters, dict) and key in meters:
        return meters[key]
    return row.get(key)


def is_valid_meter_key(key: Any) -> bool:
    return isinstance(key, str) and bool(_KEY_RE.match(key))


def normalize_tables(meters: Any) -> list[dict[str, Any]]:
    """把 store.json 里的 meters 归一化成 [(key,label,mult,color)] —— 非法项丢弃。

    只做「能不能用」的筛选,不做补默认:P2 计划 D5 要求至少 1 块表,
    数量不足由调用方(写接口)拒绝,读路径拿到空列表时由 config.py 回落 DEFAULT_METERS。
    """
    ...


def row_has_any_value(row: dict[str, Any], tables: list[dict[str, Any]]) -> bool:
    """这行有没有任一表的读数 —— 用来替代 report.py 里硬编码的 `r.get("hall")`。"""
    ...
```

- [ ] **Step 4: `constants.py` 加 `DEFAULT_TABLES`**

保持 `METER_MULTIPLIERS` 不动（还有兼容引用），新增：

```python
# 默认 4 表定义(与 modules/stores/config.py::DEFAULT_METERS 同源)
# report.py 的参数化默认值从这里取 —— 不要在 report.py 里再写一份
DEFAULT_TABLES: list[dict] = [
    {"key": "hall", "label": "1#大厅", "mult": METER_MULTIPLIERS["hall"]},
    {"key": "fire", "label": "2#消防", "mult": METER_MULTIPLIERS["fire"]},
    {"key": "private_room", "label": "3#包厢", "mult": METER_MULTIPLIERS["private_room"]},
    {"key": "ac", "label": "4#空调", "mult": METER_MULTIPLIERS["ac"]},
]
```

> ⚠️ 注意两套表定义的名字不同：`report.py` 用的是 `{"key","label","mult"}`，
> `store.json` 用的是 `{"key","label","multiplier","icon","color"}`。
> **不要**强行统一 —— `report.py` 有 9 处 `t["mult"]`，改名会扩大改动面且毫无收益。
> 转换在调用方做一次（`modules/reports/handler.py`，Task 2），并写测试锁住映射。

- [ ] **Step 5: `report.py` 参数化**

改动点（行号以当前文件为准）：

| 位置 | 现状 | 改成 |
|---|---|---|
| `report.py:20` | `TABLES = [...]` | 改为 `from constants import DEFAULT_TABLES`，删除本地定义；保留 `TABLES = DEFAULT_TABLES` 作为**过渡别名**（若有别处引用，Task 1 结束后再删） |
| `report.py:188` `find_pasted_reading_charges` | `for t in TABLES` | 加参数 `tables: list | None = None`，函数内 `tables = tables or DEFAULT_TABLES` |
| `report.py:245` `find_charge_conflicts` | 同上 | 同上 |
| `report.py:322` `_charge_attribution` | `caps = {... for t in TABLES}` | 加 `tables` 参数，一路传进 `_add` |
| `report.py:377` `calculate_monthly_report` | `(readings, charges, month)` | 加**关键字**参数 `tables=None, price=None` |
| `report.py:518` `calculate_yearly_report` | `(readings, charges, year)` | 同上（它内部会调 `calculate_monthly_report`，必须把 `tables`/`price` 透传） |
| `report.py:393-394` | `r.get("hall") is not None` | `row_has_any_value(r, tables)` |
| `report.py:499/509` | `PRICE` | `price if price is not None else PRICE` |
| `report.py:452` | `avg = {...}` 用 `span` | `span` 为 0 时除零 —— 顺带确认逻辑未被参数化改坏 |

⚠️ **签名兼容**：所有新增参数一律**关键字**且带默认值，现有 27 处 `calculate_monthly_report(a, b, "2026-11")` 调用必须零改动通过（`tests/test_charge_consistency.py` 7 处、`test_monthly_report.py` 12 处、`test_stores.py` 8 处）。

- [ ] **Step 6: 运行测试确认全绿**

```bash
python3 -m unittest tests.test_meter_tables -v
python3 -m unittest tests.test_monthly_report tests.test_charge_consistency tests.test_stores -v
```
Expected: 全绿，且 `71226.1` 断言通过。

- [ ] **Step 7: 跑存量回归**

```bash
python3 -m unittest discover -s tests 2>&1 | tail -3
```
Expected: `Ran 549+N tests ... OK`。

- [ ] **Step 8: 提交**

```bash
git add MeterStats/modules/stores/meters.py MeterStats/constants.py MeterStats/report.py \
        tests/test_meter_tables.py
git commit -m "refactor(report): 表定义改为参数,tables/price 由调用方按店传入"
```

---

### Task 2: 后端 —— 配置与数据接口按店

**Files:**
- Modify: `MeterStats/modules/system/users_handler.py`
- Modify: `MeterStats/modules/readings/handler.py`
- Modify: `MeterStats/modules/charges/handler.py`
- Modify: `MeterStats/modules/reports/handler.py`
- Modify: `MeterStats/modules/dataimport/handler.py`
- Create: `tests/test_meter_config_api.py`

- [ ] **Step 1: 先写失败测试**

新建 `tests/test_meter_config_api.py`（沿用 `tests/test_stores.py:39` 的 `StoreTestBase` 范式 —— 它已经处理了 `routing.ENFORCE_AUTH` 的开关与临时数据目录）。

⚠️ **不要重复已存在的覆盖**：`tests/test_stores.py` 里已有
`TestStoreConfig`(783) 与 `TestStoreConfigIsolation`(884)，前者测 `store.json` 存储层
（读写、默认值回落），后者测「配置与 storage LRU 缓存的隔离」（P2 的地基）。
新文件**只测 HTTP 层**：路由、当前店、校验、越权。

覆盖：

1. `GET /api/meters` 返回**当前店**的 meters 与 config（给 s002 写一套自定义 meters，断言 `main` 与 `s002` 读到的不同）。
2. `GET /api/admin/meter`（电表设置页用的那个）也必须返回**同一份**当前店配置 ——
   它与 `GET /api/meters` 读的是同一个源，**两条都要断言**（只改一条就会出现
   「设置页显示总店、别的页面显示本店」）。
3. `PUT /api/admin/meter` 只改**当前店**，另一店不受影响。
4. **增删表**：`PUT` 传 3 块表 → `GET` 回来 3 块；`PUT` 传 1 块表 → 回来 1 块。
5. **拒绝**：0 块表 → 400；倍率 0 / 负数 / 非数字 → 400；key 与旧 4 表重名 → 400；key 非法字符 → 400。
6. **越权**：员工 `PUT /api/admin/meter` → 403（`/api/admin/meter` 在主管及以上闸里，`routing.py:111`）。
7. **缓存失效**：改完倍率后立刻请求月报，必须拿到新倍率算出的数字（D8）。
8. `POST /api/readings`（`?store=s002`）能写入 `meters: {"m1": 5}`，且 `GET` 能读回。
9. 充值一致性校验用当前店的表：2 表门店下，`find_charge_conflicts` 不因「没有 hall」误判。

- [ ] **Step 2: 运行测试确认失败**

Expected: FAIL。

- [ ] **Step 3: 三个表计配置端点全部改按店**

**先看清现状 —— 这里是三个端点，不是两个，而且字段名不一致：**

| 端点 | 处理函数 | 现在读/写 | 前端调用方 |
|---|---|---|---|
| `GET /api/meters` | `users_handler.py:221` `handle_get_meters_public` | 全局 `settings["meter"]`，返回 `{meters: dict, config}` | `meterConfig.js::loadMeterConfig()` |
| `GET /api/admin/meter` | `users_handler.py:212` `handle_get_meter_settings` | 全局 `settings["meter"]`，返回 `{meter: dict, config}` | `admin.js::loadMeterSettings()`（电表设置页） |
| `PUT /api/admin/meter` | `users_handler.py:230` `handle_put_meter_settings` | 写全局 `settings["meter"]` | `admin.js::saveMeterSettings()` |

⚠️ **只改 `PUT` 不改两个 `GET`，就会得到「写进本店、读的是全局」** —— 表现为
「改完倍率保存成功，刷新后又变回原值」，而且另一家店反而被改了。
三个必须同批改完，同批上线。

⚠️ **字段名 `meter` vs `meters` 的不一致要一并收口**：统一成 **`meters`**（数组）。
为了不把老前端打断，两个 `GET` 在过渡期**同时**返回两种形状：

```python
def _meters_payload() -> dict:
    from modules.stores.config import get_store_meters, get_store_prices
    meters = get_store_meters()                    # [{key,label,icon,multiplier,color}]
    return {
        "meters": meters,                          # 新:数组
        "meter": {m["key"]: m for m in meters},    # 旧:字典(兼容过渡)
        "config": get_store_prices(),
    }
```

`handle_get_meters_public` 与 `handle_get_meter_settings` 都改成
`send_json(handler, 200, _meters_payload())`。

`handle_put_meter_settings` 改为写 `store.json`，并补校验：

```python
def handle_put_meter_settings(handler: Any) -> None:
    body = read_body(handler)
    ...
    meters = body.get("meters", body.get("meter"))   # 兼容旧字段名(旧的是字典,要转数组)
    if isinstance(meters, dict):
        meters = [{"key": k, **v} for k, v in meters.items()]
    if meters is not None:
        err = validate_meters_payload(meters)         # 至少 1 块 / 倍率为正整数 / key 合法且不与旧 4 表重名
        if err:
            send_json(handler, 400, {"error": err})
            return
    cfg = read_store_config(current_store)
    if meters is not None: cfg["meters"] = normalize_tables(meters)
    if "config" in body:   cfg["config"] = body["config"]
    write_store_config(current_store, cfg)
    invalidate_report_cache()      # D8:改表/倍率/电价必须失效月报缓存
    send_json(handler, 200, {"ok": True, **_meters_payload()})
```

- [ ] **Step 4: 抄表 / 充值接口接受 `meters` 字典**

`readings/handler.py:36-46` 现在是四个具名变量 + 「四表至少填一个」。改为：

```python
tables = get_store_meters()
vals = {t["key"]: opt_float(body, t["key"]) for t in tables}
# 旧 4 表仍写顶层(零迁移);自定义表写 meters 字典
row = {"date": date, "note": note, ...}
for t in tables:
    if t["key"] in LEGACY_KEYS:
        row[t["key"]] = vals[t["key"]]
custom = {k: v for k, v in vals.items() if k not in LEGACY_KEYS and v is not None}
if custom:
    row["meters"] = custom
if all(v is None for v in vals.values()):
    send_json(handler, 400, {"error": "至少填一块表"})
```

⚠️ 「覆盖已有日期」的分支（`readings/handler.py:51-63`）必须同步：`new_row[k] is None` 时保留旧值的逻辑，对自定义表也要成立（否则改一格把其它自定义表清空）。

`charges/handler.py` 同理；并把它调用的
`find_charge_conflicts(readings, charges)` 改为 `find_charge_conflicts(readings, charges, tables=get_store_meters())`。

- [ ] **Step 5: 报表接口传 `tables` 与 `price`**

`modules/reports/handler.py`：

```python
from modules.stores.config import get_store_meters, get_store_prices

def _report_tables() -> list[dict]:
    """store.json 的 meters → report.py 要的 {key,label,mult}。"""
    return [{"key": m["key"], "label": m["label"], "mult": m["multiplier"]}
            for m in get_store_meters()]

prices = get_store_prices()
report = calculate_monthly_report(readings, charges, month,
                                  tables=_report_tables(),
                                  price=prices["electricity_price"])
```

同文件里 4 处 `ELECTRICITY_PRICE_CONST` / `WATER_PRICE`（约 156/158/179/180 与 277/279/300/301）改为从 `get_store_prices()` 取，常量只作缺失兜底。

- [ ] **Step 6: 导入接口按当前店表集合校验**

`modules/dataimport/handler.py` 的 5 处列名校验改为按 `get_store_meters()` 生成允许列；自定义表列来自记录的 `meters` 字典（导入格式若不含自定义表，先只校验旧 4 表并**明确报错**提示「导入暂不支持自定义表」，不要静默丢列）。

- [ ] **Step 7: 运行测试**

```bash
python3 -m unittest tests.test_meter_config_api -v
python3 -m unittest discover -s tests 2>&1 | tail -3
```

- [ ] **Step 8: 提交**

```bash
git add MeterStats/modules/system/users_handler.py MeterStats/modules/readings/handler.py \
        MeterStats/modules/charges/handler.py MeterStats/modules/reports/handler.py \
        MeterStats/modules/dataimport/handler.py tests/test_meter_config_api.py
git commit -m "feat(api): 表计配置与数据接口改为按店,P2 表集合贯通"
```

---

### Task 3: 前端 —— `meterConfig.js` 动态化

**Files:**
- Modify: `MeterStats/js/core/meterConfig.js`
- Modify: `MeterStats/js/core/storeContext.js`
- Create: `tests/test_meter_config_frontend.py`

- [ ] **Step 1: 先写失败测试**

node 沙箱（沿用 `tests/test_stores_frontend.py` 的 vm 范式）：
1. 喂一个「2 块表」的 `/api/meters` 响应 → `METER_KEYS` 必须恰好 2 个、顺序一致；
   `CHARGE_METERS` 长度 2 且 `meterNo` 是 `1#`/`2#`。
2. `METER_META(key)` 返回服务端给的 label / multiplier / color。
3. **兼容两种响应形状**：`meters` 是数组（新）与字典（旧）都要能解析。
4. `resetMeterConfig()` 之后 `METER_KEYS` 回到默认 4 表。
5. **切店重载**：`StoreContext.switchTo()` 后必须调用 `resetMeterConfig()` + 重新 `loadMeterConfig()`。

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 重写 `loadMeterConfig()`**

```javascript
async function loadMeterConfig() {
  try {
    const data = await Api.admin.metersPublic();
    // 兼容两种响应形状:数组(新) / 字典(旧)
    const list = Array.isArray(data && data.meters)
      ? data.meters
      : Object.entries((data && data.meters) || {}).map(([k, v]) => ({ key: k, ...v }));
    if (list.length) {
      const cfg = {};
      list.forEach(function (m) {
        if (m && m.key) cfg[m.key] = {
          label: m.label || m.key,
          icon: m.icon || '',
          multiplier: Number(m.multiplier) || 1,
          color: m.color || '#888',
        };
      });
      window.METER_CONFIG = cfg;
      window.METER_KEYS = list.map(m => m.key).filter(Boolean);
      window.CHARGE_METERS = window.METER_KEYS.map(function (k, i) {
        const m = cfg[k];
        return { key: k, label: m.label, icon: m.icon, meterNo: (i + 1) + '#' };
      });
    }
    // config 形状不变
    if (data && data.config && typeof data.config.electricity_price === 'number') {
      window.ELECTRICITY_PRICE = data.config.electricity_price;
    }
    if (data && data.config && typeof data.config.water_price === 'number') {
      window.WATER_PRICE = data.config.water_price;
    }
  } catch (e) { /* 静默失败,用默认值 */ }
}

window.resetMeterConfig = function resetMeterConfig() {
  window.METER_CONFIG = { /* 默认 4 表 */ };
  window.METER_KEYS = ['hall', 'fire', 'private_room', 'ac'];
  window.CHARGE_METERS = [ /* 默认 4 表 */ ];
};
```

⚠️ **`METER_CONFIG` 是对象,`METER_KEYS` 是数组** —— 现有代码里 `METER_CONFIG[key] = ...`
是原地改，改成整体替换后，**任何持有旧引用的地方都会读到旧值**。全仓搜
`METER_CONFIG` 的引用确认都与 `window.` 同步读（当前都是），不要缓存局部引用。

- [ ] **Step 4: 接上切店重载（D7）**

`storeContext.js` 的 `clearCaches()` 里追加：

```javascript
try { if (typeof resetMeterConfig === 'function') resetMeterConfig(); } catch (e) {}
```

并在 `switcher` 切店成功后由 UI 层重新 `loadMeterConfig()`（与 `loadAppData()` 同一处，
顺序必须是**先 `loadMeterConfig()` 再 `loadAppData()`** —— 否则表单按旧表集合渲染）。

- [ ] **Step 5: 运行测试**

```bash
python3 -m unittest tests.test_meter_config_frontend -v
```
（需 node；缺失会自动 skip，那样不算通过 —— 本机是 **node v26.11.1**，必须实跑。）

- [ ] **Step 6: 提交**

```bash
git add MeterStats/js/core/meterConfig.js MeterStats/js/core/storeContext.js \
        tests/test_meter_config_frontend.py
git commit -m "feat(ui): meterConfig 按当前店重建表集合,切店后重载"
```

---

### Task 4: 前端 —— 抄表 / 充值表单动态化

**Files:**
- Modify: `MeterStats/index.html`
- Modify: `MeterStats/js/modules/readings.js`
- Modify: `MeterStats/js/modules/charges.js`
- Create: `tests/test_dynamic_forms.py`

- [ ] **Step 1: 先写失败测试**

node 沙箱，喂「2 表」配置：
1. 生成抄表新增表单的 DOM 片段后，包含 2 个 `<input>`，`data-key` 是那 2 个 key。
2. 收集表单值时，只提交这 2 个 key（不夹带空的自定义表）。
3. 3 表门店 → 3 个 input（数量随配置变，不是固定 4）。
4. **倍率提示跟着表走**：倍率 80 的表渲染出的提示是 `× 80`，**不许出现 `× 160`**
   （全文 25 处硬编码提示，这条断言是唯一能抓住漏改的手段）。
5. **6 组都要覆盖**：录入 / 新增 / 编辑 × 抄表 / 充值 —— 逐组断言，
   漏改一组就是「新增对了、编辑还是老的」。测试里用循环跑 6 组，别只测 1 组。

- [ ] **Step 2: `index.html` 静态项换成容器**

现状是 **6 组 × 4 表 = 24 个静态 `<input>`**，每组只出现一处 `private_room` 但整组 4 块表都写死：

| 组 | id 前缀 | 位置（当前行号） |
|---|---|---|
| 抄表录入（主页） | `hall` / `fire` / `private_room` / `ac` | 约 168–182 |
| 充值录入（主页） | `charge-*` | 约 222–235 |
| 抄表新增（弹窗） | `reading-add-*` | 约 1339 |
| 充值新增（弹窗） | `charge-add-*` | 约 1411 |
| 抄表编辑（弹窗） | `reading-edit-*` | 约 1461 |
| 充值编辑（弹窗） | `charge-edit-*` | 约 1542 |

⚠️ **同一个坑的第二层：`<label>` 里的表名和倍率提示也是写死的** ——
形如 `<label>3#包厢 <span class="hint">读数 × 160</span></label>`，
全文 **25 处** 硬编码的 `× 160` / `读数 ×` 提示。改成动态表后这些提示必须由
`label` + `multiplier` 生成，否则「自定义了一块 80 倍率的表」页面上仍写着 `× 160`
—— 用户按提示手算，就会算错。**这是本期最容易漏的一处。**

改法：每组一个空容器 + `data-role`：

```html
<div class="meter-inputs" data-role="reading-add-meters"></div>
```

保留 `date` / `note` 等**非表**字段的静态结构。

- [ ] **Step 3: `readings.js` / `charges.js` 改为按集合渲染**

- 渲染：遍历 `METER_KEYS`（抄表）/ `CHARGE_METERS`（充值）生成 input，
  `id` 用 `reading-add-<key>`、`charge-add-<key>` 等**与现状一致**的命名，减少下游改动。
- 收集：`METER_KEYS.forEach(k => v[k] = num('reading-add-' + k))`；
  旧 4 表仍按顶层字段提交，自定义表放 `meters` 字典（与 Task 2 后端一致）。
- 渲染表格表头/单元格：按 `METER_KEYS` 生成 `<th>` 与 `<td>`，不再固定 4 列。

- [ ] **Step 4: 运行测试**

```bash
python3 -m unittest tests.test_dynamic_forms -v
```

- [ ] **Step 5: 提交**

```bash
git add MeterStats/index.html MeterStats/js/modules/readings.js MeterStats/js/modules/charges.js \
        tests/test_dynamic_forms.py
git commit -m "feat(ui): 抄表与充值表单按当前店表集合动态渲染"
```

---

### Task 5: 前端 —— 报表 / 图表 / 告警动态化

**Files:**
- Modify: `MeterStats/js/modules/reports.js`（14 处）
- Modify: `MeterStats/js/modules/render_charts.js`（5 处）
- Modify: `MeterStats/js/modules/render_pie_charts.js`（6 处）
- Modify: `MeterStats/js/modules/render_weekly.js` / `render_weekly_trend.js`（各 2 处）
- Modify: `MeterStats/js/modules/alerts.js`（5 处）
- Create: `tests/test_dynamic_render.py`

- [ ] **Step 1: 先写失败测试**

node 沙箱，喂「2 表」报表数据：
1. `reports.js` 渲染出的表格**不含** `private_room` / `ac` 这类该店没有的表。
2. 图表数据集的长度 = 表数量。
3. `alerts.js` 的告警项数 = 表数量（每表一条），不出现「第 3 块表」。
4. **反向**：默认 4 表时输出与改造前一致（把改造前的输出快照进测试）。

- [ ] **Step 2: 逐个文件改**

统一改法：`['hall','fire','private_room','ac']` → `window.METER_KEYS`，
`METER_META(k).label/color` 取元数据，`by_meter[k]` 遍历。

⚠️ **小心 `reports.js` 里的「合计行」与「日均」**：表数变化后列数跟着变，
`colspan`、表头与数据行的列数必须一致（这类错不抛异常，只是错位）。

- [ ] **Step 3: 运行测试 + 人工核对一次**

```bash
python3 -m unittest tests.test_dynamic_render -v
```
再起本地实例（**直接用 `python3 server.py`，不要用 `run.sh`** —— 它的 `DATA_DIR` 是写死的），
用默认 4 表配置打开报表页，肉眼确认数字与改造前一致。

- [ ] **Step 4: 提交**

```bash
git add MeterStats/js/modules/reports.js MeterStats/js/modules/render_charts.js \
        MeterStats/js/modules/render_pie_charts.js MeterStats/js/modules/render_weekly.js \
        MeterStats/js/modules/render_weekly_trend.js MeterStats/js/modules/alerts.js \
        tests/test_dynamic_render.py
git commit -m "feat(ui): 报表与图表按当前店表集合渲染"
```

---

### Task 6: 前端 —— 电表设置页（增删表 / 按店保存）

**Files:**
- Modify: `MeterStats/admin.js`（约 437-500 行 `loadMeterSettings` / `saveMeterSettings`）
- Modify: `MeterStats/index.html`（`section-settings-meter`，约 852-880 行）
- Create: `tests/test_meter_settings_ui.py`

- [ ] **Step 1: 先写失败测试**

1. `loadMeterSettings()` 渲染出当前店表数对应的单元格（2 表 → 2 个 `.meter-cell`）。
2. 点「新增表」后多一格，key 自动生成且不与已有重复、不与旧 4 表重名。
3. 保存时 payload 里的 `meters` 是数组且含 `multiplier`。
4. 页面上标明当前正在编辑**哪家店**（避免总部账号改错店）。

- [ ] **Step 2: 改造设置页**

- `meterKeys` 硬编码（`admin.js:460`）→ 读 `loadMeterConfig()` 的结果
- 每格加「删除」按钮（至少保留 1 块，删到 1 块时按钮禁用）
- 加「新增表」：**key 自动生成**（`m1`/`m2`… 避开已用），label 可编辑
- 保存走 `PUT /api/admin/meter`（Task 2 已按店）
- 顶部显示「当前门店：<店名>」
- ⚠️ **XSS**：label 是自由文本，进 `innerHTML` 必须 `escapeHtml`；进 `value="..."` 必须 `escapeAttr`（全局只有 `utils.js` 一份强版，2026-11-26 已收口）

- [ ] **Step 3: 运行测试 + 端到端**

```bash
python3 -m unittest tests.test_meter_settings_ui -v
```
端到端（临时实例 + 临时数据目录，**直接起 `server.py`**）：
1. 给 s002 配 2 块表 → `GET /api/meters?store=s002` 返回 2 块
2. `main` 仍是 4 块，互不影响
3. 在 s002 录一条抄表（2 块表都有值）→ 报表只出这 2 块
4. 清理：`kill -9`（SIGTERM 会死锁，见 AGENTS/CHANGELOG），`rm -rf` 临时目录

- [ ] **Step 4: 提交**

```bash
git add MeterStats/admin.js MeterStats/index.html tests/test_meter_settings_ui.py
git commit -m "feat(ui): 电表设置页支持增删表并按当前店保存"
```

---

## 收尾验收（控制器执行，不派 worker）

- [ ] **Step A: 全量测试**

```bash
python3 -m unittest discover -s tests 2>&1 | tail -5
```
Expected: `OK`，用例数 ≥ 549 + 各 Task 新增。

- [ ] **Step B: 静态检查**

```bash
/private/tmp/lintvenv/bin/ruff check . 2>&1 | tail -3
/private/tmp/lintvenv/bin/mypy . --exclude 'data/' 2>&1 | tail -3
```
Expected: ruff ≤ 273；mypy ≤ 793，**新增文件零错误**。

- [ ] **Step C: 口径回归（本期最关键的一步）**

```bash
python3 -m unittest tests.test_monthly_report tests.test_charge_consistency -v 2>&1 | tail -5
```
Expected: `71226.1 度` 断言通过。**P2 动了 `report.py` 的表遍历，这条是唯一能证明「默认 4 表数字没变」的硬断言。**

- [ ] **Step D: 真实会话端到端（2 表门店 vs 4 表门店）**

直接起服务（`run.sh` 的 `DATA_DIR` 写死，不能用）：

```bash
cd MeterStats && METER_PORT=8767 METER_DATA_DIR=/tmp/meter-p2-test \
  METER_BIND=127.0.0.1 METER_INITIAL_PASS=admin123 python3 server.py
```

验证：
1. `main` 保持 4 表；新建 s002 配成 2 表（`m1`/`m2`）
2. `GET /api/meters?store=s002` → 2 块；`?store=main` → 4 块
3. 给 s002 录 2 天抄表 → 月报只出 `m1`/`m2`，`total_kwh` 与手算一致
4. 员工越权：s002 员工 `?store=main` → 403
5. 拒绝路径：0 块表 / 倍率 0 / key 重名 → 400
6. 清理：`kill -9` + `rm -rf /tmp/meter-p2-test`

- [ ] **Step E: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 **0.5.0** 章节补 P2 小节（**不递增版本号**）。

- [ ] **Step F: 提交**

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-11-26-multi-store-p2.md
git commit -m "docs: 0.5.0 补 P2 表计自定义更新日志"
```

---

## 不在本期范围

- **自定义表的导入/导出**：`dataimport` 先只支持旧 4 表，遇到自定义表列明确报错
- **表定义变更后的数据迁移工具**（改 key / 删表后清理孤儿数据）→ 后续单列
- **水电表（总表 / 分表 / 水表）自定义**：它们走 `readings_water.json`，是另一套口径（D9）
- **表计排序拖拽**：本期用上下移动按钮，不做拖拽
- **总部总览页**（P3）
- `/api/admin/dir-listing` 的 `?dir=` vs `?path=` 参数不一致（既存问题，与分店无关）
- SIGTERM 死锁（既存问题，`_shutdown` 在主线程调 `server.shutdown()` 与 `serve_forever()` 互锁）
