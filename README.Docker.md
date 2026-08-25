# 林卡电表统计 — Docker 部署指南

## 目录结构

```
newproject/
├── docker-compose.yml        # Docker Compose 配置（根目录）
├── docker-run.sh             # 快捷启动脚本
├── docker/                   # Docker 应用目录
│   ├── Dockerfile            # Docker 镜像定义
│   ├── docker-compose.yml    # Docker Compose 配置（Docker 目录内）
│   ├── .dockerignore         # Docker 忽略文件
│   ├── server.py             # 后端入口（已适配 Docker）
│   ├── app_handler.py        # HTTP 处理层
│   ├── storage.py            # 存储层
│   ├── routing.py            # 路由分发
│   ├── report.py             # 月报计算引擎
│   ├── index.html            # 前端页面
│   ├── style.css             # 样式
│   ├── app.js                # 前端脚本
│   ├── admin.js              # 管理前端脚本
│   ├── handlers/             # 路由处理器
│   └── utils/                # 工具函数
└── README.Docker.md          # 本文档
```

## 快速开始

### 方式一：使用快捷脚本（推荐）

```bash
# 启动
./docker-run.sh up

# 查看日志
./docker-run.sh logs

# 停止
./docker-run.sh down

# 重新构建
./docker-run.sh rebuild

# 查看状态
./docker-run.sh status
```

### 方式二：直接使用 docker compose

```bash
# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down

# 重新构建
docker compose up -d --build
```

## 访问地址

| 用途 | URL |
|---|---|
| 管理界面 | http://localhost:8765 |
| 健康检查 | http://localhost:8765/api/health |
| CSV 导出 | http://localhost:8765/api/export?models=readings,charges |

## 默认账户

| 用户名 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | 管理员 |

**⚠️ 请首次登录后立即修改密码！**

## 修改默认密码

编辑 `docker-compose.yml`，修改环境变量：

```yaml
environment:
  - LINCLUB_INITIAL_PASS=your-secure-password
```

然后重新创建容器：

```bash
docker compose down
docker compose up -d --build
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LINCLUB_PORT` | `8765` | 服务端口 |
| `LINCLUB_DATA_DIR` | `/data` | 数据持久化目录 |
| `LINCLUB_BIND` | `0.0.0.0` | 绑定地址 |
| `LINCLUB_INITIAL_ADMIN` | `admin` | 初始管理员用户名 |
| `LINCLUB_INITIAL_PASS` | `admin123` | 初始管理员密码 |

## 数据持久化

数据存储在 Docker Volume `linclub-data` 中：

```bash
# 查看数据目录内容
docker compose exec linclub ls -la /data

# 导出所有数据
docker compose exec linclub tar czf /tmp/linclub-data.tar.gz -C /data .
docker cp linclub:/tmp/linclub-data.tar.gz ./linclub-data-backup.tar.gz

# 备份 Volume
docker run --rm -v linclub-data:/source -v $(pwd):/backup alpine tar czf /backup/linclub-backup.tar.gz -C /source .
```

## 端口冲突

如果端口 8765 被占用，修改 `docker-compose.yml`：

```yaml
ports:
  - "8766:8765"   # 主机 8766 → 容器 8765
```

或者通过环境变量：

```yaml
environment:
  - LINCLUB_PORT=8766
```

## Nginx 反向代理（可选）

如果需要 HTTPS 或反向代理，使用以下配置：

```nginx
server {
    listen 80;
    server_name linclub.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name linclub.example.com;

    ssl_certificate     /etc/ssl/certs/linclub.crt;
    ssl_certificate_key /etc/ssl/private/linclub.key;

    location / {
        proxy_pass http://localhost:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 从 macOS 应用迁移数据

如果你已有 macOS 应用的本地数据，可以迁移到 Docker：

```bash
# 1. 找到 macOS 数据目录
# ~/Library/Application Support/com.linclub.electricity-stats/

# 2. 将数据文件复制到 Docker volume
docker cp ~/Library/Application\ Support/com.linclub.electricity-stats/readings.json linclub:/data/
docker cp ~/Library/Application\ Support/com.linclub.electricity-stats/charges.json linclub:/data/
docker cp ~/Library/Application\ Support/com.linclub.electricity-stats/items.json linclub:/data/
docker cp ~/Library/Application\ Support/com.linclub.electricity-stats/purchases.json linclub:/data/
docker cp ~/Library/Application\ Support/com.linclub.electricity-stats/settings.json linclub:/data/

# 3. 修复文件权限
docker compose exec linclub chown linclub:linclub /data/*.json
```

## 故障排查

### 容器无法启动

```bash
# 查看错误日志
docker compose logs

# 进入容器调试
docker compose exec linclub bash
```

### 数据目录为空

```bash
# 检查 volume 挂载
docker volume inspect linclub_linclub-data

# 进入容器查看
docker compose exec linclub ls -la /data
```

### 健康检查失败

```bash
# 手动测试健康端点
curl http://localhost:8765/api/health

# 查看容器健康状态
docker inspect --format='{{json .State.Health}}' linclub | python3 -m json.tool
```

### 完全重置（⚠️ 删除所有数据）

```bash
docker compose down -v   # 删除容器和数据卷
docker compose up -d
```

## 生产部署建议

1. **修改默认密码** — 设置强密码环境变量
2. **使用 HTTPS** — 添加 Nginx 反向代理 + Let's Encrypt
3. **定期备份** — 使用 cron 或 systemd timer 备份 data volume
4. **限制访问** — 使用防火墙或 VPN 限制 IP 访问
5. **日志管理** — 配置 Docker logging driver 限制日志大小

## Docker 原生构建（不进 compose）

```bash
# 构建镜像
cd docker
docker build -t linclub/electricity-stats .

# 运行容器
docker run -d \
  --name linclub \
  -p 8765:8765 \
  -v linclub-data:/data \
  -e LINCLUB_INITIAL_PASS=your-password \
  --restart unless-stopped \
  linclub/electricity-stats
```
