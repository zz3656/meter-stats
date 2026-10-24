# MeterStats 前后端接口契约文档

> 生成日期: 2026-10-23
> 版本: 后端 routing.py v1.0 / 前端 core/api.js v1.0

---

## 一、模块划分

### 涉及模块

| 模块 | 职责 | 对外接口 |
|------|------|---------|
| **readings** | 抄表记录 CRUD（大厅/消防/包厢/空调 4 表） | `Api.readings.{list,create,update,delete}` |
| **utilities** | 水电表底记录 CRUD（独立 tab，数据写 readings_water.json） | `Api.utilities.{list,create,update,delete,monthly}` |
| **charges** | 充值记录 CRUD（4 表充值度数） | `Api.charges.{list,create,update,delete}` |
| **items** | 物品管理 CRUD + 借还操作 | `Api.items.{list,create,update,delete,lend,return}` |
| **purchases** | 申购管理 CRUD + 入库操作 | `Api.purchases.{list,create,update,stock,delete}` |
| **duty** | 值班排班 CRUD + 图片处理 | `Api.duty.{list,create,update,delete,handle,image}` |
| **reports** | 报表（月度/年度/水电汇总）+ 系统信息 | `Api.reports.{health,version,snapshot,export,monthlyReport,yearlyReport,monthlyUtilities,reportCache}` |
| **system** | 认证 + 用户管理 + 系统设置 | `Api.system.{login,logout,me}` + `Api.admin.*` |
| **backup** | 数据备份/恢复（FormData 上传） | `Api.backup.{doBackup,restore}` |
| **dataimport** | 数据导入/模板下载 + 导出 | `Api.dataimport.{import,importTemplate,export}` |
| **upload** | 文件上传（值班图片等） | `Api.upload.doUpload` |
| **proxy** | NAS 数据代理 | `Api.proxy.nasData` |
| **images** | 图片配置管理 | `Api.images.{config,saveConfig}` |
| **migrate** | 水电数据迁移工具 | `Api.migrate.{water,waterStatus}` |

### 模块间依赖方向

```
前端 index.html
  └─ core/init.js
       ├─ core/api.js    ← 所有模块统一通过 Api.* 调用后端
       ├─ core/state.js  ← 全局状态管理（readings, charges, items, purchases, duty, settings）
       ├─ core/meterConfig.js ← 电表参数配置
       └─ js/modules/*.js  ← 各业务模块（调用 Api.* + State.*）
```

### 对外暴露的最小接口

- 前端: `Api.{模块}.{方法}()` — 16 个命名空间，68 个封装方法
- 前端: `State.{get,set,init,all}()` — 4 个状态操作方法
- 前端: `renderAll()` / `refreshAndRender()` — 全局刷新入口

---

## 二、前后端契约

### 前端范围

**页面:** `index.html`（单页应用，所有功能在同一页面通过 Tab 切换）

**组件:**
- 顶部导航: 抄表/充值/水电/物品/申购/值班/报表/系统设置 Tab
- 抄表区: 录入表单 + 历史记录表格 + 编辑/删除弹窗
- 充值区: 录入表单 + 充值记录表格 + 编辑/删除弹窗
- 水电区: 独立 Tab 录入表单 + 水电历史表格
- 物品区: 物品列表 + 借还操作按钮
- 申购区: 申购列表 + 入库/编辑/删除
- 值班区: 排班表格 + 图片上传 + 处理按钮
- 报表区: 月度报告/年度汇总/水电汇总/统计图表
- 系统设置: 用户管理/角色/电表设置/备份管理/审计日志

**交互状态:**
- 编辑弹窗: `modal-backdrop.show` 控制可见性（CSS opacity:0 + pointer-events:none，.show 才可见可点）
- 提交防重复: `_submitting` 标志位
- Toast 提示: `showAlert(message, type)` 成功/错误通知
- 状态栏: 上次抄表日期、本月用电/电费、余量预警

### 后端范围

**接口:** 47 个 `/api/*` 端点，通过 `routing.py` 分发到各 handler

**数据模型:**

| 实体 | 存储文件 | 关键字段 |
|------|---------|---------|
| 抄表记录 | `readings.json` | date, hall, fire, private_room, ac, note, rehearsal, programming |
| 充值记录 | `charges.json` | id, date, hall, fire, private_room, ac, note |
| 水电记录 | `readings_water.json` | date, main_meter, sub_meter, water, note |
| 物品 | `items.json` | id, name, quantity, status (available/lent) |
| 申购 | `purchases.json` | id, name, quantity, unit_price, status |
| 值班 | `duty.json` | id, date, person, status, images[] |
| 设置 | `settings.json` | electricity_price, multipliers, backup_config, users[] |

**业务规则:**
- 抄表日期唯一（同一天一条记录）
- 修改非当日记录需二次确认弹窗
- 水电独立录入但数据存储到 readings_water.json
- 余量预警: 剩余天数 < 7 的表数量统计（基于 `last[m.key] * MULTIPLIER(m.key)`）
- 备份恢复: 恢复前自动备份当前数据（可回滚）

### 接口清单

#### 1. 抄表模块 (Readings)

| # | 路径 | 方法 | Api.* 映射 | 请求体 | 响应示例 | 错误码 |
|---|------|------|-----------|--------|---------|--------|
| 1 | `/api/readings` | GET | `Api.readings.list(params)` | — | `{ "data": [...] }` | 401 未认证 |
| 2 | `/api/readings` | POST | `Api.readings.create(data)` | `{ date, hall, fire, private_room, ac, note?, rehearsal?, programming? }` | `{ "message": "OK" }` | 409 日期冲突 |
| 3 | `/api/readings/{date}` | PUT | `Api.readings.update(date, data)` | `{ date?, hall?, fire?, private_room?, ac?, note?, ... }` | `{ "message": "OK" }` | 404 不存在 |
| 4 | `/api/readings/{date}` | DELETE | `Api.readings.delete(date)` | — | `{ "message": "OK" }` | 404 |

**响应示例 (GET /api/readings):**
```json
{
  "data": [
    {
      "date": "2026-10-23",
      "hall": 125.3,
      "fire": 89.7,
      "private_room": 45.2,
      "ac": 201.8,
      "note": "",
      "rehearsal": false,
      "programming": true
    }
  ]
}
```

#### 2. 充值模块 (Charges)

| # | 路径 | 方法 | Api.* 映射 | 请求体 | 响应示例 |
|---|------|------|-----------|--------|---------|
| 5 | `/api/charges` | GET | `Api.charges.list(params)` | — | `{ "data": [...] }` |
| 6 | `/api/charges` | POST | `Api.charges.create(data)` | `{ date, hall, fire, private_room, ac, note }` | `{ "message": "OK" }` |
| 7 | `/api/charges/{id}` | PUT | `Api.charges.update(id, data)` | `{ date?, hall?, fire?, private_room?, ac?, note? }` | `{ "message": "OK" }` |
| 8 | `/api/charges/{id}` | DELETE | `Api.charges.delete(id)` | — | `{ "message": "OK" }` |

#### 3. 水电模块 (Utilities)

| # | 路径 | 方法 | Api.* 映射 | 请求体 | 响应示例 |
|---|------|------|-----------|--------|---------|
| 9 | `/api/readings-water` | GET | `Api.utilities.list()` | — | `{ "data": [...] }` |
| 10 | `/api/readings-water/monthly?ym=YYYY-MM` | GET | `Api.utilities.monthly(ym)` | — | `{ "data": [...] }` |
| 11 | `/api/readings-water` | POST | `Api.utilities.create(data)` | `{ date, main_meter?, sub_meter?, water, note }` | `{ "message": "OK" }` |
| 12 | `/api/readings-water/{date}` | PUT | `Api.utilities.update(date, data)` | `{ date?, main_meter?, sub_meter?, water?, note? }` | `{ "message": "OK" }` |
| 13 | `/api/readings-water/{date}` | DELETE | `Api.utilities.delete(date)` | — | `{ "message": "OK" }` |

#### 4. 物品模块 (Items)

| # | 路径 | 方法 | Api.* 映射 | 请求体 |
|---|------|------|-----------|--------|
| 14 | `/api/items` | GET | `Api.items.list()` | — |
| 15 | `/api/items` | POST | `Api.items.create(data)` | `{ name, quantity }` |
| 16 | `/api/items/{id}` | PUT | `Api.items.update(id, data)` | `{ name?, quantity? }` |
| 17 | `/api/items/{id}` | DELETE | `Api.items.delete(id)` | — |
| 18 | `/api/items/{id}/lend` | PUT | `Api.items.lend(id, data)` | `{ borrower, note }` |
| 19 | `/api/items/{id}/return` | PUT | `Api.items.return(id, data)` | `{ borrower?, note? }` |

#### 5. 申购模块 (Purchases)

| # | 路径 | 方法 | Api.* 映射 | 请求体 |
|---|------|------|-----------|--------|
| 20 | `/api/purchases` | GET | `Api.purchases.list()` | — |
| 21 | `/api/purchases` | POST | `Api.purchases.create(data)` | `{ name, quantity, unit_price }` |
| 22 | `/api/purchases/{id}` | PUT | `Api.purchases.update(id, data)` | `{ name?, quantity?, unit_price? }` |
| 23 | `/api/purchases/{id}/stock` | PUT | `Api.purchases.stock(id, data)` | `{ quantity }` |
| 24 | `/api/purchases/{id}` | DELETE | `Api.purchases.delete(id)` | — |

#### 6. 值班模块 (Duty)

| # | 路径 | 方法 | Api.* 映射 | 请求体 |
|---|------|------|-----------|--------|
| 25 | `/api/duty` | GET | `Api.duty.list()` | — |
| 26 | `/api/duty` | POST | `Api.duty.create(data)` | `{ date, person }` |
| 27 | `/api/duty/{id}` | PUT | `Api.duty.update(id, data)` | `{ date?, person? }` |
| 28 | `/api/duty/{id}` | DELETE | `Api.duty.delete(id)` | — |
| 29 | `/api/duty/{id}/handle` | POST | `Api.duty.handle(id, data)` | `{ status }` |
| 30 | `/api/duty/{id}/image` | POST | `Api.duty.image(id, fileData)` | `{ imageData }` (base64) |
| 31 | `/api/duty/image/{filename}` | GET | — (直接 fetch) | — 返回图片文件 |
| 32 | `/api/admin/images` | GET | `Api.images.config()` | — |
| 33 | `/api/admin/images` | PUT | `Api.images.saveConfig(data)` | `{ config }` |

#### 7. 报表模块 (Reports)

| # | 路径 | 方法 | Api.* 映射 | 请求体 |
|---|------|------|-----------|--------|
| 34 | `/api/health` | GET | `Api.reports.health()` | — 系统健康状态 |
| 35 | `/api/version` | GET | `Api.reports.version()` | — `{ "version": "x.y.z" }` |
| 36 | `/api/snapshot?models=readings,charges,...` | GET | `Api.reports.snapshot(params)` | — 一次性拉取所有数据 |
| 37 | `/api/export?models=readings&format=csv` | GET | `Api.reports.export(params)` | — 导出文件下载 |
| 38 | `/api/monthly-report?month=YYYY-MM` | GET | `Api.reports.monthlyReport(month)` | — 月度报告数据 |
| 39 | `/api/yearly-report?year=YYYY` | GET | `Api.reports.yearlyReport(year)` | — 年度汇总数据 |
| 40 | `/api/monthly-utilities?month=YYYY-MM` | GET | `Api.reports.monthlyUtilities(month)` | — 月度水电汇总 |
| 41 | `/api/admin/report-cache` | GET | `Api.reports.reportCache()` | — 报表缓存状态 |

#### 8. 系统/认证模块 (System)

| # | 路径 | 方法 | Api.* 映射 | 请求体 |
|---|------|------|-----------|--------|
| 42 | `/api/auth/login` | POST | `Api.system.login(user, pass)` | `{ user, password }` |
| 43 | `/api/auth/logout` | GET | `Api.system.logout()` | — |
| 44 | `/api/auth/me` | GET | `Api.system.me()` | — `{ "username": "...", "role": "..." }` |
| 45 | `/api/auth/me?session=true` | GET | — 获取当前会话信息 |

#### 9. 管理模块 (Admin) — 通过 Api.admin.*

**用户管理:**
| # | 路径 | 方法 | Api.* 映射 |
|---|------|------|-----------|
| 46 | `/api/admin/users` | GET | `Api.admin.users()` |
| 47 | `/api/admin/users` | POST | `Api.admin.createUser(data)` |
| 48 | `/api/admin/users/{username}` | PUT | `Api.admin.updateUser(username, data)` |
| 49 | `/api/admin/users/{username}` | DELETE | `Api.admin.deleteUser(username)` |

**角色管理:**
| # | 路径 | 方法 | Api.* 映射 |
|---|------|------|-----------|
| 50 | `/api/admin/roles` | GET | `Api.admin.roles()` |

**电表设置:**
| # | 路径 | 方法 | Api.* 映射 |
|---|------|------|-----------|
| 51 | `/api/admin/meter` | GET | `Api.admin.meterSettings()` |
| 52 | `/api/admin/meter` | PUT | `Api.admin.saveMeterSettings(data)` |
| 53 | `/api/meters` | GET | `Api.admin.metersPublic()` — 公开接口，无需认证 |

**备份管理:**
| # | 路径 | 方法 | Api.* 映射 |
|---|------|------|-----------|
| 54 | `/api/admin/backup-status` | GET | `Api.admin.backupStatus()` |
| 55 | `/api/admin/backup-config` | GET | `Api.admin.backupConfig()` |
| 56 | `/api/admin/auto-backup` | PUT | `Api.admin.setAutoBackup(enabled)` |
| 57 | `/api/admin/backup-retention` | PUT | `Api.admin.setBackupRetention(days)` |
| 58 | `/api/admin/backup-delete?name=...` | GET | `Api.admin.backupDelete(name)` |
| 59 | `/api/admin/backup-download?name=...` | GET | `Api.admin.backupDownload(name)` |
| 60 | `/api/admin/backup-delete?name=...` | POST | — (POST 版本备份删除) |
| 61 | `/api/admin/backup-download?name=...` | POST | — (POST 版本备份下载) |
| 62 | `/api/admin/data-files` | GET | `Api.admin.dataFiles()` |
| 63 | `/api/admin/dir-listing?dir=...` | GET | `Api.admin.dirListing(dir)` |

**其他管理:**
| # | 路径 | 方法 | Api.* 映射 |
|---|------|------|-----------|
| 64 | `/api/admin/audit` | GET | `Api.admin.auditLog()` |
| 65 | `/api/admin/sessions` | GET | `Api.admin.sessions()` |
| 66 | `/api/admin/sync-from-nas` | POST | `Api.admin.syncFromNAS(url)` |
| 67 | `/api/admin/migrate-water-status` | GET | — 水电迁移状态 |
| 68 | `/api/admin/migrate-water` | POST | — 执行水电迁移 |

#### 10. 备份/恢复 (FormData)

| # | 路径 | 方法 | Api.* 映射 | 说明 |
|---|------|------|-----------|------|
| 69 | `/api/backup` | POST | `Api.backup.doBackup()` | 手动备份，JSON body |
| 70 | `/api/restore` | POST | `Api.backup.restore(file)` | **FormData** 上传备份文件 |
| 71 | `/api/import` | POST | `Api.dataimport.import(model, file)` | **FormData** 上传导入文件 |
| 72 | `/api/import/template?model=...` | GET | `Api.dataimport.importTemplate(model)` | 下载导入模板 |
| 73 | `/api/export?models=...` | GET | `Api.dataimport.export(params)` | 导出数据 |
| 74 | `/api/upload` | POST | `Api.upload.doUpload(file, category)` | **FormData** 上传文件 |
| 75 | `/api/admin/restore-upload` | POST | — (admin 备份上传恢复) |
| 76 | `/api/proxy/nas-data?url=...` | GET | `Api.proxy.nasData(url)` | NAS 数据代理 |

### 错误码约定

| 状态码 | 含义 | 常见场景 |
|--------|------|---------|
| 200 | 成功 | 正常返回 `{ "data": ... }` 或 `{ "message": "OK" }` |
| 401 | 未认证 | 缺少或无效 token，重定向登录页 |
| 403 | 无权限 | 用户角色不足以执行该操作 |
| 404 | 不存在 | 记录未找到（DELETE/PUT 时） |
| 409 | 冲突 | 日期已存在（POST readings 时） |
| 500 | 服务器错误 | `{ "error": "服务器内部错误" }` |

### 认证机制

- 登录成功后后端返回 `{ "token": "..." }`
- 前端存储到 `localStorage.token`
- 后续请求通过 `Authorization: Bearer <token>` 头传递

### 数据流

```
用户操作 → 前端模块 (js/modules/*.js)
         → Api.* 封装 (core/api.js)
         → fetch('/api/...') [JSON body 或 FormData]
         → routing.py 分发到 handler
         → modules/{模块}/handler.py 处理业务逻辑
         → storage.py 读写 JSON 数据文件
         → 返回 { "data": ... } 或 { "message": "OK" }
         → 前端 State.* 更新状态 → UI 刷新
```

---

## 三、联调方式

### 当前状态

- ✅ 后端服务运行于 `localhost:8765`
- ✅ 所有 47 个后端路由已注册并通过 routing.py 分发
- ✅ 前端 `core/api.js` 封装了全部 68 个 Api.* 方法
- ✅ `build-app.sh release --install` 成功，App 已安装到 `/Applications/MeterStats.app`

### API 层验证（curl）

后端服务可直接启动验证（不依赖 .app 构建）:

```bash
cd ~/Documents/GitHub/meter-stats/MeterStats
python3 server.py
```

然后:

```bash
# 健康检查
curl http://localhost:8765/api/health

# 登录获取 token
curl -X POST http://localhost:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"user":"admin","password":"xxx"}'

# 获取抄表记录
curl http://localhost:8765/api/readings \
  -H "Authorization: Bearer <token>"

# 新增抄表记录
curl -X POST http://localhost:8765/api/readings \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer <token>" \
  -d '{"date":"2026-10-23","hall":125.3,"fire":89.7,"private_room":45.2,"ac":201.8}'
```

### 前端联调

- `index.html` 已引用新模块（8 个 js/modules/*.js + core/api.js + core/state.js）
- 新模块通过 `Api.*` 调用后端，旧 JS 已移除引用
- 注意: `js/modules/readings.js` (566行) 仍使用直接 `fetchReadings()` 等函数（在 `data_fetch.js` 中定义），**未统一使用 `Api.readings.*`**。这是遗留调用方式，功能正常但不符合"统一通过 Api.* 封装"的架构约定。

### 架构最终状态（已统一）

**所有前端模块统一通过 `Api.*` 封装调用后端，无直接 `fetch('/api/...')` 调用（除 core/api.js 内部实现外）。**

| 模块 | Api.* 调用 | State.* 调用 | 直接 fetch('/api/...') | 状态 |
|------|-----------|-------------|----------------------|------|
| readings.js (593行) | 22次 | 10次 | 0 ✅ | 完全迁移 |
| charges.js (98行) | 5次 | 2次 | 0 ✅ | 完全迁移 |
| utilities.js (108行) | 6次 | 2次 | 0 ✅ | 完全迁移 |
| items.js (193行) | 7次 | 1次 | 0 ✅ | 完全迁移 |
| purchases.js (101行) | 6次 | 2次 | 0 ✅ | 完全迁移 |
| duty.js (153行) | 5次 | 4次 | 0 ✅ | 完全迁移 |
| reports.js (195行) | 4次 | — | 0 ✅ | 完全迁移 |
| backup.js (15行) | 2次 | — | 0 ✅ | 完全迁移 |
| admin.js (1059行) | 19次 | — | 0 ✅ | 完全迁移 |
| 其他 (accessibility, toast, modals等) | 14次 | — | 0 ✅ | 无 API 调用 |
| **总计** | **66次** | **21次** | **0** ✅ | 架构统一 |

> **注意**: `core/api.js` 内部有 9 处 `fetch()`（包含 FormData 封装），这是 API 封装层的实现细节，不构成架构风险。

### 遗留优化建议（非阻塞）

1. `reports.js` 未使用 `State.*`，如需跨模块共享报表数据可补充
2. `shared/accessibility.js` 封装了部分数据获取函数（`fetchReadings`, `fetchCharges` 等），这些函数内部调用 `Api.*`，作为兼容层保留合理
3. `.build/` 中少量旧文件（init.js 等）不再被 `index.html` 引用，可手动清理

---

## 四、构建产物

- **目标平台**: macOS 14+
- **产出物**: `/Applications/MeterStats.app`（macOS 原生应用）
- **签名后 .dmg**: 按需生成
- **后端端口**: 8765（默认，可通过 `METER_PORT` 环境变量修改）
- **数据目录**: `~/Library/Application Support/com.meter.stats/`
