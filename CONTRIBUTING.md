# 贡献指南

感谢你对 linclub-electricity-stats 的关注！

## 项目结构

```
.
├── Sources/Linca/              # macOS .app 原生应用（Swift + Python）
│   ├── LincaApp.swift          # SwiftUI 入口
│   ├── ServerManager.swift     # Python 子进程管理
│   └── Resources/              # Python 后端 + 前端
│       ├── server.py           # HTTP 服务入口
│       ├── app_handler.py      # 请求处理 + 静态文件服务
│       ├── storage.py          # JSON 文件读写
│       ├── routing.py          # API 路由分发
│       ├── report.py           # 月报/年报计算引擎
│       ├── index.html          # 前端页面
│       ├── style.css           # 样式
│       ├── app.js              # 前端逻辑
│       ├── admin.js            # 管理后台逻辑
│       ├── handlers/           # 各模块 API handler
│       └── utils/              # 工具函数
├── docker/                     # Docker 部署（纯 Web 服务版）
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── server.py               # Docker 适配入口
├── tests/                      # 回归测试
├── build-app.sh                # macOS .app 打包脚本
└── sign-and-notarize.sh        # Developer ID 签名 + 公证
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
# 启动（Web 版，无需 macOS）
docker compose up -d

# 查看日志
docker compose logs -f

# 进入容器调试
docker compose exec linca bash
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

参考 [Conventional Commits](https://www.conventionalcommits.org/)：

```
feat: 添加电表充值功能
fix: 修复月报计算偏移问题
docs: 更新 README 部署章节
refactor: 重构路由模块
test: 添加备份测试
chore: 更新依赖
```

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
