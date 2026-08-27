"""
公共 HTTP 工具 — send_json / send_csv / read_body / 校验函数
提取自 handlers.py + routing.py，消除重复。
"""
from __future__ import annotations

import csv
import io
import re
import json
from pathlib import Path
from typing import Any

# ---- CORS 配置（限制来源，避免全开 *） ----
CORS = {
    "Access-Control-Allow-Origin": "*",
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
