#!/bin/bash
# ============================================================
# 林卡电表统计 — Docker 多平台镜像构建和推送到 Docker Hub
# 使用 Docker Buildx 构建 linux/amd64 + linux/arm64
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
echo " 林卡电表统计 — Docker 多平台镜像构建"
echo "=================================================="
echo ""
echo "镜像名称: ${IMAGE_NAME}"
echo "标签版本: ${TAG}"
echo "构建目录: ${DOCKER_DIR}/"
echo "支持平台: linux/amd64, linux/arm64"
echo ""

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker Desktop"
    exit 1
fi

# 检查 Docker 是否运行
if ! docker info &> /dev/null; then
    echo "❌ Docker 未运行，请先启动 Docker Desktop"
    exit 1
fi

# 检查 Buildx 是否可用
if ! docker buildx version &> /dev/null; then
    echo "❌ Docker Buildx 未安装，请更新 Docker Desktop"
    exit 1
fi

# 检查 Buildx builder 是否支持多平台
echo "==> 检查 Buildx 构建器..."
PLATFORMS=$(docker buildx inspect --bootstrap 2>/dev/null | grep -A1 "Platforms:" | tail -1 | tr ',' '\n' | sed 's/^ *//')
echo "   支持的平台:"
for p in $PLATFORMS; do
    echo "   - $p"
done
echo ""

# 检查 Docker Hub 是否已登录
if ! docker info 2>&1 | grep -q "Username"; then
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

# 检查 Dockerfile 是否存在
if [ ! -f "${DOCKER_DIR}/Dockerfile" ]; then
    echo "❌ 找不到 ${DOCKER_DIR}/Dockerfile"
    exit 1
fi

# === 多平台构建和推送 ===
echo "=================================================="
echo " 开始多平台构建 (linux/amd64 + linux/arm64)"
echo "=================================================="
echo ""

docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --provenance=false \
    --sbom=false \
    -t "${IMAGE_NAME}:${TAG}" \
    --push \
    --progress=plain \
    -f "${DOCKER_DIR}/Dockerfile" \
    "${DOCKER_DIR}"

if [ $? -ne 0 ]; then
    echo "❌ 构建或推送失败"
    exit 1
fi

echo ""
echo "=================================================="
echo " ✓ 构建和推送成功！"
echo "=================================================="
echo ""
echo "镜像地址: https://hub.docker.com/r/${IMAGE_NAME}"
echo "标签: ${TAG}"
echo "平台: linux/amd64, linux/arm64"
echo ""
echo "使用方式 (飞牛 OS / macOS / Linux):"
echo ""
echo "   docker pull ${IMAGE_NAME}:${TAG}"
echo ""
echo "   docker run -d \\"
echo "     --name linclub \\"
echo "     -p 8765:8765 \\"
echo "     -v ./data:/data \\"
echo "     -e LINCLUB_INITIAL_PASS=your-password \\"
echo "     -e TZ=Asia/Shanghai \\"
echo "     ${IMAGE_NAME}:${TAG}"
echo ""
echo "   # 或使用 docker-compose.yml（推荐）:"
echo ""
echo "   docker compose up -d"
echo "=================================================="
