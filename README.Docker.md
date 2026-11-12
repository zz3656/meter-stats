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

## 📦 工程部管理系统 v0.4.3

提交 `a45dcbc`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


### 修复

- **把抄表读数误填进充值栏，会把所有用电统计顶飞**（实测事故 2026-11-11）：`charges.json` 里多了一条 `date=2026-11-11` 的充值记录，四个数 `205.7 / 1706.5 / 197.6 / 138.9` **正好是当天的抄表读数**。系统照单全收，按「预付费表表底下降=用电、上升=刚到账」的口径把这笔「充值」算进了 11-11 → 11-12 区间 —— 大厅凭空多出 205.7 × 160 = **32912 度**，「每日趋势」页复制出去的单天用电变成 **89588.8 度 / ¥80629.92**（真实 1130.3 度 / ¥1017.27），2026-11 月报被顶到 **102700.7 度**（真实 14242.2 度）。物理上这笔钱不可能到账：205.7 表字若在 11-11 进表，11-12 表底应是 205.7 + 205.7 − 3.4 ≈ 408，实际抄到的是 202.3 —— 表底不升反降，钱根本没进表

  新增三条防线（前后端同一套规则）：

  1. **录入即拦截**：`POST /api/charges` / `PUT /api/charges/{id}` / 确认到账前，先拿当前抄表复核 —— 充值额和当天抄表读数一模一样（八成是抄错了栏），或归属区间的用电量离谱到超过该表历史日均 3 倍，直接 400 拒绝并提示「是不是把抄表读数填进充值栏了」。前端 `submitChargeAdd()` 也先自查，用弹窗给出可读的原因
  2. **统计自动排除**：与抄表对不上的充值不计入用电量，并在月报结果里带出 `conflicts` 供界面提示；「每日趋势」页单天复制出来的文本会追加一行 ⚠️ 提醒去「用电记录 → 充值」核对删除
  3. **余量预警同步排除**：钱没进表的充值不再算进表显余量，建议充值金额不再被顶飞

- **钱晚点才进表的充值被算错区间**（同一轮顺带修掉）：充值申请日当天抄表时钱还没到、到账日又晚于下一次抄表时，旧口径把这笔充值硬塞进「申请日 → 下一次抄表」区间，那一段用电凭空多出几万度、钱真正进表的那天反而算成 0。现在按「表底真正跳升的那一段」重新归属 —— 钱没进表的区间算真值（544 度），钱进表的区间算真值（528 度）

### 调整

- **月度报告结果新增 `conflicts` 字段**：列出与抄表对不上的充值记录（`charge_id` / `date` / `meter` / `amount` / `implied_kwh` / `reason`），界面可据此提示用户去修那条记录

### ⬆️ 升级

⚠️ **建议升级**:本次包含问题修复
- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

**Full Changelog**: https://github.com/zz3656/meter-stats/compare/v0.4.2...v0.4.3

