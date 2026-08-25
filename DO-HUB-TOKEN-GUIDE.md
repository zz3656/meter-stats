# GitHub Actions 自动构建多平台镜像 — 配置说明

## 第 1 步：创建 Docker Hub Access Token

1. 打开 https://hub.docker.com
2. 点击右上角头像 → **Account Settings**
3. 左侧菜单 → **Security**
4. 点击 **New Access Token**
5. 名称填：`GitHub CI`
6. 权限：Read & Write
7. 点击 **Create**
8. 复制 Token（格式：`dckr_pat_xxxxxxxx`）

## 第 2 步：在 GitHub 仓库添加 Secret

1. 打开 https://github.com/zz3656/linclub-electricity-stats
2. 点击 **Settings**（设置）
3. 左侧菜单 **Secrets and variables** → **Actions**
4. 点击 **New repository secret**
5. 填写：
   - **Name**: `DOCKERHUB_TOKEN`
   - **Secret**: 粘贴刚才复制的 Token
6. 点击 **Add secret**

## 第 3 步：手动触发构建

1. 进入 GitHub 仓库 → **Actions** 标签
2. 点击 **Build and Push Docker Image**
3. 点击 **Run workflow** 按钮
4. 点击绿色的 **Run workflow** 确认

## 第 4 步：等待构建完成

构建大约需要 5-8 分钟。完成后 Docker Hub 会自动包含：
- `linux/amd64` — x86_64 架构（飞牛 OS 用这个）
- `linux/arm64` — ARM 架构（Mac M1/M2/M3、树莓派 4 用这个）

## 第 5 步：验证

打开 https://hub.docker.com/r/zz3656/linclub-electricity-stats/tags

你会看到 `latest` 标签旁边显示：
```
linux/amd64, linux/arm64
```

## 之后每次推送代码

workflow 会自动运行，构建并推送新镜像，无需手动操作。
