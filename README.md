# 📊 电表统计 — Meter Stats

> 酒吧工程部电表统计工具。支持 4 表抄表、充值、月报、物品管理和三级权限。Docker 一键部署。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)

## 🚀 快速开始

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
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      - METER_PORT=8765
      - METER_DATA_DIR=/data
      - METER_BIND=0.0.0.0
      - METER_INITIAL_PASS=admin123
```

```bash
docker compose up -d
```

访问 **http://localhost:8765**，默认 `admin` / `admin123`（⚠️ 登录后立即修改密码）

### Docker Run

```bash
docker run -d --name meter-stats \
  -p 8765:8765 -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e METER_BIND=0.0.0.0 \
  -e METER_PORT=8765 \
  -e METER_INITIAL_PASS=your-password \
  --restart unless-stopped \
  zz3656/meter-stats:latest
```

### macOS 原生应用

```bash
./build-app.sh release --install
```

## 📋 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TZ` | `Asia/Shanghai` | 时区（POSIX 标准，支持所有 tzdata 时区名） |
| `METER_PORT` | `8765` | 服务端口 |
| `METER_DATA_DIR` | `/data` | 数据目录 |
| `METER_INITIAL_PASS` | `admin123` | 初始密码 |
| `METER_BACKUP_DIR` | `backup` | 备份目录（相对 `/data` 的相对路径，留空则默认 `/data/backup`） |

## ✨ 功能

⚡ 4 表抄表 | 💰 充值记录 | 📊 月报/年报 | 🔧 物品管理 | 📋 申购管理 | 🔐 三级权限 | 💾 自动备份 | 🎨 暗色主题 | 📥 CSV 导出

## 📦 技术

Python 3.11 · JSON 存储 · 零 pip 依赖 · ~92 MB · linux/amd64 + linux/arm64

## 📚 API

`/api/health` `/api/readings` `/api/charges` `/api/items` `/api/purchases` `/api/monthly-report` `/api/yearly-report` `/api/export` `/api/backup` `/api/restore` `/api/auth/login` `/api/admin/users`

## 🔄 升级

```bash
docker pull zz3656/meter-stats:latest
docker compose down && docker compose up -d
```

---

## 📸 界面预览

- 登录界面 — Linear 暗色风格
- 电表管理 — Tab 横排
- 月度报告 — 逐日逐表用电，支持 TSV 导出
- 管理后台 — 用户权限、电表参数配置

## 📂 项目结构

```
Sources/MeterStats/          # macOS 原生应用（Swift + Python）
docker/                   # Docker 部署（Web 版）
├── Dockerfile
├── docker-compose.yml
├── server.py
├── index.html + style.css + app.js
├── handlers/
└── utils/
tests/ · Scripts/ · Assets/
docker-compose.yml · docker-run.sh · README.Docker.md
build-app.sh · sign-and-notarize.sh · CONTRIBUTING.md · LICENSE
```

## 📖 数据模型

`readings.json` · `charges.json` · `items.json` · `purchases.json` · `settings.json`

## 🔒 安全

SHA-256 密码哈希 · 三级角色权限 · Session Token 认证 · 原子写入

## 🛠️ 开发者

```bash
python3 -m unittest discover -s tests -v   # 运行测试
./build-app.sh release --install           # macOS 打包
docker compose up -d --build               # Docker 开发
```

## 📝 故障排查

| 问题 | 解决 |
|---|---|
| 端口被占用 | 修改 docker-compose.yml 端口映射 |
| Docker 健康检查失败 | `docker inspect meter-stats | grep Health` |

## 🤝 贡献

欢迎提交 Issue 和 PR！[贡献指南](CONTRIBUTING.md) · [报告问题](https://github.com/meter-stats/meter-stats/issues)

## 📄 许可证

[MIT License](LICENSE)
