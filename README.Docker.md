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
docker compose pull && docker compose up -d
```

> **为什么不能只写 `docker compose up -d`？**
> Docker **从不会主动检查远端仓库有没有新镜像**。只要本地已经存在 `zz3656/meter-stats:latest`
> 这份镜像,`up -d` 就会直接拿本地这份用,既不提示、也不拉取——所以你看不到"有新版本"的提示。
> 只有显式 `pull` 才会去比对仓库里的 digest 并下载新镜像,`up -d` 随后发现镜像 ID 变了会自动重建容器。
> 过去常见的"先 `docker rmi` 删掉本地镜像再 `up`" 之所以有效,是因为删掉之后本地没有了,
> `up` 才会被动去拉——但那不是必要步骤,直接 `pull` 就行。
>
> 数据存放在挂载卷里,升级不会丢失。升级后需重新登录一次(会话在服务端内存,重启即失效)。
>
> 想确认当前跑的是哪个版本:
> ```bash
> curl -s http://localhost:8765/api/version    # → {"version":"0.4.2"}
> ```
> 镜像同时推送了 `latest` 与 `0.4.x` 两个标签(同一 digest),需要锁定版本时把 compose 里的
> `image:` 改成 `zz3656/meter-stats:0.4.2` 即可。

一键升级(含更新前后版本对比,兼容 `docker compose` v2 与 `docker-compose` v1):

```bash
bash scripts/docker-update.sh          # 在仓库根目录执行
bash scripts/docker-update.sh docker/docker-compose.yml   # 指定 compose 文件
```

---

## 📄 许可证

[MIT License](https://opensource.org/licenses/MIT)

## 更新历史

## 📦 工程部管理系统 v0.4.2

提交 `47783fb`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


前端实时刷新三连修 + NAS 同步鉴权改造。全部是修复类改动，无破坏性变更。

### 新增

- **NAS 同步支持远端鉴权**：远端从 v0.4.1 起所有 `/api/*` 强制会话，原来的代理裸请求 `/api/admin/data-files` 必然 401。现在本机保存远端账号密码，代理先登录换 token、再带 `Authorization: Bearer` 拉取。新增 `GET/PUT /api/admin/nas-config`（主管及以上）读写凭据：GET 只回 `nas_pass_set` 布尔值、绝不回传密码；PUT 的 `nas_pass` 不传＝保持原值、空串＝明确清除。密码明文存于本机 `settings.json`，但已被 `_BACKUP_EXCLUDED_SETTINGS_KEYS` 排除，不会进备份 ZIP
- **Docker 镜像内含版本号**：`Dockerfile` 把 `MeterStats/VERSION` 复制进镜像，`server.py` 启动时读取并经公开接口 `GET /api/version` 暴露（登录页底部与侧栏都会显示）。CI 同时推送 `latest` 与 `0.4.x` 两个标签，二者指向同一 digest
- **Docker 一键升级脚本**：`scripts/docker-update.sh` —— 拉取新镜像、重建容器，并打印更新前后的版本号对比；兼容 `docker compose`（v2）与 `docker-compose`（v1，DSM 6/7.0）

### 修复

- **余量预警卡不实时刷新**：`renderChargeAlert()` 只在 `renderAll()` 里被调用，而录入/修改/删除抄表、确认充值走的都是 `refreshAndRender()` → 数据更新了但卡片没重绘，表现为「已录入今日抄表，『含 N 度已到账未抄表』的绿色提示却不消失」。已在 `refreshAndRenderTables()` 同步 `CURRENT_*` 之后重绘预警卡
- **「每日趋势」页永远显示空态、概况卡全空**：`renderTrendChart()` 的空态分支用 `ctx.canvas.parentElement.innerHTML = …` 渲染空态，把整个 `<canvas id="chart-trend">` 从 DOM 里**永久删掉**；之后每次调用都在下一行 `getContext` 处抛 `TypeError(null.getContext)`，而调用方（`renderAll` / `_afterSectionShown`）都用 `try/catch` 静默吞掉，所以控制台一片干净、页面却是坏的。触发条件正是 App 重启后首屏 snapshot 401 → `renderAll()` 带着空数组调用 → canvas 当场被删，登录后再也回不来。现在 canvas 与空态节点并存、只切换显隐，canvas 缺失时可自愈重建
- **抄表列表月份下拉与表格内容对不上**：`renderAll()` 首屏先渲染表格（第 2 步）、后填月份下拉（第 6 步），表格过滤读到的是空值 → 不过滤 → 渲染出**所有月份**的记录；下拉随后被填成 2026-11，表格却没跟着重绘。现在 `refreshMonthSelectors()` 填完 `#record-month` 立即重绘三张表
- **水电迁移提示整条链路是死的**：`reports.js` 调用 `Api.adminTools.migrateWaterStatus()` / `Api.adminTools.migrateWater()`，而 `Api.adminTools` 对象根本不存在（2026-10-24 模块化重构遗留），每次页面加载抛 TypeError。已改到 `Api.migrate.*`
- **NAS 同步一次就把远端凭据冲掉**：`handle_post_sync_from_nas` 的 `settings.json` 分支原本整份覆盖，而远端并不知道本机的 `nas_sync_*` / `backup_dir` 字段 → 同步一次凭据即失效。改为走 `_merge_settings_after_restore()` 合并
- **NAS 同步后读到旧数据**：同步写入后失效 storage 文件缓存与月报缓存

### 调整

- **Docker 升级方式纠正**：README.Docker.md / README.md 原写 `docker compose down && docker compose up -d`，这**不会拉取新镜像** —— 本地已有镜像时 Docker 不会去查仓库，这就是「镜像没有新版本提示」的根源。正确姿势是 `docker compose pull && docker compose up -d`
- 根 `docker-compose.yml` 的头部注释与实际 image 标签对齐（该文件用的是本地构建标签 `meter-stats:local`，不是 `latest`）

### 文档

- 新增 `tests/test_nas_sync.py`（18）、`tests/test_alert_refresh.py`（3）、`tests/test_frontend_refresh.py`（7），全量 **147 项**

### ⬆️ 升级

- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

**Full Changelog**: https://github.com/zz3656/meter-stats/compare/v0.4.1...v0.4.2

