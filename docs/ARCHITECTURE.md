# 🏗️ MeterStats 架构文档

> 本文档沉淀 MeterStats 的整体架构、关键算法和设计决策。
> 写给"刚加入项目想了解全貌"或"6 个月后回头看自己代码"的人。

---

## 📑 目录

1. [项目定位](#项目定位)
2. [系统架构](#系统架构)
3. [数据流](#数据流)
4. [后端模块清单](#后端模块清单)
5. [前端模块清单](#前端模块清单)
6. [关键算法](#关键算法)
7. [安全模型](#安全模型)
8. [关键设计决策与权衡](#关键设计决策与权衡)
9. [扩展指南](#扩展指南)
10. [常见坑](#常见坑)

---

## 🎯 项目定位

面向**单一组织**(场所属工程部)的电表/物品/工作记录管理工具,数据存储于本地 JSON 文件,服务以 `ThreadingHTTPServer` 形式启动。

**非**通用 SaaS、**非**多租户、**非**实时流式 — 这些假设决定了下面的所有架构选择。

### 三种部署形态

| 形态 | 入口 | 用途 |
|------|------|------|
| macOS App | `MeterStats.app/Contents/Resources/server.py` | 单机日常使用 |
| Docker | `docker-compose.yml` | 局域网/小团队共享 |
| 浏览器(纯 HTML) | `index.html` + 静态服务器 | 临时查看 |

---

## 🏛️ 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         浏览器 (index.html)                       │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                   JS 模块 (全局脚本模式)                    │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │   │
│  │  │  Core (配置/   │  │  Data (快照/  │  │  Render (渲染/   │ │   │
│  │  │  主题/a11y)  │  │  fetch/缓存)  │  │  Chart/编辑)    │ │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘ │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │   │
│  │  │  Forms       │  │  Features    │  │  UI              │ │   │
│  │  │ (submit/selectors)│(topup/utilities)│(toast/modals)   │ │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘ │   │
│  └───────────────────────────────────────────────────────────┘   │
│                              ↕ fetch /api/*                       │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                    ThreadingHTTPServer (Python 3.9+)              │
│                              ↓                                    │
│  ┌────────────┐  ┌──────────────────────────────────────────┐    │
│  │ app_handler │  │            routing.py                    │    │
│  │  (HTTP server│ │ (URL → handler 函数映射, 错误统一包装) │    │
│  │   入口)     │  └──────────────────────────────────────────┘    │
│  └────────────┘                       ↓                            │
│                          ┌─────────────────────┐                  │
│                          │  handlers/ (按职责拆)│                  │
│                          │  - auth.py           │                  │
│                          │  - users.py          │                  │
│                          │  - readings.py       │                  │
│                          │  - charges.py        │                  │
│                          │  - items.py          │                  │
│                          │  - purchases.py      │                  │
│                          │  - duty.py           │                  │
│                          │  - reports.py        │                  │
│                          │  - backup_admin.py   │                  │
│                          │  - backup.py (业务)  │                  │
│                          │  - admin_tools.py    │                  │
│                          │  - permissions.py    │                  │
│                          │  - settings.py       │                  │
│                          │  - dataimport.py     │                  │
│                          │  - readings_water.py │                  │
│                          └─────────────────────┘                  │
│                                  ↓                                │
│                          ┌─────────────────────┐                  │
│                          │   storage.py (JSON  │                  │
│                          │   文件 + LRU 缓存 + │                  │
│                          │   原子写入)         │                  │
│                          └─────────────────────┘                  │
│                                  ↓                                │
│                          ┌─────────────────────┐                  │
│                          │   ~/Library/        │                  │
│                          │   Application       │                  │
│                          │   Support/.../      │                  │
│                          │   *.json            │                  │
│                          └─────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
                                ↓
                  ┌──────────────────────────┐
                  │    backups/ (ZIP 快照)    │
                  │    + audit.json (审计)    │
                  │    + settings.json        │
                  └──────────────────────────┘
```

---

## 🌊 数据流

### 启动流程

1. `server.py` 启动:
   - 调用 `storage.get_data_dir()` 解析数据目录(优先 `METER_DATA_DIR`,否则 macOS 标准位置,否则旧位置)
   - 调用 `storage.init_data_files()` 创建空 JSON 文件 + 启动后台自动备份线程
   - `compute_version_token()` 计算 app.js/admin.js/style.css 的内容哈希,设置到 `app_handler.STATIC_VERSION_TOKEN`(用于破坏 CDN/浏览器缓存)
   - 启动 `ThreadingHTTPServer`,绑定 `METER_BIND:METER_PORT`(默认 `0.0.0.0:8765`)

2. 浏览器加载 `index.html`:
   - 通过 `<script src="...js?v=<token>">` 引用所有 JS(`utils.api.inject_version_to_html` 在响应时注入)
   - `init.js` 的 IIFE 异步调用 `renderAll()`
   - `renderAll` 优先 `GET /api/snapshot` 一次性拉全部数据,失败回退到 5 次独立 GET
   - 渲染各模块(状态条、抄表、充值、图表、报表……)

### 单次交互流程(以"录入抄表"为例)

```
用户在表单填写 4 块表读数
  ↓ forms_submit.js: submitReadingAdd()
  ↓ POST /api/readings {date, hall, fire, private_room, ac, ...}
  ↓ app_handler: _do_api() → routing.route() → handle_post_readings()
  ↓ readings.py: 验证 + 覆盖或新增
  ↓ storage.save_json() 原子写入(.tmp + rename) + 失效缓存
  ↓ report.invalidate_report_cache() 清月报缓存
  ↓ 返回 {ok: true, row}
  ↓ forms_submit.js: refreshAndRender() → 重新拉 snapshot → 重新渲染所有区块
```

### 缓存层次

| 层 | 位置 | TTL | 失效触发 |
|----|------|-----|---------|
| 浏览器全局变量 | `CURRENT_READINGS`/`CURRENT_CHARGES`/... | 内存生命周期 | `refreshAndRender()` |
| 月报内存缓存 | `report._report_cache` | 5 分钟 | `invalidate_report_cache()`(写入触发) |
| JSON 文件 LRU 缓存 | `storage._json_cache` | 进程生命周期 | `_cache_invalidate()`(写入触发) |
| HTTP 客户端缓存 | 浏览器 | `Cache-Control: no-store` | 永不缓存 |

---

## 🐍 后端模块清单

### 入口

| 模块 | 行数 | 职责 |
|------|------|------|
| `server.py` | 174 | 进程入口,启动 ThreadingHTTPServer,设置版本 token,管理 PID 文件 |
| `routing.py` | 240 | URL → handler 函数映射,统一错误处理(`_dispatch_fn` 包装 try/except) |
| `app_handler.py` | 161 | HTTP 请求处理器基类,处理 OPTIONS/CORS,挂载静态资源 |
| `constants.py` | 65 | 全局常量(电表倍率、价格、角色定义) |

### handlers/(业务模块,每个文件 ≤ 500 行)

| 模块 | 行数 | 职责 | 依赖 |
|------|------|------|------|
| `auth.py` | 302 | 登录/会话/速率限制 | `handlers.settings`, `storage.log` |
| `users.py` | 134 | 用户 CRUD + 电表设置 + 角色查询 | `handlers.settings` |
| `readings.py` | 129 | 电表抄表CRUD(仅 hall/fire/pr/ac) | `storage`, `report.invalidate_report_cache` |
| `readings_water.py` | 135 | 水电表底 CRUD(main_meter/sub_meter/water) | `storage` |
| `charges.py` | 107 | 充值记录 CRUD | `storage`, `report.invalidate_report_cache` |
| `items.py` | 214 | 物品 CRUD + 借出/归还子路径 | `storage`, `permissions._check_delete` |
| `purchases.py` | 152 | 申购记录 + 确认购买入库 | `storage` |
| `duty.py` | 425 | 值班工作记录 CRUD + 图片上传 | `storage`, `utils.api` |
| `reports.py` | 182 | 月报/年报/水电月报/snapshot/health/export | `report` |
| `backup.py` | 456 | 备份业务逻辑(创建/恢复/上传/settings 合并) | `storage`, `utils.api` |
| `backup_admin.py` | 476 | 备份 HTTP 入口(列表/下载/删除/配置) | `handlers.backup` |
| `admin.py` | 102 | **re-export 门面**,向后兼容 `from handlers.admin import ...` |
| `admin_tools.py` | 262 | 目录浏览/审计日志/水电数据迁移 | `storage`, `handlers.auth` |
| `permissions.py` | 103 | 权限装饰器工厂(`check_permission`) | `handlers.auth.get_session` |
| `settings.py` | 324 | settings.json CRUD(用户/密码 PBKDF2/电表设置) | 标准库 hashlib + fcntl(fallback threading.Lock) |
| `dataimport.py` | 403 | CSV 导入(readings/charges/items/purchases) | `storage` |
| `_base.py` | 153 | JsonModelHandler 基类 — CRUD 复用,白名单安全 | `storage`, `utils` |

### utils/(跨 handler 共享工具)

| 模块 | 行数 | 职责 |
|------|------|------|
| `utils/__init__.py` | - | send_json / send_csv / send_favicon / read_body / CORS |
| `utils/api.py` | 197 | 公共 HTTP 工具 + ZIP Bomb 防护 + inject_version_to_html |
| `utils/audit.py` | 73 | 审计日志(audit.json 读写) |

### 核心算法

| 模块 | 行数 | 职责 |
|------|------|------|
| `report.py` | 253 | 月报/年报计算引擎,带 5 分钟内存缓存 |
| `storage.py` | 596 | 数据目录解析、JSON 原子写入、LRU 缓存、自动备份 |

---

## 🌐 前端模块清单

按职责分组,所有 JS 通过 `<script>` 标签按依赖顺序加载到 `window` 全作用域。

### Core(配置/基础设施)

| 模块 | 职责 |
|------|------|
| `core_meterConfig.js` | 从 `/api/meters` 加载电表元数据(标签/图标/倍率/颜色),fallback 默认值 |
| `core_theme.js` | 主题切换(浅色/深色/系统) |
| `core_accessibility.js` | 可访问性增强(键盘快捷键、ARIA 属性) |
| `utils_helpers.js` | 通用工具:`el()`, `escapeHtml()`, `formatDate()`, `formatDateTime()`, `formatDateTimeLocal()` |

### Data(数据获取与状态)

| 模块 | 职责 |
|------|------|
| `data_global.js` | 全 局 变 量 (`CURRENT_READINGS`/`CURRENT_CHARGES`/...)+ 远 端 写 操 作 wrapper(`saveReadingRemote` 等) |
| `data_fetch.js` | `renderAll()` / `refreshAndRender()` 主入口,statusBar 计算 |
| `data_helpers.js` | 通用算法:`calcMonthlyDailyUsage` / `sumChargesBetween` / `addDaysToDate` |
| `data_water_migration.js` | 一次性提示用户迁移旧水电数据 |

### Render(渲染)

| 模块 | 职责 |
|------|------|
| `render_stats.js` | 当月统计卡片(4 表 + 合计) |
| `render_charts.js` | 每日用电折线图 + 单天饼图 + 月度饼图 |
| `render_charge_alert.js` | 充值预警卡片(剩余天数 + 建议充值金额) |
| `render_records.js` | 抄表/水电历史记录表 |
| `render_tables.js` | 物品/申购/工作记录表格 |
| `render_edit.js` | 编辑弹窗(充值/水电/物品借出归还)+ `escapeHtml` |
| `render_monthly.js` | 月度报告页 + 工作记录图片上传/压缩 |
| `render_weekly.js` | 每周汇报(4 表对比、趋势卡片、复制到剪贴板) |
| `render_weekly_trend.js` | 每周汇报的"4 块表详细趋势"卡片 |
| `render_yearly.js` | 年度汇总页 |
| `render_reports.js` | 月度报告页 + 单日汇报复制 |
| `render_duty_images.js` | 工作记录图片灯箱(独立文件避免循环依赖) |

### Forms(表单处理)

| 模块 | 职责 |
|------|------|
| `forms_submit.js` | 抄表/充值/水电录入提交 |
| `forms_selectors.js` | 月份/年份/历史下拉刷新 |
| `forms_open.js` / `forms_close.js` / `forms_tab.js` | 弹窗 open/close/tab 切换 |
| `forms_confirm.js` / `forms_buttons.js` | 确认/按钮逻辑 |

### Features(独立功能)

| 模块 | 职责 |
|------|------|
| `features_topup.js` | 充值计算器(按预充天数反推充值金额) |
| `features_utilities.js` | 水电月报 + 跨月对比 |
| `features_image_settings.js` | 工作记录图片存储配置 |

### UI(交互组件)

| 模块 | 职责 |
|------|------|
| `ui_toast.js` | 短暂提示(`showAlert(msg, kind)`),全局单 Toast |
| `ui_modals.js` | 模态确认弹窗(`showModal({title, body, ...})`),返回 Promise<boolean> |

> **约定**: 仅这两个 API。任何代码不应再创建 `showItemAlert` 等别名(2025-09 重构已统一)。

### 入口

| 模块 | 职责 |
|------|------|
| `init.js` | 启动 IIFE: `todayStr()` 填默认日期、`renderAll()` 拉数据、绑定事件 |
| `app.js` | 兼容旧入口 |

### 外部

| 模块 | 职责 |
|------|------|
| `admin.js` | 后台管理(用户/备份/审计/Docker 检测),单独作用域 |

---

## 🧮 关键算法

### 1. 月报半开半闭抄表区间

**位置**: `report.py:33-100`

抄表对 `[X, Y]` 表示从 X 日抄表到 Y 日抄表,**用电包含**:

```
实际用电度数 = (X.val - Y.val + 期间充电度数) × 倍率
```

**关键约定**: 充电日期归属规则是 **`X.date < charge.date <= Y.date`**(左开右闭)。

这意味着:
- 抄表当天 `X` 的充电 **不** 算到 `[X, Y]` 段,算到 `[prev, X]` 段
- 抄表当天 `Y` 的充电 **算到** `[X, Y]` 段

**均摊**: 用电均摊到区间内的每天 `usage / span = ... 度/天`。`Y` 那一天本身**不**算入段(`d < Y_dt`)。

```python
# 简化示意
for X, Y in pairs:  # 所有相邻抄表对
    charges_in_range = [c for c in charges if X.date < c.date <= Y.date]
    usage = (X.val - Y.val + sum(charges_in_range)) × multiplier
    avg_per_day = usage / span_days
    for d in range(X.date, Y.date):  # d < Y.date
        if d in target_month:
            daily[d] = avg_per_day
```

**测试**: `tests/test_monthly_report.py:test_charge_on_reading_day_left_open_right_closed`

### 2. JSON 缓存 LRU

**位置**: `storage.py:316-360`

基于 `OrderedDict` 实现真正 LRU:
- **读命中** 调用 `move_to_end(key)` 标记为最近访问
- **写覆盖** 先 `pop(key)` 再 `setdefault`,保证顺序更新
- **超容量** 调用 `popitem(last=False)` 弹出最久未访问的 key

**为什么用 OrderedDict 而非 dict**:Python 3.7+ 的 dict 是插入序,但**重复读不会更新顺序** — 也就是说普通 dict 实现不了 LRU(只能实现 FIFO)。

**容量**: `_JSON_CACHE_SIZE = 20`(6 个模型文件 + 14 个配置/历史等,基本足够)

### 3. 充值余量推算

**位置**: `js/data_helpers.js:calcMonthlyDailyUsage()`

```
余量度数 = latest_reading[meter] × 倍率
日均用电 = 当月所有抄表对的(读数差 + 期间充电)加权和 / 总天数
剩余天数 = 余量 / 日均
```

当月优先,无当月数据用上月,无上月用最近抄表对(fallback)。

### 4. 跨月抄表对处理

月报计算时会拉**上月末最后一条**和**下月初第一条**抄表,作为本月第一/末段的"虚拟抄表对",保证分摊合理。

---

## 🔒 安全模型

### 1. 认证

- **密码哈希**: PBKDF2-HMAC-SHA256, 600,000 轮, 16 字节 salt(参数见 `handlers/settings.py:_hash_pass`)
- **会话**: `secrets.token_hex(32)` 生成,内存存储,30 分钟 TTL(自动清理过期)
- **登录速率限制**: 5 分钟滑动窗口 10 次尝试,失败后 2 分钟冷却(`_check_login_rate_limit`)

### 2. 权限

三级:
- `employee`(员工): 读 + 写
- `supervisor`(主管): 读 + 写 + 删除
- `admin`(管理员): 全部 + 用户管理

通过 `@check_permission("read"/"write"/"delete"/"admin")` 装饰器强制。

### 3. 输入验证

- **JSON body**: `utils.api.opt_float` / `validate_date` / `validate_float`
- **文件路径**: 备份下载/删除前 `resolve()` 后校验 `str(real_path).startswith(str(allowed_root))`
- **ZIP 上传**: 4 重防护
  - 文件数量 ≤ 5000
  - 解压总大小 ≤ 100 MB
  - 文件名长度 ≤ 512
  - 目录穿越检测(`_validate_zip_safely`)
- **multipart 上传**: 显式 boundary 解析,**不**用第三方库

### 4. PUT 字段白名单

**位置**: `handlers/_base.py:JsonModelHandler`

PUT 操作三档行为:
1. 子类提供 `_update_fields(existing, body)` → 完全自定义(duty 模块)
2. 子类声明 `updatable_fields = frozenset({...})` → 只接受白名单(items 模块)
3. 都不声明 → **拒绝所有更新 + 500**(避免默认接受任意 body 字段的安全隐患)

### 5. 前端 XSS 防护

所有用户输入字段(`note` / `name` / `borrower` / `supplier` / `fault_area` 等)在拼接 `innerHTML` 前必须经 `escapeHtml()`(定义在 `utils_helpers.js`)。

**反面示例**(已修):

```js
// ❌ 危险:XSS
`<td>${r.note || '—'}</td>`

// ✅ 安全
`<td>${r.note ? escapeHtml(r.note) : '—'}</td>`
```

### 6. 跨平台兼容

`fcntl` 是 Unix 专属。`handlers/settings.py:init_settings` 检测:
- 有 fcntl → 文件锁 `flock`(支持多进程)
- 无 fcntl(Windows)→ 进程内 `threading.Lock`(单进程足够)

---

## ⚖️ 关键设计决策与权衡

### 1. **JSON 文件 vs SQLite**

选择 JSON 文件,**理由**:
- ✅ 零依赖(标准库)
- ✅ 人类可读、易备份/迁移
- ✅ 用文本编辑器直接修
- ❌ 无索引、无事务(自己用 RLock + 原子写入模拟)
- ❌ 全量加载(数据量 < 10MB 时无压力)

**何时该迁移**: 当单文件 > 50MB 或并发写 > 5 RPS 时考虑 SQLite。

### 2. **浏览器全局脚本 vs ES Modules**

选择全局脚本(`<script>` 标签链式加载),**理由**:
- ✅ 不需要打包工具(Webpack/Vite)
- ✅ macOS App 中直接随 .app 资源打包
- ✅ 调试时直接刷新即生效
- ❌ 文件需手动排序,避免隐式依赖
- ❌ 单文件 ≤ 450 行硬性约束

**约束**: 每个 JS 文件必须在 `window` 暴露它提供的函数,文件顶部注释 `// depends on: xxx.js` 说明依赖。

**当前超 450 行的 JS 文件**:无。最近一次重构已将三个超限文件全部拆分:

- `render_charts.js` 447 → 311 行(拆出 `render_pie_charts.js` 143 行)
- `render_weekly.js` 443 → 316 行(拆出 `render_weekly_utils.js` 134 行)
- `render_monthly.js` 403 → 279 行(拆出 `render_duty_image_upload.js` 127 行)

拆分原则见下文[关键设计决策](#关键设计决策与权衡)。

### 3. **后端 ThreadingHTTPServer vs 异步框架**

选择标准库 `ThreadingHTTPServer`,**理由**:
- ✅ 零外部依赖
- ✅ 单进程足够支持小团队
- ❌ GIL 限制 CPU 密集任务(本项目纯 IO,无影响)

### 4. **JSON Cache vs 每次读盘**

选择带 LRU 缓存,**理由**:
- ✅ 5 个模型文件每次操作读一次太慢(尤其 snapshot 要读 5 次)
- ✅ 写后立即失效缓存,一致性可保证
- ❌ 多进程部署时各进程独立缓存,内存占用 × 进程数(本项目单进程无影响)

### 5. **月报内存缓存 vs 每次重算**

5 分钟 TTL,**理由**:
- 月报计算含大量循环(12 个月 × 多表 × 多天)
- 5 分钟内数据写入会主动 invalidate,期间不会过期
- 用户切换月份查看是高频操作,缓存能极大降低 CPU

### 6. **前端 XSS vs 性能**

`escapeHtml` 后再拼接,**理由**:
- ✅ 简单可靠
- ❌ 字符串拼接比 DOM API 快(但可读性差)

**长期改进**: 用 `<template>` 元素或 web component 重构,但代价大。

### 7. **admin.py 拆分 vs 单文件**

选择拆分(1162 → 102 行门面 + 4 个职责清晰子模块),**理由**:
- ✅ 单文件 ≤ 450 行的项目硬性约束
- ✅ 各模块可独立测试
- ❌ 跨文件 re-export 不可变类型有陷阱(参见 `handlers/auth.py` 测试修复)

**陷阱**: `from auth import _last_cleanup_time; admin._last_cleanup_time = 0` 只改 admin 模块属性(值复制),不改 auth.需要测试直接 import 底层模块。

---

## 📱 响应式策略

MeterStats 以桌面端为主,移动端需支持「在会议室/仓库现场快速查看」。响应式策略写在 `style.css` 顶部注释,这里整理一表速查:

| 断点 | 调整内容 | 关键 CSS |
|------|---------|---------|
| ≥ 1280px | 桌面默认:侧栏 + 主内容 3 栏 | (无 `@media`) |
| ≤ 960px | 饼图/大图表变 1 列 | `.chart-grid { grid-template-columns: 1fr }` |
| ≤ 900px | 侧栏变抽屉(汉堡菜单)、表格行更紧凑 | `.sidebar { transform: translateX(-100%) }` |
| ≤ 768px | stat-grid 2 列、touch target ≥ 38px | `.stat-grid { grid-template-columns: repeat(2, 1fr) }` |
| ≤ 720px | 4 块表趋势卡片变 1 列 | `.meter-trend-grid { grid-template-columns: 1fr }` |
| ≤ 700px | meter-grid 1 列 | `.meter-grid { grid-template-columns: 1fr }` |
| ≤ 600px | card-header 纵向堆叠、弹窗底部 sheet、header 简化 | `.card-header { flex-wrap: wrap }` |
| ≤ 480px | stat-grid 1 列、数字 22px、卡片 padding 14px | `.stat-grid { grid-template-columns: 1fr !important }` |

**重点设计原则**:

1. **表格纵向/横向滚动** — 所有 `history-table` 都被 `<div style="overflow-x:auto">` 包裹,窄屏可横向滑动不裁剪。`.table-container`(月报) 也补上了 `overflow-x:auto`,避免月报 6 列在窄屏溢出。

2. **touch target ≥ 36-44px** — iOS HIG / Android Material 都推荐 44px。`.btn-sm` 在 ≤ 768px 被覆盖到 min-height: 36px 满足基本可点。

3. **status-bar 横向滚动** — 顶部 4 项状态条用 `overflow-x:auto` + `flex-wrap: nowrap`,窄屏可滑动查看,不换行挤压。

4. **避开硬编码 min-width** — 代码中已确认无内联 `width: 1000px` 之类,所有容器都跟随视口。

**新组件添加时的检查清单**:
- [ ] 在 ≤ 600px 时容器是否仍然可用?
- [ ] 表格/长文本是否被 `overflow-x:auto` 包裹?
- [ ] 按钮 touch target 是否 ≥ 36px?
- [ ] 表单 label/input 是否会换行挤压?

---

## 🛠️ 扩展指南

### 添加新的抄表数据类型

1. 在 `constants.py:METER_LABELS`/`METER_ICONS`/`METER_COLORS` 加配置
2. 在 `storage.py:DATA_FILES` 加文件映射(自动获得 LRU 缓存、自动备份)
3. 在 `handlers/` 创建 `<model>.py`,继承 `JsonModelHandler`
4. 在 `handlers/<model>.py` 声明 `updatable_fields = frozenset({...})` 白名单
5. 在 `routing.py` 加 4 个路由(GET / POST / PUT / DELETE)
6. 前端:
   - 在 `js/data_global.js` 加 `fetchXxxRemote()` 等 wrapper
   - 在 `js/data_fetch.js` 的 `renderAll()` 加渲染调用
   - 创建 `render_<model>.js` 处理 DOM 渲染
   - 在 `js/render_records.js` 等历史表加显示
   - 在 `index.html` 加 `<script>` 引入

### 添加新的报表页面

参考 `render_weekly_trend.js` 加到每周汇报的实际经验:

1. **后端**(如需新计算):
   - 在 `report.py` 加计算函数(参考 `calculate_monthly_report` 的结构)
   - 如需新 handler:在 `handlers/reports.py` 加端点,在 `routing.py` 注册路由
2. **后端缓存策略**:
   - 新函数必须在写入时调用 `invalidate_report_cache()`(在 `handlers/readings.py` / `charges.py` 等)
   - 同一测试类中混合真实 fixture 和自定义数据时,`setUp` 必须 `invalidate_report_cache()` 清缓存防污染
3. **前端新模块**:
   - 创建 `render_<feature>.js`(单文件 ≤ 450 行;若超过,按职责拆为 `xxx_main.js` + `xxx_utils.js`)
   - 仅暴露函数到 `window` 即可,无需打包工具
4. **前端接入**:
   - 在 `index.html` 加 `<script src="js/render_<feature>.js"></script>`(放在它依赖的文件之后)
   - 在 `js/data_fetch.js:renderAll()` 中调用新渲染函数
   - 在 `js/init.js` 或对应表单处绑定事件
5. **测试**:
   - 后端逻辑用 `unittest` 加测试,数据用临时目录隔离(`tempfile.TemporaryDirectory`)
   - 前端逻辑若可独立测(纯函数),抽出后用 Node.js 单测

### 添加新的月报计算字段

1. 在 `report.py:calculate_monthly_report` 加计算逻辑
2. 在 `tests/test_monthly_report.py` 加测试(`setUp` 会自动清缓存)
3. 前端:
   - 在 `js/render_monthly.js` / `js/render_charts.js` 等加渲染调用
   - 必要时加 Chart.js 配置

### 添加新的 HTTP 权限级别

1. 在 `constants.py:ROLES` 加定义
2. 在 `handlers/settings.py:OP_REQUIRED` 加操作→最低等级映射
3. 在 `handlers/permissions.py:ROLE_LEVEL` 加角色→等级映射
4. 装饰器 `@check_permission("xxx")` 即可使用

### 添加新的备份恢复策略

1. 在 `handlers/backup.py` 加 `_extract_xxx_to_target()` helper
2. 在 `handle_post_restore_upload` / `handle_post_upload` 调新 helper
3. 在 `tests/test_handlers.py:TestBackupApi` 加测试用例

---

## ⚠️ 常见坑

### 1. `_last_cleanup_time` re-export 陷阱

参见 `handlers/auth.py` 的 memory_remember。Python `from auth import x; admin.x = 5` 只改 admin,不改 auth。

### 2. JSON 缓存 key 冲突

`calculate_monthly_report(readings, charges, month)` 用 month 字符串做缓存键 — 即使参数不同,同 month 会命中缓存。**测试混合真实 fixture 和自定义数据时,setUp 必须 `invalidate_report_cache()`**。

### 3. 时区陷阱

所有日期处理必须用**本地时间**(`new Date()`, `dt.getFullYear()` 等),**禁用** `toISOString()`(会变 UTC)。`utils_helpers.js:formatDate()` 已封装。

### 4. fcntl 在 Windows 上 ImportError

参见 `handlers/settings.py:init_settings` 的 fcntl fallback。Windows 用户跑起来会自动用 threading.Lock,但**多进程部署下不能跨进程同步**。

### 5. items 借出数量边界

`total_qty - lent_qty` 计算可借出。**`available_qty <= 0` 时拒绝借出**(即使借 0.5 也拒)。但 `0.5 + 0.5 = 1.0` 浮点边界没问题(用户输入是整数)。

### 6. 抄表当天充电归属

参见算法章节。**抄表当天的充电归属下一段**,否则同一天充电+抄表会重复计算。

### 7. settings.json 并发初始化

`init_settings` 用 fcntl + threading.Lock 双层防 TOCTOU(两个线程同时检测到 settings.json 不存在,都尝试初始化,导致其中一个的默认用户覆盖另一个)。**测试并发 50 个 init_settings,应只有一个成功创建** — 已有 `test_concurrent_init_only_one_writes`。

### 8. _readingsBetween 过滤

`handlers/_base.py` 中 `_readingsBetween` 过滤 `r.hall != null` 跳过只录水电的行 — 这是抄表与水电分离后必须保持的逻辑,**复制此函数时记得同步**。

---

## 📚 相关文档

- `README.md` — 用户视角(功能/部署/快速开始)
- `README.Docker.md` — Docker 部署细节
- `OPTIMIZATION_REPORT.md` — 优化历程(已修复的 P0/P1/P2 清单)
- `tests/` — 88 个单元测试,覆盖核心算法与边界
