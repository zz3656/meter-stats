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
| 单元测试 | `python3 -m unittest discover -s tests -v` (88 tests, ~1s) |
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
- **测试**: `tests/` 下 5 个测试文件, 88 个用例。运行: `python3 -m unittest discover -s tests -v`。

## Pitfalls

1. **数据目录不要手动改 JSON**: `storage.py` 依赖原子写入保证一致性,手改会破坏。崩溃后从 `backup/` 自动恢复,但手改内容会被覆盖。
2. **端口 8765 可能冲突**: 用 `./run.sh status` 检查,或被占用时通过 `METER_PORT=8888` 改端口。
3. **macOS 未签名应用首次打开被拦**: ad-hoc 签名,需 `xattr -dr com.apple.quarantine "/Applications/MeterStats.app"` 或右键→打开。
4. **Docker 数据持久化**: 容器用 `meter-data:/data` 卷,升级只需 `docker pull && docker compose down && up -d`,数据不丢。
5. **忘记密码**: 删除 `./data/settings.json` 后重启,密码回到默认 `admin123`。
6. **JS 文件拆分后**: 旧的 `app.js`/`admin.js` 仍存在,新代码在 `js/*.js`。修改前端注意两个入口都可能加载了旧文件。
7. **`.data/` 目录被 gitignore**: 本地运行时数据在 `MeterStats/.data/`,不会被提交,但会被 `.server.log` 旁边的备份机制保护。
