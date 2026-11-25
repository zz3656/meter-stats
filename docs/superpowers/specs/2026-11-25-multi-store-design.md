# 分店功能设计规格（多门店 MeterStats）

- 日期：2026-11-25
- 状态：待评审
- 范围：在现有 MeterStats 上增加"分店"能力

---

## 1. 已确认的需求决策

| 决策点 | 结论 |
|---|---|
| 数据隔离 | 单实例，每店独立数据目录 |
| 总部视图 | 需要一张总表看全部分店 |
| 用户归属 | 分店员工绑定单店，总部账号可跨店 |
| 表计配置 | 每店可自定义表数量与倍率 |

---

## 2. 现状盘点（决定改造成本的依据）

### 2.1 后端

| 事实 | 出处 | 对分店的影响 |
|---|---|---|
| 所有数据走单一 `DATA_PATHS` 全局字典（7 个 JSON） | `app_handler.py:30` | **最佳切入口**：改成按门店解析即可 |
| `DATA_PATHS` 直接引用仅 4 处 | `modules/_storage.py:37`、`modules/_base.py:31,83`、`settings_handler.py:35` | 改造面比预想小得多 |
| 所有 CRUD 走 `JsonModelHandler` 基类 | `modules/_base.py:61` | 基类换路径 → 全部 handler 自动按店读写 |
| 路由唯一入口 + 统一鉴权闸 | `routing.py:240` `_route()` / `routing.py:106` `_auth_gate()` | 门店上下文与门店越权校验挂在同一层，**默认覆盖所有新接口** |
| `report.py` 是纯函数（收 list 不碰存储） | `report.py:377` `calculate_monthly_report(readings, charges, month)` | 各店独立计算天然成立，总部再做横向合并 |
| 表定义硬编码 4 表 | `report.py:20` `TABLES`、`constants.py:9` | **必须改造**：改为运行时传入 |
| 电价/水价在 `reports/handler.py` 直接用常量 | `modules/reports/handler.py:7,156,179` | 必须改为按店取值 |
| `settings.json` 混装 users + meter + config + 部署配置 | `modules/system/settings_handler.py` | 需拆成"全局 settings" + "门店 store.json" |
| 已有远端实例登录并拉数据的能力 | `modules/backup/admin_handler.py:437` `_nas_login_token()` | 多机场景可复用，但本次是单实例，不依赖它 |

### 2.2 前端

| 事实 | 出处 | 对分店的影响 |
|---|---|---|
| 全量拉取 + 客户端过滤 | `js/modules/readings.js:641` `renderAll()` 调 `/api/snapshot` | 门店切换 = 换参数重拉，渲染层基本不用重写 |
| 4 表硬编码约 70 处 | `index.html`(12)、`reports.js`(32)、`readings.js`(21)、`admin.js`(29)、`render_charts.js`(13)、`alerts.js`(10)、`meterConfig.js`(6) | **前端最大工作量**：抄表表单与报表渲染要改成动态表 |
| 元数据已有动态加载机制 | `js/core/meterConfig.js:28` `loadMeterConfig()` 从 `/api/meters` 读 | 动态表有现成挂载点，改造可复用 |
| `CHARGE_METERS` 硬编码表序号 | `js/core/meterConfig.js:50` | 需改为按门店表定义生成 |

### 2.3 部署与运维

- Docker：`meter-data:/data` 卷，改成子目录后无需改 compose。
- macOS `.app`：`~/Library/Application Support/com.meter.stats/`，同理。
- `build-app.sh` 会 `rm -rf` 该目录 —— **本次改造期间不要跑它**，跑之前必须另做独立备份。

---

## 3. 目标架构

### 3.1 数据布局

```
<data_dir>/
├── settings.json              # 全局：users[] / stores[] / 部署配置
├── stores/
│   ├── main/                  # 默认店（总店）
│   │   ├── readings.json
│   │   ├── readings_water.json
│   │   ├── charges.json
│   │   ├── items.json
│   │   ├── purchases.json
│   │   ├── duty.json
│   │   ├── store.json         # 本店表定义 + 价格配置
│   │   └── images/            # 本店值班图片
│   └── <store_id>/            # 各分店，结构同上
├── backup/
└── images/                    # 旧路径，仅迁移期读取兼容
```

`settings.json` 新增：

```json
{
  "users": [
    { "id": 1, "username": "admin", "role": "admin",
      "all_stores": true, "store_ids": [] }
  ],
  "stores": [
    { "id": "main", "name": "总店", "code": "HQ",
      "address": "", "active": true, "created_at": "2026-11-25T..." }
  ]
}
```

`stores/<id>/store.json`（每店独立）：

```json
{
  "id": "main",
  "name": "总店",
  "meters": [
    { "key": "hall",         "label": "大厅", "icon": "🎤", "multiplier": 160, "color": "#2563eb" },
    { "key": "fire",         "label": "消防", "icon": "🧯", "multiplier": 1,   "color": "#dc2626" },
    { "key": "private_room", "label": "包厢", "icon": "🛋️", "multiplier": 160, "color": "#059669" },
    { "key": "ac",           "label": "空调", "icon": "❄️", "multiplier": 160, "color": "#d97706" }
  ],
  "config": {
    "electricity_price": 0.9, "water_price": 4.5,
    "main_mult": 50, "sub_mult": 40
  }
}
```

### 3.2 门店上下文（核心机制）

新增包 `modules/stores/`：

| 文件 | 职责 |
|---|---|
| `context.py` | thread-local 当前门店；`set_current_store()` / `get_current_store()` / `current_store_paths()` |
| `registry.py` | 门店注册表 CRUD（读写 `settings.json` 的 `stores[]`） |
| `config.py` | `store.json` 读写；表定义；`row_values()` 读表值 |
| `handler.py` | 门店管理 / 总览 HTTP API |

`routing.py::_route()` 流程变为：

```
_auth_gate(...)                  # 已有：会话 + 角色
  ↓
_store_gate(handler, session)    # 新增：解析 ?store= → 校验权限 → 403
  ↓
set_current_store(store_id)      # 新增：写 thread-local
  ↓
原有分发（handler 通过 get_data_paths() 自动拿到本店路径）
```

`_store_gate()` 解析规则：

1. 读查询参数 `store`（缺省读 `X-Store` 头，最终由前端统一放 query）
2. 用户 `all_stores=true`（admin 默认）→ 允许任意合法 store_id
3. 否则 `store_ids` 必须包含该店，否则 **403**
4. 未指定 store：取用户第一个 `store_ids`；`all_stores` 用户取默认店 `main`

**关键收益**：`modules/_base.py::get_data_paths()` 改为返回 `current_store_paths()`，所有 `JsonModelHandler` 子类**一行不改**就自动按门店读写。`modules/_storage.py` 与 `settings_handler._get_current_dir()` 同步改。

### 3.3 表计自定义

**记录格式（向后兼容）**：

```json
{
  "date": "2026-11-25",
  "hall": 65.3, "fire": 1305.2, "private_room": 79.8, "ac": 52.1,
  "meters": { "m1": 12.3, "m2": 45.6 },
  "note": ""
}
```

- 原有 4 表继续用顶层字段 → **历史数据 100% 兼容，零迁移**
- 门店自定义的新表写进 `meters` 字典
- 统一读取器 `row_values(row, tables)`：先查 `meters[key]`，缺失则 fallback 顶层 `row[key]`

**`report.py` 参数化**：所有 `TABLES` 全局引用改为局部参数

```python
def calculate_monthly_report(readings, charges, month,
                              tables=None, price=None, cache_key=None) -> dict
```

`tables` 默认 `constants.DEFAULT_TABLES`（4 表），`price` 默认 `constants.ELECTRICITY_PRICE`。
同步改造的内部函数：`find_pasted_reading_charges` / `find_charge_conflicts` / `_charge_attribution` / `_resolve_charge`。

**价格来源**：`modules/reports/handler.py` 里的 `ELECTRICITY_PRICE_CONST` / `WATER_PRICE` 改为从当前店 `store.json` 读取，缺失回退常量。

### 3.4 权限模型

| 角色 | 门店范围 | 备注 |
|---|---|---|
| admin | 全部 | `all_stores=true` |
| supervisor | `store_ids` 内 | 可删/可管本店 |
| employee | `store_ids` 内 | 只读+录入本店 |

- 分店员工登录后只能看到本店；`store_ids` 为空的账号登录后显示"未分配门店"空态。
- 总部账号在侧栏顶部看到门店切换下拉。
- 门店越权（改 `?store=` 参数访问别店）由 `_store_gate()` 统一 403，与 `_auth_gate()` 同级，覆盖所有接口。

### 3.5 总部总表

新接口 `GET /api/stores/overview?month=2026-11`：

```json
{
  "month": "2026-11",
  "stores": [
    { "id": "main", "name": "总店",
      "total_kwh": 14242.2, "total_cost": 12817.98, "reading_days": 18,
      "by_meter": { "hall": 8100.1, "fire": 12.3, "private_room": 5000.2, "ac": 1129.6 },
      "utilities": { "main_kwh": 3200.0, "water_usage": 18.5 } }
  ],
  "total": { "total_kwh": 28484.4, "total_cost": 25635.96 }
}
```

实现：遍历 `stores[]`，各店用自己的 `tables`/`price` 跑 `calculate_monthly_report` 后横向合并。

### 3.6 前端改动

| 改动 | 位置 |
|---|---|
| 门店上下文（新） | `js/core/storeContext.js` —— 当前店、门店列表、切换事件 |
| API 层统一带 `store` 参数 | `js/core/api.js` `_request()` |
| 侧栏顶部门店切换器 | `index.html` + `js/core/storeContext.js`（仅总部/多店用户可见） |
| 抄表/充值表单动态表 | `index.html` 固定 input → 按当前店 `meters` 动态生成 |
| 表元数据动态化 | `js/core/meterConfig.js` `METER_CONFIG`/`METER_KEYS`/`CHARGE_METERS` 按当前店重建 |
| 报表渲染动态表 | `js/modules/reports.js`、`render_charts.js`、`alerts.js` 遍历当前店表集合 |
| 用户管理加"可访问门店"多选 | `admin.js` |
| 新增"门店总览"页 | 新侧栏项 + `js/modules/stores.js` |

### 3.7 备份 / 恢复 / NAS 同步

现有实现全部只认顶层文件，必须扩展：

| 路径 | 现状 | 改造 |
|---|---|---|
| `storage.backup_data()` | 只复制 `DATA_FILES.values()` | 递归复制 `stores/` 整个子树 + 顶层 `settings.json` |
| `handle_get_data_files` | 只扫顶层 json | 返回值 key 增加 `stores/<id>/<name>.json` 形式 |
| `handle_post_restore` / `handle_post_upload` | 顶层文件名白名单 | 白名单扩展为 `stores/<safe_id>/<safe_name>`，**保留路径穿越防护** |
| `handle_post_backup_download` | 同上 | 同上 |
| `handle_post_sync_from_nas` | 顶层文件名 | 支持嵌套 key 写入 |

### 3.8 图片

`modules/duty/handler.py` 的图片目录改为 `stores/<store_id>/images/`；文件名带门店前缀防跨店撞名。

### 3.9 数据迁移（幂等）

启动时执行 `migrate_to_stores(data_dir)`：

1. `stores/main/readings.json` 已存在 → 已迁移，跳过
2. 顶层 `readings.json` 存在 → **先自动全量备份 data_dir** → 搬进 `stores/main/`
3. 顶层 `settings.json` 的 `meter`/`config` → 写入 `stores/main/store.json`
4. `settings.json` 写入 `stores[]` 注册表，默认店 `id="main"`、`name="总店"`
5. 现有 admin 用户补 `all_stores: true`
6. 写 `stores/.schema_version`

**失败不阻塞启动**：读取时若 `stores/<id>/` 无对应文件，fallback 到顶层文件（读双写单）。

**顶层旧文件的去留**：迁移成功后**不删除**顶层 `readings.json` 等 6 个文件，保留为可回滚副本。fallback 规则仅对默认店 `main` 生效——分店目录缺失时直接报"门店数据目录不存在"，不回落顶层（否则分店会读到总店数据）。

---

## 4. 风险清单

| # | 风险 | 影响 | 应对 |
|---|---|---|---|
| R1 | `report.py` 缓存 key 未带 store_id | 总店与分店同月报表互相串，数字全错 | 缓存 key 强制 `f"{store_id}:{month}"`；加专项回归测试 |
| R2 | 前端 4 表硬编码约 70 处 | 分店自定义表数后页面显示错表 | P2 集中改造 `meterConfig` + 动态表单；保留旧 key 兼容 |
| R3 | 迁移出错导致生产数据丢失 | 不可逆 | 迁移前强制全量备份 + 幂等 + 失败回退读顶层 + 迁移后逐文件比对 |
| R4 | `settings.json` 语义变化（meter/config 迁走） | 老代码读不到电价/倍率 | 顶层保留副本兜底；`get_store_settings()` 优先读 `store.json` |
| R5 | 备份/恢复/NAS 漏掉 `stores/` 子树 | 备份不完整，恢复后数据丢失 | 四条路径全部覆盖并加测试 |
| R6 | 越权访问别店 | 数据泄漏 | `_store_gate()` 在 `_route()` 统一拦截 |
| R7 | `build-app.sh` 清 Application Support | 打包时删生产数据 | 本次改造期间不跑该脚本；跑之前另做独立备份并逐文件比对 |
| R8 | Docker 卷 / macOS 路径下子目录权限 | 启动失败 | `stores/` 首次启动自动创建；compose 无需改 |
| R9 | `settings.json` 迁移期被并发写 | 配置丢失 | 复用现有 `_SETTINGS_LOCK` + 原子写入 |

---

## 5. 分期实施

| 期 | 内容 | 后端 | 前端 | 新增用例 | 人日 |
|---|---|---|---|---|---|
| **P0** | 门店底座：注册表 / 上下文 / 鉴权闸 / 幂等迁移 / 按店读写 | ~500 行 | ~250 行 | ~15 | 3–4 |
| **P1** | 门店切换器 + 前端 `store` 参数贯通 | ~150 行 | ~300 行 | ~8 | 1.5–2 |
| **P2** | 表计自定义：`store.json` + `report.py` 参数化 + 动态表单与渲染 | ~450 行 | ~700 行 | ~15 | 3–4 |
| **P3** | 总部总表 + 总览页 | ~250 行 | ~350 行 | ~10 | 2–2.5 |
| | **合计** | ~1350 行 | ~1600 行 | **~48** | **10–13** |

> **备份/恢复改造并入 P0**（不单列工期，已计入 P0 后端行数）。P0 一旦把数据搬进
> `stores/` 子目录，现有 `backup_data()` / 恢复 / 上传 / NAS 同步就只抓得到顶层文件，
> 会立刻产出残缺备份。**备份覆盖面必须与数据搬迁同批上线**，不能拖到 P1/P2。
> P0 结束时的验收项包含：手动备份产出的 ZIP 内含 `stores/` 完整子树。

风险缓冲 +20% → 实际 **12–16 人日**（单人开发）。

### 每期收尾标准

- `python3 -m unittest discover -s tests -v` 全绿（147 个存量用例必须继续通过）
- `ruff check .` 与 `mypy .` 无新增告警
- **口径回归**：用 2026 年 6 月 Excel 核对值 **71226.1 度** 复验（P2 动了 `report.py` 表遍历后必须重跑）

### 建议顺序

P0 单独可上线（行为与现在完全一致，只是底层换了目录），先跑一周确认无回归，再进 P1 → P2 → P3。

---

## 6. 不在本次范围

- 分店之间的数据合并/拆分（迁店工具）
- 多租户计费与结算
- 分店独立部署（NAS 同步链路已有，本次用不上）
- 移动端 / 小程序
- 报表 PDF 导出
