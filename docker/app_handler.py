"""
林卡酒吧电表统计 — HTTP 处理层（入口 + 静态文件）
===============================
入口类 Handler 负责路由分发和静态文件服务。
数据操作 handler 已迁移至 handlers/ 子模块。
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 端口由 server.py 设置
PORT = 8765

# 数据文件映射 (由 server.py main() 设置)
DATA_PATHS: dict = {
    "readings": None,
    "charges": None,
    "items": None,
    "purchases": None,
}


def _sync_data_paths():
    """同步 DATA_PATHS（供 server.py 调用，作为未来扩展的入口）。"""
    try:
        # 初始化 settings.json（用户/权限/电表参数）
        from handlers.settings import init_settings
        for model, path in DATA_PATHS.items():
            if path:
                data_dir = Path(path).parent
                init_settings(data_dir)
                break
    except Exception as e:
        print(f"[linclub] [WARNING] _sync_data_paths: {e}")

class Handler(BaseHTTPRequestHandler):
    """HTTP 请求处理类：静态文件 + API 路由。"""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    def _dispatch(self, method: str):
        if self.path.startswith("/api/"):
            try:
                from routing import route
                route(method, self, self.path)
            except Exception as e:
                from storage import log
                log(f"[ERROR] {method} {self.path}: {e}")
                import traceback
                log(traceback.format_exc())
                from utils import send_json
                send_json(self, 500, {"error": "服务器内部错误"})
        else:
            self._handle_static(method)

    def _handle_static(self, method: str):
        path = self.path

        if path == "/" or path == "":
            path = "/index.html"

        if path == "/favicon.ico":
            from utils import send_favicon
            send_favicon(self)
            return

        file_path = (ROOT / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(ROOT)):
            self.send_error(403)
            return
        if not file_path.is_file():
            self.send_error(404)
            return

        mime = "text/plain"
        if file_path.suffix == ".html":
            mime = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            mime = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            mime = "application/javascript; charset=utf-8"
        elif file_path.suffix == ".json":
            mime = "application/json; charset=utf-8"
        elif file_path.suffix == ".svg":
            mime = "image/svg+xml; charset=utf-8"
        elif file_path.suffix == ".png":
            mime = "image/png"
        elif file_path.suffix == ".ico":
            mime = "image/x-icon"

        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        from utils import CORS
        for k, v in CORS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


# 供测试模块调用 (向后兼容)
def _do_api(method, handler, path):
    from routing import route
    route(method, handler, path)
