# ============================================================
# 林卡电表统计 — 飞牛 OS (fnOS) 部署指南
# ============================================================
# 此文件提供飞牛 OS 图形化界面部署的完整步骤
# ============================================================

# ---- 方式一：通过 docker-compose.yml 部署（推荐） ----

# 步骤 1：下载 compose 文件
# 1.1 在飞牛 OS 文件管理中，创建目录（如 /docker/linclub）
# 1.2 将 docker-compose.yml 上传到该目录

# 步骤 2：修改配置（可选）
# 2.1 打开 docker-compose.yml
# 2.2 如需修改端口，找到 ports 行：
#       - "8765:8765"  → 修改为 - "你的端口:8765"
#       例如：- "8888:8765" 表示主机 8888 端口映射到容器 8765

# 步骤 3：通过飞牛 OS 部署
# 3.1 打开飞牛 OS 桌面 → 打开"Container Manager"（容器管理）
# 3.2 点击左侧"项目" → 点击"新建"
# 3.3 填写项目名：linclub
# 3.4 项目路径：选择刚才上传 docker-compose.yml 的目录（如 /docker/linclub）
# 3.5 点击"创建" → "启动"

# 步骤 4：访问应用
# 打开浏览器访问：http://你的NAS_IP:8765
# 默认登录：admin / admin123

# ---- 方式二：通过图形化界面手动部署 ----

# 步骤 1：打开 Container Manager → 映像
# 1.1 点击"创建" → "从网址拉取"
# 1.2 填写：
#       映像名称：linclub/electricity-stats
#       标签：latest
# 1.3 点击"确定"等待下载完成
#    （如果下载失败，可在终端执行：docker pull python:3.11-slim 然后重新构建）

# 步骤 2：手动创建容器
# 2.1 点击 Container Manager → 容器 → 创建
# 2.2 基本设置：
#       容器名称：linclub
#       映像：linclub/electricity-stats:latest
#       勾选"启用自动重新启动"

# 2.3 空间 → 端口设置：
#       本地端口：8765
#       容器端口：8765
#       协议：TCP

# 2.4 空间 → 卷设置（重要！数据持久化）：
#       添加挂载点：
#       本地路径：/docker/linclub/data（提前在文件管理中创建）
#       容器路径：/data
#       模式：读写

# 2.5 环境 → 环境变量：
#       添加变量：
#       名称：LINCLUB_INITIAL_PASS
#       值：修改为你想要的密码（如 MyStrongPass123!）
#
#       可选添加：
#       名称：LINCLUB_PORT
#       值：8765（默认端口）

# 2.6 网络 → 网络设置：
#       网络模式：bridge（默认）

# 步骤 3：启动容器
# 点击"完成" → 容器列表中找到 linclub → 点击"启动"

# ---- 方式三：终端命令行部署（适合熟练用户） ----

# 前提：确认 Docker 已安装
$ docker --version

# 步骤 1：创建数据目录
$ mkdir -p /docker/linclub/data

# 步骤 2：创建 docker-compose.yml 文件
$ vi /docker/linclub/docker-compose.yml
# 粘贴以下内容（见下方）

# 步骤 3：启动容器
$ cd /docker/linclub
$ docker compose up -d

# 步骤 4：查看状态
$ docker compose ps
$ docker compose logs -f

# 步骤 5：访问应用
# 浏览器打开：http://NAS_IP:8765

# ============================================================
# docker-compose.yml 内容（方式三需要手动创建）
# ============================================================
# services:
#   linclub:
#     build:
#       context: ./docker
#       dockerfile: Dockerfile
#     container_name: linclub
#     restart: unless-stopped
#     ports:
#       - "8765:8765"
#     volumes:
#       - ./data:/data
#     environment:
#       - LINCLUB_PORT=8765
#       - LINCLUB_DATA_DIR=/data
#       - LINCLUB_BIND=0.0.0.0
#       - LINCLUB_INITIAL_PASS=admin123  # ⚠️ 请修改！
#     healthcheck:
#       test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/health')"]
#       interval: 30s
#       timeout: 5s
#       retries: 3
#       start_period: 10s

# ============================================================
# 常用管理命令
# ============================================================

# 查看容器状态
$ docker compose ps

# 查看实时日志
$ docker compose logs -f

# 停止容器
$ docker compose stop

# 启动容器
$ docker compose start

# 重启容器
$ docker compose restart

# 停止并删除容器
$ docker compose down

# 更新版本（拉取最新代码后）
$ git pull
$ docker compose down
$ docker compose up -d --build

# 进入容器终端调试
$ docker exec -it linclub bash

# 查看数据文件
$ docker exec -it linclub ls -la /data

# ============================================================
# 数据迁移（从 macOS 到飞牛 OS）
# ============================================================

# 1. 在飞牛 OS 上先启动容器（不传数据）
#    让容器初始化 settings.json

# 2. 上传 macOS 数据文件到飞牛 OS
#    可通过 SFTP/FTP 或文件管理器上传
#    macOS 数据位置：~/Library/Application Support/com.linca.electricity-stats/
#    需要上传的文件：
#    - readings.json
#    - charges.json
#    - items.json
#    - purchases.json
#    - settings.json

# 3. 复制到容器内
$ docker cp readings.json linclub:/data/
$ docker cp charges.json linclub:/data/
$ docker cp items.json linclub:/data/
$ docker cp purchases.json linclub:/data/
$ docker cp settings.json linclub:/data/

# 4. 重启容器使数据生效
$ docker compose restart

# 5. 验证数据
$ docker exec -it linclub ls -la /data

# ============================================================
# 常见问题排查
# ============================================================

## Q1：容器启动后访问 404 或拒绝连接

**排查步骤：**
1. 检查容器状态：`docker compose ps` 看是否是 healthy
2. 查看日志：`docker compose logs` 看是否有错误
3. 确认端口没有被占用：在飞牛 OS 终端执行 `netstat -tlnp | grep 8765`
4. 如果端口被占，修改 docker-compose.yml 的端口映射

## Q2：数据丢失或为空

**原因：** 忘记挂载数据目录

**解决：**
1. 停止容器：`docker compose stop`
2. 检查是否挂载了持久化目录
3. 重新挂载 /data 到本地目录
4. 启动容器：`docker compose start`

## Q3：无法通过浏览器访问

**排查步骤：**
1. 确认飞牛 OS 防火墙允许 8765 端口
2. 尝试在同一 NAS 上访问：http://127.0.0.1:8765
3. 检查 IP 地址是否正确：`ip addr show`
4. 尝试 ping NAS IP：`ping 你的NAS_IP`

## Q4：Docker 映像拉取失败

**原因：** 网络问题或镜像源限制

**解决：**
```bash
# 方法 1：使用国内镜像源
docker pull registry.cn-hangzhou.aliyuncs.com/library/python:3.11-slim

# 方法 2：在 Container Manager 中更换镜像源为阿里云
# 设置 → Docker → 镜像加速器 → 添加阿里云地址
```

## Q5：修改密码后忘记

**解决：**
1. 进入容器终端：`docker exec -it linclub bash`
2. 查看 /data/settings.json
3. 修改密码哈希（需要先重新生成哈希）
4. 或者重置为默认：
   ```bash
   docker compose down
   rm -rf /docker/linclub/data
   docker compose up -d
   ```

## Q6：数据迁移后权限问题

**解决：**
```bash
# 进入容器
docker exec -it linclub bash

# 修改文件权限
chown linclub:linclub /data/*.json

# 退出并重启
exit
docker compose restart
```

## Q7：容器日志已满

**解决：**
1. 在飞牛 OS Container Manager 中：
   - 容器 → linclub → 日志
   - 点击"清空日志"
2. 或限制日志大小，修改 docker-compose.yml：
   ```yaml
   logging:
     driver: "json-file"
     options:
       max-size: "10m"
       max-file: "3"
   ```

## Q8：飞牛 OS 自动更新后 Docker 失效

**解决：**
1. 更新后重启 Docker 服务
2. 确认容器自动重启（启用"自动重新启动"选项）
3. 如未自动启动，手动启动容器

# ============================================================
# 安全建议
# ============================================================

1. **首次登录后立即修改默认密码**
2. **修改默认端口**（8765 → 其他端口如 8888）
3. **启用 HTTPS**（飞牛 OS 支持反代 + SSL 证书）
4. **限制访问 IP**（在路由器防火墙中设置）
5. **定期备份数据**（/docker/linclub/data 目录）

# ============================================================
# 备份与恢复
# ============================================================

## 备份
```bash
# 方法 1：直接复制数据目录
cp -r /docker/linclub/data /docker/linclub/data_backup_$(date +%Y%m%d)

# 方法 2：使用 docker compose
docker exec -it linclub tar czf /tmp/linclub-backup.tar.gz -C /data .
docker cp linclub:/tmp/linclub-backup.tar.gz /docker/linclub-backup.tar.gz
```

## 恢复
```bash
# 停止容器
docker compose stop

# 删除旧数据
rm -rf /docker/linclub/data

# 恢复备份
tar xzf /docker/linclub-backup.tar.gz -C /docker/linclub/data/

# 重启容器
docker compose start
```

# ============================================================
# 📦 从 macOS 数据迁移到飞牛 OS（完整步骤）
# ============================================================

## 场景说明

你在 macOS 上使用过「工程部管理系统.app」，数据存储在：
```
~/Library/Application Support/com.linca.electricity-stats/
├── readings.json       ← 抄表记录
├── charges.json        ← 充值记录
├── items.json          ← 物品库存
├── purchases.json      ← 申购记录
└── settings.json       ← 用户和配置
```

现在要把这些数据迁移到飞牛 OS 的 Docker 容器中。

---

## 方法一：通过文件管理器上传（推荐，最直观）

### 第 1 步：从 macOS 导出数据文件

1. 打开 macOS **Finder**
2. 按下 `Cmd + Shift + G`（前往文件夹）
3. 输入路径：
   ```
   ~/Library/Application Support/com.linca.electricity-stats/
   ```
4. 找到以下文件，复制到桌面或其他临时位置：
   - `readings.json`
   - `charges.json`
   - `items.json`
   - `purchases.json`
   - `settings.json`

### 第 2 步：上传到飞牛 OS

1. 打开飞牛 OS 桌面 → **文件管理器**
2. 找到或创建目录：`/docker/linclub/data/`
3. 将刚才从 macOS 复制的 5 个 `.json` 文件上传到该目录

### 第 3 步：启动 Docker 容器

如果还没有启动容器，按以下方式：

**Container Manager → 项目 → 创建新项目：**
- 项目名：`linclub`
- 项目路径：`/docker/linclub/`（包含 docker-compose.yml）
- 启动项目

### 第 4 步：验证数据

```bash
# 进入飞牛 OS 终端
docker exec -it linclub ls -la /data
docker exec -it linclub cat /data/readings.json | head -20
```

应该能看到你的抄表记录。

---

## 方法二：通过 SFTP/FTP 上传

1. 在飞牛 OS 中启用 **SFTP 服务**（控制面板 → 文件服务 → SFTP）
2. 使用 FileZilla、WinSCP 或 Termius 等工具连接
   - 主机：你的飞牛 OS IP
   - 端口：22（默认）
   - 用户名/密码：你的飞牛 OS 登录账号
3. 连接后导航到 `/docker/linclub/data/`
4. 拖拽上传 macOS 导出的 5 个 `.json` 文件

---

## 方法三：通过 docker cp 命令（最快捷）

如果飞牛 OS 终端可以直接访问：

### 第 1 步：准备数据

在 macOS 上，将数据文件放到一个临时目录：

```bash
# macOS 终端
mkdir -p ~/linca-migration
cp ~/Library/Application\ Support/com.linca.electricity-stats/*.json ~/linca-migration/
```

### 第 2 步：上传到飞牛 OS

```bash
# macOS 终端执行（替换 NAS_IP 为你的飞牛 OS IP）
scp ~/linca-migration/*.json admin@NAS_IP:/tmp/linca-data/
```

### 第 3 步：复制到容器内

```bash
# 飞牛 OS 终端执行
docker cp /tmp/linca-data/readings.json linclub:/data/
docker cp /tmp/linca-data/charges.json linclub:/data/
docker cp /tmp/linca-data/items.json linclub:/data/
docker cp /tmp/linca-data/purchases.json linclub:/data/
docker cp /tmp/linca-data/settings.json linclub:/data/
```

### 第 4 步：重启容器

```bash
docker compose restart
```

---

## 迁移后验证清单

| 检查项 | 命令 | 应该看到 |
|--------|------|----------|
| 数据文件存在 | `docker exec linclub ls -la /data` | 5 个 `.json` 文件 |
| 抄表记录 | `docker exec linclub python3 -c "import json; print(len(json.load(open('/data/readings.json'))))"` | 你的抄表条数 |
| 充值记录 | `docker exec linclub python3 -c "import json; print(len(json.load(open('/data/charges.json'))))"` | 你的充值条数 |
| 物品库存 | `docker exec linclub python3 -c "import json; print(len(json.load(open('/data/items.json'))))"` | 你的物品数 |
| 申购记录 | `docker exec linclub python3 -c "import json; print(len(json.load(open('/data/purchases.json'))))"` | 你的申购条数 |
| 用户配置 | `docker exec linclub cat /data/settings.json` | 你的用户信息 |

---

## ⚠️ 注意事项

1. **settings.json 包含用户密码哈希**，迁移后会保留你的账号密码，无需重新设置
2. **确保覆盖而非新建**，上传文件时要选择「覆盖已存在文件」
3. **如果提示权限问题**，在飞牛 OS 终端执行：
   ```bash
   docker exec -it linclub chown linclub:linclub /data/*.json
   ```
4. **迁移完成后建议做一次备份**：
   ```bash
   docker exec -it linclub python3 -c "
   import json
   with open('/data/settings.json') as f:
       s = json.load(f)
   print(f'用户: {[u[\"username\"] for u in s.get(\"users\", [])]}')
   "
   ```

---

## 迁移完成后

1. 打开浏览器访问：`http://NAS_IP:8765`
2. 使用原来的账号密码登录
3. 检查所有数据是否正常显示
4. 确认月度报告等计算功能正常
5. 建议登录后台修改默认密码（如果之前没改过）

