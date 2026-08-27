# 📊 林卡电表统计 — Linclub Electricity Stats

> 酒吧 / 场所工程部电表用量统计工具。支持 4 块电表独立抄表、充值记录、月度/年度报告、物品申购管理和三级用户权限。Docker 容器化部署，浏览器直接访问。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![Image Size](https://img.shields.io/docker/image-size/zz3656/linclub-electricity-stats/latest?label=image%20size)](https://hub.docker.com/r/zz3656/linclub-electricity-stats)
[![Platforms](https://img.shields.io/badge/platforms-linux%2Famd64%20%7C%20linux%2Farm64-brightgreen.svg)](https://hub.docker.com/r/zz3656/linclub-electricity-stats)

---

## ✨ 功能特性

| 功能 | 说明 |
|---|---|
| ⚡ 电表管理 | 4 块电表独立抄表读数（大厅 / 消防 / 包厢 / 空调） |
| 💰 充值记录 | 按表充值，支持备注，余额统计 |
| 📊 月度报告 | 逐日逐表用电计算，自动分摊区间 |
| 📅 年度汇总 | 12 个月数据汇总，一目了然 |
| 🔧 物品管理 | 库存 CRUD，实时库存跟踪 |
| 📋 申购管理 | 申购 → 入库完整流转 |
| 🔐 用户权限 | 管理员 / 主管 / 员工三级权限 |
| 💾 自动备份 | 每日自动备份数据（只加不删） |
| 🎨 暗色主题 | Linear.app 风格，护眼光线 |
| 📥 CSV 导出 | 支持按模型导出 CSV |

---

## 🚀 快速开始

### 方式一：Docker Run

```bash
docker pull zz3656/linclub-electricity-stats:latest

# 1. 先创建数据目录
mkdir -p data

# 2. 启动容器（数据存放在当前目录下的 data/）
docker run -d \
  --name linclub \
  -p 8765:8765 \
  -v $(pwd)/data:/data \
  -e LINCLUB_INITIAL_PASS=your-secure-password \
  --restart unless-stopped \
  zz3656/linclub-electricity-stats:latest
```

### 方式二：Docker Compose（推荐）

```yaml
services:
  linclub:
    image: zz3656/linclub-electricity-stats:latest
    container_name: linclub
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      # ⬇️ 数据持久化目录，可自行修改路径
      - ./data:/data
    environment:
      - LINCLUB_PORT=8765
      - LINCLUB_DATA_DIR=/data
      - LINCLUB_BIND=0.0.0.0
      - LINCLUB_INITIAL_PASS=admin123
```

保存为 `docker-compose.yml` 后运行：

```bash
docker compose up -d
```

打开浏览器访问 **http://localhost:8765**，默认登录：`admin` / `admin123`（⚠️ 请登录后立即修改密码）

---

## 📋 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LINCLUB_PORT` | `8765` | 服务端口 |
| `LINCLUB_DATA_DIR` | `/data` | 数据持久化目录 |
| `LINCLUB_BIND` | `0.0.0.0` | 绑定地址 |
| `LINCLUB_INITIAL_ADMIN` | `admin` | 初始管理员用户名 |
| `LINCLUB_INITIAL_PASS` | `admin123` | 初始管理员密码 |
| `LINCLUB_BACKUP_DIR` | `backup` | 备份目录（相对 `/data` 的相对路径，留空则默认 `/data/backup`） |

---

## 🖥️ 架构

```
┌──────────┐         ┌────────────────────────┐
│ 浏览器   │ ──────→ │  Python HTTP Server    │
└──────────┘  8765   │  /data (JSON 存储)     │
                      └────────────────────────┘
```

- **前端**：纯 HTML + CSS + JS，零框架依赖，单文件即可部署
- **后端**：Python 3 `http.server` 标准库，零 pip 依赖
- **存储**：JSON 文件原子写入（写临时文件 → rename）
- **安全**：非 root 用户运行，SHA-256 密码哈希，Session Token 认证

---

## 📦 技术栈

| 层 | 技术 |
|---|---|
| 运行环境 | Python 3.11-slim |
| 镜像大小 | ~92 MB |
| 多平台 | linux/amd64 + linux/arm64 |
| 存储 | JSON（原子写入 + 每日自动备份） |
| 网络 | HTTP REST API + 静态文件服务 |

---

## 📚 API 参考

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

---

## 💾 数据持久化

数据存储在 Docker Volume `/data` 中，包含：

| 文件 | 说明 |
|---|---|
| `readings.json` | 抄表记录（日期、各表读数、备注） |
| `charges.json` | 充值记录（日期、各表金额、备注） |
| `items.json` | 物品库存（名称、数量、单位） |
| `purchases.json` | 申购记录（名称、数量、状态、入库） |
| `settings.json` | 系统配置（用户、电表参数、价格） |

**自动备份**：每次启动时备份到 `/data/backup/YYYYMMDD/`（同一天只备份一次）

---

## 🔄 升级

```bash
# 拉取最新镜像
docker pull zz3656/linclub-electricity-stats:latest

# 重启容器
docker compose down
docker compose up -d

# 数据不会丢失（存储在 Volume 中）
```

---

## 🛡️ 安全建议

1. **修改默认密码** — 使用 `LINCLUB_INITIAL_PASS` 环境变量
2. **修改端口** — 如果 8765 被占用，修改 `-p` 参数
3. **限制访问** — 使用防火墙或 VPN 限制 IP
4. **定期备份** — `docker compose exec linclub tar czf /backup.tar.gz -C /data .`
5. **启用 HTTPS** — 通过 Nginx 反向代理 + SSL 证书

---

## ❓ 故障排查

| 问题 | 解决 |
|---|---|
| 端口被占用 | 修改 `docker-compose.yml` 中的端口映射 |
| 容器启动失败 | 执行 `docker logs linclub` 查看日志 |
| 数据丢失 | 检查 `/data/backup/` 目录，使用 API 恢复 |
| 健康检查失败 | `docker inspect linclub | grep Health` |

---

## 📄 许可证

[MIT License](https://opensource.org/licenses/MIT)

---

**项目仓库**: GitHub · 欢迎 Star 和提交 Issue / PR
