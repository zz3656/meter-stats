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

# ---- CORS 配置 ----
# 默认同源（local 开发）。通过 METER_CORS_ORIGIN=* 可放开（docker/远程部署用）。
_DEFAULT_ORIGIN = f"http://localhost:{os.environ.get('METER_PORT', '8765')}"
CORS_ORIGIN = os.environ.get("METER_CORS_ORIGIN", _DEFAULT_ORIGIN)

CORS = {
    "Access-Control-Allow-Origin": CORS_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    # 只有放开跨域时才需要 Credentials；同源下浏览器忽略此头。
    **(
        {"Access-Control-Allow-Credentials": "true"}
        if CORS_ORIGIN != _DEFAULT_ORIGIN
        else {}
    ),
}

# ---- 1x1 透明 PNG（favicon 静默响应） ----
_FAKE_FAVICON = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)

# ---- 校验正则 ----
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _write_cors_headers(handler, headers: dict) -> None:
    """批量写入 CORS 头。"""
    for k, v in headers.items():
        handler.send_header(k, v)


def send_json(handler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    _write_cors_headers(handler, CORS)
    handler.end_headers()
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
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Cache-Control", "no-store")
    _write_cors_headers(handler, CORS)
    handler.end_headers()
    handler.wfile.write(body)


def send_favicon(handler) -> None:
    """响应一个 1x1 透明 PNG（静默 favicon）。"""
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(_FAKE_FAVICON)))
    _write_cors_headers(handler, CORS)
    handler.end_headers()
    handler.wfile.write(_FAKE_FAVICON)


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
    """在 index.html 的 <script>/<link> 标签里加 ?v=<TOKEN>,破坏 CDN/浏览器缓存。

    重要场景:容器重启后,如果 CDN 缓存了旧 app.js,用户浏览器
    会一直拿到旧代码导致 bug 修不好。注入版本 token 后,index.html 引用变成
    app.js?v=abc123,URL 变化 → 浏览器/CDN 必须回源拉新文件。
    """
    if not token:
        return html
    import re
    def _add_v(match):
        full = match.group(0)
        attr = match.group(1)   # src / href
        quote = match.group(2)  # " / '
        src = match.group(3)
        if src.startswith(("https://", "http://", "//")):
            return full
        if "?" in src:
            return full
        return f'{attr}={quote}{src}?v={token}{quote}'
    return re.sub(r'(src|href)=("[^"]+"|' + r"'[^']+')" , _add_v, html)


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
            if not str(member_path).startswith(str(extract_to_resolved)):
                return None, f"目录穿越检测: {name}"

        # 全部校验通过，安全解压
        zf.extractall(extract_to)

    return extract_to, None
