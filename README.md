# 林卡电表统计 — Linca Electricity Stats

> 酒吧/场所工程部电表用量统计工具。支持 macOS 原生桌面应用和 Docker Web 服务两种部署方式。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![macOS](https://img.shields.io/badge/macOS-14+-000000?logo=apple)](https://www.apple.com/macos/)
[![Docker](https://img.shields.io/badge/Docker-Compose-ready-blue.svg)](https://www.docker.com/)

## ✨ 功能特性

| 功能 | 说明 |
|---|---|
| ⚡ 电表管理 | 4 块电表独立抄表读数（大厅/消防/包厢/空调） |
| 💰 充值记录 | 按表充值，支持备注 |
| 🧾 月度报告 | 逐日逐表用电计算，自动分摊区间 |
| 📊 年度汇总 | 12 个月数据汇总 |
| 🔧 物品管理 | 库存 CRUD |
| 📋 申购管理 | 申购 → 入库流转 |
| 🔐 用户权限 | 管理员 / 主管 / 员工三级权限 |
| 💾 自动备份 | 每日自动备份数据文件（只加不删） |
| 🎨 Linear 暗色主题 | 参考 Linear.app 的设计系统 |
| 📥 CSV 导出 | 支持按模型导出 CSV |

## 🚀 快速开始

### 方式一：Docker 部署（推荐 — 跨平台，无需 macOS）

```bash
# 启动
git clone https://github.com/linclub/linclub-electricity-stats.git
cd linclub-electricity-stats
docker compose up -d

# 访问 http://localhost:8765
# 默认管理员: admin / admin123（⚠️ 请登录后立即修改密码）
```

详细文档：[README.Docker.md](README.Docker.md)

### 方式二：macOS 原生应用

```bash
# 需要 macOS 14+、Xcode 16+、Python 3（系统自带）

# Build + 安装到 ~/Applications
./build-app.sh release --install

# 双击 ~/Applications/工程部管理系统.app 即可使用
```

详细文档见下方「开发者指南」。

## 📸 界面预览

- 登录界面 — 简洁的 Linear 暗色风格
- 电表管理 — Tab 横排（⚡ 电表 / 🔧 物品 / 📚 历史）
- 月度报告 — 逐日逐表用电，支持 TSV 导出到 Excel
- 管理后台 — 用户权限管理、电表参数配置

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────┐
│  macOS 原生应用（双击 .app）                              │
│  ┌──────────────┐    ┌──────────────────────────────┐   │
│  │ SwiftUI+WK   │ →→ │  Python HTTP Server          │   │
│  │ WebView 渲染  │    │  port 8765 · JSON 文件存储   │   │
│  └──────────────┘    └──────────────────────────────┘   │
│                                          ↓              │
│                          ~/Library/Application Support/   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Docker 部署（浏览器访问）                                │
│  ┌──────────────┐    ┌──────────────────────────────┐   │
│  │ 浏览器       │ →→ │  Python HTTP Server          │   │
│  │ 直接访问     │    │  port 8765 · Docker Volume   │   │
│  └──────────────┘    └──────────────────────────────┘   │
│                                          ↓              │
│                          /data (Docker Volume)            │
└─────────────────────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 |
|---|---|
| 前端 UI | SwiftUI + WKWebView（macOS 版）/ 浏览器（Docker 版） |
| 前端页面 | 纯 HTML + CSS + JS（零依赖，单文件部署） |
| 后端 | Python 3 `http.server`（标准库，零 pip 依赖） |
| 数据存储 | JSON 文件（原子写入，自带每日备份） |
| macOS 打包 | Swift Package Manager |
| Docker | Python 3.11-slim |

## 📂 项目结构

```
.
├── Sources/Linca/              # macOS 原生应用（Swift + Python）
│   ├── LincaApp.swift          SwiftUI 入口 + WKWebView
│   ├── ServerManager.swift     Python 子进程管理
│   └── Resources/              Python 后端 + 前端静态文件
│       ├── server.py           HTTP 服务入口
│       ├── app_handler.py      请求处理 + 静态文件
│       ├── storage.py          JSON 读写 + 备份
│       ├── routing.py          API 路由
│       ├── report.py           月报/年报引擎
│       ├── index.html          前端页面
│       ├── style.css           样式（Linear 暗色风格）
│       ├── app.js              前端逻辑
│       ├── admin.js            管理后台
│       ├── handlers/           各模块 API handler
│       └── utils/              工具函数
├── docker/                     # Docker 部署（Web 版）
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── server.py               Docker 适配入口
├── tests/                      # 回归测试
├── Scripts/                    # 辅助脚本
├── Assets/                     # App 图标资源
├── build-app.sh                macOS .app 打包脚本
├── sign-and-notarize.sh        Developer ID 签名 + 公证
├── docker-compose.yml          Docker Compose（快捷入口）
├── docker-run.sh               Docker 快捷启动脚本
├── README.Docker.md            Docker 部署文档
├── CONTRIBUTING.md             贡献指南
├── LICENSE                     MIT License
└── README.md                   本文档
```

## 📚 数据模型

```
readings.json    抄表读数（date, hall, fire, private_room, ac, main_meter, sub_meter, water, note）
charges.json     充值记录（id, date, hall, fire, private_room, ac, note）
items.json       物品库存（id, name, qty, unit, note, created_at）
purchases.json   申购记录（id, date, name, qty, unit, est_price, supplier, status, note）
settings.json    系统设置（users, meter, config）
```

## 📖 用户手册

### macOS 应用部署

1. Build：`./build-app.sh release --install`
2. 首次启动：右键 `.app` → **打开**（绕过 ad-hoc 签名警告）
3. 日常使用：双击 `.app` → 自动启动后端 → 弹出窗口
4. 卸载：拖到垃圾桶（数据保留在 Application Support）
5. 数据位置：`~/Library/Application Support/com.linca.electricity-stats/`

### Docker 应用部署

1. 启动：`docker compose up -d`
2. 访问：http://localhost:8765
3. 停止：`docker compose down`
4. 查看日志：`docker compose logs -f`

### 数据备份

- **自动备份**：每次启动时备份到 `backup/YYYYMMDD/`（同一天只备一次）
- **手动备份**：通过 API `POST /api/backup`
- **数据恢复**：通过 API `POST /api/restore`
- **Docker 备份**：`docker compose exec linca tar czf /tmp/backup.tar.gz -C /data .`

### API 参考

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/readings` | 抄表列表 |
| POST | `/api/readings` | 新增抄表 |
| PUT | `/api/readings/{date}` | 更新抄表 |
| DELETE | `/api/readings/{date}` | 删除抄表 |
| GET | `/api/charges` | 充值列表 |
| POST | `/api/charges` | 新增充值 |
| GET | `/api/items` | 物品列表 |
| POST | `/api/items` | 新增物品 |
| GET | `/api/purchases` | 申购列表 |
| GET | `/api/monthly-report?month=YYYY-MM` | 月报 |
| GET | `/api/yearly-report?year=YYYY` | 年报 |
| GET | `/api/export?models=readings,charges` | CSV 导出 |
| POST | `/api/backup` | 手动备份 |
| POST | `/api/restore` | 数据恢复 |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/admin/users` | 用户管理 |

## 🔒 安全

- 用户密码使用 SHA-256 哈希存储
- 三级角色权限（管理员 / 主管 / 员工）
- Session Token 认证
- CORS 配置（可自定义来源）
- 所有数据写入使用原子操作（写临时文件 → rename）

## 🛠️ 开发者指南

### 前置条件

- macOS 14+（原生应用）/ 任意平台（Docker）
- Swift 5.9+ / Xcode 16+（macOS 应用）
- Python 3.10+（零第三方依赖）
- Docker + Docker Compose（Docker 部署）

### 运行测试

```bash
python3 -m unittest discover -s tests -v
```

### macOS 打包

```bash
# 仅 build
./build-app.sh release

# Build + 安装
./build-app.sh release --install

# Developer ID 签名 + 公证
./sign-and-notarize.sh "Developer ID Application: Your Name (TEAMID)"
```

### Docker 开发

```bash
# 重新构建
docker compose up -d --build

# 进入容器调试
docker compose exec linca bash

# 快捷脚本
./docker-run.sh up | down | logs | rebuild | status
```

## 📝 故障排查

| 问题 | 解决 |
|---|---|
| Docker 端口被占用 | 修改 `docker-compose.yml` 的端口映射 |
| 首次启动无法验证开发者 | macOS 右键 `.app` → 打开 |
| 后端启动超时 | 查看 `logs/server.log` |
| 数据不显示 | 检查 `backup/` 目录可恢复 |
| Docker 健康检查失败 | `docker inspect linca | grep Health` |

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

- [贡献指南](CONTRIBUTING.md) — 开发流程与代码规范
- [报告问题](https://github.com/linclub/linclub-electricity-stats/issues) — Bug 和功能建议

## 📄 许可证

[MIT License](LICENSE) — 自由使用、修改、分发
