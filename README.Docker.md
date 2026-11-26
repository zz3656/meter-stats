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

## 📦 工程部管理系统 v0.5.11

提交 `230bc2b`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


### 改进(UI:降低长时间观看的视觉疲劳)

用户反馈「看久了容易视觉疲劳」。先量化再改,结论是**四件事叠在一起**:

| 实测问题 | 旧值 | 新值 |
|---|---|---|
| 暗色主文字对比过曝 | `#e8eaf0` on `#0d0f14` = **15.94:1** | `#d5d9e2` on `#14161c` = **12.8:1** |
| 暗色辅助文字不过 AA | `#6b7280` = **3.96:1**(卡片上 3.49) | `#8b93a3` = **5.9:1** |
| 暗色最弱文字基本隐形 | `#4a5058` = **2.35:1** | `#868ea0` = **5.1:1** |
| 亮色最弱文字不过 AA | `#a6adb8` = **3.87:1** | `#67707c` = **5.0:1** |
| 字号偏小 | 11px ×22 处、12px ×34 处 | 表头 11px→12px 并取消大写变换;行距 8px→9px |
| 每行彩色噪音 | 12 行表格 = 24 个彩色「编辑/删除」 | 中性文字,hover 才上语义色 |
| 最响元素是辅助开关 | 「大字」是**实心紫**按钮 | 改幽灵按钮,实心主色独家留给主动作 |
| 无动效降级 | 没有 `prefers-reduced-motion` | 已支持,动效统一 180ms |

- 主色降一档饱和:`#6366f1`→`#5b5fd6`(亮)/ `#818cf8`→`#8f97f2`(暗),长看不发紫光
- 分割线整体再轻一档(`--border` .10→.09,`--border-subtle` .06→.045)
- 4 表卡片色条 3px→2px;侧栏 emoji `saturate(.82)`
- 移动端表格行内操作 30px→40px(触屏误触是"烦躁"的隐性来源)
- `readings.js` 里 3 处删除按钮的**内联样式**移除,统一走 CSS

### 新增

- `PRODUCT.md`:战略层(用户/场景/反例/设计原则/无障碍目标)。关键结论:**四项使用场景全中**——暗光、白天、需要大字、主要用手机
- `DESIGN.md`:视觉系统说明书(主题/token/字体阶梯/组件/动效/改动纪律)
- `tests/test_contrast.py`(4 项):机械校验两套主题的对比度 —— 主文字必须落在 **11–14.5:1**(够清楚又不刺眼),其余 ≥4.5:1,主色块白字 ≥4.5:1;并检查 `prefers-reduced-motion` 存在。**这条会把"以后又改回刺眼"直接挡在 CI 上**

### 验证

- 截图对比(暗/亮 × 1440/390 四种组合):暗色 42.3% 像素变化、平均差 **5.2/255** —— 全局轻微变柔而非重做;近白像素占比 0.2% → **0.0%**(刺眼的纯白没了);亮色 7.3% 变化(集中在表头与行内操作)
- 改动**不动布局与信息架构**:所有卡片、表格列、导航位置像素级保持原位

### 文档

- 项目根新增两份上下文文件,`docs/ARCHITECTURE.md` 与技术文档体系不变

### ⬆️ 升级

- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

**Full Changelog**: https://github.com/zz3656/meter-stats/compare/v0.5.10...v0.5.11

