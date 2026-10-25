# 📊 工程部管理系统 — Meter Stats

> 面向酒吧工程部的电表数据管理工具。4 表抄表、充值、月度/年度报表、物品借还、申购、值班工作记录,支持字段级图片上传,三级权限。Docker 一键部署,浏览器直接访问。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Image Size](https://img.shields.io/docker/image-size/zz3656/meter-stats/latest?label=image%20size)](https://hub.docker.com/r/zz3656/meter-stats)
[![Platforms](https://img.shields.io/badge/platforms-linux%2Famd64%20%7C%20linux%2Farm64-brightgreen.svg)](https://hub.docker.com/r/zz3656/meter-stats)

---

## 🚀 快速开始

### Docker Compose(推荐)

```yaml
services:
  meter-stats:
    image: zz3656/meter-stats:latest
    container_name: meter-stats
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      - METER_PORT=8765
      - METER_DATA_DIR=/data
      - METER_DOCKER=1
      - METER_BIND=0.0.0.0
      - METER_INITIAL_PASS=admin123
```

```bash
docker compose up -d
```

访问 **http://localhost:8765**,默认账号 `admin` / `admin123`。

### Docker Run

```bash
docker run -d --name meter-stats -p 8765:8765 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai -e METER_INITIAL_PASS=your-password \
  --restart unless-stopped \
  zz3656/meter-stats:latest
```

---

## ✨ 核心功能

- ⚡ **抄表管理** — 4 块电表独立抄表,月底水电录入(总表/分表/水表)
- 💰 **充值记录** — 4 表分别充值,实时余量预警 + 建议充值金额
- 🧮 **充值计算器** — 按预充天数自动计算需充值表读数 + 金额
- 📊 **报表分析** — 每日趋势 / 月度报告 / 水电月报 / 年度汇总
- 📦 **物品借还** — 借出/归还流水,支持部分归还;借出人可填名字或直接传照片
- 🛒 **申购管理** — 申购 → 确认购买 → 自动入库(可选是否同时入库)
- 🔧 **值班工作记录** — 故障信息必填,支持文字 + 照片同时填写
- 🖼️ **图片上传** — 图片归到具体字段(借出人/归还人/申购名称/故障信息/处理方案),上传自动压缩,表格显示缩略图
- 🔐 **三级权限** — 员工 / 主管 / 管理员
- 💾 **自动备份** — 启动时 + 每日 0 点备份,按**保留个数**清理(默认最新 5 个),支持手动备份/恢复/下载

---

## 📋 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TZ` | `Asia/Shanghai` | 时区 |
| `METER_PORT` | `8765` | 服务端口 |
| `METER_BIND` | `0.0.0.0` | 监听地址 |
| `METER_DATA_DIR` | `/data` | 数据持久化目录 |
| `METER_DOCKER` | 自动检测 | 标记 Docker 环境(锁定备份/图片目录编辑) |
| `METER_INITIAL_ADMIN` | `admin` | 初始管理员用户名 |
| `METER_INITIAL_PASS` | `admin123` | 初始管理员密码(**首次生效**) |
| `METER_BACKUP_DIR` | `backup` | 备份目录(相对 `METER_DATA_DIR`) |
| `METER_IMAGE_DIR` | `images` | 图片目录(相对 `METER_DATA_DIR`) |

---

## 🔄 升级

```bash
docker compose down && docker compose up -d
```

---

## 📄 许可证

[MIT License](https://opensource.org/licenses/MIT)

## 更新历史

## 📦 工程部管理系统 v0.3.0

提交 `e095db1`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


模块化重构完成后的第一个稳定版本。侧栏、报表、设置、图片上传、备份系统全面重做，并修复了十几处重构过程中丢失的绑定与调用。

### 新增

**界面**

- 侧栏固定 12 项、四字命名：用电记录 / 物品记录 / 申购记录 / 工作记录 / 每日趋势 / 每周汇报 / 月度报告 / 年度汇总 / 用户管理 / 电表设置 / 数据管理 / 权限管理
- 用电记录合并为三 Tab：📝 抄表 / ⚡ 充值 / 💧 水电
- 四张报表页统一为「概况卡 + 图表 + 明细表」结构
- 系统设置拆成四页：用户管理 / 电表设置 / 数据管理 / 权限管理
- 顶部状态条只在「用电记录」页显示，其他页面隐藏
- 侧栏底部显示版本号 `v0.3.0`

**图片上传**

- 图片入口下沉到具体字段：借出人 / 归还人 / 申购物品名称 / 工作记录故障信息 / 处理方案
- 必填校验放宽为「文字或图片满足其一」，只传照片也能提交
- 工作记录新增「故障信息」必填字段（textarea），支持文字 + 图片同时填写，表格同步新增该列
- 申购新增弹窗只保留物品名称后一个图片入口，备注恢复纯文本
- 上传前自动压缩：最长边 1600px、JPEG 质量 0.82；小于 200KB 的原图跳过
- 文件名带来源前缀，便于在图片目录里区分：`lend-` / `return-` / `purchase-name-` / `purchase-note-` / `duty-note-` / `duty-handle-`，格式 `{scope}-{毫秒时间戳}{ext}`
- 表格对应列显示缩略图，点击可放大

**备份**

- 「备份与恢复」卡片合并为单一「保存」按钮，一次提交备份目录 + 保留个数
- 自动备份保留策略从「保留天数」改为「保留个数」，默认保留最新 5 个
- 修改保留个数后立即清理超出的旧备份，不用等下次备份
- 备份列表每项支持「⬇️ 下载」

**Docker**

- `docker/entrypoint.sh` 自动注入 `METER_DOCKER` / `METER_BACKUP_DIR` / `METER_IMAGE_DIR`
- Docker 环境下备份目录、图片目录由环境变量控制，UI 自动锁定并显示 `🔒` 提示

### 修复

**macOS 应用内图片选择完全无反应**

三层问题叠加，逐一修复：

1. `wv.uiDelegate = WebViewUIDelegate()` —— `uiDelegate` 和 `navigationDelegate` 都是 **weak** 引用，对象创建完当场释放变 nil。改用静态容器持有。
2. `PickFileHandler` 存了 `weak var webView`，注册时传 `nil`，`evaluateJavaScript` 从来没执行过（备份恢复桥也从没工作过）。改用 `message.webView`。
3. `<input type="file">` 在 WKWebView 里即便 delegate 接上也不可靠。

最终方案：**完全绕开 web 文件选择器**，所有 📷 走原生桥 `macOSPickImage` —— Swift 弹 `NSOpenPanel`、原生压缩、base64 回传，JS 转 File 上传。浏览器无此 handler 时自动回退到 `input.click()`，网页行为不变。

**备份与恢复**

- 自动备份开关 `settings.auto_backup` 没有任何代码读取，关掉也照样备份 → 现在两处备份线程都尊重该开关
- 「今天已备份就跳过」的判断看的是临时目录，而该目录打包完即删，导致每次启动都重做一遍 → 改判最终 ZIP
- 前端 `setBackupRetention` 传的参数名是 `retention_days`，后端读 `retention_count`，静默失败、永不生效 → 参数名对齐
- 「选择目录」按钮实际只把一个输入框 `display:block`，根本不弹面板；且 `BackupDirHandler` 同样中了 `weak var webView` 的坑 → 改走桥 `pickBackupDir`

**图片目录**

- `pickImageDirInput()` 往 `#image-dir-raw` 写值，而 HTML 里没有这个元素 → 一点就抛 `Cannot set properties of null`，按钮完全没反应
- 与备份卡片共用 `window.__backupDirChosen` 回调，互相覆盖 → 拆成独立的 `__imageDirChosen`，Swift 端用 `kind` 参数区分标题与回调
- 显示格式和按钮文案与备份卡片不一致 → 统一为 `📁 路径` + `📂 选择目录` / `保存`
- placeholder 原写「留空 = 默认」，但后端要求图片目录必须在数据目录内 → 文案修正

**其他重构回归**

- 弹窗取消/提交整段绑定丢失 → 新建 `js/modules/modal_bindings.js` 集中管理
- 模型名 `renderAll()` / `refreshAndRender()` 缺失
- 借还历史不显示 —— 记录挂在 `item.lend_records`，`refreshItems()` 漏调 `renderLendHistory()`
- 申购删除后不刷新表格
- 工作记录字段名与后端不符（`type` vs `duty_type`、`time` vs `record_time` 等）
- 物品列表 `limit=0` 被 `max(1, ...)` 强制成 1，导致「新增后看不到」
- 充值汇总恒为 0 —— 硬算当前自然月，改为按所选月份
- 每周汇报图表静默不渲染 —— `#chart-weekly-bar` 容器不存在
- 单个天数复制按钮未绑定事件
- 月度水电区块被误移出月报，已移回

### 变更

- 申购「购买」后同时保留两条记录：原申购记录置为 `purchased`（留档「申请过什么」），另新增 `kind='purchase'` 记录带 `ref_id`，仅勾选「同时添加到物品记录」才累加库存
- Docker 镜像基础环境不变，无需重建；`docker compose pull && docker compose up -d` 即可升级

### 已知限制

- macOS `.app` 为 ad-hoc 签名，未签名应用首次打开可能被 Gatekeeper 拦截，需 `xattr -dr com.apple.quarantine` 或右键 → 打开
- 单窗口截图 `screencapture -l <id>` 在部分 macOS 版本被拒，自动化测试只能用全屏截图 + 裁剪

---

### ⬆️ 升级

⚠️ **建议升级**:本次包含问题修复
- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

💡 [完整代码改动](https://github.com/zz3656/meter-stats/compare/v0.2.0...e095db1)

