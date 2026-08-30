"""备份相关 API handler。"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from utils import send_json, read_body
from storage import backup_data, DATA_FILES, log


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


def _cleanup_manual_backups(backup_parent):
    """手动备份只保留最新的 10 个,超过则删除最旧的(meter-backup- 前缀)。

    自动备份(auto-bak- 前缀)不受此限制,由 storage.py 按保留天数清理。
    """
    backups = sorted(
        (f for f in backup_parent.rglob("meter-backup-*.zip") if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for f in backups[10:]:
        try:
            f.unlink()
            log(f"[BACKUP] 手动备份超上限(10),删除最旧: {f.name}")
        except OSError as e:
            log(f"[WARN] 清理手动备份失败 {f.name}: {e}")


def _resolve_backup_parent(data_dir):
    """解析备份父目录(所有备份相关 handler 共用,保持一致):
    settings.json 的 backup_dir > METER_BACKUP_DIR 环境变量 > data_dir/backup
    """
    try:
        from handlers.settings import get_settings
        settings = get_settings()
        custom_backup = settings.get("backup_dir")
        if custom_backup:
            return Path(custom_backup)
    except Exception:
        pass
    backup_rel = os.environ.get("METER_BACKUP_DIR", "").strip()
    if backup_rel:
        return Path(data_dir) / backup_rel
    return Path(data_dir) / "backup"


def handle_post_backup(handler):
    """POST /api/backup

    手动备份: 创建数据快照 → 打包为 ZIP 压缩包 → 保存到备份目录。

    备份目录由 settings.json 的 backup_dir(用户自定义)或 METER_BACKUP_DIR 环境变量控制，
    均未设置时默认 data_dir/backup。

    每次点击都新建一个备份(同日可多次),手动备份最多保留 10 个(自动清理最旧的)。

    返回 { ok: true, zip_path: "/data/backup/20250101_120000/meter-backup-20250101_120000.zip", backup_name: "20250101_120000" }
    """
    import datetime

    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    source_dir = data_dir.parent
    backup_parent = _resolve_backup_parent(source_dir)

    backup_parent.mkdir(parents=True, exist_ok=True)

    # 生成带时间戳的备份目录名和文件名(含毫秒,同秒多次点击也不会重名覆盖)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
    backup_dir = backup_parent / stamp
    zip_filename = f"meter-backup-{stamp}.zip"

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

        # 2. 打包为 ZIP（同时打包临时目录中的数据和 zip 自身）
        zip_path = backup_dir / zip_filename
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in backup_dir.rglob('*'):
                if f.is_file():
                    zf.write(f, f.name)

        # 3. 将 zip 移到备份父目录（避免被 rmtree 误删），再清理临时目录
        final_zip = backup_parent / zip_filename
        shutil.move(str(zip_path), str(final_zip))
        shutil.rmtree(backup_dir, ignore_errors=True)

        # 4. 手动备份只保留最新 10 个(自动备份按天数由 storage.py 清理)
        _cleanup_manual_backups(backup_parent)

        send_json(handler, 200, {
            "ok": True,
            "zip_path": str(final_zip),
            "backup_name": stamp,
            "backup_dir": str(backup_parent),
            "manual_backup_max": 10,
        })
    except Exception as e:
        # 出错时清理残留
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        send_json(handler, 200, {"ok": False, "error": f"备份失败: {e}"})


def handle_post_restore(handler):
    """POST /api/restore

    body: { "zip_path": "/data/backup/20250101_120000/meter-backup-20250101_120000.zip" }
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
