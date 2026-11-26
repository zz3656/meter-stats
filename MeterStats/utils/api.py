"""
公共 HTTP 工具 — send_json / send_csv / read_body / 校验函数
提取自 handlers.py + routing.py，消除重复。
"""
from __future__ import annotations

import csv
import io
import os
import re
import json
from pathlib import Path
from typing import Any

from constants import DEFAULT_PORT

# ---- CORS 配置 ----
# 默认同源（local 开发）。通过 METER_CORS_ORIGIN=* 可放开（docker/远程部署用）。
_default_port = os.environ.get("METER_PORT", str(DEFAULT_PORT))
_DEFAULT_ORIGIN = f"http://localhost:{_default_port}"
CORS_ORIGIN = os.environ.get("METER_CORS_ORIGIN", _DEFAULT_ORIGIN)

CORS = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

# ---- 1x1 透明 PNG（favicon 静默响应） ----
_FAKE_FAVICON = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)

# ---- 校验正则 ----
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _add_cors(handler) -> None:
    """动态写入 CORS 头：回显请求的 Origin 头。

    关键修复：页面从 http://127.0.0.1:8765/ 加载时，
    如果 CORS 头固定为 http://localhost:8765，
    浏览器会认为 127.0.0.1 和 localhost 是不同的源，
    导致跨域请求被拒绝（"Load failed"）。

    解决方案：回显请求的 Origin 头，使 CORS 头与请求源完全匹配。
    如果请求没有 Origin 头（非跨域），则不发送 CORS 头。
    """
    origin = handler.headers.get("Origin")
    if origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Access-Control-Allow-Credentials", "true")
    # 非跨域请求不需要 CORS 头


def send_json(handler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    # 安全响应头: 防点击劫持 + MIME 嗅探 + XSS 过滤
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-XSS-Protection", "1; mode=block")
    handler.send_header("Cache-Control", "no-store")
    _add_cors(handler)
    handler.end_headers()
    # HEAD:头照发(含 Content-Length),body 不发 —— 让 curl -I / 监控探针能正常判活
    if not getattr(handler, "_head_only", False):
        handler.wfile.write(body)


def send_csv(handler, filename: str, headers: list, rows: list) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    body = buf.getvalue().encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-XSS-Protection", "1; mode=block")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Cache-Control", "no-store")
    _add_cors(handler)
    handler.end_headers()
    handler.wfile.write(body)


def send_favicon(handler) -> None:
    """响应一个 1x1 透明 PNG（静默 favicon）。"""
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(_FAKE_FAVICON)))
    _add_cors(handler)
    handler.end_headers()
    handler.wfile.write(_FAKE_FAVICON)


# 查询串里需要脱敏的参数名 —— 它们一旦进日志就等于把会话/凭据抄了一份。
_SECRET_QUERY_KEYS = ("token", "password", "nas_pass", "pass")


def mask_secret_query(path: str) -> str:
    """把 URL 查询串里的敏感参数值抹成 ***,保留参数名便于排查。

    >>> mask_secret_query("/api/x?a=1&token=deadbeef")
    '/api/x?a=1&token=***'
    """
    if not path or "?" not in path:
        return path
    head, _, query = path.partition("?")
    parts = []
    for kv in query.split("&"):
        name, sep, _value = kv.partition("=")
        if sep and name.lower() in _SECRET_QUERY_KEYS:
            parts.append(f"{name}=***")
        else:
            parts.append(kv)
    return head + "?" + "&".join(parts)


def read_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", handler.headers.get("content-length", "0")))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def opt_float(body: dict, key: str):
    """读可选数字字段:缺省/空/非法 → None。"""
    v = body.get(key)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def validate_date(value: str) -> str | None:
    """验证日期格式 YYYY-MM-DD，通过返回 value，否则返回 None。"""
    if isinstance(value, str) and _DATE_RE.match(value):
        return value
    return None


def validate_float(value, key: str = ""):
    """验证可为空浮点数: None → None, 合法数字 → float, 非法 → 抛出 ValueError。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"字段 '{key}' 需要合法数字")


# ---- ZIP Bomb 防护 ----
# 最大解压缩总大小：100 MB
ZIP_MAX_DECOMPRESSED_SIZE = 100 * 1024 * 1024
# 最大单个文件名长度（防 Unicode 炸弹）
ZIP_MAX_FILENAME_LEN = 512
# 最大文件数量（防存档爆炸）
ZIP_MAX_FILE_COUNT = 5000


def inject_version_to_html(html: str, token: str) -> str:
    """给 index.html 里**本地**的 <script src> / <link href> 加 `?v=<TOKEN>`。

    为什么必须加:token 是启动时按 JS/CSS/HTML 内容算的哈希,内容一变 URL 就变,
    所以静态资源可以放心用 `immutable` 长缓存(见 app_handler 的 Cache-Control);
    CDN/浏览器也不会拿旧代码糊住用户(以前容器重启后 CDN 缓存旧 app.js,
    修好的 bug 在用户那边"没修好")。

    三种情况分别处理:
    - 外链(https:// / http:// / //)→ 不动,那是 CDN 的事;
    - URL 里已有 `?v=<TIMESTAMP>` 占位符 → 换成真实 token(老写法,index.html 里
      历史遗留;占位符原样发给浏览器会让 URL 永远不变);
    - 其它本地 URL 且不带 query → 追加 `?v=<token>`。
    """
    if not token:
        return html
    import re

    def _add_v(match):
        full = match.group(0)
        attr = match.group(1)   # src / href
        quote = match.group(2)  # " / '
        src = match.group(3)
        # 外链 / 锚点 / 伪协议一律不动(给 "#" 或 "javascript:" 加 ?v= 会把它们打断)
        if src.startswith(("https://", "http://", "//", "#", "data:", "blob:", "javascript:", "mailto:")):
            return full
        if "<TIMESTAMP>" in src:
            return f'{attr}={quote}{src.replace("<TIMESTAMP>", token)}{quote}'
        if "?" in src:
            return full
        return f'{attr}={quote}{src}?v={token}{quote}'

    # 三个捕获组:属性名、引号、URL —— 反向引用 \2 保证引号配对
    return re.sub(r"""(src|href)=(["'])([^"']+)\2""", _add_v, html)


def _validate_zip_safely(zip_path, extract_to, max_size: int = ZIP_MAX_DECOMPRESSED_SIZE):
    """安全解压 ZIP 文件，防止 ZIP Bomb 攻击。

    - 检查每个成员的 uncompressed_size
    - 累计总大小不超过 max_size
    - 检查文件名长度
    - 检查文件数量

    返回: (extracted_dir, error_message | None)
    """
    import zipfile as zf_mod

    with zf_mod.ZipFile(zip_path, 'r') as zf:
        namelist = zf.namelist()

        # 1. 文件数量检查
        if len(namelist) > ZIP_MAX_FILE_COUNT:
            return None, f"ZIP 包含 {len(namelist)} 个文件，超过上限 {ZIP_MAX_FILE_COUNT}"

        # 2. 总大小检查
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if total_uncompressed > max_size:
            return None, (
                f"ZIP 解压总大小 {total_uncompressed / 1024 / 1024:.1f} MB，"
                f"超过上限 {max_size / 1024 / 1024:.0f} MB"
            )

        # 3. 文件名长度检查
        for name in namelist:
            if len(name) > ZIP_MAX_FILENAME_LEN:
                return None, f"文件名过长: {name[:80]}..."

        # 4. 检查目录穿越
        extract_to_resolved = Path(extract_to).resolve()
        for name in namelist:
            member_path = (extract_to_resolved / name).resolve()
            # 同上:字符串前缀判断挡不住同级目录(/data/backup 前缀命中 /data/backup-x)
            if not member_path.is_relative_to(extract_to_resolved):
                return None, f"目录穿越检测: {name}"

        # 全部校验通过，安全解压
        zf.extractall(extract_to)

    return extract_to, None
