# 贡献指南

感谢你对 meter-stats 的关注！

## 项目结构

```
.
├── MeterStats/                      # macOS .app 原生应用（Swift + Python）
│   ├── MeterStatsApp.swift          # SwiftUI 入口
│   ├── ServerManager.swift          # Python 子进程管理
│   ├── server.py                    # HTTP 服务入口
│   ├── app_handler.py               # 请求处理 + 静态文件服务
│   ├── storage.py                   # JSON 文件读写
│   ├── routing.py                   # API 路由分发
│   ├── report.py                    # 月报/年报计算引擎
│   ├── index.html                   # 前端页面
│   ├── style.css                    # 样式
│   ├── admin.js                     # 管理后台逻辑（弹窗/设置）
│   ├── js/                          # 前端模块（core/helpers/modules/shared）
│   ├── modules/                     # 各业务域 API（readings/charges/items/...）
│   └── utils/                       # 工具函数
├── docker/                          # Docker 部署（纯后端服务版）
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── entrypoint.sh                # Docker 适配入口
├── tests/                           # 回归测试
├── build-app.sh                     # macOS .app 打包脚本
└── sign-and-notarize.sh             # Developer ID 签名 + 公证
```

## 开发环境

### macOS 原生开发

```bash
# 前置条件
# - macOS 14+
# - Xcode 16+ (Swift 5.9+)
# - Python 3 (系统自带 /usr/bin/python3)

# 运行回归测试
python3 -m unittest discover -s tests -v

# Build .app
./build-app.sh release

# Build + 安装到 ~/Applications
./build-app.sh release --install
```

### Docker 开发

```bash
# 启动（无需 macOS)）
docker compose up -d

# 查看日志
docker compose logs -f

# 进入容器调试
docker compose exec meter-stats bash
```

## 贡献流程

1. **Fork** 本仓库
2. **创建特性分支**：`git checkout -b feature/my-feature`
3. **提交改动**：`git commit -am 'Add: 说明改动内容'`
4. **推送到分支**：`git push origin feature/my-feature`
5. **提交 Pull Request**

## 代码规范

- Python 代码使用 Python 3.10+ 语法
- 缩进：4 空格
- 文件编码：UTF-8
- 函数/变量命名：snake_case
- 常量命名：UPPER_SNAKE_CASE
- 类命名：PascalCase

## 提交规范

参考 [Conventional Commits](https://www.conventionalcommits.org/)。

仓库根目录有 `.gitmessage` 模板文件,已配置为 git 的 commit template,
运行 `git commit` 时会自动加载。模板里有详细说明和示例。

### 格式

```
<type>(<scope>): <subject>      ← 必填,首行 ≤ 50 字符
<空行>
<body>                          ← 选填,描述改动动机和效果
<空行>
影响范围(选填,release notes 会解析):
  - web: ...
  - macOS: ...
  - docker: ...
  - 双端: ...
```

### type 必填

| type | 说明 | 影响 release notes 分类 |
|---|---|---|
| `feat` | 新功能 | ✨ feat |
| `fix` | 问题修复 | 🐛 fix |
| `perf` | 性能优化 | ⚡ perf |
| `refactor` | 重构(非功能) | ♻️ refactor |
| `docs` | 文档 | 📖 docs |
| `ci` | CI/CD | 🚀 ci |
| `build` | 构建系统 | 📦 build |
| `test` | 测试 | ✅ test |
| `chore` | 其他杂项 | 🔧 chore |

### scope 选填

用于标识改动的影响范围,会让 release notes **按 scope 二级分组**:

| scope | 说明 | release notes 显示 |
|---|---|---|
| `web` / `frontend` | macOS 前端 | 🍎 macOS 前端 |
| `macos` / `mac` / `mac-app` | macOS 原生 App | 🍎 macOS 原生 App |
| `docker` / `container` | Docker 部署 | 🐳 Docker 部署 |
| `backend` / `server` | 后端 Python | 📦 backend |
| `deploy` / `release` | 部署/CDN | 🚀 部署/CDN |
| `ci` / `workflow` | GitHub Actions | 🚀 CI/CD |

### 示例

```
feat(charges): 支持批量导入历史充值记录

用户反馈需要从 Excel 批量导入历史充值数据,
避免手工逐条录入。

修复:
  1. 新增 POST /api/charges/batch,接受 JSON 数组
  2. 前端 charges-batch.html 上传 Excel 解析后调用

影响范围:
  - macOS: 需要重新安装应用
  - 双端: 后端 API 升级,需重启服务

验证步骤:
  1. 准备 5 条 JSON 测试数据
  2. POST /api/charges/batch 看是否全部写入
  3. 页面刷新看 charges 列表
```

### 简写(type only,scope 省略)

不重要的改动可以省略 scope,会落入"未分类"子节:

```
fix: 拼写错误
chore: 清理调试代码
```

### 一次性 type(scope)

`git commit` 没设 hook 时,如果你不想用模板,可以手动写。
编辑器注释行(`#` 开头)在 commit 时会被 git 自动删除。

## 发布清单（发版前逐项过）

> 大部分条目**已经有测试兜底**(见每行末尾),跑一遍 `python3 -m unittest discover -s tests` 即可;
> 没兜底的几条需要人看一眼。清单本身不要写成"记得检查"——凡是能写成断言的都写成了断言。

| # | 检查项 | 怎么验 |
|---|---|---|
| 1 | **VERSION 与 CHANGELOG 顶部章节一致** | `tests/test_docs_consistency.py::TestVersionConsistency` |
| 2 | **新功能能在 README 里找到入口**:功能表加了行没有? | `tests/test_docs_consistency.py::TestCapabilitiesAreDiscoverable` |
| 3 | **结构树与真实目录一致**:新增 `modules/xxx/` 或顶层 `*.py` 必须同步两份文档 | `tests/test_docs_consistency.py::TestStructureTreesMatchReality` |
| 4 | **文档里的用例数/测试文件数是真的**(改完测试记得更新) | `tests/test_docs_consistency.py::TestDocumentedCountsAreReal` |
| 5 | **打包链路仍是枚举 `*.py`**,没退回硬编码清单 | `tests/test_docs_consistency.py::TestPackagingStaysGeneric` |
| 6 | **单个文档没长成"实施计划"**(>2000 行要归档/拆分) | `tests/test_docs_consistency.py::TestDocsDoNotBlowUp` |
| 7 | 口径回归:**2026-06 月报 = 71226.1 度** | `tests/test_monthly_report.py` |
| 8 | 全量测试绿(CI 会跑 Python 3.9 + 3.11 两条腿) | `python3 -m unittest discover -s tests -v` |
| 9 | 新增顶层模块/静态资源后,**本地构建一次 .app 并启动** | `./build-app.sh release`(先备份生产数据,`--install` 会清 Application Support) |
| 10 | 改了口径/权限/备份规则 → CHANGELOG 要写清**根因与症状**,不只写"修复 X" | 人工 |
| 11 | 推送 `main` 后确认三条流水线绿 | `gh run list`(测试 / Docker 镜像 / DMG Release) |
| 12 | 推送后抽查发布结果 | `curl -s <host>/api/version`、`docker pull zz3656/meter-stats:latest`、GitHub Releases 页面 |

**为什么第 2/3 条重要**:2026-11-27 出现过「多门店功能已上线、CHANGELOG 写得很全,但 README
一个字都没提、结构树还缺 `modules/stores/`」——功能做完了门面没跟上,用户以为没这个功能。
现在这两条由测试守着,漏了会直接红。

## 报告问题

请使用 GitHub Issues 报告问题，包含：

- 运行方式（.app 或 Docker）
- 复现步骤
- 期望行为 vs 实际行为
- 错误日志或截图

## 功能建议

欢迎提交 Feature Request，建议包含：

- 使用场景描述
- 方案建议（如果有）
- 优先级说明

## 代码审查

所有 PR 需要至少一个 Review 才能合并。我们关注：

- 代码正确性
- 安全性（特别是认证/权限相关改动）
- 向后兼容性
- 文档更新
