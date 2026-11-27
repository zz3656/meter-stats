# 📊 工程部管理系统 — Meter Stats

> 面向酒吧工程部的电表数据管理工具。**支持多门店**(每店一套表集合与电价、员工按门店授权、门店总览),另含抄表、充值、月度/年度报表、物品借还、申购、值班工作记录,字段级图片上传,三级权限。Docker 一键部署,浏览器直接访问。

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

- 🏪 **多门店** — 单实例跑多家店:每店独立数据目录、**可自定义表集合与电价**,侧栏一键切店;总部账号跨店、分店员工绑定本店;门店总览横向对比各店用电与费用
- ⚡ **抄表管理** — 每店可自定义表集合(默认 4 块:大厅/消防/包厢/空调),月底水电录入(总表/分表/水表)
- 💰 **充值记录** — 按当前门店的表集合分别充值,实时余量预警 + 建议充值金额
- 🧮 **充值计算器** — 按预充天数自动计算需充值表读数 + 金额
- 📊 **报表分析** — 每日趋势 / 月度报告 / 水电月报 / 年度汇总
- 📦 **物品借还** — 借出/归还流水,支持部分归还;借出人可填名字或直接传照片
- 🛒 **申购管理** — 申购 → 确认购买 → 自动入库(可选是否同时入库)
- 🔧 **值班工作记录** — 故障信息必填,支持文字 + 照片同时填写
- 🖼️ **图片上传** — 图片归到具体字段(借出人/归还人/申购名称/故障信息/处理方案),上传自动压缩,表格显示缩略图
- 🔐 **三级权限** — 员工 / 主管 / 管理员;**账号可绑定门店,越权一律 403**
- 💾 **自动备份** — 启动时 + 每日 0 点备份,按**保留个数**清理(默认最新 5 个),支持手动备份/恢复/下载;**含全部门店与值班照片**

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

### 从 0.4.x 升级到 0.5.x:数据布局会自动迁移

0.5.0 起数据从「数据根目录」搬到「每店一个目录 `stores/<id>/`」,首次启动自动完成:

- 顶层 6 个数据文件 + `images/` **复制**到 `stores/main/`;**顶层原文件保留**作回滚副本;迁移前自动打完整备份
- 幂等(完成标记 `stores/main/.migrated`),中途失败下次启动补做;备份失败则放弃迁移、继续以单店模式运行
- 回滚:停服 → 删 `stores/` → 从备份恢复顶层文件 → 用 0.4.x 镜像启动
- **升级前请先备份数据卷**:
  ```bash
  docker run --rm -v "$PWD/data":/data -v "$PWD":/backup alpine \
    tar czf /backup/meterstats-data-$(date +%Y%m%d).tgz -C /data .
  ```
- 若「图片目录」设置里还是老的 `/data/images`,建议清空(全局覆盖项,留着会让所有门店照片混在同一目录)
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

## 📦 工程部管理系统 v0.5.12

提交 `e6b0875`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


### 改进(UI:emoji → 统一线性图标)

接上一版的「安静化」。用户反馈的第二类噪音是**颜色太杂**,清点后确认:常驻界面上有
**405 处 emoji**(其中 39 种出现在侧栏/标题/按钮/状态栏里)。emoji 有三个硬伤:
不同系统渲染差异大、自带颜色不受主题控制、无法跟随 hover/active 变色。

- 新增内联 SVG sprite(`index.html` 的 `#icon-sprite`,**43 个 symbol**,24×24 / stroke 1.6 /
  `currentColor`),零构建、零网络请求;配套 `js/shared/icons.js` 提供 `icon(name)` 与 `fillIcons()`
- `index.html` 替换 **120 处** chrome emoji;JS 渲染的标题/按钮再替换 10 处
  (`theme.js` 主题按钮、`accessibility.js` 大字按钮、`reports.js` 年报小标题 3 处、
  `stores.js` 门店页标题与全局徽标、`modals.js` 传图片、`admin.js` 下载/删除/权限勾选)
- 常驻界面 emoji 残留 **0**(文案类 `⚠️` 提示前缀保留 —— 那是文字不是图标)
- 顺手改进 3 个在 14–16px 下辨识度不足的图标几何(droplet / coins / scroll)

### 改进(配色 token 化)

清出**「第三套紫」**:12 处 `rgba(113,112,255,α)`(#7170ff)—— 既不是 `--primary` 也不是
`--primary-bg`,而且在暗色主题下不会跟着变(写死了亮色紫)。同一个界面出现三种紫,
正是"颜色太杂"的实物证据。

- 12 处收敛到 `--tint-*(2/3/4/5)` / `--tint-border` / `--focus-ring`,**两主题自动跟随**
- 另 8 处 `rgba(99,102,241,α)`(等于 `#6366f1`)同步收敛;`var(--primary, #6366f1)` 的冗余兜底去掉
- 新增两个语义 token:`--info` / `--info-soft`(.tag-rehearsal、处理记录行此前是裸 `rgba(37,99,235,…)`)

### 新增护栏

- `tests/test_icon_system.py`(5 项):图标名必须存在、不许有死图标、`icons.js` 必须在消费者之前加载、
  常驻界面与 JS 标题里不许有 emoji
- `tests/test_contrast.py` 增 2 项:组件规则里**不许再出现品牌色裸值**(`#6366f1`/`#818cf8`/`#7170ff`/
  `rgba(113,112,255,…)`);两主题必须定义 `--primary`/`--tint-*`/`--info*`
- `test_scope_badges.py` 断言改为「徽标 span 里同时有图标引用 + 文案」,不再锁死 emoji 形态
- `test_stores_frontend.py` 的 node 沙箱补 `icon()` 桩(它只加载 stores.js,没有 sprite)

### 文档

- `DESIGN.md` 新增 Icons 章节(规格、用法、为什么不用 emoji、以及"表计 emoji 有意保留"的理由:
  那是 `store.json` 里的数据,且要出现在 canvas 图表图例里)

### ⬆️ 升级

- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

**Full Changelog**: https://github.com/zz3656/meter-stats/compare/v0.5.11...v0.5.12

