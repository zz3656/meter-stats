"""
审计日志 — 记录谁在什么时间做了什么操作。

日志写入 JSON 文件 (audit.json), 每条记录包含:
  - ts: ISO 时间戳 (UTC)
  - user: 操作用户名 (anonymous if unauthenticated)
  - role: 用户角色
  - action: 操作类型 (READ/WRITE/DELETE/LOGIN/LOGOUT/MANAGER)
  - resource: 操作资源 (readings/charges/users/admin/meter/backup)
  - detail: 简要描述
  - ip: 客户端 IP (来自 request REMOTE_ADDR)
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_audit_lock = threading.Lock()
_audit_file: Optional[Path] = None

_AUDIT_MAX_LINES = 5000  # 日志文件最大行数，超出则截断


def init_audit_log(data_dir: Path) -> None:
    """初始化审计日志文件路径。"""
    global _audit_file
    _audit_file = data_dir / "audit.json"
    # 确保文件存在
    if not _audit_file.exists():
        _audit_file.write_text("[]", encoding="utf-8")


def log_audit(
    action: str,
    resource: str,
    detail: str = "",
    user: str = "anonymous",
    role: str = "public",
    ip: str = "",
) -> None:
    """追加一条审计日志。线程安全。"""
    if _audit_file is None:
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user,
        "role": role,
        "action": action,
        "resource": resource,
        "detail": detail,
        "ip": ip,
    }
    with _audit_lock:
        try:
            with _audit_file.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError):
            entries = []
        entries.append(entry)
        # 截断旧日志
        if len(entries) > _AUDIT_MAX_LINES:
            entries = entries[-_AUDIT_MAX_LINES:]
        with _audit_file.open("w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)


def get_audit_log(count: int = 100) -> list:
    """获取最近的审计日志。"""
    if _audit_file is None:
        return []
    try:
        with _audit_file.open("r", encoding="utf-8") as f:
            entries = json.load(f)
        return entries[-count:]
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return []
