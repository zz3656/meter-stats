#!/usr/bin/env python3
"""
场所电表统计 — 后端 HTTP 服务
====================================
场所工程部电表用量统计工具的后端服务。

启动:
    cd ~/Applications/电表.app/Contents/Resources/
    python3 server.py

访问: http://localhost:8765

停止: Ctrl+C

数据文件:
    ~/Library/Application Support/com.meter.stats/

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

PORT = int(os.environ.get("METER_PORT", "8765"))
# 从 VERSION 文件读取版本号（支持打包 app 中 version 打包到资源）
# 注意:Python 3.13 才给 Path.read_text 加 strip 参数,3.11/3.12 都没有。
# 这里用 .strip() 手动处理,兼容所有 Python 版本。
VERSION = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()


def _write_pid(data_dir: Path):
    """写入 PID 文件，便于外部检测/终止。"""
    pid_file = data_dir / "server.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


# index.html 里 <script src="app.js"> → <script src="app.js?v=<TOKEN>"> 中的 token
# 启动时根据 app.js/admin.js/style.css 的内容哈希生成;文件改动 → token 变 →
# 浏览器/CDN 看到新 URL,绕过缓存回源拉新文件。
# 这是修复 CDN(如 Cloudflare)缓存导致前端看不到代码修复的关键机制。
def compute_version_token():
    """根据 app.js / admin.js / style.css 的内容哈希生成版本 token。"""
    import hashlib
    files = ["app.js", "admin.js", "style.css", "index.html"]
    h = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for fname in files:
        p = root / fname
        if p.exists():
            try:
                h.update(p.read_bytes())
            except OSError:
                pass
    # 取前 8 位 hex(短 token,够用)
    return h.hexdigest()[:8]


# inject_version_to_html 已迁移至 utils.api;保留此别名供 app_handler.py 向后兼容
from utils.api import inject_version_to_html


def _remove_pid():
    """清理 PID 文件。"""
    from storage import get_data_dir
    try:
        pid_file = get_data_dir() / "server.pid"
        if pid_file.exists():
            pid_file.unlink()
    except Exception:
        pass


def main():
    data_dir = get_data_dir()

    # 计算版本 token(用于绕过 CDN 缓存,在 app_handler 渲染 index.html 时注入)
    token = compute_version_token()
    from storage import log as _log
    _log(f"  静态资源版本 token: v={token} (启动时根据 JS/CSS/HTML 内容哈希生成)")
    # 设到 app_handler.STATIC_VERSION_TOKEN，供请求时静态文件服务读取。
    # 注意:python3 server.py 启动时 __main__ 和 sys.modules['server'] 是不同对象，
    # 因此不能依赖模块级 global，必须直接设 app_handler 属性。
    try:
        import app_handler as _ah
        _ah.STATIC_VERSION_TOKEN = token
    except Exception:
        pass

    # 初始化数据文件并获取文件映射（会自动创建不存在的空数据文件）
    data_paths = init_data_files(data_dir)

    # 运行启动时数据迁移（将旧版 readings.json 中的水电字段迁移到 readings_water.json）
    from storage import run_startup_migration as _run_startup_migration
    _run_startup_migration(data_dir)

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
    print("电表统计 -- 后端服务")
    print("=" * 50)
    print(f"数据目录: {data_dir}")
    print(f"访问地址: http://localhost:{PORT}")
    print(f"健康检查: http://localhost:{PORT}/api/health")
    print(f"PID: {os.getpid()}")
    print("按 Ctrl+C 停止")
    print("=" * 50)

    # 将文件映射暴露给 app_handler 模块
    import app_handler
    app_handler.DATA_PATHS = data_paths
    app_handler._sync_data_paths()  # 初始化 settings.json

    bind_host = os.environ.get("METER_BIND", "0.0.0.0")
    server = ThreadingHTTPServer((bind_host, PORT), app_handler.Handler)
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
