"""
电表统计 — 存储层
==========================
数据目录解析、JSON 文件读写、原子写入。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from functools import lru_cache
from threading import RLock


# 支持的模型: 数据文件映射
DATA_FILES = {
    "readings": "readings.json",           # 电表抄表 (hall/fire/private_room/ac)
    "readings_water": "readings_water.json", # 水电表底 (main_meter/sub_meter/water)
    "charges": "charges.json",
    "items": "items.json",
    "purchases": "purchases.json",
    "duty": "duty.json",
}

# 每个模型的读写锁,避免 ThreadingHTTPServer 下并发写冲突
_FILE_LOCKS: Dict[str, threading.Lock] = {name: threading.Lock() for name in DATA_FILES}
def get_data_dir() -> Path:
    """确定数据目录。

    优先级:
    1. 环境变量 METER_DATA_DIR(显式覆盖)
    2. ~/Library/Application Support/com.meter.stats/(macOS 标准位置)
    3. ~/Documents/electricity-stats/data/(旧默认 — 兼容)

    首次启动时,自动从旧位置(~2)迁移数据到新位置(~1),并保留旧数据
    备份 30 天以便回滚。
    """
    # 1. 显式环境变量
    env_dir = os.environ.get("METER_DATA_DIR")
    if env_dir:
        d = Path(env_dir).expanduser().resolve()
        d.mkdir(parents=True, exist_ok=True)
        return d

    # 2. macOS 标准位置
    standard = Path.home() / "Library" / "Application Support" / "com.meter.stats"

    # 3. 旧默认位置(兼容)
    legacy = Path.home() / "Documents" / "electricity-stats" / "data"

    # 如果已经在标准位置,直接用
    if standard.exists() and any(standard.glob("*.json")):
        standard.mkdir(parents=True, exist_ok=True)
        return standard

    # 如果标准位置空,但旧位置有数据 -> 迁移
    if legacy.exists() and any(legacy.glob("*.json")) and not any(standard.glob("*.json")):
        log(f"[METER] 首次启动 -- 从旧位置迁移数据...")
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

    # 启动时自动备份：使用后台线程，不阻塞 HTTP 服务。
    # 如果备份目录在慢速磁盘（NFS、USB）上，ZIP 打包不应阻塞请求处理。
    try:
        import threading as _threading
        t = _threading.Thread(target=backup_data, args=(data_dir,), daemon=True)
        t.start()
        log("  [AUTO-BACKUP] 后台线程启动自动备份（不阻塞服务）")
    except Exception as e:
        log(f"  [WARN] 启动自动备份后台线程失败: {e}")

    return files


def backup_data(data_dir: Path, force: bool = False, target_parent: "Optional[Path]" = None):
    """备份数据文件。

    - target_parent=None: 优先使用 METER_BACKUP_DIR 环境变量指定的备份目录
                          （值为相对路径，如 "backup" → /data/backup/）；
                          若环境变量未设置则备份到 data_dir/backup/(默认)
    - target_parent=Path: 备份到该目录(用户自选备份目录)
    - force=False: 每日一次(YYYYMMDD 目录,当天已存在则跳过)
    - force=True:  手动备份(YYYYMMDD_HHMMSS 目录,每次独立,不覆盖自动备份)

    只加不删,用户可随时手动清理 backup/ 旧目录。
    返回备份目录路径(跳过时返回 None)。
    """
    if target_parent is not None:
        parent = target_parent
    else:
        # 优先从 settings.json 读取用户自定义备份目录。
        # 注意:启动时 init_data_files→backup_data 在 DATA_PATHS 就绪前执行,
        # 不能依赖 handlers.settings.get_settings()(它从 DATA_PATHS 取目录),
        # 直接用传入的 data_dir 读 settings.json。
        try:
            import json as _json
            settings = _json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))
            custom_backup = settings.get("backup_dir")
            if custom_backup:
                parent = Path(custom_backup)
            else:
                # settings 中没有 backup_dir，使用环境变量或默认路径
                backup_rel = os.environ.get("METER_BACKUP_DIR", "").strip()
                if backup_rel:
                    parent = data_dir / backup_rel
                else:
                    parent = data_dir / "backup"
        except Exception:
            # settings 加载失败，使用环境变量或默认路径
            backup_rel = os.environ.get("METER_BACKUP_DIR", "").strip()
            if backup_rel:
                parent = data_dir / backup_rel
            else:
                parent = data_dir / "backup"
    log(f"[BACKUP] data_dir={data_dir}, target_parent={target_parent}, parent={parent}, force={force}")
    # 使用 UTC 时间戳确保备份目录名可排序且与时区无关
    utc_now = datetime.now(timezone.utc)
    if force:
        stamp = utc_now.strftime("%Y%m%d_%H%M%S")
        backup_dir = parent / stamp
    else:
        today = utc_now.strftime("%Y%m%d")
        backup_dir = parent / today
        if backup_dir.exists():
            log(f"[BACKUP] 跳过: {backup_dir} 已存在")
            _cleanup_legacy_backups(parent)
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

    # 打包为 ZIP 并清理临时目录（自动备份使用 auto-bak- 前缀，便于按天数清理）
    stamp_name = backup_dir.name
    zip_filename = f"auto-bak-{stamp_name}.zip"
    zip_path = parent / zip_filename

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 只打包数据文件,跳过 zip_path 自身(避免 zip 包含自身 0 字节空文件)
            for f in sorted(backup_dir.iterdir()):
                if f.is_file() and f != zip_path:
                    zf.write(f, f.name)
        log(f"[BACKUP] 已打包 ZIP: {zip_filename}")
    except Exception as e:
        log(f"[BACKUP] 打包 ZIP 失败: {e}")
        shutil.rmtree(backup_dir, ignore_errors=True)
        return None

    # 清理临时目录
    shutil.rmtree(backup_dir, ignore_errors=True)

    # 清理旧格式的非 ZIP 备份目录（保持统一为 ZIP 格式）
    _cleanup_legacy_backups(parent)

    # 按保留天数清理过期自动备份(只清理 auto-bak- 前缀,不影响手动备份 meter-backup-)
    try:
        retention_days = int(json.loads((data_dir / "settings.json").read_text(encoding="utf-8")).get("backup_retention_count", 5))
    except Exception:
        retention_days = 5
    now = datetime.now(timezone.utc)
    cutoff_ts = (now - timedelta(days=retention_days)).timestamp()
    for f in parent.rglob("*.zip"):
        if f.is_file() and not f.name.startswith("auto-bak-"):
            continue
        if f.stat().st_mtime < cutoff_ts:
            try:
                f.unlink()
                log(f"[BACKUP] 清理过期自动备份: {f.name}")
            except OSError as e:
                log(f"[WARN] 清理过期备份失败 {f.name}: {e}")

    log(f"  OK data backed up to {zip_path}")
    return zip_path


def _cleanup_legacy_backups(backup_parent: Path) -> None:
    """清理旧格式的非 ZIP 备份目录。

    只要目录名对应的 ZIP 文件不存在，该目录就是旧格式备份，应被清理。
    """
    try:
        for d in sorted(backup_parent.iterdir()):
            if not d.is_dir():
                continue
            zip_name = f"meter-backup-{d.name}.zip"
            if not (backup_parent / zip_name).exists():
                try:
                    shutil.rmtree(d)
                    log(f"[BACKUP] 清理旧目录: {d.name}（无对应 ZIP，旧格式）")
                except OSError as e:
                    log(f"[WARN] 清理旧目录失败 {d.name}: {e}")
    except Exception as e:
        log(f"[WARN] 清理旧备份目录失败: {e}")


def log(msg: str) -> None:
    utc_now = datetime.now(timezone.utc)
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


# ============ JSON 文件缓存 ============

# { path_str: (mtime_ns, data) }
_json_cache: Dict[str, tuple] = {}
_json_cache_lock = RLock()
_JSON_CACHE_SIZE = 20  # 最多缓存 20 个文件

def _cache_get(path_str: str):
    """从缓存读取。返回 (mtime_ns, data) 或 (None, None)。"""
    with _json_cache_lock:
        entry = _json_cache.get(path_str)
        if entry is not None:
            return entry  # (mtime_ns, data)
        return None, None

def _cache_set(path_str: str, mtime_ns: int, data: list) -> None:
    """写入缓存。LRU 策略：新写入插到末尾，淘汰最老的（字典头部）。"""
    with _json_cache_lock:
        _json_cache[path_str] = (mtime_ns, data)
        # 超出容量时删除字典的第一个条目（最久未写入的）
        while len(_json_cache) > _JSON_CACHE_SIZE:
            _json_cache.pop(next(iter(_json_cache)), None)

def _cache_invalidate(path_str: str) -> None:
    """失效指定路径的缓存。"""
    with _json_cache_lock:
        _json_cache.pop(path_str, None)

def _cache_clear() -> None:
    """清除全部缓存。"""
    with _json_cache_lock:
        _json_cache.clear()


def load_json(path: Path, default=None):
    """加载 JSON,文件不存在或损坏时尝试从备份恢复。

    使用基于 mtime 的简单缓存：如果文件修改时间未变，直接返回缓存数据。
    """
    if default is None:
        default = []

    path_str = str(path.resolve())

    # 优先查缓存
    entry = _cache_get(path_str)
    if entry[0] is not None:
        cache_mtime, data = entry
        # 验证 mtime
        try:
            actual_mtime = path.stat().st_mtime_ns
            if cache_mtime == actual_mtime:
                return data
        except OSError:
            pass

    # 缓存未命中或文件已更新，从磁盘读取
    if not path.exists():
        restored = _try_restore_from_backup(path)
        if restored is not None:
            # 写入缓存
            try:
                _cache_set(path_str, path.stat().st_mtime_ns, restored)
            except OSError:
                pass
            return restored
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # 写入缓存
        try:
            _cache_set(path_str, path.stat().st_mtime_ns, data)
        except OSError:
            pass
        return data
    except (json.JSONDecodeError, OSError) as e:
        log(f"[WARN] 加载 {path.name} 失败: {e},尝试从备份恢复")
        restored = _try_restore_from_backup(path)
        if restored is not None:
            return restored
        return default


def save_json(path: Path, data) -> None:
    """原子写入:先写临时文件,再 rename,防止中途崩溃导致损坏。

    同时失效该路径的缓存。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    # 失效缓存
    _cache_invalidate(str(path.resolve()))
    log(f"  OK {path.name} 已保存 ({len(data)} 条)")


def get_lock(model: str) -> threading.Lock:
    """获取指定模型的读写锁。"""
    return _FILE_LOCKS.get(model, _FILE_LOCKS["readings"])


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
