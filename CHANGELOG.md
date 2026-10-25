# 更新日志

本项目的所有重要变更都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.3.0] — 2026-10-25

模块化重构完成后的第一个稳定版本。侧栏、报表、设置、图片上传、备份系统全面重做，并修复了十几处重构过程中丢失的绑定与调用。

### 新增

**界面**

- 侧栏固定 12 项、四字命名：用电记录 / 物品记录 / 申购记录 / 工作记录 / 每日趋势 / 每周汇报 / 月度报告 / 年度汇总 / 用户管理 / 电表设置 / 数据管理 / 权限管理
- 用电记录合并为三 Tab：📝 抄表 / ⚡ 充值 / 💧 水电
- 四张报表页统一为「概况卡 + 图表 + 明细表」结构
- 系统设置拆成四页：用户管理 / 电表设置 / 数据管理 / 权限管理
- 顶部状态条只在「用电记录」页显示，其他页面隐藏
- 侧栏底部显示版本号 `v0.3.0`

**图片上传**

- 图片入口下沉到具体字段：借出人 / 归还人 / 申购物品名称 / 工作记录故障信息 / 处理方案
- 必填校验放宽为「文字或图片满足其一」，只传照片也能提交
- 工作记录新增「故障信息」必填字段（textarea），支持文字 + 图片同时填写，表格同步新增该列
- 申购新增弹窗只保留物品名称后一个图片入口，备注恢复纯文本
- 上传前自动压缩：最长边 1600px、JPEG 质量 0.82；小于 200KB 的原图跳过
- 文件名带来源前缀，便于在图片目录里区分：`lend-` / `return-` / `purchase-name-` / `purchase-note-` / `duty-note-` / `duty-handle-`，格式 `{scope}-{毫秒时间戳}{ext}`
- 表格对应列显示缩略图，点击可放大

**备份**

- 「备份与恢复」卡片合并为单一「保存」按钮，一次提交备份目录 + 保留个数
- 自动备份保留策略从「保留天数」改为「保留个数」，默认保留最新 5 个
- 修改保留个数后立即清理超出的旧备份，不用等下次备份
- 备份列表每项支持「⬇️ 下载」

**Docker**

- `docker/entrypoint.sh` 自动注入 `METER_DOCKER` / `METER_BACKUP_DIR` / `METER_IMAGE_DIR`
- Docker 环境下备份目录、图片目录由环境变量控制，UI 自动锁定并显示 `🔒` 提示

### 修复

**macOS 应用内图片选择完全无反应**

三层问题叠加，逐一修复：

1. `wv.uiDelegate = WebViewUIDelegate()` —— `uiDelegate` 和 `navigationDelegate` 都是 **weak** 引用，对象创建完当场释放变 nil。改用静态容器持有。
2. `PickFileHandler` 存了 `weak var webView`，注册时传 `nil`，`evaluateJavaScript` 从来没执行过（备份恢复桥也从没工作过）。改用 `message.webView`。
3. `<input type="file">` 在 WKWebView 里即便 delegate 接上也不可靠。

最终方案：**完全绕开 web 文件选择器**，所有 📷 走原生桥 `macOSPickImage` —— Swift 弹 `NSOpenPanel`、原生压缩、base64 回传，JS 转 File 上传。浏览器无此 handler 时自动回退到 `input.click()`，网页行为不变。

**备份与恢复**

- 自动备份开关 `settings.auto_backup` 没有任何代码读取，关掉也照样备份 → 现在两处备份线程都尊重该开关
- 「今天已备份就跳过」的判断看的是临时目录，而该目录打包完即删，导致每次启动都重做一遍 → 改判最终 ZIP
- 前端 `setBackupRetention` 传的参数名是 `retention_days`，后端读 `retention_count`，静默失败、永不生效 → 参数名对齐
- 「选择目录」按钮实际只把一个输入框 `display:block`，根本不弹面板；且 `BackupDirHandler` 同样中了 `weak var webView` 的坑 → 改走桥 `pickBackupDir`

**图片目录**

- `pickImageDirInput()` 往 `#image-dir-raw` 写值，而 HTML 里没有这个元素 → 一点就抛 `Cannot set properties of null`，按钮完全没反应
- 与备份卡片共用 `window.__backupDirChosen` 回调，互相覆盖 → 拆成独立的 `__imageDirChosen`，Swift 端用 `kind` 参数区分标题与回调
- 显示格式和按钮文案与备份卡片不一致 → 统一为 `📁 路径` + `📂 选择目录` / `保存`
- placeholder 原写「留空 = 默认」，但后端要求图片目录必须在数据目录内 → 文案修正

**其他重构回归**

- 弹窗取消/提交整段绑定丢失 → 新建 `js/modules/modal_bindings.js` 集中管理
- 模型名 `renderAll()` / `refreshAndRender()` 缺失
- 借还历史不显示 —— 记录挂在 `item.lend_records`，`refreshItems()` 漏调 `renderLendHistory()`
- 申购删除后不刷新表格
- 工作记录字段名与后端不符（`type` vs `duty_type`、`time` vs `record_time` 等）
- 物品列表 `limit=0` 被 `max(1, ...)` 强制成 1，导致「新增后看不到」
- 充值汇总恒为 0 —— 硬算当前自然月，改为按所选月份
- 每周汇报图表静默不渲染 —— `#chart-weekly-bar` 容器不存在
- 单个天数复制按钮未绑定事件
- 月度水电区块被误移出月报，已移回

### 变更

- 申购「购买」后同时保留两条记录：原申购记录置为 `purchased`（留档「申请过什么」），另新增 `kind='purchase'` 记录带 `ref_id`，仅勾选「同时添加到物品记录」才累加库存
- Docker 镜像基础环境不变，无需重建；`docker compose pull && docker compose up -d` 即可升级

### 已知限制

- macOS `.app` 为 ad-hoc 签名，未签名应用首次打开可能被 Gatekeeper 拦截，需 `xattr -dr com.apple.quarantine` 或右键 → 打开
- 单窗口截图 `screencapture -l <id>` 在部分 macOS 版本被拒，自动化测试只能用全屏截图 + 裁剪

---

## [0.2.0] — 2026-10-20

- 前端 JS 按功能拆分到 `js/` 目录
- 后端 handler 按业务域拆分到 `modules/`
- 修复模块化重构后登录空白、数据目录错乱等问题

## [0.1.0] — 2026-08-27

首个可用版本：抄表 / 充值 / 报表 / 物品 / 申购 / 工作记录，macOS `.app` 与 Docker 双端部署。
