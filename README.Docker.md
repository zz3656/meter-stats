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

## 📦 工程部管理系统 v0.4.1

提交 `819b183`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


一次合并发布：登录从"界面遮罩"改为真正的访问控制，充值统计口径改为按**实际到账时间**归属，余量计入**已到账但还没抄表**的充值。

### 破坏性变更

- 除 `GET /api/health`、`GET /api/version`、`POST /api/auth/login` 三个白名单端点外，**所有 `/api/*` 请求都必须携带有效会话 token**，否则返回 `401 {"error":"未登录或会话已过期,请重新登录"}`。此前抄表、充值、物品、申购、工作记录、报表、快照、导出等读写接口不带 token 也能访问和提交——任何绕过界面直接调接口的脚本/curl 都需要先登录取 token
- token 支持 `?token=` 查询参数、`Authorization: Bearer` 头、`meter_token` Cookie 三种方式；`<img src>` / `<a href>` 这类带不了请求头的访问改用查询参数，图片地址由 `getDutyImageUrl()` 自动拼接
- 升级后需重新登录一次；`ENFORCE_AUTH` 仅作单元测试内部开关，生产不读环境变量，无法从外部关闭

### 新增

- **接口级鉴权 + 角色分层**：统一在 `routing._auth_gate()` 拦截；删除类操作需主管或管理员，`/api/admin/users` 仅管理员（此前任何登录用户都能新建管理员账号自我提权），审计日志、数据文件、目录列表、NAS 同步、备份删除/恢复、电价倍率与图片目录配置需主管及以上；员工保留录入与编辑
- **登录页显示版本号**：底部显示「版本 v0.4.1」（读 `/api/version`，无需登录；取不到时自动隐藏）
- **余量计入已到账未抄表的充值**：预付费表钱打进表后余额立刻生效，却要等下次抄表才进读数；现在余量 = 最新读数 + 已到账但尚未反映进读数的充值，预警卡与充值计算器同时标注来源（如「含 33600 度已到账未抄表（2026-11-02 抄表 27.1 表字）」）
- **抄表后发现表底上升且无充值记录时主动追问**：保存成功后提示「充值数据是否没录入？」，点「去补录充值」自动切到 充值 Tab 并打开新增表单——**日期填成表数异常那天**，各表充值数按「上升量 + 该段日均消耗」估算并取整到十位，备注写明来源；若该区间只有待确认申请，则提示「有充值待确认到账」并跳到充值 Tab 去确认
- 测试：新增 `test_auth_enforcement.py`（17）、`test_login_rate_limit.py`（8），归属规则用例 7 个，全量 **119 项**

### 修复

- **表数上升提醒点确认后不保存**：抄表弹「表数上升提醒」时，点「已充值，继续保存」只处理了取消分支、确认分支没有接续保存流程——弹窗关掉、数据没写进库、仍停在新增抄表界面，再点提交又弹同样提醒，形成死循环
- **任何人可免密码进入系统**：登录失败时后端返回 HTTP 200 + `{ok:false}`，前端 `doLogin` 从不检查 `res.ok`，把 `undefined` 当 token 并隐藏登录页；叠加上面的接口不鉴权，界面数据照常加载。现在只有同时拿到 `token` 和 `user` 才放行
- **密码输错一次就锁定 5 分钟**：限速把"是否在冷却期"写成 `if failed_attempts:`，失败记录时间戳就是刚刚，必然触发冷却，后面 `>= 5 次` 的阈值永远执行不到；且尝试记录只保留 60 秒，真触发锁定后 60 秒也会失效。现在 1 分钟内连续错满 5 次才锁 5 分钟，锁定状态独立记录、按用户名隔离，登录成功即清
- **充值被当成已用电量，日均虚高几十倍**：旧口径 `(上次, 本次]` 无条件把本次抄表当天的充值并进这段用电量——大厅真实 656 度/天被算成 34256 度/天、可用 0.1 天「预计今天断电」、建议充值 ¥1,136,822。改为**按表底实际跳变 + confirmed_at 归属每一笔充值**（前后端同一套规则）：到账日当天抄表且表底上升→归上一段；当天没上升→归下一段；落在两段中间→归该区间；之后没抄表→暂不归属。该口径精确复现 2026 年 6 月 Excel 核对过的 **71,226.1 度**
- **余量漏掉已到账的充值**：11-02 那笔 210 表字（33600 度）充完，预警仍显示只剩 4336 度、6.6 天；修正后大厅 37,936 度、约 58 天。与归属引擎同源，补录抄表后不会重复累加
- **手动录入充值只要填包厢就静默失败**：`charges.js` 字段 id 写成 `charge-private-room`，页面实际是 `charge-private_room`，`getElementById` 取 null 后读 `.value` 抛异常；侧栏表单与新增弹窗两条路径都提交不了
- **`build-app.sh release --install` 每次在收尾阶段无声中断**：`INSTALL_PARENT` 与 `BUNDLE_PARENT` 同为 `/Applications`，那段"同步到 /Applications"实为把文件复制给自己，`cp` 报 "are the same file" 被 `set -e` 掐断，后面的 runtime 覆盖从未执行；现在跳过自拷贝并把复制失败改为显式告警（该脚本在 `.gitignore` 内，只对本机生效）

### 调整

- 充值归属判断依据从记录日期改为**实际到账日**（`confirmed_at`；11-02 提申请、11-03 打款到账按 11-03），无该字段的历史记录退回记录日期
- 充值记录列表的月份筛选、「本月充值次数 / 充值度数 / 充值金额」统一按到账日归月（`chargeEffectiveDate()`）；表格日期列仍显示申请日，作为记录标识

### 文档

- `AGENTS.md` 补接口鉴权架构、充值与用电归属口径（含 71226.1 度回归基准），Pitfalls 增加 `build-app.sh` 会清空 Application Support 的警示

### ⬆️ 升级

- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

**Full Changelog**: https://github.com/zz3656/meter-stats/compare/v0.3.5...v0.4.1

