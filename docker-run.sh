# ============================================================
# 林卡电表统计 — Docker 快速启动脚本
# ============================================================
# 用法:  ./docker-run.sh [命令]
# 命令:  up / down / logs / rebuild / stop
# ============================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/docker" && pwd)"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

case "${1:-up}" in
  up)
    echo "==> 启动林卡电表服务..."
    cd "$ROOT_DIR"
    docker compose up -d
    echo ""
    echo "✓ 服务已启动!"
    echo "  访问地址: http://localhost:8765"
    echo "  健康检查: http://localhost:8765/api/health"
    echo "  默认管理员: admin / admin123"
    echo "  查看日志:   $0 logs"
    echo "  停止服务:   $0 down"
    ;;
  down)
    echo "==> 停止林卡电表服务..."
    cd "$ROOT_DIR"
    docker compose down
    echo "✓ 服务已停止"
    ;;
  logs)
    cd "$ROOT_DIR"
    docker compose logs -f
    ;;
  rebuild)
    echo "==> 重新构建并启动..."
    cd "$ROOT_DIR"
    docker compose up -d --build
    echo "✓ 重建完成"
    ;;
  stop)
    echo "==> 停止容器..."
    cd "$ROOT_DIR"
    docker compose stop
    echo "✓ 已停止"
    ;;
  start)
    echo "==> 启动容器..."
    cd "$ROOT_DIR"
    docker compose start
    echo "✓ 已启动"
    ;;
  status)
    cd "$ROOT_DIR"
    docker compose ps
    ;;
  exec)
    cd "$ROOT_DIR"
    docker compose exec linclub "$@"
    ;;
  *)
    echo "用法: $0 {up|down|logs|rebuild|stop|start|status|exec <cmd>}"
    exit 1
    ;;
esac
