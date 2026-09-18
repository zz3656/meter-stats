# MeterStats 项目代码优化建议

> 审计范围:全部 Python 后端 + 全部 JS/HTML/CSS 前端
> 报告生成时间:基于最新 working tree 状态

---

## 🚨 P0 — 安全风险(必修)

### 1. XSS:用户输入未转义就插入 innerHTML
**位置**:
- `js/render_records.js:36` — `r.note || '—'` 直接插入(抄表记录)
- `js/render_records.js:88` — `w.note || '—'` 直接插入(水电记录)
- `js/render_charts.js:204` — `${day}` 已转义但 `${usage.totalCost}` 等数字 OK;但 **render_weekly.js** 卡片有 `chargeHint`(检查)
- `js/render_weekly.js:88-130` — 数据可来自用户 note,需 review
- `js/render_charge_alert.js:62` — `multiplierHint` 用 `multiplier`,数据安全但无 escape
- `js/render_edit.js:1` 已定义 `escapeHtml`,但**未在所有地方使用**

**风险**:用户在 note 字段输入 `<img src=x onerror=alert(1)>` 会立即执行任意 JS。
而 `escapeHtml` 已经定义,只是部分表格忘了调用。

**修复**:
1. 改 `render_records.js:36`:
   ```js
   <td>${r.note ? escapeHtml(r.note) : '—'}${tagsHtml}</td>
   ```
2. 全项目 grep `innerHTML.*\${[^}]*\}` 统一过一遍
3. 长期方案:引入轻量 helper(例如 `el(tag, props, ...children)`)替代字符串拼接

---

### 2. 死代码 handler 暴露潜在攻击面
**位置**: `handlers/readings.py:23` `handle_get_readings_monthly`、`handlers/charges.py:26` `handle_get_charges_monthly`

**问题**: 这两个函数定义了但**从未被 routing.py 导入**。前端也没用 `/api/readings/monthly` 或 `/api/charges/monthly`。

**风险**: 死代码带来:
- 维护成本(改动时不知道谁在用)
- 未来如果有人加进 routing,行为可能不符合预期

**修复**: 删除这两个函数,或在 routing.py 中显式注册并加上明确说明。

---

### 3. fcntl 不可移植
**位置**: `handlers/settings.py:72,84,142`

```python
import fcntl
fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
```

**问题**: `fcntl` 是 Unix 专用,**在 Windows 上直接 ImportError**。`pyproject.toml` 写的是 `requires-python = ">=3.9"`,但没限制 OS。

**风险**: 用户在 Windows 上启动服务,settings 初始化时会崩溃。

**修复**: 
```python
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

# 锁时:fcntl 可用就用,否则退化为 threading.Lock
```

---

### 4. CORS 默认值在远程部署下不安全
**位置**: `utils/api.py:13`
```python
_DEFAULT_ORIGIN = f"http://localhost:{os.environ.get('METER_PORT', '8765')}"
```

**问题**: 如果用户部署到公网但忘记设 `METER_CORS_ORIGIN`,会用默认 localhost,所有跨域请求都会被拒。但更危险的是,如果有人**显式设置** `METER_CORS_ORIGIN=*`,代码会允许任意 origin + credentials,产生 CSRF 风险。

**位置**: `utils/api.py:23`
```python
**({"Access-Control-Allow-Credentials": "true"} if CORS_ORIGIN != _DEFAULT_ORIGIN else {})
```

**修复**: 当 origin = `*` 时,**强制**不发送 `Allow-Credentials: true`,并加 warning 日志。

---

### 5. SQL 注入(N/A 但需复核)
**位置**: 无 SQL — 项目用的是 JSON 文件,无 SQL 注入风险。✓ 但应避免将来引入数据库时使用字符串拼接。

---

## ⚠️ P1 — 性能与可靠性(高优)

### 6. `load_json` 缓存失效隐患
**位置**: `storage.py:307-353` 的 `_json_cache` 实现

**问题**: 
- LRU 用 `while len > N: pop(next(iter()))` 字典迭代顺序 = 插入顺序,但**重新赋值不会更新顺序**(Python 3.7+ 字典是插入顺序)。
- 也就是说,反复读同一文件不会刷新"最近使用",可能被错误淘汰。
- 缓存的 mtime 与 stat 是不同数据源,如果文件被外部修改(用户用文本编辑器直接改 JSON),缓存仍命中旧 mtime。

**修复**:
```python
# 用 collections.OrderedDict 实现真正的 LRU
from collections import OrderedDict
_cache: OrderedDict[str, tuple] = OrderedDict()

def _cache_get(path_str):
    with _json_cache_lock:
        if path_str in _cache:
            _cache.move_to_end(path_str)  # 标记为最近使用
            return _cache[path_str]
    return None, None
```

---

### 7. N+1 读取与"按需加载"反模式
**位置**: `handlers/reports.py:21-25`、`handlers/items.py:73-86` 等多个 handler

**问题**: 每个 handler 单独调用 `load_json(path)`。但 storage 已经有缓存,这部分**还好**。真正的问题是 `handle_get_health`、`handle_get_snapshot` 会**依次**调用 `_load(name)` N 次,每次都查缓存字典。

**修复**: `snapshot` 一次性读所有文件,可以并行(asyncio)但当前是 sync HTTP server,只能串行。**当前实现可以接受** — 不算严重问题,只算"非最优"。

---

### 8. `admin.py` 1162 行 — 单一文件过大
**位置**: `handlers/admin.py`

**问题**: 一个文件包含:
- 会话管理
- 登录速率限制
- 用户 CRUD
- 电表设置
- 角色查询
- 备份管理
- 目录浏览
- 审计日志
- 水电迁移
- ……

按项目约定("单文件 ≤ 450 行")严重超标。

**修复**: 拆为:
- `handlers/auth.py` — 登录/会话/速率限制
- `handlers/users.py` — 用户 CRUD
- `handlers/backup_api.py` — 备份/恢复/下载/删除/配置(已存在 backup.py,合并)
- `handlers/admin_tools.py` — 目录浏览、审计日志、水电迁移

---

### 9. storage.py `_validate_zip_safely` 在 `handlers/backup.py` 重复定义
**位置**: 
- `handlers/backup.py` 顶层有 `_resolve_backup_parent`、`_cleanup_manual_backups`
- `handlers/admin.py` 重复 import 或定义

**修复**: 统一到 `handlers/backup.py`,其他模块引用。

---

### 10. `index.html` 1528 行,内联样式 373 处
**位置**: `index.html`

**问题**: 维护噩梦。每次小调整都要碰 HTML。响应式也基本没做 — 整个页面假设桌面 ≥ 1024px。

**修复**:
1. 提取"重复 5 次以上"的 inline style 为 CSS class,例如:
   - `style="display:none;margin-top:16px;"` → `.section-block`
   - `style="color:var(--text-muted);font-size:12px;"` → `.meta-text`
2. 长远方案:用 `<template>` 元素或 web component 重构,但代价大。

---

### 11. 跨文件隐式依赖
**位置**:
- `js/render_tables.js:283` 用 `openLightbox`,但定义在 `js/render_monthly.js:403`
- `js/render_tables.js:282` 用 `getDutyImageUrl`,定义在 `js/render_monthly.js:412`
- `js/render_stats.js:39` 用 `_monthCopyData`,定义在 `js/render_reports.js:86` (`window._monthCopyData`)
- `js/forms_submit.js` 用 `_submitting`,定义在 `js/render_monthly.js:2`

**问题**: 文件加载顺序错(例如 admin.js 比 render_monthly.js 早)就立即 crash。命名冲突风险。

**修复**: 在每个文件顶部 `// depends on: render_monthly.js` 注释(至少),或建立 `js/globals.js` 显式声明共享状态。

---

### 12. `_submitting` 全局锁太粗
**位置**: `js/render_monthly.js:2`,`js/forms_submit.js` 多处

**问题**: 一个表单提交时,其他表单(比如充值)也按不动。设计意图可能是"防双击",但实际上是"防误操作"过严。

**修复**: 改为**每个按钮**独立 disable:
```js
const btn = document.getElementById('reading-submit-btn');
btn.disabled = true;
btn.textContent = '保存中…';
// after
btn.disabled = false;
```

---

## 🔧 P2 — 代码质量与可维护性

### 13. 日期格式化重复 20+ 次
**位置**: 
- `js/init.js:6-7`(todayStr)
- `js/init.js:18-22`(nowDateTimeStr)
- `js/render_weekly.js:93,113,181-182,375-376`(fmt 函数)
- `js/render_charts.js`(多处)
- `js/data_fetch.js`(多处)

**修复**: 在 `js/utils_helpers.js`(目前只有 132 行)中加:
```js
window.formatDate = (d) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
window.formatDateTime = (d) => `${formatDate(d)} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
```

---

### 14. `index.html` 中 `onclick="..."` 45 处
**问题**: 不利于 CSP;并且函数作用域容易冲突。

**修复**: 改用 `addEventListener`,在 init 阶段统一绑定。

---

### 15. `data_global.js` 仅 132 行,功能简单却单独成文件
**位置**: `js/data_global.js`

**问题**: 文件太小,仅定义了 5 个 API wrapper。可以合并到 `data_fetch.js` 或 `data_helpers.js`。

---

### 16. 后端日志混乱
**位置**: `storage.py` `log()`, `handlers/admin.py` 中 `print()`

**问题**: 
- 一些用 `print(f"[{ts}] {msg}", flush=True)`
- 一些用 `log(f"  ...")`
- 一些用 `print(f"  OK ...", file=sys.stderr)`

**修复**: 全部用 `log()`,并加日志级别(DEBUG/INFO/WARN/ERROR)。

---

### 17. `_check_delete` 内部重复实现权限检查
**位置**: `handlers/items.py:183-200`

**问题**: `permissions.py` 已有 `check_delete_permission` 装饰器,但 `items.py` 重新手写了权限检查(因为该 handler 不走基类 handle_delete)。

**修复**: 删除 `_check_delete`,改用装饰器:
```python
@check_delete_permission
def handle_delete_items(handler, path_clean):
    _h.handle_delete(handler, path_clean)
```

---

### 18. 报表缓存 key 用裸字符串
**位置**: `report.py:46`, `report.py:97`

**问题**: `cache_key = f"yearly:{year}"` 用前缀区分,但 monthly 没前缀 — 容易冲突(例如将来加 `"yearly-2025"` 也走缓存)。

**修复**: 用 enum 或 const:
```python
CACHE_KEY_MONTHLY = "monthly"
CACHE_KEY_YEARLY = "yearly"
```

---

### 19. `handlers/_base.py` 字段处理逻辑可简化
**位置**: `_base.py:97-103`

```python
updater = getattr(self, "_update_fields", None)
if updater:
    updater(existing, body)
else:
    for k, v in body.items():
        if k != "id":
            existing[k] = v
```

**问题**: 默认行为是直接覆盖,意味着 PUT 接收的所有字段都会被写入 — 没白名单,没字段过滤。

**修复**: 加白名单(每个子类声明 `model` + `fields`):
```python
class JsonModelHandler:
    model: str = ""
    fields: list[str] = []  # 子类声明合法字段
    ...
```

---

## 📋 P3 — 体验/UX 优化

### 20. 大量 `style="display:none"` 重复
**位置**: 全 index.html

**修复**: 提取 class:`.hidden { display: none; }` 或 `.section-block[hidden]`。

---

### 21. `style.css` 3101 行,变量系统是否真的统一?
**位置**: `style.css`

**修复建议**:
1. grep `--` 变量定义数量,确认是否有一致的设计 token
2. 重复的颜色值(例如 `rgba(0,0,0,0.08)`)应统一

---

### 22. 移动端体验差
**问题**: 整页基本无响应式。表格在窄屏上溢出但无横向滚动优化。

**修复**: 加 `@media (max-width: 720px) { ... }` 适配。

---

### 23. toast/alerts 系统不一致
**位置**: `js/ui_toast.js`,`js/render_tables.js`(showItemAlert),`js/render_charts.js`(showAlert)

**问题**: 同时存在 `showAlert`、`showItemAlert`、`showModal` — 一个简单消息竟然用 3 个 API。

**修复**: 统一为 `showToast(kind, msg)`。

---

### 24. 测试覆盖薄弱
**位置**: `tests/`

**现状**:
- `test_handlers.py`
- `test_import.py`
- `test_monthly_report.py`
- `test_sessions.py`
- `test_settings_init.py`

**问题**: 多个关键 handler(items lend/return, admin user CRUD, backup upload)没测试。前端零测试。

**修复**: 优先加:
1. `test_items_lend_return.py` — 借出/归还边界(超量、部分归还)
2. `test_admin_users.py` — RBAC 权限矩阵
3. `test_backup_restore.py` — ZIP 损坏、目录穿越、设置合并
4. `test_xss_escape.py` — 前后端 XSS 测试

---

### 25. 文档
**位置**: `README.md` (11KB)、`README.Docker.md` (6KB)

**问题**: 没有架构图、没有"代码导览"、没有"如何添加新报表"指南。

**修复**: 加 `docs/ARCHITECTURE.md`、`docs/ADDING_REPORTS.md`。

---

## 🎯 快速取胜(优先级排序实施清单)

| # | 改动 | 预计时间 | 价值 |
|---|------|----------|------|
| 1 | 给所有未 escape 的 innerHTML 加 `escapeHtml` | 1h | 防 XSS |
| 2 | 删 `handle_get_*_monthly` 死代码 | 10min | 减维护成本 |
| 3 | fcntl 加 try/except 兼容 Windows | 15min | 防崩溃 |
| 4 | 抽 `formatDate` 到 utils_helpers.js | 30min | 减 ~50 行重复 |
| 5 | `admin.py` 拆分为 4 个文件 | 2h | 减单文件体积 |
| 6 | 给 storage 缓存换 OrderedDict | 30min | 修复潜在 stale 数据 |
| 7 | 提取重复 inline style 到 CSS class | 1h | HTML 可读性 |
| 8 | 用 `check_delete_permission` 装饰器替换 `_check_delete` | 15min | 统一权限 |

---

## 📝 总结

项目整体**架构清晰**(handler 拆分、storage 抽象、permission 中间件),**安全基线合理**(PBKDF2、CSRF token、ZIP 防护、目录穿越检查),但有以下核心问题:

1. **XSS 是最大隐患**(P0,1h 内可修)
2. **admin.py 1162 行严重超标**(违反项目自身约定)
3. **跨文件隐式依赖**(没有 globals 文件或命名空间)
4. **死代码未清理**
5. **测试覆盖不足**(尤其是前端 XSS 风险)

修复这些后,项目会显著更安全、更易维护。
