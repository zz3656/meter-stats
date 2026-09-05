"""
电表统计 — HTTP 处理层（入口 + 静态文件）
===============================
入口类 Handler 负责路由分发和静态文件服务。
数据操作 handler 已迁移至 handlers/ 子模块。
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from utils.api import inject_version_to_html as _inject_version_to_html

ROOT = Path(__file__).resolve().parent

# 端口由 server.py 设置
PORT = 8765

# 静态文件版本 token:启动时由 server.py 计算并设置到这里,
# 用于在 index.html 注入 ?v=<token> 绕过 CDN 缓存。
# 注意:存在 app_handler 里而不是 server,因为用 python3 server.py 启动时
# __main__ 和 sys.modules['server'] 是两个不同模块对象,设到 server 会丢失。
STATIC_VERSION_TOKEN: str = None

# 数据文件映射 (由 server.py main() 设置)
# 注意：必须与 storage.DATA_FILES 的 key 保持一致，
# 否则在 server.py 完成替换前，handler 可能因 KeyError 崩溃。
DATA_PATHS: dict = {
    "readings": None,
    "readings_water": None,  # 水电表底 (main_meter/sub_meter/water)
    "charges": None,
    "items": None,
    "purchases": None,
    "duty": None,
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
        print(f"[meter-stats] [WARNING] _sync_data_paths: {e}")

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
        # 去掉 query string(用于 ?v=<token> 绕过 CDN 缓存)
        if "?" in path:
            path = path.split("?", 1)[0]

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

        is_html = file_path.suffix == ".html"
        is_js_or_css = file_path.suffix in (".js", ".css")

        if is_html:
            # index.html 走动态注入:把启动时计算的 ?v=<token> 加到 <script>/<link>
            # 这样 CDN(如 Cloudflare)缓存的旧 app.js 永远用不到,新版本每次都能加载。
            html = file_path.read_text(encoding="utf-8")
            if STATIC_VERSION_TOKEN:
                import re
                def _add_v(match):
                    attr = match.group(1)
                    quote = match.group(2)
                    src = match.group(3)
                    if src.startswith(("https://", "http://", "//")):
                        return match.group(0)
                    if "?" in src:
                        return match.group(0)
                    return f'{attr}={quote}{src}?v={STATIC_VERSION_TOKEN}{quote}'
                html = re.sub(r'(src|href)=(["\'])([^"\']+)\2', _add_v, html)
            body = html.encode("utf-8")
        else:
            body = file_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        # ⚠️ 关键: js/css/html 都不要缓存(避免 CDN/浏览器缓存旧版代码)
        # Cloudflare 默认会缓存这些静态文件,即使我们没有显式声明 cache-control。
        if is_html or is_js_or_css:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        from utils import CORS
        for k, v in CORS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


# 供测试模块调用 (向后兼容)
def _do_api(method, handler, path):
    from routing import route
    route(method, handler, path)
