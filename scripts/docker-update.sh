#!/usr/bin/env bash
# ============================================================
# 工程部管理系统 — Docker 一键升级
# ============================================================
# 用途:拉取远端最新镜像 → 重建容器 → 打印更新前后的版本号对比
#
# 为什么需要这个脚本:
#   Docker **从不会主动检查远端仓库**。只要本地已经存在
#   zz3656/meter-stats:latest 这份镜像,`docker compose up -d` 就会直接
#   拿本地这份用 —— 既不提示"有新版本",也不去拉取。所以只写
#   `up -d` 永远停在旧版本。
#   过去"先 docker rmi 删掉本地镜像再 up"之所以有效,只是因为删掉后
#   本地没有了,up 才会被动去拉 —— 那是多余的步骤,显式 pull 就行。
#
# 用法:
#   bash scripts/docker-update.sh                     # 自动挑 compose 文件
#   bash scripts/docker-update.sh docker/docker-compose.yml
#   bash scripts/docker-update.sh -f /vol1/docker/linclub/docker-compose.yml
#
# 兼容:
#   docker compose      (Compose v2,DSM 7.2+ / Docker Desktop)
#   docker-compose      (Compose v1,DSM 6 / 7.0 / 7.1)
#
# 数据: 存放在 compose 挂载的卷里,升级不会丢失。
# ============================================================
set -eo pipefail

SERVICE="meter-stats"
CONTAINER="${METER_CONTAINER:-meter-stats}"

# ---- 参数解析 -------------------------------------------------------------
COMPOSE_FILE=""
while [ $# -gt 0 ]; do
    case "$1" in
        -f|--file) COMPOSE_FILE="$2"; shift 2 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) COMPOSE_FILE="$1"; shift ;;
    esac
done

# ---- 定位 compose 命令 ----------------------------------------------------
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    echo "❌ 找不到 docker compose / docker-compose,无法升级" >&2
    exit 1
fi

# ---- Docker 守护进程 ------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker 守护进程未运行,无法升级" >&2
    echo "   先启动 Docker(Docker Desktop / systemctl start docker / NAS 的 Docker 套件)" >&2
    exit 1
fi

# ---- 定位 compose 文件 ----------------------------------------------------
if [ -z "$COMPOSE_FILE" ]; then
    # 优先用 docker/ 下的那份(image 是 zz3656/meter-stats:latest,真正用于部署);
    # 仓库根目录那份用的是本地构建标签 meter-stats:local,拉不到远端镜像。
    for candidate in docker/docker-compose.yml docker-compose.yml; do
        if [ -f "$candidate" ]; then
            COMPOSE_FILE="$candidate"
            break
        fi
    done
fi

if [ -z "$COMPOSE_FILE" ]; then
    echo "❌ 找不到 docker-compose.yml,请显式指定:bash scripts/docker-update.sh <路径>" >&2
    exit 1
fi
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "❌ compose 文件不存在: $COMPOSE_FILE" >&2
    exit 1
fi

compose() {
    if [ -n "$COMPOSE_FILE" ]; then
        $COMPOSE_CMD -f "$COMPOSE_FILE" "$@"
    else
        $COMPOSE_CMD "$@"
    fi
}

# ---- 升级前状态 -----------------------------------------------------------
echo "=================================================="
echo " Docker 升级"
echo "=================================================="
echo " compose 命令 : $COMPOSE_CMD"
echo " compose 文件 : $COMPOSE_FILE"
echo ""

OLD_VERSION=""
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    OLD_VERSION=$(docker exec "$CONTAINER" cat /app/VERSION 2>/dev/null | tr -d '[:space:]' || true)
fi
[ -z "$OLD_VERSION" ] && OLD_VERSION=$(curl -s -m 5 http://localhost:8765/api/version 2>/dev/null \
    | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)

OLD_IMAGE=$(docker images --format '{{.ID}}' zz3656/meter-stats:latest 2>/dev/null | head -1 || true)

echo " 当前版本 : ${OLD_VERSION:-未知}"
echo " 当前镜像 : ${OLD_IMAGE:-本地无此镜像}"
echo ""

# ---- 拉取 + 重建 ----------------------------------------------------------
echo "==> 拉取远端最新镜像 ..."
if ! compose pull; then
    echo "❌ 拉取失败。若提示找不到镜像,检查 compose 里的 image: 标签是否指向 Docker Hub" >&2
    exit 1
fi

echo "==> 重建容器 ..."
compose up -d

# ---- 等健康检查通过再读版本 ----------------------------------------------
echo "==> 等待容器启动 ..."
for _ in $(seq 1 30); do
    STATUS=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo "none")
    case "$STATUS" in
        healthy) break ;;
        unhealthy) echo "⚠️ 容器健康检查未通过,继续输出版本信息"; break ;;
    esac
    sleep 2
done

NEW_VERSION=""
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    NEW_VERSION=$(docker exec "$CONTAINER" cat /app/VERSION 2>/dev/null | tr -d '[:space:]' || true)
fi
[ -z "$NEW_VERSION" ] && NEW_VERSION=$(curl -s -m 5 http://localhost:8765/api/version 2>/dev/null \
    | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)

NEW_IMAGE=$(docker images --format '{{.ID}}' zz3656/meter-stats:latest 2>/dev/null | head -1 || true)

echo ""
echo "=================================================="
echo " 升级完成"
echo "=================================================="
echo " 版本 : ${OLD_VERSION:-未知} → ${NEW_VERSION:-未知}"
echo " 镜像 : ${OLD_IMAGE:-无} → ${NEW_IMAGE:-无}"
if [ "$OLD_VERSION" != "$NEW_VERSION" ]; then
    echo " ✅ 镜像已更新"
else
    echo " ℹ️  版本号未变化(已是最新镜像,或本次发布未改 VERSION)"
fi
echo ""
echo " ⚠️ 升级后需重新登录一次(会话保存在服务端内存,重启即失效)"
