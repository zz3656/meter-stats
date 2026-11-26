"""
电表统计 — HTTP 处理层（入口 + 静态文件）
===============================
入口类 Handler 负责路由分发和静态文件服务。
数据操作 handler 已迁移至 modules/ 包（按业务域分包）。
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from utils.api import inject_version_to_html as _inject_version_to_html

ROOT = Path(__file__).resolve().parent

# 只允许服务**前端静态资源**的扩展名。
#
# ⚠️ 这个 handler 原来把「ROOT 之下的任意文件」直接发出去 ——
#    http://<host>:8765/routing.py 能下载到后端源码(接口面、鉴权逻辑全暴露),
#    .db / .log / .plist / .sh / .swift 同理。服务还监听在所有网卡上,
#    等于同网段任何人都能拿走源码。
# 现在按白名单收口:不在表里的一律 404(用 404 而不是 403 ——
#    不告诉外面"这个文件存在但不能读")。
_STATIC_ALLOWED_SUFFIXES = frozenset({
    ".html", ".css", ".js",                # 页面与脚本
    ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico",   # 图片
    ".woff", ".woff2", ".ttf",             # 字体
})


from constants import DEFAULT_PORT

# 端口由 server.py 设置
PORT = DEFAULT_PORT

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
        from modules.system.settings_handler import init_settings
        for model, path in DATA_PATHS.items():
            if path:
                data_dir = Path(path).parent
                init_settings(data_dir)
                break
    except Exception as e:
        from storage import log
        log(f"  [meter-stats] [WARNING] _sync_data_paths: {e}")

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

    def do_HEAD(self):
        """HEAD = 与 GET 相同的状态码与响应头,但不发 body。

        ⚠️ 以前没有这个方法,http.server 直接回 501 Unsupported method ——
        `curl -I`、许多监控探针(Uptime Kuma / 各类 uptime 检查)、
        以及部分反向代理的健康检查都走 HEAD,拿到 501 会把服务判成"挂了"。
        """
        self._head_only = True
        self._dispatch("HEAD")

    def _dispatch(self, method: str):
        import time
        start = time.time()
        # HEAD 走 GET 的路由(状态码/头一致),body 由各写出点按 _head_only 抑制
        route_method = "GET" if method == "HEAD" else method
        if self.path.startswith("/api/"):
            # 请求体大小限制: 防止超大 body 拖垮服务 (1MB)
            content_length = int(self.headers.get("Content-Length", 0))
            MAX_BODY = 1 * 1024 * 1024  # 1 MB
            if content_length > MAX_BODY:
                from utils import send_json
                send_json(self, 413, {"error": f"请求体过大 (最大 {MAX_BODY // 1024}KB)"})
                return
            try:
                from routing import route
                handled = route(route_method, self, self.path)
                if handled is False:
                    # ⚠️ 绝不能什么都不做就返回：不发响应会让客户端收到空连接，
                    # 在 WKWebView/浏览器里表现为 "TypeError: Load failed"（-1005 Connection reset）。
                    # 路由未命中必须显式返回 404 JSON。
                    from storage import log
                    log(f"[404] {method} {self.path}")
                    from utils import send_json
                    send_json(self, 404, {"error": f"未知接口: {self.path.split('?')[0]}"})
            except Exception as e:
                from storage import log
                elapsed = time.time() - start
                client_ip = self.headers.get("X-Forwarded-For", self.client_address[0] if hasattr(self, 'client_address') else "?")
                log(f"[{elapsed*1000:.0f}ms] {method} {self.path} 4xx/5xx from {client_ip}: {e}")
                import traceback
                log(traceback.format_exc())
                from utils import send_json
                send_json(self, 500, {"error": "服务器内部错误"})
        else:
            self._handle_static(method)

    def _handle_static(self, method: str):
        path = self.path
        query = ""
        # 拆出 query:它决定这个资源能不能长缓存(带 ?v=<内容哈希> 才敢 immutable)
        if "?" in path:
            path, _, query = path.partition("?")
        has_version = "v=" in query

        if path == "/" or path == "":
            path = "/index.html"

        if path == "/favicon.ico":
            from utils import send_favicon
            send_favicon(self)
            return

        file_path = (ROOT / path.lstrip("/")).resolve()
        # ⚠️ 用 is_relative_to 而不是 str.startswith:字符串前缀判断会把**同级目录**
        #    也算进去 —— /…/meter-stats/MeterStats.bak/x.js 的前缀同样是
        #    "/…/meter-stats/MeterStats",于是仓库旁边一个 MeterStats.bak/ 就能
        #    被匿名读走(静态服务是第一道门,连鉴权都没有)。
        if not file_path.is_relative_to(ROOT):
            self.send_error(403)
            return
        if not file_path.is_file():
            self.send_error(404)
            return

        # 只发前端资源:后端源码(.py)、配置(.json)、缓存(.db)、日志、脚本一律不对外
        if file_path.suffix.lower() not in _STATIC_ALLOWED_SUFFIXES:
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

        is_html = file_path.suffix == ".html"

        if is_html:
            # index.html 走动态注入:把启动时算的 `?v=<内容哈希>` 加到本地
            # <script>/<link> 上。URL 随内容变 → 静态资源可以放心长缓存。
            #
            # ⚠️ 这里原来有一段**自己实现**的注入逻辑,而它只替换 <TIMESTAMP> 占位符、
            #    给普通路径**不加** ?v=(src 里没有 "?" 时直接原样返回)。于是 30 个
            #    JS 文件里只有 admin.js 拿到版本号,其余全是无版本 URL + no-store
            #    —— 每次刷新重下 ~620KB/37 个请求。上面 import 的
            #    `_inject_version_to_html`(实现是对的)一直没被调用。
            html = file_path.read_text(encoding="utf-8")
            html = _inject_version_to_html(html, STATIC_VERSION_TOKEN)
            body = html.encode("utf-8")
        else:
            body = file_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        # 安全响应头: 防点击劫持 + MIME 嗅探 + XSS 过滤
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-XSS-Protection", "1; mode=block")
        # 缓存策略:
        # - index.html:**永不缓存**(它带着当前的 ?v=,缓存了就等于缓存了旧版引用)
        # - 带 ?v=<内容哈希> 的静态资源:**一年 + immutable** —— URL 随内容变,
        #   内容一改 URL 就变,不会出现「CDN 糊住旧代码」。首屏 37 个请求从
        #   「每次全量重下」变成「第二次起 0 请求」。
        # - 不带版本号的静态资源:维持 no-store(兜底,正常不会走到)
        if is_html:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        elif has_version:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        from utils import CORS, _add_cors
        for k, v in CORS.items():
            self.send_header(k, v)
        _add_cors(self)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)


# 供测试模块调用 (向后兼容)
def _do_api(method, handler, path):
    from routing import route
    route(method, handler, path)
