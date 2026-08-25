#!/bin/bash
# ============================================================
# 林卡电表统计 — Docker 镜像构建和推送到 Docker Hub
# ============================================================
# 用法: ./docker-build-push.sh [tag]
# 例如: ./docker-build-push.sh v0.1.0
#       ./docker-build-push.sh latest
# ============================================================

set -e

# 配置
IMAGE_NAME="zz3656/linclub-electricity-stats"
DOCKER_DIR="docker"
TAG="${1:-latest}"

echo "=================================================="
echo " 林卡电表统计 — Docker 镜像构建"
echo "=================================================="
echo ""
echo "镜像名称: ${IMAGE_NAME}"
echo "标签版本: ${TAG}"
echo "构建目录: ${DOCKER_DIR}/"
echo ""

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    echo "   macOS: brew install docker"
    echo "   Windows: 安装 Docker Desktop"
    echo "   Linux: 参考 https://docs.docker.com/engine/install/"
    exit 1
fi

# 检查 Docker 是否运行
if ! docker info &> /dev/null; then
    echo "❌ Docker 未运行，请先启动 Docker"
    exit 1
fi

# 检查 Docker Hub 是否已登录
if ! docker info | grep -q "Login Succeeded"; then
    echo "⚠️  未登录 Docker Hub，请先登录"
    echo ""
    echo "   运行: docker login"
    echo "   用户名: zz3656"
    echo ""
    echo "   是否继续？(y/n)"
    read -r confirm
    if [ "$confirm" != "y" ]; then
        exit 0
    fi
fi

# 进入构建目录
if [ ! -d "${DOCKER_DIR}" ]; then
    echo "❌ 找不到目录 ${DOCKER_DIR}/"
    exit 1
fi

cd "${DOCKER_DIR}"

# 构建镜像
echo "==> 构建镜像..."
docker build \
    -t "${IMAGE_NAME}:${TAG}" \
    --progress=plain \
    -f Dockerfile \
    .

if [ $? -ne 0 ]; then
    echo "❌ 构建失败"
    exit 1
fi

echo "✓ 镜像构建成功"
echo ""

# 测试镜像（可选）
echo "==> 快速测试镜像..."
docker run --rm --name linclub-test "${IMAGE_NAME}:${TAG}" \
    python3 -c "import server; print('✓ 镜像测试通过')" 2>&1 | head -1

# 推送到 Docker Hub
echo ""
echo "==> 推送到 Docker Hub..."
docker push "${IMAGE_NAME}:${TAG}"

if [ $? -ne 0 ]; then
    echo "❌ 推送失败，请检查网络连接和 Docker Hub 权限"
    exit 1
fi

echo "✓ 推送成功"
echo ""
echo "=================================================="
echo " 完成！"
echo "=================================================="
echo "镜像地址: https://hub.docker.com/r/${IMAGE_NAME}"
echo "标签: ${TAG}"
echo ""
echo "使用方式:"
echo "   docker pull ${IMAGE_NAME}:${TAG}"
echo ""
echo "   docker run -d \\"
echo "     --name linclub \\"
echo "     -p 8765:8765 \\"
echo "     -v linclub-data:/data \\"
echo "     -e LINCLUB_INITIAL_PASS=your-password \\"
echo "     ${IMAGE_NAME}:${TAG}"
echo "=================================================="
