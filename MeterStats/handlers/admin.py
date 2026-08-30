"""认证 + 后台管理 API handler。
"""
from __future__ import annotations
import datetime
import os
import secrets
import zipfile
import tempfile
import shutil
from pathlib import Path
from utils import send_json, read_body
from handlers.settings import (
    get_settings, save_settings, init_settings, verify_password,
    add_user, update_user, delete_user, ROLES,
)
from handlers.backup import _get_backup_retention_count
from storage import log


def _get_data_paths():
    import app_handler as _h
    return _h.DATA_PATHS


# 会话存储: session_id -> {user_id, username, role, name}
_SESSIONS: dict = {}
SESSION_SECRET = secrets.token_hex(32)


def handle_post_login(handler):
    """POST /api/auth/login {username, password} → {ok, token, user}"""
    body = read_body(handler)
    username = (body or {}).get("username", "").strip()
    password = (body or {}).get("password", "")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    settings = get_settings()
    users = settings.get("users", [])
    user = next((u for u in users if u["username"] == username), None)

    if not user or not user.get("enabled", True):
        send_json(handler, 200, {"ok": False, "error": "用户不存在或已禁用"})
        return

    if not verify_password(password, user["password"]):
        send_json(handler, 200, {"ok": False, "error": "密码错误"})
        return

    token = secrets.token_hex(32)
    _SESSIONS[token] = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "name": user["name"],
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }

    send_json(handler, 200, {
        "ok": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
        },
    })


def handle_get_logout(handler):
    """GET /api/auth/logout?token=xxx → {ok}"""
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0]
    if token and token in _SESSIONS:
        del _SESSIONS[token]
    send_json(handler, 200, {"ok": True})


def handle_get_me(handler):
    """GET /api/auth/me?token=xxx → {user} or {user: null}"""
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    token = qs.get("token", [None])[0]

    if token and token in _SESSIONS:
        sess = _SESSIONS[token]
        send_json(handler, 200, {"user": {
            "id": sess["user_id"],
            "username": sess["username"],
            "name": sess["name"],
            "role": sess["role"],
        }})
    else:
        send_json(handler, 200, {"user": None})


# ============ 用户管理 CRUD ============

def handle_get_users(handler):
    """GET /api/admin/users → [users]"""
    settings = get_settings()
    # 不返回密码
    users = [{k: v for k, v in u.items() if k != "password"} for u in settings.get("users", [])]
    send_json(handler, 200, users)


def handle_post_users(handler):
    """POST /api/admin/users {username, password, name, role} → {ok, user}"""
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    users = settings.get("users", [])
    username = (body or {}).get("username", "")
    password = (body or {}).get("password", "")
    name = (body or {}).get("name", username)
    role = (body or {}).get("role", "employee")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    result = add_user(users, username, password, name, role)
    if isinstance(result, dict) and "error" in result:
        send_json(handler, 200, {"ok": False, "error": result["error"]})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "user": result})


def handle_put_users(handler, path_clean: str):
    """PUT /api/admin/users/<uid> {fields} → {ok, user}"""
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(handler.path).query)
    uid_str = qs.get("id", [None])[0]
    if not uid_str or not uid_str.isdigit():
        send_json(handler, 200, {"ok": False, "error": "无效的用户ID"})
        return

    uid = int(uid_str)
    settings = get_settings()
    users = settings.get("users", [])
    result = update_user(users, uid, (body := read_body(handler)))
    if result is None:
        send_json(handler, 200, {"ok": False, "error": "用户不存在"})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "user": {k: v for k, v in result.items() if k != "password"}})


def handle_delete_users(handler, path_clean: str):
    """DELETE /api/admin/users/<uid> → {ok}"""
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(handler.path).query)
    uid_str = qs.get("id", [None])[0]
    if not uid_str or not uid_str.isdigit():
        send_json(handler, 200, {"ok": False, "error": "无效的用户ID"})
        return

    uid = int(uid_str)
    settings = get_settings()
    users = settings.get("users", [])
    deleted = delete_user(users, uid)
    if not deleted:
        send_json(handler, 200, {"ok": False, "error": "用户不存在"})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True})


# ============ 电表设置 ============

def handle_get_meter_settings(handler):
    """GET /api/admin/meter → {meter, config}"""
    settings = get_settings()
    send_json(handler, 200, {
        "meter": settings.get("meter", {}),
        "config": settings.get("config", {}),
    })


def handle_put_meter_settings(handler):
    """PUT /api/admin/meter → {meter, config}"""
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    if "meter" in body:
        settings["meter"] = body["meter"]
    if "config" in body:
        settings["config"] = body["config"]
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "meter": settings["meter"], "config": settings["config"]})


# ============ 权限管理 ============

def handle_get_roles(handler):
    """GET /api/admin/roles → [roles]"""
    send_json(handler, 200, [{"key": k, "name": v} for k, v in ROLES.items()])


# ============ 数据管理 ============

def handle_get_backup_status(handler):
    """GET /api/admin/backup-status → {auto_backup, backup_count, backups: [...]}

    列出备份目录下所有的 ZIP 压缩包(手动 meter-backup- + 自动 auto-bak-)，
    每个 ZIP 算一个备份，带 type 字段区分(manual/auto)。
    返回 { name, zip_path, file_count, total_size, created_at, type }
    """
    import zipfile as zf_mod
    from storage import get_data_dir
    from handlers.backup import _resolve_backup_parent

    settings = get_settings()
    auto_backup = settings.get("auto_backup", True)
    data_dir = get_data_dir()
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
                with zf_mod.ZipFile(f, 'r') as zf:
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

        # 再列出旧格式的备份目录（非 .zip 目录，排除带 _ 的时间戳目录，因为已被 ZIP 覆盖）
        for d in sorted(backup_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if d.is_dir() and not d.name.endswith('.zip'):
                # 只列出没有对应 .zip 的旧目录
                zip_name = f"meter-backup-{d.name}.zip"
                if not (backup_dir / zip_name).exists():
                    # 统计目录内文件
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


def handle_get_backup_download(handler):
    """GET /api/admin/backup-download?zip_name=meter-backup-20250101_120000.zip → 下载 .zip 文件"""
    from storage import get_data_dir
    from handlers.backup import _resolve_backup_parent
    from urllib.parse import parse_qs, urlparse

    data_dir = get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)

    qs = parse_qs(urlparse(handler.path).query)
    zip_name = qs.get("zip_name", [None])[0]

    if not zip_name:
        # 兼容旧版 dir 参数
        dir_name = qs.get("dir", [None])[0]
        if dir_name:
            zip_name = f"meter-backup-{dir_name}.zip"
        else:
            send_json(handler, 400, {"error": "缺少 zip_name 参数"})
            return

    zip_path = backup_dir / zip_name
    if not zip_path.is_file():
        send_json(handler, 404, {"error": f"备份文件不存在: {zip_name}"})
        return

    zip_data = zip_path.read_bytes()

    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
    handler.send_header("Content-Length", str(len(zip_data)))
    from utils import CORS
    for k, v in CORS.items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(zip_data)


def handle_get_backup_delete(handler):
    """GET /api/admin/backup-delete?zip_name=meter-backup-20250101_120000.zip → 删除备份"""
    from storage import get_data_dir
    from handlers.backup import _resolve_backup_parent
    from urllib.parse import parse_qs, urlparse

    data_dir = get_data_dir()
    backup_dir = _resolve_backup_parent(data_dir)

    qs = parse_qs(urlparse(handler.path).query)
    zip_name = qs.get("zip_name", [None])[0]

    if not zip_name:
        send_json(handler, 400, {"ok": False, "error": "缺少 zip_name 参数"})
        return

    zip_path = backup_dir / zip_name
    if not zip_path.is_file():
        send_json(handler, 404, {"ok": False, "error": f"备份文件不存在: {zip_name}"})
        return

    try:
        zip_path.unlink()
        log(f"[BACKUP] 删除备份: {zip_name}")
        send_json(handler, 200, {"ok": True, "message": "已删除备份"})
    except OSError as e:
        send_json(handler, 500, {"ok": False, "error": f"删除失败: {e}"})


def handle_put_auto_backup(handler):
    """PUT /api/admin/auto-backup {enabled: true/false}"""
    body = read_body(handler)
    settings = get_settings()
    settings["auto_backup"] = bool((body or {}).get("enabled", True))
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "auto_backup": settings["auto_backup"]})


def handle_put_backup_retention(handler):
    """PUT /api/admin/backup-retention {retention_count: 5}

    设置备份文件保留数量。默认 5 个，最小 1。
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
    """GET /api/admin/backup-config → {ok: true, backup_dir: path|null, backup_dir_label: str, data_dir: str}

    macOS App 环境: 从 settings.json 读取 backup_dir 字段，用户可自定义备份目录。
    Docker 环境: 备份目录由 METER_BACKUP_DIR 环境变量控制，返回 null + 当前 data_dir 提示前端显示默认路径。
    """
    from storage import get_data_dir
    data_dir = get_data_dir()

    # Docker 环境下备份目录由环境变量控制，不可修改
    if os.environ.get("METER_DOCKER"):
        backup_rel = os.environ.get("METER_BACKUP_DIR", "").strip()
        if backup_rel:
            effective_backup = str(data_dir / backup_rel)
        else:
            effective_backup = str(data_dir / "backup")
        send_json(handler, 200, {
            "ok": True,
            "backup_dir": effective_backup,
            "backup_dir_label": "Docker 备份目录（不可修改）",
            "data_dir": str(data_dir),
            "customizable": False,
        })
        return

    # macOS App 环境: 从 settings.json 读取
    try:
        from handlers.settings import get_settings
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
    注意: 已有备份文件不会移动，新备份将保存到新目录。
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
        from handlers.settings import get_settings, save_settings
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


def handle_post_restore_upload(handler):
    """POST /api/admin/restore-upload — 上传 ZIP 备份文件并恢复

    接受 multipart/form-data，上传一个 .zip 文件，服务端自动解压并恢复数据。
    恢复前自动备份当前数据（可回滚）。

    返回 { ok: true, restored: [...], message: "..." }
    """
    import zipfile as zf_mod

    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    target_dir = data_dir.parent
    from storage import backup_data

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

    for part in parts:
        if part.strip() in (b"", b"--"):
            continue
        # 分离 headers 和 body
        if b"\r\n\r\n" in part:
            headers, file_body = part.split(b"\r\n\r\n", 1)
            header_str = headers.decode("utf-8", errors="replace")
            # 提取文件名
            fname_match = __import__('re').search(r'filename="([^"]+\.zip)"', header_str)
            if fname_match:
                zip_filename = fname_match.group(1)
                # 去掉尾部 \r\n
                zip_content = file_body.rstrip(b"\r\n")
                break

    if not zip_content:
        send_json(handler, 200, {"ok": False, "error": "未找到 ZIP 文件"})
        return

    # 恢复前自动备份当前数据
    pre_backup = backup_data(target_dir, force=True)

    try:
        # 解压 ZIP 到临时目录
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_buffer = __import__('io').BytesIO(zip_content)
            with zf_mod.ZipFile(zip_buffer, 'r') as zf:
                # 校验：必须是有效的 ZIP 且包含数据文件
                namelist = zf.namelist()
                has_readings = any("readings.json" in n for n in namelist)
                if not has_readings:
                    send_json(handler, 200, {"ok": False, "error": "ZIP 文件不包含 readings.json，不是有效的备份文件"})
                    return

                zf.extractall(tmp_dir)

            # 找到数据目录（可能是 YYYYMMDD_HHMMSS/ 子目录或根目录）
            extract_dir = Path(tmp_dir)
            children = list(extract_dir.iterdir())
            if len(children) == 1 and children[0].is_dir():
                extract_dir = children[0]

            # 恢复数据文件
            from storage import DATA_FILES
            restored = []
            for name in DATA_FILES.values():
                src_file = extract_dir / name
                if src_file.exists():
                    shutil.copy2(src_file, target_dir / name)
                    restored.append(name)
                    log(f"  恢复 {name} <- {src_file}")

            # 恢复 settings.json
            settings_src = extract_dir / "settings.json"
            if settings_src.exists():
                shutil.copy2(settings_src, target_dir / "settings.json")
                restored.append("settings.json")

        send_json(handler, 200, {
            "ok": True,
            "restored": restored,
            "zip_name": zip_filename,
            "pre_backup": str(pre_backup) if pre_backup else "无",
            "message": f"✅ 已从 {zip_filename} 恢复 {len(restored)} 个文件",
        })
    except zf_mod.BadZipFile:
        send_json(handler, 200, {"ok": False, "error": "ZIP 文件格式错误，请确认是有效的备份文件"})
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"恢复失败: {e}"})


def handle_get_dir_listing(handler):
    """GET /api/admin/dir-listing?path=/data → { ok, path, entries: [{name, is_dir, is_file, size}] }"""
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(handler.path).query)
    target_path = qs.get("path", [None])[0]

    if not target_path:
        send_json(handler, 400, {"error": "缺少 path 参数"})
        return

    try:
        p = Path(target_path).resolve()
    except Exception:
        send_json(handler, 400, {"error": f"无效路径: {target_path}"})
        return

    if not p.exists():
        send_json(handler, 404, {"error": f"路径不存在: {target_path}"})
        return

    if p.is_file():
        send_json(handler, 200, {"path": str(p), "entries": []})
        return

    entries = []
    try:
        for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            stat_info = item.stat()
            entries.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "is_file": item.is_file(),
                "size": stat_info.st_size if item.is_file() else 0,
                "modified": datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    except PermissionError:
        send_json(handler, 403, {"error": f"没有权限读取: {target_path}"})
        return
    except OSError as e:
        send_json(handler, 500, {"error": f"读取失败: {e}"})
        return

    send_json(handler, 200, {"path": target_path, "entries": entries})
