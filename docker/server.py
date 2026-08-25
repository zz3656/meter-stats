#!/usr/bin/env python3
"""
林卡酒吧电表统计 — 后端 HTTP 服务（Docker 版）
===============================================

启动方式:
    docker run -p 8765:8765 -v linclub-data:/data linclub/electricity-stats

环境变量:
    LINCLUB_PORT          端口号 (默认: 8765)
    LINCLUB_DATA_DIR      数据目录 (默认: /data)
    LINCLUB_BIND          绑定地址 (默认: 0.0.0.0)
    LINCLUB_INITIAL_ADMIN  初始管理员用户名 (默认: admin)
    LINCLUB_INITIAL_PASS   初始管理员密码 (默认: admin123)

访问: http://localhost:8765

API 端点:
    GET    /api/readings          抄表列表
    GET    /api/charges           充值列表
    GET    /api/items             物品列表
    GET    /api/purchases         申购列表
    GET    /api/health            健康检查
    GET    /api/monthly-report    月报 (month=2026-07)
    GET    /api/export            CSV 导出 (models=readings,charges)
    POST   /api/readings          新增/覆盖抄表
    POST   /api/charges           新增充值
    POST   /api/backup            手动备份
    PUT    /api/readings/{date}   更新抄表
    PUT    /api/charges/{id}      更新充值
    PUT    /api/items             新增物品
    PUT    /api/purchases         新增申购
    PUT    /api/purchases/{id}/stock  入库
    DELETE /api/readings/{date}   删除抄表
    DELETE /api/charges/{id}      删除充值
    DELETE /api/items/{id}        删除物品
    DELETE /api/purchases/{id}    删除申购
"""
from __future__ import annotations

import atexit
import json
import os
import signal
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

from storage import get_data_dir, init_data_files, log

# ====== Docker 环境变量配置 ======
PORT = int(os.environ.get("LINCLUB_PORT", "8765"))
DATA_DIR = os.environ.get("LINCLUB_DATA_DIR", "/data")
BIND = os.environ.get("LINCLUB_BIND", "0.0.0.0")
VERSION = "0.1.0"


def _write_pid(data_dir: Path):
    """写入 PID 文件，便于外部检测/终止。"""
    pid_file = data_dir / "server.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid():
    """清理 PID 文件。"""
    from storage import get_data_dir
    try:
        pid_file = get_data_dir() / "server.pid"
        if pid_file.exists():
            pid_file.unlink()
    except Exception:
        pass


def _ensure_default_admin(data_dir: Path):
    """确保默认管理员账户存在（首次启动时创建）。"""
    from handlers.settings import init_settings, get_settings, ROLE_ADMIN

    init_settings(data_dir)
    settings = get_settings()
    users = settings.get("users", [])

    username = os.environ.get("LINCLUB_INITIAL_ADMIN", "admin")
    password = os.environ.get("LINCLUB_INITIAL_PASS", "admin123")

    # 检查是否已有管理员
    existing_admin = next((u for u in users if u.get("role") == ROLE_ADMIN), None)
    if existing_admin:
        log(f"  管理员账户已存在: {existing_admin['username']}")
        return

    # 创建默认管理员
    from handlers.settings import add_user
    add_user(users, username, password, "管理员", ROLE_ADMIN)
    settings["users"] = users
    from handlers.settings import save_settings
    save_settings(settings)
    log(f"  OK 默认管理员已创建: {username}")


def main():
    data_dir = Path(DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 初始化数据文件
    data_paths = init_data_files(data_dir)

    # 将文件映射暴露给 app_handler 模块（必须在 admin 初始化之前）
    import app_handler
    app_handler.DATA_PATHS = data_paths

    # 确保默认管理员账户
    _ensure_default_admin(data_dir)

    # 写入 PID 文件
    _write_pid(data_dir)

    # 注册优雅关闭
    def _shutdown(signum=None, frame=None):
        log(f"  收到信号 {signum}, 准备退出...")
        try:
            server.shutdown()
        except Exception:
            pass
        _remove_pid()
        if signum is not None:
            sys.exit(0)

    atexit.register(_remove_pid)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print("=" * 50)
    print("林卡酒吧电表统计 -- Docker 后端服务")
    print("=" * 50)
    print(f"数据目录: {data_dir}")
    print(f"监听地址: {BIND}:{PORT}")
    print(f"健康检查: http://{BIND}:{PORT}/api/health")
    print(f"PID: {os.getpid()}")
    print("按 Ctrl+C 停止")
    print("=" * 50)

    app_handler._sync_data_paths()  # 初始化 settings.json

    server = ThreadingHTTPServer((BIND, PORT), app_handler.Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.shutdown()
    finally:
        _remove_pid()


if __name__ == "__main__":
    try:
        main()
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"错误 端口 {PORT} 已被占用,先关掉其它服务或改端口")
            sys.exit(1)
        raise
