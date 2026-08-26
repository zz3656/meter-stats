"""
林卡酒吧电表统计 — 存储层
==========================
数据目录解析、JSON 文件读写、原子写入。
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# 支持的模型: 数据文件映射
DATA_FILES = {
    "readings": "readings.json",
    "charges": "charges.json",
    "items": "items.json",
    "purchases": "purchases.json",
}

# 每个模型的读写锁,避免 ThreadingHTTPServer 下并发写冲突
_file_locks: Dict[str, threading.Lock] = {name: threading.Lock() for name in DATA_FILES}


def get_data_dir() -> Path:
    """确定数据目录。

    优先级:
    1. 环境变量 LINCLUB_DATA_DIR(显式覆盖)
    2. ~/Library/Application Support/com.linclub.electricity-stats/(macOS 标准位置)
    3. ~/Documents/electricity-stats/data/(旧默认 — 兼容)

    首次启动时,自动从旧位置(~2)迁移数据到新位置(~1),并保留旧数据
    备份 30 天以便回滚。
    """
    # 1. 显式环境变量
    env_dir = os.environ.get("LINCLUB_DATA_DIR")
    if env_dir:
        d = Path(env_dir).expanduser().resolve()
        d.mkdir(parents=True, exist_ok=True)
        return d

    # 2. macOS 标准位置
    standard = Path.home() / "Library" / "Application Support" / "com.linclub.electricity-stats"

    # 3. 旧默认位置(兼容)
    legacy = Path.home() / "Documents" / "electricity-stats" / "data"

    # 如果已经在标准位置,直接用
    if standard.exists() and any(standard.glob("*.json")):
        standard.mkdir(parents=True, exist_ok=True)
        return standard

    # 如果标准位置空,但旧位置有数据 -> 迁移
    if legacy.exists() and any(legacy.glob("*.json")) and not any(standard.glob("*.json")):
        log(f"[[linclub]] 首次启动 -- 从旧位置迁移数据...")
        log(f"  源: {legacy}")
        log(f"  目标: {standard}")
        standard.mkdir(parents=True, exist_ok=True)

        # 拷贝所有 .json 文件
        for src in legacy.glob("*.json"):
            dst = standard / src.name
            shutil.copy2(src, dst)
            log(f"  OK 已迁移 {src.name}")

        # 拷贝 logs(如果有)
        legacy_logs = legacy.parent / "logs"
        if legacy_logs.exists():
            standard_logs = standard / "logs"
            standard_logs.mkdir(exist_ok=True)
            for src in legacy_logs.glob("*.log"):
                shutil.copy2(src, standard_logs / src.name)

        # 备份旧数据(以便回滚)
        backup_dir = legacy.parent / "data-migrated-backup"
        if not backup_dir.exists():
            shutil.copytree(legacy, backup_dir)
            log(f"  OK 旧数据已备份到: {backup_dir}")

        return standard

    # 都没有,用标准位置(创建空文件)
    standard.mkdir(parents=True, exist_ok=True)
    return standard


def init_data_files(data_dir: Path) -> dict:
    """确保所有数据文件存在,不存在则创建空数组文件。

    返回 {model: file_path} 映射。
    """
    files = {}
    for model, filename in DATA_FILES.items():
        filepath = data_dir / filename
        if not filepath.exists():
            save_json(filepath, [])
        files[model] = filepath
    backup_data(data_dir)  # 启动时每日自动备份
    return files


def backup_data(data_dir: Path, force: bool = False, target_parent: "Optional[Path]" = None):
    """备份数据文件。

    - target_parent=None: 备份到 data_dir/backup/(默认)
    - target_parent=Path: 备份到该目录(用户自选备份目录)
    - force=False: 每日一次(YYYYMMDD 目录,当天已存在则跳过)
    - force=True:  手动备份(YYYYMMDD_HHMMSS 目录,每次独立,不覆盖自动备份)

    只加不删,用户可随时手动清理 backup/ 旧目录。
    返回备份目录路径(跳过时返回 None)。
    """
    parent = target_parent if target_parent is not None else (data_dir / "backup")
    log(f"[BACKUP] data_dir={data_dir}, target_parent={target_parent}, parent={parent}, force={force}")
    # 使用 UTC 时间戳确保备份目录名可排序且与时区无关
    utc_now = datetime.utcnow()
    if force:
        stamp = utc_now.strftime("%Y%m%d_%H%M%S")
        backup_dir = parent / stamp
    else:
        today = utc_now.strftime("%Y%m%d")
        backup_dir = parent / today
        if backup_dir.exists():
            log(f"[BACKUP] 跳过: {backup_dir} 已存在")
            return None  # 今天已备份过
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log(f"[BACKUP] 无法创建目录 {backup_dir}: {e}")
        raise
    for name in DATA_FILES.values():
        src = data_dir / name
        if src.exists():
            try:
                shutil.copy2(src, backup_dir / name)
                log(f"[BACKUP] 已复制 {name} → {backup_dir}")
            except OSError as e:
                log(f"[BACKUP] 复制 {name} 失败: {e}")
                raise
        else:
            log(f"[BACKUP] 跳过 {name}: 文件不存在")
    log(f"  OK data backed up to {backup_dir}")
    return backup_dir


def log(msg: str) -> None:
    utc_now = datetime.utcnow()
    ts = utc_now.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _try_restore_from_backup(path: Path):
    """从 data_dir/backup/ 最新日期目录恢复文件。

    返回恢复后的数据(成功时),否则返回 None。
    """
    backup_root = path.parent / "backup"
    if not backup_root.exists():
        return None
    # 按日期目录名(YYYYMMDD)倒序,取最新的
    date_dirs = sorted(
        (d for d in backup_root.iterdir() if d.is_dir() and d.name.isdigit()),
        reverse=True,
    )
    for d in date_dirs:
        src = d / path.name
        if src.exists():
            try:
                with src.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                save_json(path, data)  # 恢复文件到原位置
                log(f"[RECOVER] 已从备份 {d.name} 恢复 {path.name}")
                return data
            except (json.JSONDecodeError, OSError):
                continue
    return None


def load_json(path: Path, default=None):
    """加载 JSON,文件不存在或损坏时尝试从备份恢复。"""
    if default is None:
        default = []
    if not path.exists():
        restored = _try_restore_from_backup(path)
        return restored if restored is not None else default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"[WARN] 加载 {path.name} 失败: {e},尝试从备份恢复")
        restored = _try_restore_from_backup(path)
        return restored if restored is not None else default


def save_json(path: Path, data) -> None:
    """原子写入:先写临时文件,再 rename,防止中途崩溃导致损坏。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    log(f"  OK {path.name} 已保存 ({len(data)} 条)")


def get_lock(model: str) -> threading.Lock:
    """获取指定模型的读写锁。"""
    return _file_locks.get(model, _file_locks["readings"])


def get_all_model_names() -> List[str]:
    """返回所有数据模型名称列表。"""
    return list(DATA_FILES.keys())


def get_file_count(data_dir: Path) -> Dict[str, int]:
    """获取各数据文件当前记录数。"""
    counts = {}
    for name in get_all_model_names():
        filepath = data_dir / DATA_FILES[name]
        if filepath.exists():
            try:
                counts[name] = len(load_json(filepath))
            except Exception:
                counts[name] = 0
        else:
            counts[name] = 0
    return counts
