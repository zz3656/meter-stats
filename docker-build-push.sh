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

# === 更新 Docker Hub 仓库描述 ===
echo ""
echo "=================================================="
echo " 更新 Docker Hub 仓库描述 (Overview / About)"
echo "=================================================="
echo ""

if [ -n "$DOCKERHUB_TOKEN" ]; then
  python3 - "$DOCKERHUB_TOKEN" << 'PYEOF'
import json, sys, urllib.request, urllib.error

TOKEN = sys.argv[1]
USERNAME = "zz3656"
REPO = "linclub-electricity-stats"
SHORT_DESC = "林卡酒吧工程部电表统计工具 · Web服务"
FULL_DESC = "# 林卡电表统计 — Linclub Electricity Stats\n\n> 酒吧/场所工程部电表用量统计工具。支持 macOS 桌面应用和 Docker Web 服务两种部署方式。\n\n## ✨ 功能特性\n\n| 功能 | 说明 |\n|---|---|\n| ⚡ 电表管理 | 4 块电表独立抄表读数 |\n| 💰 充值记录 | 按表充值，支持备注 |\n| 🧾 月度报告 | 逐日逐表用电计算 |\n| 📊 年度汇总 | 12 个月数据汇总 |\n| 🔧 物品管理 | 库存 CRUD |\n| 📋 申购管理 | 申购 → 入库流转 |\n| 🔐 用户权限 | 三级权限管理 |\n| 💾 自动备份 | 每日自动备份 |\n\n## 🚀 快速开始\n\n```bash\ndocker run -d \\\n  --name linclub \\\n  -p 8765:8765 \\\n  -v ./data:/data \\\n  -e LINCLUB_INITIAL_PASS=your-password \\\n  -e LINCLUB_TZ=Asia/Shanghai \\\n  zz3656/linclub-electricity-stats:latest\n```\n\n## 默认账户\n\n| 用户名 | 密码 | 角色 |\n|---|---|---|\n| admin | admin123 | 管理员 |\n\n**⚠️ 请首次登录后立即修改密码！**\n"

# Login to get JWT for hub operations
login_url = "https://hub.docker.com/v2/users/login/"
payload = json.dumps({"username": USERNAME, "password": TOKEN}).encode()
req = urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        jwt = data.get("token", data.get("jwt", ""))
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"⚠️ Docker Hub 登录失败 (HTTP {e.code}): {body[:100]}")
    sys.exit(0)

# PATCH repository description
desc_data = {"description": SHORT_DESC, "full_description": FULL_DESC}
desc_payload = json.dumps(desc_data, ensure_ascii=False).encode()
api_url = f"https://hub.docker.com/v2/repositories/{USERNAME}/{REPO}/"

req2 = urllib.request.Request(api_url, data=desc_payload,
    headers={"Authorization": "JWT " + jwt, "Content-Type": "application/json"}, method="PATCH")

with urllib.request.urlopen(req2, timeout=30) as resp2:
    result = json.loads(resp2.read())
    print("✅ Docker Hub 仓库描述已更新！")
    print(f"   访问: https://hub.docker.com/r/{USERNAME}/{result.get('name', REPO)}")
PYEOF
else
  echo "⚠️  未找到 DOCKERHUB_TOKEN 环境变量，跳过描述更新。"
  echo "   设置: export DOCKERHUB_TOKEN=dckr_pat_xxxxxxxx"
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
echo "     -e LINCLUB_TZ=Asia/Shanghai \\"
echo "     ${IMAGE_NAME}:${TAG}"
echo ""
echo "   # 或使用 docker-compose.yml（推荐）:"
echo ""
echo "   docker compose up -d"
echo "=================================================="
