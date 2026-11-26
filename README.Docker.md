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

## 📦 工程部管理系统 v0.5.1

提交 `d4c8c78`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


**备份 / 恢复加固轮(A 批止血)。** 全部是「坏了但没人发现」的既存缺陷,
不是新功能;业务口径零改动,全量 **788** 项单测通过(A–E 五批共新增 55 项)。

### 修复

- **「下载备份」按钮 100% 失败**(实测 HTTP 400「缺少 zip_name 参数」):取 `zip_name` 用的是
  `try: read_body() except: 当作 GET`,而 `read_body()` 对**没有 Content-Length 的 GET 返回 `{}`
  且不抛异常**(`utils/api.py`)→ `except` 分支永远执行不到。前端 `downloadBackup()` 用 `<a href>`
  发 GET,于是按钮必坏;POST 路径一直是好的,而原有测试只断言「不是 401/403」,400 照样绿。
  现在 GET 直接按 query 取参(路由已经分好 GET/POST,不需要再靠 Content-Type 猜)
- **下载 GET 修好后立刻暴露的第二个坑:响应头写中文**。`X-API-Migration: 已弃用: …` 会让
  `http.server` 在**已经开始写响应头之后**抛 `UnicodeEncodeError`,客户端拿到「200 + 半截头」+
  断连(0 字节文件,curl 报 `Header without colon`)。改成 ASCII,并新增源码级护栏:
  任何 `send_header(...)` 里出现中文直接失败
- **`/api/admin/data-files` 原样吐出 `settings.json`**:里面是 `users[].password` 的 PBKDF2 哈希
  和 `nas_sync_pass` 明文,而这个接口**主管就能调**(实测返回了哈希)。备份 ZIP 早就写了
  `BACKUP_EXCLUDED_SETTINGS_KEYS` 做剥离,这条旁路把机制绕过去了。现在整份不发
  (不发打码版:`/api/upload` 能写 settings.json,发打码版再上传回去会让全站账号登不进)
- **`/api/upload` 的 multipart ZIP 分支是四处解压入口里唯一不校验的**:几 KB 的递归 ZIP 能
  解出 TB 级内容撑爆 `/data`,解压期间还占满 GIL(那个 100MB body 上限对这种包无效)。
  现在与另外三处一样走 `_validate_zip_safely`
- **四处路径包含判断用手写 `str.startswith`**:同级目录前缀同样命中
  (`/…/MeterStats.bak/x.js` 的前缀就是 `/…/MeterStats`;`/data/backup-x/` 的前缀就是
  `/data/backup`)。静态资源那条**连鉴权都没有**。统一改 `Path.is_relative_to()`

### 权限收口(接口授权矩阵)

- **接口最低角色收敛成一张表**(`routing.MIN_ROLE_PREFIXES`):以前是
  `ADMIN_ONLY_PREFIXES` / `MANAGER_ONLY_PREFIXES` 两个元组 + 两次 `startswith`,
  漂移出三类问题:
  - **重复** 5 条(`backup-config` / `nas-config` / `auto-backup` / `backup-retention` /
    `images` 在两个表里各写一遍,admin 检查在前 → 后一组永远走不到);
  - **漏项**:`backup-status` / `report-cache` / `roles` / `sessions` 两张表里都没有 →
    **任何登录用户(包括只能录入抄表的员工)**都能 `GET /api/admin/backup-status`
    拿到全站备份清单与绝对路径、`GET /api/admin/report-cache` 拿到跨店缓存键;
  - **前缀不按段比**:`startswith("/api/admin/users")` 会把 `/api/admin/users-anything`
    一起放进来。现在按路径段边界匹配。实测:员工访问上述 4 条全部 403,主管访问
    `backup-status`/`audit`/`roles` 200,`report-cache`/`sessions` 仍仅管理员

### 前端正确性

- **5 对同名全局函数互相覆盖,全部清理**(`escapeHtml` 那次事故的同类):
  `submitUtilityAdd`、`refreshDayCopySelect`、`checkDutyReminder`、`calcDayUsage`、
  `copyTextWithFallback` —— **每一对的内容都不一样**,谁生效只取决于 `index.html` 里
  `<script>` 的顺序。其中 `copyTextWithFallback` 最讽刺:带 macOS 原生剪贴板桥的那份
  在 `render_charts.js`,一直静默覆盖 `utils.js` 的旧版,改 utils.js 等于白改。
  现在每个名字只剩一处定义,并新增**源码级护栏**:跨文件同名全局函数直接测试失败
- **`module.exports` 里塞别的文件的标识符**:`reports.js` 导出了 `renderTrendChart` /
  `renderMonthlyPie` / `copyDayUsage` 等 5 个不属于本文件的裸标识符 —— 浏览器里
  `module` 未定义看不出来,Node 下 `require` 直接 ReferenceError(清理同名副本时
  又新增两处)。现在导出只列本文件定义的函数,同样有护栏
- **用户管理表格的存储型 XSS**:`renderUsersTable` 把 `username` / `name` 直接拼进
  `innerHTML`,还把用户名拼进 `onclick="editAdminUser(id,'用户名')"` —— 后端
  `add_user` 不校验字符集,管理员建个 `<img src=x onerror=...>` 当用户名,
  任何打开该页的人(含主管)都会执行;而用户名里**一个单引号**就能把那行按钮打断。
  现在自由文本走 `escapeHtml`、属性值走 `escapeAttr`,按钮改成 `data-*` + tbody 上
  一次事件委托(顺带解决「每次重绘都在累加监听器」)
- **一次刷新把同一块表画 2~3 遍**:`renderReadingTable()` 尾部无条件调
  `renderWaterTable()`,而水电数据是第三个请求才回来的 —— 那次渲染用的是**旧 State**
  (闪一帧旧水表数据),随后又被真正那次覆盖;`renderAll()` 里 `updateStatusBar` 也连调
  两次。现在水电表在数据到齐后显式渲染一次,重复调用已删
- **自定义表/倍率的口径漏洞**:饼图明细行写死 `['hall','fire','private_room','ac']`
  (2 表门店 → 扇区 2 项、明细 4 行,多出来的行读 `undefined` 直接抛错);
  饼图取表值直接 `row[key]`,而自定义表存在 `row.meters` 里 → NaN%;报表与设置页
  还有 6 处 `|| 50` / `|| 40` 字面量兜底(改成 ×100 的门店会看到「总表 ×50」)。
  现在一律跟 `window.METER_KEYS` / `meterValue()` / `MAIN_METER_MULT`·`SUB_METER_MULT` 走,
  并有静态护栏禁止字面量倍率兜底

### 性能(报告引擎)

- **年报 1210ms → 31ms(37×),月报 100ms → 28ms(3.5×)**(合成 1100 行抄表 / 160 笔充值;
  真实数据 97 行:年报 15ms → 5ms)。点一次「年度报表」原来要独占 GIL 两秒。
  四处改动,口径零变化:
  - **日期索引只建一次**:`_attributed_segment` 里每笔充值 × 每块表都重建一次
    `{日期: 下标}`(1100 行 × 160 笔 × 4 表 ≈ 7 万次 O(R) 重建,年报再 ×12)。
    改为 `_prepare()` 统一过滤+排序+建索引,往下传
  - **冲突判定与充值归属合并成一遍扫描**(`_analyze_charges`):这两件事的判据完全相同
    (都是对「充值 × 表」调一次 `_resolve_charge`),以前两个函数各跑一遍最贵的内核。
    两个公开函数保留为薄包装,判据只留一处(避免「冲突规则改了、归属没改」的漂移)
  - **年报不再循环调 12 次月报**:准备一次(排序/冲突/归属),再跑 12 次便宜的部分
  - **区间∩月份天数改成算术**:原来是「区间内每天 `strptime` 一遍再逐条比对」的
    O(天数²) 扫描,区间首尾相接、互不重叠,直接相减即可
- 等价性验证(不是"看着对"):月报/年报/冲突清单在**六类输入**(真实 fixture、
  合成 1100 行、2 表门店、含负数/零额充值、空数据、单条读数)× 10 个月 + 2 个年份下,
  与改造前实现**逐字节一致**;`71226.1 度` 口径回归通过;线上接口实测
  「年报里 2026-06 = 月报 2026-06」
- 新测试 `tests/test_report_perf.py`:年度汇总与逐月自洽、冲突清单两条入口一致、
  **年报耗时不得退化成月报的 12 倍**(阈值 4×,改造前比值 11.9)
- 顺带删掉 `report.py` 里两个长期未使用的 import(`timezone` / `Path`)

### 其他

- **支持 HEAD 请求**:以前没有 `do_HEAD`,`http.server` 直接回 `501 Unsupported method` ——
  `curl -I`、多数监控探针(Uptime Kuma 一类)、部分反向代理的健康检查都走 HEAD,
  会把服务判成"挂了"。现在静态资源与 API 的 HEAD 都返回与 GET 相同的状态码和响应头
  (含 `Content-Length`),只是不发 body
- **文档与实际对齐**:`AGENTS.md` / `README.md` 里"147 个用例、~2s"早已是公开数字,
  实际是 **43 个测试文件 / 788 个用例 / 约 30 秒**;同时补上「CI 门禁到底跑什么」、
  「`ruff` / `mypy` 为什么没进门禁」(基线本就有既存告警,直接加会红)、以及
  「前端两个入口 + 同名全局会被静默覆盖」(Pitfall 6 原来写的是已不存在的 `app.js`)

### 工程卫生

- **删掉 21 个零引用函数**:`js/shared/toast.js` 349 → 113 行(12 个 `datamgmt*` 弹窗/
  base64/自动备份开关死函数 —— 那套弹窗早被独立页面取代,`index.html` 里连对应节点都没有),
  `admin.js` 1715 → 1489 行(9 个死函数 + `#datamgmt-backup-list`/`#datamgmt-backup-retention`
  死分支)。死代码不是按"看着像没用"删的:用**引用可达性**分析(根 = 顶层代码 + 别的文件 +
  `index.html` 的 onclick),传递闭包之外的才动
- **报表缓存失效收敛到写盘层**:以前 11 处 handler 各自写一行 `invalidate_report_cache()`,
  漏一处就是脏读(症状:改完电价/录完抄表报表数字不变,等 5 分钟 TTL 才"自己好"),
  而 `registry` 建店写 `store.json` 那条路根本没接上。现在 `storage.save_json()` 对
  `readings/charges/purchases/store/settings.json` 写盘即失效,handler 里的显式调用保留作双保险
- **CI 终于跑测试了**:新增 `.github/workflows/tests.yml`,push/PR 上跑 Python **3.9 与 3.11**
  双版本的 `compileall` + 全量 `unittest` + `node --check`。在此之前全量测试**从来没在 CI 跑过**
  —— 那三个 workflow 只打包 DMG 和推镜像,"测试绿不绿"全靠本地自觉
- **静态资源真的能缓存了**(首屏 37 个请求 → 第二次起全部命中):
  - 修 `inject_version_to_html`:`utils/api.py` 里那份是对的,但 `app_handler` 里另有一段
    自己实现的注入逻辑(只替换 `<TIMESTAMP>` 占位符、普通路径**不加** `?v=`),实际生效的是它
    —— 所以 30 多个 JS 里只有 `admin.js` 拿到版本号,其余全是无版本 URL + `no-store`,
    每次刷新重下 ~620KB
  - 现在本地资源统一注入 `?v=<内容哈希>`,`index.html` 保持 `no-store`;
    带版本号的静态资源给 `public, max-age=31536000, immutable`(内容一改 URL 就变,
    不会出现「CDN 糊住旧代码」)
- **Chart.js 改 `defer`**,不再阻塞首屏解析(以前 CDN 慢,登录页也要等它);配套:
  - 5 处 `new Chart(...)` 与 `Chart.defaults` 访问都加「Chart 未就绪就跳过」守卫,
    CDN 挂掉只是没图,不会把后续渲染一起掐断
  - 加有限次轮询(100ms × 100),Chart 到位后补画首屏图表 —— 否则 defer 会让
    「首屏第一次渲染时 Chart 还没到」变成「首屏永远没有图」
- **`_yearlyChart` 死变量**:`accessibility.js` 读的是一个**从不赋值**的 `var _yearlyChart`,
  真实例在 `reports.js` 里叫 `window._yearlyBarChart` → 「切换深色/大字模式后年度柱图重排」
  这段保修代码从来没生效过

### 新增

- **值班照片进备份,恢复也认**:以前 `images/` 从来没进过备份包 —— 换机器 / 重建容器即永久丢失。
  现在 `stores/<id>/images/*` 与单店布局的 `images/*` 都进包,恢复时按原路径写回
- **备份/恢复共用一套路径规则**(`MeterStats/backup_paths.py`):以前备份侧 `rglob` 收任意深度、
  恢复侧白名单只认 1 段/3 段,漂移出来的后果是「包里有文件、恢复时静默丢弃」。现在两侧都调
  `classify_rel()`,并确立 round-trip 不变式:**包里的每个文件都恢复得回去,恢复得回去的都在包里**
- 顺带修掉:崩溃残留的 `*.json.tmp` 以前会被打进备份包(它是原子写入的中间产物,不是数据)

### 注意

- 备份包会因照片而变大;自动备份按「份数」保留(默认 5),照片多的部署请留意磁盘占用
- 「图片目录」若被设置指到**数据目录之外**的绝对路径,那份照片不在备份里(遍历不到,
  但恢复侧同样认不回来,不会出现「包里有、恢复丢」)

### ⬆️ 升级

⚠️ **建议升级**:本次包含问题修复
- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

**Full Changelog**: https://github.com/zz3656/meter-stats/compare/v0.4.3...v0.5.1

