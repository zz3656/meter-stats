"""备份相关 API handler。"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from utils import send_json, read_body
from storage import backup_data, DATA_FILES


def _get_data_paths():
    import app_handler as _h
    return _h.DATA_PATHS


def handle_get_data_files(handler):
    """GET /api/admin/data-files — 浏览器备份: 获取所有数据文件的当前内容。

    返回 { ok: true, files: { "readings.json": "<JSON字符串>", ... } }
    用于 Docker/浏览器环境下的备份（无需 Swift 桥接）。
    """
    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    target_dir = data_dir.parent
    files = {}
    data_file_names = set(DATA_FILES.values()) | {"settings.json"}

    for f in target_dir.iterdir():
        if f.is_file() and f.suffix == '.json' and f.name in data_file_names:
            try:
                files[f.name] = f.read_text(encoding="utf-8")
            except OSError as e:
                log(f"[WARN] 读取 {f.name} 失败: {e}")

    send_json(handler, 200, {"ok": True, "files": files})


def _get_backup_retention_count():
    """从 settings.json 读取备份保留数量，默认 5。"""
    try:
        from handlers.settings import get_settings
        settings = get_settings()
        count = settings.get("backup_retention_count", 5)
        if isinstance(count, int) and count >= 1:
            return count
    except Exception:
        pass
    return 5


def _cleanup_old_backups(backup_parent, max_count):
    """清理多余的旧备份，只保留最新的 max_count 个 ZIP 文件。"""
    if max_count < 1:
        return
    backups = sorted(backup_parent.rglob("*.zip"), reverse=True)
    if len(backups) <= max_count:
        return
    for old_backup in backups[max_count:]:
        try:
            old_backup.unlink()
            log(f"[BACKUP] 清理旧备份: {old_backup.name}")
        except OSError as e:
            log(f"[WARN] 清理旧备份失败 {old_backup.name}: {e}")


def handle_post_backup(handler):
    """POST /api/backup

    手动备份: 创建数据快照 → 打包为 ZIP 压缩包 → 保存到备份目录。

    备份目录由 LINCLUB_BACKUP_DIR 环境变量控制（相对路径，
    如 "backup" → /data/backup/）；若未设置则默认 /data/backup/。

    备份数量由 settings.json 中的 backup_retention_count 控制，默认保留 5 个。

    返回 { ok: true, zip_path: "/data/backup/20250101_120000/linclub-backup-20250101_120000.zip", backup_name: "20250101_120000" }
    """
    import datetime

    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    source_dir = data_dir.parent

    # 确定备份父目录
    backup_rel = os.environ.get("LINCLUB_BACKUP_DIR", "").strip()
    if backup_rel:
        backup_parent = source_dir / backup_rel
    else:
        backup_parent = source_dir / "backup"

    backup_parent.mkdir(parents=True, exist_ok=True)

    # 生成带时间戳的备份目录名和文件名
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_parent / stamp
    zip_filename = f"linclub-backup-{stamp}.zip"

    try:
        # 1. 先创建数据目录（复制所有数据文件）
        backup_dir.mkdir(parents=True, exist_ok=True)
        settings_src = source_dir / "settings.json"
        for name in DATA_FILES.values():
            src = source_dir / name
            if src.exists():
                shutil.copy2(src, backup_dir / name)
        if settings_src.exists():
            shutil.copy2(settings_src, backup_dir / "settings.json")

        # 2. 打包为 ZIP
        zip_path = backup_dir / zip_filename
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in backup_dir.rglob('*'):
                if f.is_file():
                    zf.write(f, f.name)

        # 3. 清理临时目录（只保留 zip）
        shutil.rmtree(backup_dir, ignore_errors=True)

        # 4. 清理多余旧备份，只保留最新的 N 个
        retention = _get_backup_retention_count()
        _cleanup_old_backups(backup_parent, retention)

        send_json(handler, 200, {
            "ok": True,
            "zip_path": str(zip_path),
            "backup_name": stamp,
            "backup_dir": str(backup_parent),
            "retention_count": retention,
        })
    except Exception as e:
        # 出错时清理残留
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        send_json(handler, 200, {"ok": False, "error": f"备份失败: {e}"})


def handle_post_restore(handler):
    """POST /api/restore

    body: { "zip_path": "/data/backup/20250101_120000/linclub-backup-20250101_120000.zip" }
    从 ZIP 压缩包恢复数据到数据目录。
    ⚠️ 安全措施: 恢复前先把当前数据自动备份一份(可回滚),再解压覆盖。
    """
    import datetime
    import zipfile

    body = read_body(handler)
    zip_path = (body or {}).get("zip_path") or ""
    zip_file = Path(zip_path)

    if not zip_file.is_file():
        send_json(handler, 200, {"ok": False, "error": f"ZIP 文件不存在: {zip_path}"})
        return

    # 恢复前自动备份当前数据(可回滚)
    pre_backup = backup_data(data_dir.parent, force=True) if (data_dir := _get_data_paths().get("readings")) else None

    try:
        # 解压到临时目录
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(zip_file, 'r') as zf:
                zf.extractall(tmp_dir)

            target_dir = (data_dir.parent if data_dir else Path("/data"))

            # 找到解压出的数据目录（可能是 YYYYMMDD_HHMMSS/ 子目录或根目录）
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

            # 恢复 settings.json
            settings_src = extract_dir / "settings.json"
            if settings_src.exists():
                shutil.copy2(settings_src, target_dir / "settings.json")
                restored.append("settings.json")

        send_json(handler, 200, {
            "ok": True,
            "restored": restored,
            "pre_backup": str(pre_backup) if pre_backup else "无",
            "source_zip": str(zip_file),
        })
    except zipfile.BadZipFile:
        send_json(handler, 200, {"ok": False, "error": "ZIP 文件格式错误"})
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"恢复失败: {e}"})


def handle_post_upload(handler):
    """POST /api/upload — 浏览器直接上传 JSON 文件恢复数据

    接受 multipart/form-data 或 JSON body:
      - multipart: 上传 readings.json, charges.json, items.json, purchases.json, settings.json
      - JSON body: { "files": { "readings.json": [...], "charges.json": [...] } }

    上传后直接覆盖 /data/ 中对应的数据文件。
    """
    import shutil
    import tempfile
    import os

    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    target_dir = data_dir.parent

    content_type = handler.headers.get("Content-Type", "")

    uploaded = []

    if "multipart/form-data" in content_type:
        # multipart/form-data 上传
        # 解析表单数据 (简化版: 每个 field name 是文件名)
        boundary = content_type.split("boundary=", 1)[1]
        if not boundary:
            send_json(handler, 200, {"ok": False, "error": "无法解析 multipart boundary"})
            return

        body = read_body(handler)
        # 尝试用 multipart 解析
        data = handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
        lines = data.split(boundary.encode())
        for line in lines:
            line_str = line.decode("utf-8", errors="replace")
            # 提取文件名
            fname_match = re.search(r'filename="([^"]+)"', line_str)
            if not fname_match:
                continue
            fname = fname_match.group(1)
            if fname not in DATA_FILES.values() and fname != "settings.json":
                continue
            # 提取文件内容 (在第二个 \r\n\r\n 之后)
            parts = line.split(b"\r\n\r\n", 1)
            if len(parts) != 2:
                continue
            file_content = parts[1].rstrip(b"\r\n")
            if fname == "--":
                continue
            dest = target_dir / fname
            dest.write_bytes(file_content)
            uploaded.append(fname)
            log(f"  上传 {fname} → {dest}")

    else:
        # JSON body: { "files": { "readings.json": [...], ... } }
        body = read_body(handler)
        files = (body or {}).get("files")
        if not files:
            send_json(handler, 200, {"ok": False, "error": "请提供 files 字段"})
            return

        for fname, content in files.items():
            if fname not in DATA_FILES.values() and fname != "settings.json":
                continue
            dest = target_dir / fname
            if isinstance(content, list) or isinstance(content, dict):
                dest.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            elif isinstance(content, str):
                dest.write_text(content, encoding="utf-8")
            uploaded.append(fname)
            log(f"  上传 {fname} → {dest}")

    send_json(handler, 200, {
        "ok": True,
        "uploaded": uploaded,
    })
