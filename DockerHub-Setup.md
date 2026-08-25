# Docker Hub 部署步骤
# ===================

## 方式一：通过 GitHub Actions 自动推送（推荐）

### 第 1 步：创建 Docker Hub Access Token

1. 登录 Docker Hub: https://hub.docker.com
2. 点击右上角头像 → **Account Settings**
3. 左侧菜单 → **Security**
4. 点击 **New Access Token**
5. 填写名称（如 "GitHub CI"），权限选 **Read & Write**
6. 点击 **Create**，复制 Token（类似 `dckr_pat_xxxxxxxx`）

### 第 2 步：在 GitHub 仓库添加 Secret

1. 打开仓库: https://github.com/zz3656/linclub-electricity-stats
2. 点击 **Settings** → **Secrets and variables** → **Actions**
3. 点击 **New repository secret**
4. 填写：
   - **Name**: `DOCKERHUB_TOKEN`
   - **Secret**: 粘贴刚才复制的 Docker Hub Token
5. 点击 **Add secret**

### 第 3 步：触发构建

有两种方式触发：

**方式 A：手动触发（推荐首次）**
- 进入 GitHub 仓库 → **Actions** 标签
- 点击 **Build and Push Docker Image** workflow
- 点击 **Run workflow** 下拉箭头
- 点击绿色的 **Run workflow** 按钮
- 等待几分钟完成

**方式 B：自动触发**
- 每次推送代码到 main 分支，workflow 自动运行

### 第 4 步：查看构建日志

- 进入 GitHub 仓库 → **Actions** 标签
- 点击最新的 workflow run
- 查看详细构建日志

### 第 5 步：验证推送

访问: https://hub.docker.com/r/zz3656/linclub-electricity-stats

---

## 方式二：本地构建并推送

### 前提条件

需要安装 Docker。

**macOS:**
```bash
brew install docker
brew services start docker
```

**Windows:** 安装 Docker Desktop

**Linux (Ubuntu):**
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

### 第 1 步：登录 Docker Hub

```bash
docker login
# 用户名: zz3656
# 密码或 Access Token
```

### 第 2 步：运行构建脚本

```bash
# 方法 A：使用脚本（推荐）
./docker-build-push.sh latest

# 方法 B：手动构建和推送
cd docker
docker build -t zz3656/linclub-electricity-stats:latest .
docker push zz3656/linclub-electricity-stats:latest
```

---

## 在飞牛 OS 上使用推送的镜像

更新 `/docker/linclub/docker-compose.yml`：

```yaml
services:
  linclub:
    image: zz3656/linclub-electricity-stats:latest  # 从 Docker Hub 拉取
    container_name: linclub
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - ./data:/data
    environment:
      - LINCLUB_INITIAL_PASS=your-password
```

然后启动：

```bash
cd /docker/linclub
docker compose up -d
```
