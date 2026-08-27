# 📊 电表统计 — Meter Stats

> 酒吧 / 场所工程部电表用量统计工具。支持 4 块电表独立抄表、充值记录、月度/年度报告、物品申购管理和三级用户权限。Docker 容器化部署，浏览器直接访问。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)

---

## ✨ 功能特性

| 功能 | 说明 |
|---|---|
| ⚡ 电表管理 | 4 块电表独立抄表读数（大厅 / 消防 / 包厢 / 空调） |
| 💰 充值记录 | 按表充值，支持备注，余额统计 |
| 📊 月度报告 | 逐日逐表用电计算，自动分摊区间 |
| 📅 年度汇总 | 12 个月数据汇总 |
| 🔧 物品管理 | 库存 CRUD，实时库存跟踪 |
| 📋 申购管理 | 申购 → 入库完整流转 |
| 🔐 用户权限 | 管理员 / 主管 / 员工三级权限 |
| 💾 自动备份 | 每日自动备份数据（只加不删） |
| 🎨 暗色主题 | Linear.app 风格 |
| 📥 CSV 导出 | 支持按模型导出 CSV |

---

## 🚀 快速开始

### Docker Run

```bash
docker pull zz3656/meter-stats:latest

docker run -d \
  --name meter-stats \
  -p 8765:8765 \
  -v meter-data:/data \
  -e METER_INITIAL_PASS=your-secure-password \
  -e TZ=Asia/Shanghai \
  --restart unless-stopped \
  zz3656/meter-stats:latest
```

### Docker Compose（推荐）

```yaml
services:
  meter-stats:
    image: zz3656/meter-stats:latest
    container_name: meter-stats
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - meter-data:/data
    environment:
      - METER_PORT=8765
      - METER_DATA_DIR=/data
      - METER_BIND=0.0.0.0
      - METER_INITIAL_PASS=admin123
volumes:
  meter-data:
    driver: local
```

```bash
docker compose up -d
```

打开浏览器访问 **http://localhost:8765**，默认登录：`admin` / `admin123`（⚠️ 请登录后立即修改密码）

---

## 📋 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `METER_PORT` | `8765` | 服务端口 |
| `METER_DATA_DIR` | `/data` | 数据持久化目录 |
| `METER_BIND` | `0.0.0.0` | 绑定地址 |
| `METER_INITIAL_ADMIN` | `admin` | 初始管理员用户名 |
| `METER_INITIAL_PASS` | `admin123` | 初始管理员密码 |

---

## 📦 技术栈

| 层 | 技术 |
|---|---|
| 运行环境 | Python 3.11-slim |
| 镜像大小 | ~92 MB |
| 多平台 | linux/amd64 + linux/arm64 |
| 存储 | JSON（原子写入 + 每日自动备份） |

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

数据存储在 Docker Volume `/data` 中，包含 `readings.json`、`charges.json`、`items.json`、`purchases.json`、`settings.json`。

**自动备份**：每次启动时备份到 `/data/backup/YYYYMMDD/`（同一天只备份一次）

---

## 🔄 升级

```bash
docker pull zz3656/meter-stats:latest
docker compose down
docker compose up -d
```

---

## 📄 许可证

[MIT License](https://opensource.org/licenses/MIT)
