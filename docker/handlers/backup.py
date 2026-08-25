"""备份相关 API handler。"""
from __future__ import annotations

from pathlib import Path

from utils import send_json, read_body
from storage import backup_data


def _get_data_paths():
    import app_handler as _h
    return _h.DATA_PATHS


def handle_post_backup(handler):
    """POST /api/backup

    body 可选: { "target_dir": "/用户/选择的/目录" }
    - 带 target_dir:备份到 所选目录/YYYYMMDD_HHMMSS/(用户自选备份目录)
    - 不带:         备份到 数据目录/backup/YYYYMMDD_HHMMSS/(默认)
    备份目录以「日期时间」命名,与自动备份格式一致。
    """
    body = read_body(handler)
    target_dir = (body or {}).get("target_dir") or None

    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    if target_dir:
        target = Path(target_dir).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            send_json(handler, 200, {"ok": False, "error": f"无法创建备份目录: {e}"})
            return
    else:
        target = None  # 默认走数据目录/backup

    result = backup_data(data_dir.parent, force=True, target_parent=target)
    if result:
        send_json(handler, 200, {"ok": True, "backup_dir": str(result)})
    else:
        send_json(handler, 200, {"ok": True, "backup_dir": str(target or (data_dir / "backup"))})


def handle_post_restore(handler):
    """POST /api/restore

    body: { "source_dir": "/用户选择的/备份文件夹" }
    从所选备份文件夹恢复数据到数据目录。
    ⚠️ 安全措施:恢复前先把当前数据自动备份一份(可回滚),再复制备份文件覆盖。
    只恢复存在的 .json 数据文件,不删除任何当前数据。
    """
    from storage import DATA_FILES, log

    body = read_body(handler)
    source_dir = (body or {}).get("source_dir") or ""
    src = Path(source_dir).expanduser()

    if not src.is_dir():
        send_json(handler, 200, {"ok": False, "error": f"目录不存在: {source_dir}"})
        return

    # 校验:必须是备份文件夹(含 readings.json)
    if not (src / "readings.json").exists():
        send_json(handler, 200, {"ok": False, "error": "所选目录不是备份文件夹(未找到 readings.json)"})
        return

    data_dir = _get_data_paths().get("readings")
    if not data_dir:
        send_json(handler, 200, {"ok": False, "error": "数据目录未知"})
        return

    # 1. 恢复前自动备份当前数据(可回滚)
    pre_backup = backup_data(data_dir.parent, force=True)
    # 2. 复制备份文件 → 数据目录(只覆盖存在的文件,不删除)
    #    ⚠️ data_dir 是 readings.json 文件路径,目标目录是它的 parent
    restored = []
    target_dir = data_dir.parent
    for name in DATA_FILES.values():
        src_file = src / name
        if src_file.exists():
            import shutil
            shutil.copy2(src_file, target_dir / name)
            restored.append(name)
            log(f"  恢复 {name} <- {src_file}")

    send_json(handler, 200, {
        "ok": True,
        "restored": restored,
        "pre_backup": str(pre_backup) if pre_backup else "无",
        "source_dir": str(src),
    })
