# 📊 电表统计 — Meter Stats

> 面向酒吧工程部的电表数据管理工具。支持 4 表抄表、充值、月度/年度报表、物品借还、申购、值班工作记录，三级权限管理。Web、macOS、Docker 三端部署，开箱即用。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![Platforms](https://img.shields.io/badge/platform-web%20%7C%20macOS%20%7C%20docker-lightgrey.svg)](#-部署方式)

## ✨ 核心功能

| 模块 | 功能 |
|------|------|
| 📝 **抄表管理** | 4 块表(大厅/消防/包厢/空调)每日读数录入 + 月底水电录入(总表/分表/水表);自动计算日均用电与预计断电日期 |
| 💰 **充值管理** | 4 表分别充值记录;实时余量预警(按日均推算剩余天数 + 建议充值金额) |
| 📊 **报表分析** | 日报(每日用电趋势 + 当日占比)、月报(按日分表用电 + 当月占比)、水电月报、年报汇总;支持复制到剪贴板、导出 Word |
| 🧮 **充值计算器** | 按预充天数 × 本月日均,自动算出每块表需充值表读数 + 金额(实时联动) |
| 📦 **物品管理** | 工具/耗材登记、借出/归还流水;借出强制填借出人,归还支持部分归还 |
| 🛒 **申购管理** | 申购→确认购买→自动入库三步流程;跟踪待购/已购/已入库状态 |
| 🔧 **值班工作记录** | 类型(维修/更换/拆除)+ 故障区域 + 班次(白/中/夜班) + 处理状态(已处理/未处理);按月筛选 |
| 🔐 **三级权限** | 员工(读写)/ 主管(读+写+删)/ 管理员(全部 + 用户管理);SHA-256 密码 + Session Token |
| 💾 **数据备份** | 启动时每日自动备份(可配置保留天数 ZIP);支持手动备份/上传恢复/下载 |
| 🎨 **UI** | 浅色/深色/跟随系统三档主题;完整移动端响应式;侧栏分组 + 抽屉;弹窗底部 sheet |
| 📤 **导出** | CSV 导出(自定义列);月报 TSV 复制;Word 导出 |

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

```yaml
services:
  meter-stats:
    image: zz3656/meter-stats:latest
    container_name: meter-stats
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - ./data:/data       # 数据持久化目录
    environment:
      - TZ=Asia/Shanghai
      - METER_PORT=8765
      - METER_DATA_DIR=/data
      - METER_BIND=0.0.0.0
      - METER_INITIAL_PASS=admin123    # 首次登录密码(可改)
      - METER_BACKUP_DIR=backup        # 备份目录(相对数据目录,默认 backup)
      - METER_IMAGE_DIR=images         # 图片目录(相对数据目录,默认 images)
```

```bash
docker compose up -d
```

访问 **http://localhost:8765**,默认账号 `admin` / `admin123`(登录后立即在「系统设置 → 用户管理」修改密码)。

### 方式二：Docker Run

```bash
docker run -d --name meter-stats \
  -p 8765:8765 -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e METER_BIND=0.0.0.0 \
  -e METER_PORT=8765 \
  -e METER_INITIAL_PASS=your-password \
  -e METER_BACKUP_DIR=backup \
  -e METER_IMAGE_DIR=images \
  --restart unless-stopped \
  zz3656/meter-stats:latest
```

### 方式三：macOS 原生应用

从 [GitHub Releases](https://github.com/zz3656/meter-stats/releases) 下载最新 DMG,挂载后把 `MeterStats.app` 拖入「应用程序」。

> ⚠️ **关于首次打开被拦截**:未配置 Apple Developer ID 签名/公证时,应用是 ad-hoc 本地签名,首次打开 macOS 会提示「Apple 无法验证是否包含恶意软件」。**应用本身安全**,只需手动放行一次:
> 1. **右键点击应用 → 打开** → 弹窗中再点「打开」(最简单)
> 2. 或:系统设置 → 隐私与安全性 → 点「仍要打开」
> 3. 或终端:`xattr -dr com.apple.quarantine "/Applications/MeterStats.app"`
>
> 如需彻底免提示,需配置 Apple Developer ID 证书并走签名+公证流程(打 `v*` tag 自动执行)。

### 方式四：源码本地运行

```bash
# 要求 Python 3.9+(零 pip 依赖)
cd MeterStats
./run.sh    # 一键启动;数据写入 MeterStats/.data(已 gitignore)
```

## 📦 三端部署

| 端 | 入口 | 产物 | 适用 |
|---|---|---|---|
| 🌐 Web | `python3 server.py` | Docker 镜像 `zz3656/meter-stats` | 服务器/NAS / 远程访问 |
| 🍎 macOS | Swift + Python | `MeterStats.app` (DMG) | 工程部本地机 |
| 🐳 Docker | docker-compose | 多平台镜像 (amd64 + arm64) | 飞牛 OS / Linux 服务器 |

> macOS 应用其实是把 Python runtime 打包进 `.app` bundle 里的同一份后端,所以三端**共享同一份业务代码**(`MeterStats/` 下的 Python handlers)。

## 📋 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TZ` | `Asia/Shanghai` | 时区(POSIX 标准,支持所有 tzdata 时区名) |
| `METER_PORT` | `8765` | 服务端口 |
| `METER_BIND` | `0.0.0.0` | 监听地址(改成 `127.0.0.1` 仅本机访问) |
| `METER_DATA_DIR` | `/data` | 数据目录(Docker 推荐挂载到此路径) |
| `METER_INITIAL_PASS` | `admin123` | 初始 admin 密码(**首次启动生效**,之后改不生效) |
| `METER_INITIAL_ADMIN` | `admin` | 初始 admin 用户名 |
| `METER_BACKUP_DIR` | `backup` | 备份目录(相对 `METER_DATA_DIR` 的路径) |
| `METER_IMAGE_DIR`  | `images` | 图片目录(相对 `METER_DATA_DIR` 的路径,macOS 本地使用 settings.json 配置) |
| `METER_CORS_ORIGIN` | `http://localhost:8765` | 跨域来源(`*` 表示完全开放,适合 Docker / 远程访问) |

## 🔄 升级

```bash
# Docker 镜像升级
docker pull zz3656/meter-stats:latest
docker compose down && docker compose up -d
# 数据通过 ./data 持久化,升级不会丢失

# macOS 应用升级
# 从 GitHub Releases 下载新版 DMG 覆盖安装即可
```

## 🛠️ 技术

| 项 | 说明 |
|---|---|
| 后端 | Python 3.11 · 零 pip 依赖 · `http.server.ThreadingHTTPServer` |
| 存储 | JSON 文件 + 原子写入(临时文件 + rename) + 行级锁 |
| 前端 | 纯原生 HTML/CSS/JS(无构建步骤),Chart.js |
| macOS | Swift 5 + SwiftPM + 内嵌 Python runtime |
| CI/CD | GitHub Actions:`push main` 自动构建并推送 Docker 镜像;`push tag v*` 自动打包 DMG |

## 📂 项目结构

```
.
├── MeterStats/                  # 后端 + macOS bundle 内容(共享)
│   ├── handlers/                # API 路由处理
│   │   ├── _base.py             # JsonModelHandler 基类
│   │   ├── readings.py
│   │   ├── charges.py
│   │   ├── items.py
│   │   ├── purchases.py
│   │   ├── duty.py              # 值班录入
│   │   ├── admin.py
│   │   ├── backup.py
│   │   ├── reports.py
│   │   ├── settings.py
│   │   └── permissions.py
│   ├── utils/api.py             # send_json / read_body / CORS
│   ├── index.html               # SPA 入口(所有页面都在这里)
│   ├── app.js / admin.js        # 前端逻辑
│   ├── style.css                # 主题变量 + 响应式
│   ├── server.py                # 入口
│   ├── ServerManager.swift      # macOS 启动 Python 后端
│   └── ...
├── docker/                      # Docker 镜像构建
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── entrypoint.sh
│   └── .dockerignore
├── docker-compose.yml           # 项目根目录 compose(指向 docker/)
├── Package.swift                # SwiftPM 依赖(Chart.js 等)
├── .github/workflows/           # CI/CD
│   ├── docker-publish.yml       # push main → 自动构建并推送镜像
│   ├── sync-readme-to-dockerhub.yml  # push README → 自动同步到 DockerHub 描述
│   └── build-dmg.yml            # push tag v* → 自动打包 macOS DMG
├── tests/                       # 单元测试
├── Scripts/                     # 辅助脚本(图标生成等)
├── Assets/                      # macOS 应用图标资源
└── README.Docker.md             # Docker Hub 镜像描述(独立文件,sync workflow 读取)
```

## 📡 API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/snapshot` | **一次性返回所有数据**(前端启动用,5 次 GET → 1 次) |
| GET/POST | `/api/readings` | 抄表列表 / 新增抄表 |
| PUT/DELETE | `/api/readings/{date}` | 更新 / 删除某日抄表 |
| GET/POST/PUT/DELETE | `/api/charges` `/api/items` `/api/purchases` `/api/duty` | 同上模式 |
| PUT | `/api/items/{id}/lend` `/api/items/{id}/return` | 借出 / 归还物品 |
| PUT | `/api/purchases/{id}/stock` | 申购入库 |
| GET | `/api/monthly-report?month=2026-07` `/api/yearly-report?year=2026` | 报表 |
| GET | `/api/monthly-utilities?month=2026-07` | 水电月报 |
| GET | `/api/export?models=readings,charges,items,purchases` | CSV 导出 |
| POST | `/api/auth/login` `/api/backup` `/api/restore` `/api/upload` | 鉴权 / 备份 |
| GET/POST/PUT/DELETE | `/api/admin/users` `/api/admin/meter` `/api/admin/backup-config` | 管理后台 |

## 🔒 安全

- SHA-256 密码哈希(非明文)
- 三级角色权限(员工 / 主管 / 管理员)
- Session Token 认证(cookie + Bearer header)
- 原子写入(`tmp` + `rename`,崩溃不会损坏数据)
- 行级文件锁(`threading.Lock`,并发写安全)
- CORS 默认同源(`METER_CORS_ORIGIN=*` 才会放开)

## 🛠️ 开发者

```bash
# 单元测试
python3 -m unittest discover -s tests -v

# Docker 开发(本地重建镜像)
docker compose up -d --build

# macOS 打包
./build-app.sh release --install

# 提交规范:用约定式提交(feat / fix / refactor / docs / style)
# 仓库根目录的 .gitmessage 是 commit 模板,首次跑 ./MeterStats/run.sh 会自动设置
# 详细规范见 CONTRIBUTING.md § 提交规范
git commit  # 自动加载模板,提示 type/scope/影响范围
git commit -m "feat: 简述"  # 快速提交(跳过模板)
```

## 📝 故障排查

| 问题 | 解决 |
|------|------|
| 端口 8765 被占用 | `METER_PORT=8888` 修改环境变量 |
| Docker 容器健康检查失败 | `docker inspect meter-stats | grep Health -A 5` |
| 数据丢失 | Docker 用户从挂载目录 `./data` 恢复;本地用户从 `MeterStats/.data/backup/auto-bak-*.zip` 自动备份恢复 |
| macOS 应用「已损坏」 | 见 macOS 安装说明里的 `xattr -dr com.apple.quarantine` 命令 |
| 忘记密码 | 删除 `./data/settings.json` 容器重启(密码回到默认 `admin123`) |

## 🤝 贡献

欢迎提交 Issue 和 PR!详见 [贡献指南](CONTRIBUTING.md)。

## 📄 许可证

[MIT License](LICENSE)

---

**Made with ❤️ for 工程部 · 数据不撒谎**