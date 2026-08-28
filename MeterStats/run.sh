#!/usr/bin/env bash
# 电表统计 — 一键启动脚本
# 用法:
#   ./run.sh              # 启动本地服务
#   ./run.sh stop         # 停止服务
#   ./run.sh restart      # 重启服务
#   ./run.sh status       # 查看状态
#   ./run.sh docker       # 启动 Docker 容器
#   ./run.sh docker-stop  # 停止 Docker 容器
#   ./run.sh logs         # 查看日志
#
# 需要安装 Python 3.9+，无其他依赖

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_PY="$SCRIPT_DIR/server.py"
LOG_FILE="$SCRIPT_DIR/.server.log"
DATA_DIR="$SCRIPT_DIR/.data"
PORT=8765
CONTAINER_NAME="meter-stats"
IMAGE="zz3656/meter-stats:latest"
PASS="${METER_INITIAL_PASS:-admin}"

# ---------- 工具函数 ----------

is_server_running() {
    lsof -i :"${PORT}" -sTCP:LISTEN >/dev/null 2>&1
}

is_docker_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER_NAME"
}

get_server_pid() {
    lsof -t -i :"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1
}

# ---------- 命令 ----------

cmd_start() {
    if is_server_running; then
        echo "⚠️  服务已在运行 (PID $(get_server_pid))"
        return 0
    fi

    # 创建本地数据目录（sandbox 内，避免权限问题）
    mkdir -p "$DATA_DIR"

    echo "🚀 启动电表统计服务..."
    cd "$SCRIPT_DIR"
    # 后台启动，指定数据目录到 workspace 内
    METER_DATA_DIR="$DATA_DIR" nohup python3 "$SERVER_PY" > "$LOG_FILE" 2>&1 &
    disown

    # 等待服务就绪
    for i in $(seq 1 15); do
        if curl -s http://localhost:"${PORT}"/api/health >/dev/null 2>&1; then
            echo "✅ 服务已启动  http://localhost:${PORT}"
            echo "📁 数据目录: ${DATA_DIR}"
            return 0
        fi
        sleep 0.5
    done

    echo "⚠️  服务可能未正常启动，查看日志: $0 logs"
    return 1
}

cmd_stop() {
    local stopped=false

    # 停本地
    if is_server_running; then
        local pid
        pid=$(get_server_pid)
        kill -9 "$pid" 2>/dev/null || true
        echo "🛑 已停止本地服务 (PID $pid)"
        stopped=true
    fi

    # 停 Docker
    if is_docker_running; then
        docker stop "$CONTAINER_NAME" >/dev/null 2>&1
        echo "🛑 已停止 Docker 容器"
        stopped=true
    fi

    if ! $stopped; then
        echo "ℹ️  没有运行中的服务"
    fi
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

cmd_status() {
    if is_server_running; then
        echo "🟢 本地服务运行中 (PID $(get_server_pid))"
    else
        echo "⚪ 本地服务未运行"
    fi

    if is_docker_running; then
        local since
        since=$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER_NAME" 2>/dev/null || echo "?")
        echo "🟢 Docker 容器运行中 (启动于 $since)"
    else
        echo "⚪ Docker 容器未运行"
    fi
}

cmd_docker() {
    if is_docker_running; then
        echo "ℹ️  Docker 容器已在运行"
        docker logs --tail 5 "$CONTAINER_NAME"
        return
    fi

    echo "🐳 启动 Docker 容器..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart unless-stopped \
        -p "$PORT:$PORT" \
        -v meter-data:/data \
        -e METER_INITIAL_PASS="$PASS" \
        "$IMAGE"

    echo "⏳ 等待容器就绪..."
    for i in $(seq 1 20); do
        if curl -s http://localhost:"${PORT}"/api/health >/dev/null 2>&1; then
            echo "✅ Docker 容器已启动  http://localhost:${PORT}"
            return 0
        fi
        sleep 1
    done
    echo "⚠️  容器可能未正常启动，查看日志: $0 logs"
}

cmd_docker_stop() {
    if is_docker_running; then
        docker stop "$CONTAINER_NAME" >/dev/null
        echo "🛑 已停止 Docker 容器"
    else
        echo "ℹ️  Docker 容器未运行"
    fi
}

cmd_logs() {
    if is_docker_running; then
        docker logs --tail 20 -f "$CONTAINER_NAME"
    elif [[ -f "$LOG_FILE" ]]; then
        tail -f "$LOG_FILE"
    else
        echo "ℹ️  没有可用日志"
    fi
}

cmd_cleanup() {
    cmd_stop
    echo "🧹 清理数据目录: ${DATA_DIR}"
    rm -rf "$DATA_DIR"
    echo "✅ 已清理"
}

# ---------- 主入口 ----------

case "${1:-start}" in
    start|-s)      cmd_start ;;
    stop|-S)       cmd_stop ;;
    restart|-r)    cmd_restart ;;
    status|-st)    cmd_status ;;
    docker|-d)     cmd_docker ;;
    docker-stop)   cmd_docker_stop ;;
    logs|-l)       cmd_logs ;;
    cleanup|-c)    cmd_cleanup ;;
    *)
        echo "电表统计 — 一键启动脚本"
        echo ""
        echo "用法: $0 {start|stop|restart|status|docker|docker-stop|logs|cleanup}"
        echo ""
        echo "  start         启动本地服务（推荐开发时用，修改代码后直接重启）"
        echo "  stop          停止本地服务或 Docker 容器"
        echo "  restart       重启服务"
        echo "  status        查看服务状态"
        echo "  docker        以 Docker 容器方式运行（部署用）"
        echo "  docker-stop   停止 Docker 容器"
        echo "  logs          查看实时日志"
        echo "  cleanup       清理所有数据（危险操作）"
        ;;
esac
