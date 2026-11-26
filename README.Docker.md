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

## 📦 工程部管理系统 v0.5.6

提交 `66a4530`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


### 改进

- **键盘焦点可见性**:按钮 / 链接 / 可聚焦容器补 `:focus-visible` —— 主题色 2px 描边
  (`outline-offset: 2px`)。此前这些元素完全依赖浏览器默认焦点环,浅色主题下是几乎看不见的
  浅色光晕(截图对比:差异 1082 像素,全部落在按钮的焦点环上)
  - **刻意不含表单控件**(input / select / textarea):规范里文本控件即便鼠标点击也命中
    `:focus-visible`,加上描边会变成「每点一次输入框就多一圈环」;而它们本来就有
    「边框变主色 + 3px 柔光环 + 背景提亮」,深浅两套主题都配好了
  - 只在支持 `:focus-visible` 的浏览器生效(macOS 12+ / Safari 15.4+),老浏览器行为不变
- 验证手法:临时写了一个「焦点探针」页(autofocus 按钮)+ headless 截图对比,确认
  ① 焦点环确实变清晰 ② 输入框区域零变化 ③ 其它像素零变化,然后才提交(探针页已删)

### ⬆️ 升级

- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

**Full Changelog**: https://github.com/zz3656/meter-stats/compare/v0.5.5...v0.5.6

