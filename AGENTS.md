# 📊 工程部管理系统 — Meter Stats

> 面向酒吧工程部的电表数据管理工具。Python 后端 (零 pip 依赖) + 纯 HTML/CSS/JS 前端，支持 macOS .app、Docker 双端部署。所有端共享同一套后端代码 (`MeterStats/`)。

## 运行与构建

| 操作 | 命令 |
|------|------|
| 启动本地服务 | `cd MeterStats && ./run.sh start` (端口 8765, 数据在 `MeterStats/.data/`) |
| 停止服务 | `./run.sh stop` |
| 重启服务 | `./run.sh restart` |
| 查看日志 | `./run.sh logs` |
| Docker 启动 | `docker compose up -d` (镜像 `zz3656/meter-stats`) |
| 单元测试 | `python3 -m unittest discover -s tests -v` (147 tests, ~2s) |
| 构建 macOS .app | `./build-app.sh release --install` (需要 Xcode) |
| Ruff 检查 | `ruff check .` (line-length 100, ignore E501) |
| MyPy 类型检查 | `mypy .` (strict mode, py39) |

**环境变量**: `METER_PORT`(默认 8765), `METER_DATA_DIR`(数据目录), `METER_BIND`(默认 0.0.0.0), `METER_INITIAL_PASS`(首次启动 admin 密码)。完整列表见 README.md。

## 项目结构

```
MeterStats/
├── server.py              # 入口, ThreadingHTTPServer
├── storage.py             # 存储层: JSON 读写 + 原子写入 + 行级锁
├── app_handler.py         # HTTP handler, 路由分发
├── routing.py             # URL → handler 映射
├── constants.py           # 常量定义
├── modules/               # API 处理模块(按业务域拆目录)
│   ├── _base.py           # JsonModelHandler 基类
│   ├── readings/          # 抄表 + 水电表底
│   ├── charges/           # 充值
│   ├── items/             # 物品 + 借还流水
│   ├── purchases/         # 申购流程
│   ├── duty/              # 值班记录 + 图片上传
│   ├── reports/           # 报表生成
│   ├── backup/            # 备份/恢复/NAS 同步
│   ├── system/            # 设置/用户/权限/鉴权
│   └── utilities/         # 水电计算
├── utils/
│   ├── api.py             # send_json / read_body / CORS 工具
│   └── audit.py           # 审计日志
├── js/                    # 前端 JS (无构建步骤)
│   ├── core/              # api / init / navigation / state / meterConfig
│   ├── helpers/utils.js   # 压缩图片 / 字段图片组件 / 格式化
│   ├── modules/           # 业务模块 + render_*.js + modal_bindings.js
│   ├── shared/            # modals / theme / toast / accessibility / image_settings
│   └── nas_sync.js        # NAS 远端同步
├── index.html             # SPA 入口
├── style.css              # 主题变量 + 响应式
├── admin.js               # 管理页逻辑(仍保留)
└── VERSION                # 版本文件 (server.py 启动时读取)
```

## 关键约定

- **后端**: Python 3.9+, `from __future__ import annotations`, 零外部依赖。用 `http.server.ThreadingHTTPServer`。
- **存储**: JSON 文件 + 原子写入 (写 tmp 再 rename) + `threading.Lock` 行级锁。数据目录: Docker 用 `METER_DATA_DIR`(默认 `/data`), macOS `.app` 用 `~/Library/Application Support/com.meter.stats/`, 本地源码运行用 `MeterStats/.data/`。
- **前端**: 纯 HTML/CSS/JS, 无构建步骤。Chart.js 通过 CDN 加载。JS 文件按功能拆到 `js/` 目录,在 `index.html` 中 `<script>` 引入。
- **提交规范**: 约定式提交 (feat/fix/refactor/docs/style/scope)。`./run.sh` 首次运行自动设置 `.gitmessage` 为 commit template。
- **版本号**: 唯一来源是 `MeterStats/VERSION`。**只在推送前确定一次**——开发过程中反复改动不要逐次递增版本号,等用户本地测试通过、准备提交推送时再统一敲定并合并 `CHANGELOG.md` 章节。递增规则:小幅更新末位 +1,破坏性更新中间位 +1;GitHub Release 与 Docker 镜像标签由 CI 依据此文件自动发布,不要新建其他 VERSION 文件。`Dockerfile` 会把 `VERSION` 复制进镜像,`server.py` 启动时读取并经公开接口 `GET /api/version` 暴露;CI 同时推 `latest` 与 `0.4.x` 两个标签(同一 digest)。
- **Docker 升级**: 必须显式 `docker compose pull && docker compose up -d`——Docker **从不会主动检查远端仓库**,本地已有镜像时 `up -d` 既不提示也不拉取(所以"没有新版本提示"是 Docker 的设计行为,不是故障);`docker compose down && up` 同样不会拉新镜像。仓库根脚本 `scripts/docker-update.sh` 封装了 pull + up + 打印更新前后版本号,兼容 Compose v1/v2。`docker/docker-compose.yml` 用 `zz3656/meter-stats:latest`(部署用),仓库根 `docker-compose.yml` 用 `meter-stats:local`(本地构建,`pull` 会失败)。`pull_policy: always` 仅 Compose v2 支持,写在注释里按需开启。
- **接口鉴权 (v0.4.1 起)**: 统一在 `routing.py` 的 `_auth_gate()` 拦截,挂在 `_route()` 这个唯一入口上——**新增接口默认就带鉴权,不需要单独加**。白名单只有 `GET /api/health`(Docker HEALTHCHECK / run.sh 探测 / 登录页健康检查)、`GET /api/version`(登录页未登录也要显示版本号)、`POST /api/auth/login`(取 token 的入口);要新增公开接口必须显式加进 `PUBLIC_API_PATHS`,并同步确认 `tests/test_auth_enforcement.py` 的预期。角色分层:任何登录用户可读/录入,`DELETE` 需主管或管理员,`/api/admin/users` 仅管理员(否则任何登录用户能建管理员账号自我提权),审计/数据文件/目录列表/NAS 同步/备份删除/电价配置/图片目录等管理接口需主管及以上。token 由 `permissions_handler._get_token()` 依次尝试 Cookie → `?token=` → `Authorization: Bearer`,所以 `<img src>` / `<a href>` 这类拿不到请求头的访问必须把 token 拼进 query。前端**只能**通过 `admin.js` 的 `currentAuthToken()` 取 token——历史上有 `token` / `meter_admin_token` / `meter_token` 三套键名,后两个是死键(导致刷新掉登录、备份下载永远不带 token),不要再直接读 localStorage。`ENFORCE_AUTH` 只给单元测试关业务回归的鉴权用,生产不读环境变量。
- **充值与用电口径**: 预付费表表底下降=用电、上升=刚到账。充值记录的 `date` 是**申请日**,真正到账时间看 `confirmed_at`(11-02 提申请、11-03 打款到账)。用电归属按 `report.py::_charge_attribution()`(前端 `meterConfig.js::chargeAttribution()`,两套规则必须保持一致)把每笔充值归到它实际到账的抄表区间:到账日当天抄表且表底上升→归上一段;当天没上升→归下一段;到账日落在两段中间→归该区间;之后没抄表→暂不归属。**不要**再用日期窗口 `(上次,本次]` 硬切——那会把刚充进表、一度还没用的余额当成已用电量,日均被顶高几十倍(实际事故:大厅 656 度/天被算成 34256 度/天)。归月统计一律走 `chargeEffectiveDate()`(已确认取 `confirmed_at`,否则取 `date`)。口径变更必须先用 2026 年 6 月 Excel 核对值 **71226.1 度** 回归验证。待确认(`status: pending`)的充值不计入任何统计。
- **测试**: `tests/` 下 10 个测试文件, 147 个用例。运行: `python3 -m unittest discover -s tests -v`。业务回归在 `TestApiBase.setUp` 里显式关闭鉴权开关;鉴权与限速分别由 `test_auth_enforcement.py`、`test_login_rate_limit.py` 覆盖。

## Pitfalls

1. **数据目录不要手动改 JSON**: `storage.py` 依赖原子写入保证一致性,手改会破坏。崩溃后从 `backup/` 自动恢复,但手改内容会被覆盖。
2. **端口 8765 可能冲突**: 用 `./run.sh status` 检查,或被占用时通过 `METER_PORT=8888` 改端口。
3. **macOS 未签名应用首次打开被拦**: ad-hoc 签名,需 `xattr -dr com.apple.quarantine "/Applications/MeterStats.app"` 或右键→打开。
4. **Docker 数据持久化**: 容器用 `meter-data:/data` 卷,升级只需 `docker pull && docker compose down && up -d`,数据不丢。
5. **忘记密码**: 删除 `./data/settings.json` 后重启,密码回到默认 `admin123`。
6. **JS 文件拆分后**: 旧的 `app.js`/`admin.js` 仍存在,新代码在 `js/*.js`。修改前端注意两个入口都可能加载了旧文件。
7. **`.data/` 目录被 gitignore**: 本地运行时数据在 `MeterStats/.data/`,不会被提交,但会被 `.server.log` 旁边的备份机制保护。
8. **`build-app.sh` 会清 Application Support**: `./build-app.sh release --install` 会先 `rm -rf ~/Library/Application Support/com.meter.stats/`(内含真实生产数据),它自带的 `.data` 备份步骤带 `2>/dev/null`,静默失败也照删——**跑之前必须另做一份独立备份并事后逐文件比对**。该脚本在 `.gitignore` 内,改动只对本机生效。登录限速计数在内存里,重启应用即解除锁定。
