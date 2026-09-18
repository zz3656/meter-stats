"""备份管理 HTTP API — 列表 / 下载 / 删除 / 自动备份配置 / 备份目录配置 / 上传恢复。
业务逻辑在 handlers/backup.py,本文件只负责 HTTP 入口。
从原 handlers.admin.py 拆分而来。
"""
from __future__ import annotations
import datetime
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body, CORS
from storage import log, DATA_FILES, backup_data
from handlers.settings import get_settings, save_settings
from handlers.backup import (
    _get_backup_retention_count,
    _merge_settings_after_restore,
    _resolve_backup_parent,
)
from handlers._base import get_data_paths as _get_data_paths
from utils.api import _validate_zip_safely


# ============ 备份列表 ============

def handle_get_backup_status(handler):
    """GET /api/admin/backup-status → {auto_backup, backup_count, backups: [...]}

    列出备份目录下所有的 ZIP 压缩包(手动 meter-backup- + 自动 auto-bak-),
    每个 ZIP 算一个备份,带 type 字段区分(manual/auto)。
    返回 { name, zip_path, file_count, total_size, created_at, type }
    """
    settings = get_settings()
    auto_backup = settings.get("auto_backup", True)
    data_dir = _get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)

    backup_entries = []
    if backup_dir.exists():
        for f in sorted(backup_dir.rglob("*.zip"), reverse=True):
            if not f.is_file():
                continue
            # 手动备份 meter-backup- 前缀,自动备份 auto-bak- 前缀
            if f.name.startswith("meter-backup-"):
                btype = "manual"
                try:
                    ts = f.name.replace("meter-backup-", "").replace(".zip", "")
                except Exception:
                    ts = f.name
            elif f.name.startswith("auto-bak-"):
                btype = "auto"
                try:
                    ts = f.name.replace("auto-bak-", "").replace(".zip", "")
                except Exception:
                    ts = f.name
            else:
                continue

            # 统计 ZIP 内文件数
            file_count = 0
            total_size = 0
            try:
                with zipfile.ZipFile(f, 'r') as zf:
                    file_count = len(zf.namelist())
                    total_size = sum(info.file_size for info in zf.infolist())
            except Exception:
                total_size = f.stat().st_size

            backup_entries.append({
                "name": ts,
                "zip_path": str(f),
                "zip_name": f.name,
                "file_count": file_count,
                "total_size": total_size,
                "created_at": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "format": "zip",
                "type": btype,
            })

        # 再列出旧格式的备份目录(非 .zip 目录,排除带 _ 的时间戳目录,因为已被 ZIP 覆盖)
        for d in sorted(backup_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if d.is_dir() and not d.name.endswith('.zip'):
                zip_name = f"meter-backup-{d.name}.zip"
                if not (backup_dir / zip_name).exists():
                    file_count = sum(1 for _ in d.rglob('*') if _.is_file())
                    total_size = sum(f.stat().st_size for f in d.rglob('*') if f.is_file())
                    backup_entries.append({
                        "name": d.name,
                        "zip_path": str(d),
                        "zip_name": None,
                        "file_count": file_count,
                        "total_size": total_size,
                        "created_at": datetime.datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "format": "dir",
                        "type": "manual",
                    })

    send_json(handler, 200, {
        "auto_backup": auto_backup,
        "backup_count": len(backup_entries),
        "retention_count": _get_backup_retention_count(),
        "manual_backup_max": 10,
        "data_dir": str(data_dir),
        "backups": backup_entries,
    })


def _get_data_dir():
    """从 storage 获取数据目录(避免循环 import)。"""
    from storage import get_data_dir
    return get_data_dir()


# ============ 备份下载 ============

def handle_get_backup_download(handler):
    """GET /api/admin/backup-download?zip_name=xxx → 下载 .zip 文件

    ⚠️ 已弃用: 推荐使用 POST /api/admin/backup-download
    GET 下载可能被浏览器预取/爬虫意外触发。保留 GET 兼容性。
    """
    return handle_post_backup_download(handler, use_get=True)


def handle_post_backup_download(handler, use_get=False):
    """POST /api/admin/backup-download {zip_name} → 下载 .zip 文件

    使用 POST 而非 GET,防止浏览器预取/SEO 爬虫意外下载备份文件。
    请求体: { "zip_name": "meter-backup-20250101_120000.zip" }
    """
    data_dir = _get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)

    # 获取 zip_name(POST body 或 query)
    is_get = use_get
    try:
        body = read_body(handler)
        zip_name = (body or {}).get("zip_name", "")
    except Exception:
        # GET 兼容路径
        is_get = True
        qs = parse_qs(urlparse(handler.path).query)
        zip_name = qs.get("zip_name", [None])[0]
        if not zip_name:
            dir_name = qs.get("dir", [None])[0]
            if dir_name:
                zip_name = f"meter-backup-{dir_name}.zip"

    if not zip_name:
        send_json(handler, 400, {"error": "缺少 zip_name 参数"})
        return

    zip_path = backup_dir / zip_name
    if not zip_path.is_file():
        send_json(handler, 404, {"error": f"备份文件不存在: {zip_name}"})
        return

    # 安全校验: 防止目录穿越
    real_backup = backup_dir.resolve()
    real_zip = zip_path.resolve()
    if not str(real_zip).startswith(str(real_backup)):
        send_json(handler, 403, {"error": "非法备份文件名"})
        return

    zip_data = zip_path.read_bytes()

    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
    handler.send_header("Content-Length", str(len(zip_data)))
    handler.send_header("Cache-Control", "no-store")
    for k, v in CORS.items():
        handler.send_header(k, v)
    if is_get:
        handler.send_header("X-API-Migration", "已弃用: 请使用 POST /api/admin/backup-download")
    handler.end_headers()
    handler.wfile.write(zip_data)


# ============ 备份删除 ============

def handle_get_backup_delete(handler):
    """GET /api/admin/backup-delete?zip_name=xxx → 删除备份

    ⚠️ 已弃用: 推荐使用 POST /api/admin/backup-delete
    """
    return handle_post_backup_delete(handler, use_get=True)


def handle_post_backup_delete(handler, use_get=False):
    """POST /api/admin/backup-delete {zip_name} → 删除备份

    使用 POST 而非 GET,防止浏览器预取意外删除。
    """
    # 检查 Content-Type 防止 CSRF
    if use_get:
        content_type = handler.headers.get("Content-Type", handler.headers.get("content-type", ""))
        is_get = "application/json" not in content_type
    else:
        is_get = False

    if is_get:
        qs = parse_qs(urlparse(handler.path).query)
        zip_name = qs.get("zip_name", [None])[0]
    else:
        body = read_body(handler)
        zip_name = (body or {}).get("zip_name", "")

    if not zip_name:
        send_json(handler, 400, {"ok": False, "error": "缺少 zip_name 参数"})
        return

    data_dir = _get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)
    zip_path = backup_dir / zip_name

    if not zip_path.is_file():
        send_json(handler, 404, {"ok": False, "error": f"备份文件不存在: {zip_name}"})
        return

    # 安全校验: 防止目录穿越
    real_backup = backup_dir.resolve()
    real_zip = zip_path.resolve()
    if not str(real_zip).startswith(str(real_backup)):
        send_json(handler, 403, {"ok": False, "error": "非法备份文件名"})
        return

    try:
        zip_path.unlink()
        log(f"[BACKUP] 删除备份: {zip_name}")
        send_json(handler, 200, {"ok": True, "message": "已删除备份"})
    except OSError as e:
        send_json(handler, 500, {"ok": False, "error": f"删除失败: {e}"})


# ============ 自动备份配置 ============

def handle_put_auto_backup(handler):
    """PUT /api/admin/auto-backup {enabled: true/false}"""
    body = read_body(handler)
    settings = get_settings()
    settings["auto_backup"] = bool((body or {}).get("enabled", True))
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "auto_backup": settings["auto_backup"]})


def handle_put_backup_retention(handler):
    """PUT /api/admin/backup-retention {retention_count: 5}

    设置备份文件保留数量。默认 5 个,最小 1。
    """
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return
    count = body.get("retention_count", 5)
    if not isinstance(count, int) or count < 1:
        send_json(handler, 200, {"ok": False, "error": "保留数量必须为 ≥1 的整数"})
        return
    settings = get_settings()
    settings["backup_retention_count"] = count
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "retention_count": count})


# ============ 备份目录配置 ============

def handle_get_backup_config(handler):
    """GET /api/admin/backup-config → {ok: true, backup_dir: path|null, ...}

    macOS App 环境: 从 settings.json 读取 backup_dir 字段,用户可自定义备份目录。
    Docker 环境: 备份目录由 METER_BACKUP_DIR 环境变量控制,返回 null + 当前 data_dir 提示前端。
    """
    data_dir = _get_data_dir()

    # Docker 环境下备份目录由环境变量控制,不可修改
    if os.environ.get("METER_DOCKER"):
        backup_rel = os.environ.get("METER_BACKUP_DIR", "").strip()
        if backup_rel:
            effective_backup = str(data_dir / backup_rel)
        else:
            effective_backup = str(data_dir / "backup")
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": effective_backup,
            "backup_dir_label": "Docker 备份目录(不可修改)",
            "data_dir": str(data_dir),
            "customizable": False,
        })
        return

    # macOS App 环境: 从 settings.json 读取
    try:
        settings = get_settings()
        custom_dir = settings.get("backup_dir")
        if custom_dir:
            label = custom_dir
        else:
            custom_dir = None
            label = "默认备份目录 (data/backup)"
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": custom_dir,  # null 表示使用默认
            "backup_dir_label": label,
            "data_dir": str(data_dir),
            "customizable": True,
        })
    except Exception:
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": None,
            "backup_dir_label": "默认备份目录",
            "data_dir": str(data_dir),
            "customizable": True,
        })


def handle_put_backup_config(handler):
    """PUT /api/admin/backup-config → {ok: bool, backup_dir: path|null, error: str?}

    macOS App 环境: 将用户选择的备份目录保存到 settings.json。
    注意: 已有备份文件不会移动,新备份将保存到新目录。
    """
    # Docker 环境不允许修改
    if os.environ.get("METER_DOCKER"):
        send_json(handler, 200, {
            "ok": False,
            "error": "Docker 环境下备份目录由环境变量 METER_BACKUP_DIR 控制",
            "backup_dir": None,
            "backup_dir_label": None,
        })
        return

    body = read_body(handler)
    new_backup_dir = (body or {}).get("backup_dir")  # null 或绝对路径字符串

    try:
        settings = get_settings()
        settings["backup_dir"] = new_backup_dir
        save_settings(settings)

        label = new_backup_dir if new_backup_dir else "默认备份目录 (data/backup)"
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": new_backup_dir,
            "backup_dir_label": label,
        })
    except Exception as e:
        send_json(handler, 200, {
            "ok": False,
            "error": f"保存失败: {e}",
            "backup_dir": None,
            "backup_dir_label": None,
        })


# ============ 上传恢复 ============

def handle_post_restore_upload(handler):
    """POST /api/admin/restore-upload — 上传 ZIP 备份文件并恢复

    接受 multipart/form-data,上传一个 .zip 文件,服务端自动解压并恢复数据。
    恢复前自动备份当前数据(可回滚)。

    返回 { ok: true, restored: [...], message: "..." }
    """
    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    target_dir = data_dir.parent

    # 解析 multipart 上传
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        send_json(handler, 200, {"ok": False, "error": "请上传 ZIP 文件 (multipart/form-data)"})
        return

    # 读取上传内容
    content_length = int(handler.headers.get("Content-Length", 0))
    body_data = handler.rfile.read(content_length)
    boundary = content_type.split("boundary=", 1)[1] if "boundary=" in content_type else None

    if not boundary:
        send_json(handler, 200, {"ok": False, "error": "无法解析 multipart boundary"})
        return

    # 解析 ZIP 文件
    zip_content = None
    zip_filename = "backup.zip"

    boundary_bytes = b"--" + boundary.encode()
    parts = body_data.split(boundary_bytes)

    import re
    for part in parts:
        if part.strip() in (b"", b"--"):
            continue
        if b"\r\n\r\n" in part:
            headers, file_body = part.split(b"\r\n\r\n", 1)
            header_str = headers.decode("utf-8", errors="replace")
            fname_match = re.search(r'filename="([^"]+\.zip)"', header_str)
            if fname_match:
                zip_filename = fname_match.group(1)
                zip_content = file_body.rstrip(b"\r\n")
                break

    if not zip_content:
        send_json(handler, 200, {"ok": False, "error": "未找到 ZIP 文件"})
        return

    # 恢复前自动备份当前数据
    pre_backup = backup_data(target_dir, force=True)

    try:
        # 解压到临时目录
        import io
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_buffer_obj = io.BytesIO(zip_content)
            zip_path = Path(tmp_dir) / "restore_upload.zip"
            zip_path.write_bytes(zip_buffer_obj.read())

            # 校验: ZIP Bomb 防护
            safe_dir, error = _validate_zip_safely(zip_path, tmp_dir)
            if error:
                send_json(handler, 200, {"ok": False, "error": f"ZIP 文件不安全: {error}"})
                return

            # 校验: 必须是有效的 ZIP 且包含数据文件
            with zipfile.ZipFile(zip_buffer_obj, 'r') as zf:
                namelist = zf.namelist()
                has_readings = any("readings.json" in n for n in namelist)
                if not has_readings:
                    send_json(handler, 200, {"ok": False, "error": "ZIP 文件不包含 readings.json,不是有效的备份文件"})
                    return

            # 找到数据目录(可能是 YYYYMMDD_HHMMSS/ 子目录或根目录)
            extract_dir = Path(tmp_dir)
            children = list(extract_dir.iterdir())
            if len(children) == 1 and children[0].is_dir():
                extract_dir = children[0]

            # 恢复数据文件
            restored = []
            for name in DATA_FILES.values():
                src_file = extract_dir / name
                if src_file.exists():
                    shutil.copy2(src_file, target_dir / name)
                    restored.append(name)
                    log(f"  恢复 {name} <- {src_file}")

            # 恢复 settings.json:合并业务字段,保留目标环境的部署字段(backup_dir 等)
            settings_src = extract_dir / "settings.json"
            if settings_src.exists():
                try:
                    import json as _json
                    src_settings = _json.loads(settings_src.read_text(encoding="utf-8"))
                    _merge_settings_after_restore(target_dir, src_settings)
                    restored.append("settings.json")
                except Exception as e:
                    log(f"  [WARN] 解析/合并 settings.json 失败: {e}")

        send_json(handler, 200, {
            "ok": True,
            "restored": restored,
            "zip_name": zip_filename,
            "pre_backup": str(pre_backup) if pre_backup else "无",
            "message": f"✅ 已从 {zip_filename} 恢复 {len(restored)} 个文件",
        })
    except zipfile.BadZipFile:
        send_json(handler, 200, {"ok": False, "error": "ZIP 文件格式错误,请确认是有效的备份文件"})
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"恢复失败: {e}"})
