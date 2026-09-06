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

## 更新历史

## 📦 MeterStats v0.1.0

> macOS + Docker + Web 三端统一部署 · 提交 `b4770ef` · 完整改动见下方

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


#### 📦 backup

- 恢复流程直接弹文件选择器 + 支持 zip 备份上传 (
a5b123)
  ## 文件选择器: 跳过中间模态框
  > - pickBackupDir 在浏览器/Docker 环境下,原本需要先弹一个确认模态框
  > (showBrowserBackupPicker) → 用户点「选择文件」才触发文件选择器
  > - 现在 pickBackupFiles() 直接创建 <input type='file'> → 自动弹出系统文件选择器,
  > 用户选完后直接进入恢复流程(中间不再需要点确认)

#### 📦 duty

- 值班录入新增故障区域字段 (
7d1fe8)
  > - 值班录入表单新增「故障区域」输入框(选填,如:1#大厅、2#消防)
  > - 工作记录表格新增「故障区域」列展示
  > - 后端 duty.py POST/PUT 都支持 fault_area 字段,空值默认空串(向后兼容旧记录)

- 录入集成+侧栏重构+UI统一+移动端适配 (
4a5d7e)
  ## 录入整合与弹窗合并
  > - 每个记录页面在 header 加 ➕ 新增按钮(弹窗与侧栏录入共用 submitXxxAdd(source) 函数)
  > - 抄表/水电弹窗合并为带 Tab 的单弹窗(reading-add-modal),充电计算独立弹窗
  > - 工作记录弹窗标题改「📝 新增记录」,字段顺序:故障区域(首行)→ 类型 → 时间 → 班次 → 备注 → 处理状态(末行带 dashed 分隔)
  ## 报表分析重构

- 完善借出归还 — 新增历史记录表与归还弹窗 (
236e44)
  > - 物品记录页面新增「借出 / 归还 记录」表格,展示每次借出和后续归还情况
  > - 归还流程从简单的二次确认弹窗改为完整弹窗:不要求借出人,可填归还数量(默认全还)和备注
  > - 借出仍强制要求填借出人(后端校验已存在)
  > - 借出/归还记录保存在物品的 lend_records 数组里(后端未变,前端展示新增)

- 物品记录新增借出和归还功能 (
86b140)
  > - handlers/items.py 添加借出/归还API处理
  > - routing.py 添借出/归还路由
  > - index.html 添加借出弹窗和物品表格更新
  > - app.js 添加借出/归还前端逻辑

- 新增值班录入和工作记录功能 (
ebde2e)
  > - 新增 handlers/duty.py 处理值班录入API
  > - routing.py 添加 duty 相关路由
  > - app_handler.py DATA_PATHS 添加 duty
  > - storage.py DATA_FILES 添加 duty.json
  > - index.html 添加值班录入和工作记录页面
### 🐛 fix

#### 📦 backup

- 手动备份恢复数据到 docker 不生效 (
844411)
  > 根因:
  > 1. datamgmtRestore 恢复后调用 refreshAll() 只刷 items/purchases,
  > 不刷新 readings/charges/图表等页面 → 改用 renderAll() 全量刷新
  > 2. 手动备份 zip 含完整 settings.json(含 backup_dir 宿主机路径),
  > 恢复到 docker 容器会把容器 backup_dir 覆盖为无效路径

#### 🚀 CI/CD

- build-dmg shell 步骤改用 $version 取版本号($VERSION 为空) (
c8a474)
  > 之前 $GITHUB_ENV 写入的是 'version=0.1.0' (小写),但 Create DMG/Notarize/
  > Publish Release 等步骤用 ${VERSION} (大写),shell 中 $VERSION 是空,
  > 导致 dmg 文件名变成 'MeterStats--macos.dmg'(双横线)。
  > 统一改成 ${version} (与 $GITHUB_ENV 写入的小写名一致)。

- 修正 build-dmg release artifact 文件名缺失版本号 (
a30640)
  > ${{ env.version }} 在 $GITHUB_ENV 写入后只在 step shell 中可见,
  > YAML 表达式上下文读不到,导致 artifact 名为 'MeterStats--macos.dmg' (双横线)。
  > 改用 step output(${{ steps.version.outputs.version }}) 暴露版本号,
  > artifact 名修正为 'MeterStats-0.1.0-macos.dmg'。

- 修复 Build DMG 失败 + push 自动构建发布 (
352490)
  > - 修复手动触发 Build DMG 失败:无 Apple secrets 时证书步骤无条件执行
  > 导致 security import 失败。改为运行时检测 secret,未配置则跳过
  > 证书安装/正式签名/公证(仅 ad-hoc 签名+发布)
  > - 实现 push main 自动构建并发布 Release:
  > 触发改为 push branches main(paths-ignore 文档/CI 文件)+手动触发,

#### 🚀 部署/CDN

- 注入 ?v=<token> 绕过 Cloudflare CDN 缓存旧版 app.js (
e53d93)
  > 根因:Cloudflare CDN 默认缓存 .js/.css/.html 静态文件 4 小时(max-age=14400)。
  > 即便 docker 容器已经拉了新镜像重启,Cloudflare 仍然返回旧的 app.js 给用户浏览器,
  > 导致用户看到的是修复前的代码,bug 看似'修不好'。
  > 修复两层防护:
  > 1. _handle_static 给 html/js/css 响应加 Cache-Control: no-cache, no-store,

#### 🍎 macOS 原生 App

- 修复 macOS app 点击恢复数据不弹文件选择器 (
381fe6)
  > 根因:macOS WKWebView 默认不实现 WKUIDelegate,任何 <input type="file">
  > 的 .click() 调用都静默失败(用户无任何反馈),且没有 Swift 桥让前端
  > 显式弹 NSOpenPanel 选文件。
  > 修复:
  > 1. Swift 新增 PickFileHandler: macOSPickFile WKScriptMessage,

#### 📦 swift

- url.lastPath → url.lastPathComponent (
44c210)
  > Swift URL 类型的属性名是 lastPathComponent,不是 lastPath。
  > DMG build 失败已修复。

#### 🌐 Web/Docker 前端

- 修复 fetchSnapshot/admin 恢复后页面不刷新导致用户看不到数据 (
a2c621)
  > 两个相关 bug:
  > - fetchSnapshot 成功路径只写 localStorage 缓存,未赋值全局
  > CURRENT_READINGS / CURRENT_CHARGES,导致 renderAll 拿到空数组,
  > 页面始终显示'暂无抄表记录'(即使后端有 35 条数据)。
  > 修复:成功路径同时赋值 CURRENT_READINGS/CHARGES/ITEMS/PURCHASES/DUTY

- ensure DATA_PATHS includes readings_water and add Docker data diagnostics (
6c8ae6)
  > - Add 'readings_water' to DATA_PATHS in app_handler.py to match storage.DATA_FILES
  > Prevents KeyError if handler reads DATA_PATHS before server.py completes replacement
  > - Add diagnostic logs in storage.get_data_dir() when METER_DATA_DIR has no data files
  > Helps users locate lost data after Docker image update/redeploy

- 修复 build-dmg.yml 工作流 (
6a6eaa)
  > - 移除已弃用的 altool 引用
  > - 使用新的 notarytool 替代 altool --notarize 公证

- 完善 build-dmg.yml 版本判断逻辑 (
bbbcea)
### ♻️ refactor

#### 📦 backend

- 拆分 handlers/ + utils/, 引入认证/会话/CORS/PBKDF2 (
95a4ef)
  > 把原 server.py 内联的所有 handler 拆到 handlers/ 子模块(每个 model 一个
  > 文件),通用工具( send_json / send_csv / read_body / ZIP 校验)抽到
  > utils/api.py,审计日志抽到 utils/audit.py,业务常量抽到 constants.py,
  > 消除原本 1000+ 行单文件带来的维护痛点。
  > 新增能力:
  **影响范围**:
  - web: 后端接口拆分,前端无 API 路径变化,兼容性保持
  - docker: 镜像结构无变化,镜像内 Python 路径相同
  - 三端: 数据结构与字段不变,存量 JSON 文件无需迁移
### 📖 docs

- 更新 README 和 docker-compose 添加 METER_BACKUP_DIR 和 METER_IMAGE_DIR 环境变量说明 (b4770ef)
  > - README 环境变量表格新增 METER_IMAGE_DIR 说明
  > - README Docker Compose 和 Docker Run 示例添加备份目录和图片目录环境变量
  > - docker-compose.yml 将两个环境变量从注释改为默认启用

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
8f2d37)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
307c9c)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
e2fc98)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
24cd0b)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
9099f5)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
c99e0e)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
e4da33)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
00f098)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
a30a9a)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
1ac42c)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
996753)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
858c3f)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
7b88f1)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
f4d646)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
2f165f)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
e19fdd)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
6c20ea)

- 自动同步 v changelog 到 README.Docker.md [skip ci] (
0fd8f0)

- 重写 README + DockerHub 描述;清理冗余文件 (
3c6afb)
  ## 删除冗余(从仓库移除)
  > - .run.sh:与 MeterStats/run.sh 重复(MeterStats/run.sh 已存在)
  > - Info.plist(根目录):与 MeterStats/Info.plist 重复(bundle 用的是后者)
  > - DEPLOY_FNOS.md:内容已合并到 README.md
  > - DO-HUB-TOKEN-GUIDE.md:同上
### 📝 其他改动

- 
171c6e2ada580fad46778f7c44ccd42185ebed41 ()
  > feat: 修复删除处理记录还原报修状态，Docker环境配置目录变量
- 
4653ef384ca4222a5137bf46af40e1b12d66a295 ()
  > fix: 移除备份目录恢复默认按钮，Docker环境下隐藏保存按钮
- 
7ea5edd952575fbafb529403dbfa77a40de10661 ()
  > fix: 备份/图片目录改为先选择/输入再保存,标题改为图片目录
- 
1aa9070ca2d2213fbb8075cd2f9174b4b7b1e0ae ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
b7f717cfbe45402b503e3dafb737ffc67ba129f1 ()
  > fix: 修复admin/images路由参数不匹配导致500错误
- 
6b544a60f0f0c8c9a28a8210e1dde66225f522ee ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
701c43600af876b0c72f4955ba910462e69c1ffa ()
  > fix: 图片目录选择简化为prompt,加载失败时提示重启后端
- 
c4644988cddb55608819007e843a18af030eb325 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
6a980b7da76563fb283ddd40bc3bdce406e98dbe ()
  > feat: 数据管理新增图片目录设置项,默认保存在/data/images
- 
87c8813beb56d368060e92b29eaab4648aabcc90 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
be55379ecf858d7878a0052b3a1c26d3acf4b2b7 ()
  > fix: 修复duty.py缺少JsonModelHandler导入导致导入崩溃
- 
6f10a7702c6d26b53de69649aa9a735c3aef023d ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
0986d4fec81e911d1e51b6868b180abb97f4de05 ()
  > feat: 工作记录新增记录和处理时增加图片上传功能,表格中展示图片缩略图
- 
30d5d8287a59e7c62630391c9a18d5e90d4a0a00 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
2ed66efab98977497df309e9cbf0d181ef5b41a9 ()
  > fix: 处理工作记录 API 增加详细错误日志
- 
2630d6f17ed4e7c0f578d7c1948952b30b17c39a ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
6b5d61cbc966fdcc3a820f7ea779d4d1c75d50ca ()
  > feat: 处理工作记录时创建独立处理记录,报修和处理各一条记录
- 
9fca3f44b34acf3bf1b9cd98ab8b44e1a867552c ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
9b322b6b622342e6e2e520f670d484c3cdb7706a ()
  > feat: 工作记录表格增加处理方案列,待处理记录显示醒目横幅
- 
0fc29b7cd1ca703720eaa632cb5edd7a6180b34b ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
2620d4b9adfa531affaa3084d3926446b03dc035 ()
  > feat: 工作记录未处理项添加处理按钮,支持处理时间/班次/方案/备注
- 
f5cd0daf3c05a6a9112aafaae11ff1007116fdbd ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
f19ba4939ae05b8caf10c8c6b72bc553e2526cde ()
  > fix: login page theme button now matches post-login (3-state cycle)
- 
d5503e56e2c38a36eb4fa00ab9ff0bc31c85c69c ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
98fd375104572ad3e671bca3a4b55514099a6917 ()
  > fix: expose global variables across JS modules for browser script loading
- 
d557162b42463c217630713772ed77f946f761bc ()
  > fix: Dockerfile 复制 js/ 子目录以包含所有模块化文件
- 
97c616383385222c9edae9f1e48152b20a4bdd70 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
a5e5f2b370975dba76cd3190f8387330437e7b3f ()
  > refactor: 模块化重构前端 JS，将 app.js 拆分为 29 个功能模块
- 
175a5d846481c3dd36b422329dad1560de02e25b ()
  > refactor: 登录页控制按钮与全局 header 按钮统一样式
- 
cb0afde95cc15b3eba8687ceba2551c5797b8b22 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
eb3bb8b5f093a56a875c581dbd32e8dc62636070 ()
  > feat: 登录页面增加主题和大字模式切换按钮，全局一致体验
- 
64b9231fdf8143bd03e32e84e58c513883d78db6 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
6a21ca2ee8d569c4b638e4274dbe1b7d5a98c07e ()
  > fix: 大字模式在登录界面即可显示，提前初始化避免闪烁
- 
4738ace1c42b478a222eadbcddc7ac11d81a7818 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
ec77417425d1e28a25b73795321f2bc1756b5b03 ()
  > feat: 添加大字醒目模式(辅助功能)，方便老年录入人员手机操作
- 
265a6d036ae9da974ea87bf3c93209f925544296 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
f3de41209f92e2278de4e66b50947faf89a6f540 ()
  > fix: 修复水表表底月份选择后抄表记录消失
- 
4b178201f1e94d887f8d1d2c5ffff61d18a140a3 ()
  > fix: 水表表底月份选择后不刷新表格
- 
3a628c0e58c79ea394f632498facc2b2b5e80efe ()
  > feat: split readings table into two independent tables
- 
af48094e29edff6ffa4ab9ca8f8263758838d7d3 ()
  > fix: display water-only records in history table + fix delete for water-only dates
- 
d715f0ab98ce58270e69845ddff396d5843417d5 ()
  > fix: properly handle water meter delete in inline edit
- 
e1cb5a7f191c04e66d28d1349ff8a44f177bed0b ()
  > fix: show water meter fields in inline edit + auto-select latest utility month
- 
3c67f2a92e9fa50e6ac02144f28781cdd587dbe2 ()
  > fix: auto-migrate water data on startup
- 
fff03f218bf5b201d29d27b46862ae94bcdd5e71 ()
  > feat: 分离水电表底数据到独立文件,支持在线迁移
- 
39ba440d100e35706c178dd2f3b2845e3d8da8de ()
  > fix(deploy): 修复 VERSION 读取/Docker 构建/ZIP 上传/Docker 检测 4 个 bug
- 
29b8a793546fafc128d10b064641e4a84992a04f ()
  > fix(ci): NOTES=$(...) 不再合并 stderr(2>&1),避免 set -x 调试污染
- 
dc81fe25cbe447830ed668c6933d7df6fb2f2ed3 ()
  > ci(release): 加调试输出确认 NOTES 生成
- 
1001533d92f6b4594aaac6e05affc8f3bf1b4d03 ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
6010b2836867c51e1676dc847fa3ef3f03a9cc7b ()
  > fix(repo): 重命名 Scripts/ → scripts/ 保持 Linux CI case-sensitive 一致
- 
099fb8f06784313072ac5d1f22a02c1c0a703e9b ()
  > docs: 自动同步 v changelog 到 README.Docker.md [skip ci]
- 
1672b6670f007c3cfa689a1841aeb7062c300595 ()
  > fix(release): 无 git tag 时 release notes 只取最近一个 commit
- 
c94accace30e6e06fde6220cd8db5de14f51419f ()
  > docs(repo): 加 commit message 模板(.gitmessage)提升 release notes 质量
- 
1c0f17b908b780afdb3a8ec40c66b7e06dadff84 ()
  > fix(ci): 修复 build-dmg gh release create 行被误删
- 
547d79ef3985f8398cba0308a0da3a959dfd1ffd ()
  > ci(release): 用结构化 commit 解析生成详细 release notes + 同步 Docker README
- 
6b72706def55e37e35b69584542cba1de724fbb2 ()
  > fix: 修复 build-dmg.yml 中判断 tag push 的条件
### ⬆️ 升级指引

⚠️ **强烈建议升级**:本次包含问题修复。
- 🌐 **Web/Docker 用户**:重启 docker 容器 `docker compose pull && docker compose up -d`,浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)。
- 🍎 **macOS 用户**:下载下方 DMG 覆盖安装。

---

💡 完整代码改动请看 [commits 页面](https://github.com/zz3656/meter-stats/compare/v0.1.0...b4770ef)

