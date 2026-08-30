# 📊 电表统计 — Meter Stats

> 面向酒吧工程部的电表数据管理工具。4 表抄表、充值、月度/年度报表、物品借还、申购、值班工作记录,三级权限。Docker 一键部署,浏览器直接访问。

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
      - METER_BIND=0.0.0.0
      - METER_INITIAL_PASS=admin123
```

```bash
docker compose up -d
```

### Docker Run

```bash
docker pull zz3656/meter-stats:latest

mkdir -p data

docker run -d \
  --name meter-stats \
  -p 8765:8765 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e METER_BIND=0.0.0.0 \
  -e METER_INITIAL_PASS=your-secure-password \
  --restart unless-stopped \
  zz3656/meter-stats:latest
```

访问 **http://localhost:8765**,默认账号 `admin` / `admin123`(登录后请立即在「系统设置 → 用户管理」修改密码)。

---

## ✨ 核心功能

- ⚡ **抄表管理** — 4 块电表独立抄表(大厅/消防/包厢/空调),月底水电录入(总表/分表/水表)
- 💰 **充值记录** — 4 表分别充值,实时余量预警 + 建议充值金额
- 🧮 **充值计算器** — 按预充天数 × 本月日均,自动算出每块表需充值表读数 + 金额
- 📊 **报表分析** — 每日趋势(当日占比)、月度报告(当月占比)、水电月报、年度汇总,支持 TSV 复制 / CSV 导出
- 📦 **物品借还** — 借出强制填借出人,归还支持部分归还,流水完整留痕
- 🛒 **申购管理** — 申购→确认购买→自动入库三步流程
- 🔧 **值班工作记录** — 类型(维修/更换/拆除)+ 故障区域 + 班次 + 处理状态
- 🔐 **三级权限** — 员工 / 主管 / 管理员,SHA-256 密码哈希 + Session Token
- 💾 **自动备份** — 启动时每日备份,可配置保留天数 ZIP
- 🎨 **完整 UI** — 浅/深色主题切换,移动端响应式,弹窗底部 sheet
- 📤 **导出** — CSV / TSV / Word,自定义列

---

## 📋 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TZ` | `Asia/Shanghai` | 时区(POSIX 标准,支持所有 tzdata 时区名) |
| `METER_PORT` | `8765` | 服务端口 |
| `METER_BIND` | `0.0.0.0` | 监听地址(`127.0.0.1` 仅本机访问) |
| `METER_DATA_DIR` | `/data` | 数据持久化目录(Docker 推荐挂载到此路径) |
| `METER_INITIAL_ADMIN` | `admin` | 初始管理员用户名(**首次启动生效**) |
| `METER_INITIAL_PASS` | `admin123` | 初始管理员密码(**首次启动生效,之后改不生效**) |
| `METER_BACKUP_DIR` | `backup` | 备份目录(相对 `METER_DATA_DIR` 的相对路径) |
| `METER_CORS_ORIGIN` | `http://localhost:8765` | 跨域来源(`*` 完全开放,适合 Docker / 远程访问) |

---

## 💾 数据持久化

数据存储在容器 `/data` 目录,务必挂载到宿主机:

| 挂载示例 | 用途 |
|---------|------|
| `-v $(pwd)/data:/data` | 宿主当前目录 `data/` 子目录 |
| `-v meter-data:/data` | Docker 命名 volume(推荐生产环境) |

数据文件:

| 文件 | 说明 |
|------|------|
| `readings.json` | 抄表记录(日期、各表读数、水电) |
| `charges.json` | 充值记录 |
| `items.json` | 物品库存(含 lend_records 借出流水) |
| `purchases.json` | 申购记录 |
| `duty.json` | 值班工作记录 |
| `settings.json` | 用户/电表参数/系统配置 |
| `backup/auto-bak-*.zip` | 自动备份(每日一次,可配置保留天数) |

**升级镜像不会丢失数据**,只要挂载目录不丢。

---

## 🔄 升级

```bash
docker pull zz3656/meter-stats:latest
docker compose down && docker compose up -d
```

---

## 🏗️ 架构

```
浏览器(PC/手机/平板)
    ↓ HTTP :8765
容器内 Python http.server
    ↓ 读写
/data (挂载到宿主)
    ↓ JSON 文件
    每日启动时打包 → backup/auto-bak-YYYYMMDD.zip
```

- **后端**:Python 3.11 标准库 + `http.server.ThreadingHTTPServer`,**零 pip 依赖**
- **前端**:纯 HTML + CSS + JS,单文件 SPA,**无构建步骤**
- **存储**:JSON 文件 + 原子写入(临时文件 + rename)
- **镜像大小**:~92 MB

---

## 📡 API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/snapshot` | 一次性返回所有数据 |
| GET/POST/PUT/DELETE | `/api/readings` `/api/charges` `/api/items` `/api/purchases` `/api/duty` | 5 大数据模型 CRUD |
| PUT | `/api/items/{id}/lend` `/api/items/{id}/return` | 借出 / 归还物品 |
| PUT | `/api/purchases/{id}/stock` | 申购入库 |
| GET | `/api/monthly-report?month=2026-07` `/api/yearly-report?year=2026` | 报表 |
| GET | `/api/monthly-utilities?month=2026-07` | 水电月报 |
| GET | `/api/export?models=readings,charges,items,purchases` | CSV 导出 |
| POST | `/api/auth/login` `/api/backup` `/api/restore` | 鉴权 / 备份 |
| GET/POST/PUT/DELETE | `/api/admin/users` `/api/admin/meter` `/api/admin/backup-config` | 管理后台 |

---

## 🛡️ 安全建议

1. **修改默认密码** — 用 `METER_INITIAL_PASS` 自定义
2. **限制访问** — 防火墙 / VPN / Nginx 反向代理 + SSL
3. **定期备份** — `docker compose exec meter-stats cat /data/backup/auto-bak-YYYYMMDD.zip > backup.zip`
4. **忘记密码恢复** — 删 `data/settings.json` 后重启容器,密码回到 `admin123`

---

## ❓ 故障排查

| 问题 | 解决 |
|------|------|
| 端口 8765 被占用 | 修改 `docker-compose.yml` 端口映射 |
| 容器启动失败 | `docker logs meter-stats` 查看日志 |
| 数据丢失 | 检查挂载的 `./data/backup/`,用 API `/api/restore` 恢复 |
| 健康检查失败 | `docker inspect meter-stats \| grep Health -A 5` |
| 健康检查超时 | 镜像拉取后首次启动慢(健康检查默认 `start_period: 30s`),稍等即可 |
| macOS 应用被拦截(非 Docker 用户参考) | `xattr -dr com.apple.quarantine "/Applications/MeterStats.app"` |

---

## 📂 多端支持

| 端 | 说明 |
|---|---|
| 🐳 **Docker** | 本镜像,服务器 / NAS / 远程访问首选 |
| 🍎 **macOS** | GitHub Releases 下载 DMG(打 `v*` tag 自动构建) |
| 🌐 **源码** | `python3 server.py`,零依赖 |

---

## 📄 许可证

[MIT License](https://opensource.org/licenses/MIT)

---

**项目仓库**: [github.com/zz3656/meter-stats](https://github.com/zz3656/meter-stats) · 欢迎 ⭐ 和提交 Issue / PR