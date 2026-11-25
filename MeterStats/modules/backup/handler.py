"""备份相关 API handler。"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

from utils import read_body, send_json
from utils.api import _validate_zip_safely

from storage import (
    BACKUP_EXCLUDED_SETTINGS_KEYS,
    DATA_FILES,
    _cache_clear,
    backup_data,
    log,
)

# settings.json 中属于"部署环境配置"的字段,备份时不应包含(避免恢复到其他机器时破坏部署)
# 这些字段在每台机器/容器上独立配置,不是业务数据
#
# ⚠️ 键集合的**唯一真相来源**在 storage.BACKUP_EXCLUDED_SETTINGS_KEYS ——
#    手动备份与自动备份共用它。以前各写一份,自动备份漏了 nas_sync_*,
#    自动备份的 ZIP 里明文躺着 NAS 密码。
_BACKUP_EXCLUDED_SETTINGS_KEYS = BACKUP_EXCLUDED_SETTINGS_KEYS


def _iter_store_files(base_dir: Path) -> list[tuple[str, Path]]:
    """列出 stores/ 子树下的数据文件。

    返回 [(相对路径, 绝对路径)],相对路径形如 "stores/s002/readings.json"。

    ⚠️ 只认 *.json —— 值班照片(images/)从来就没被备份过,维持现状。
    若将来要把图片纳入备份,这里必须同步扩展,恢复侧(_safe_rel_target 的白名单)
    也要一起扩展,否则会出现「备份包里有照片、恢复时静默丢弃」。
    """
    out: list[tuple[str, Path]] = []
    stores_dir = base_dir / "stores"
    if not stores_dir.is_dir():
        return out
    for src in sorted(stores_dir.rglob("*.json")):
        if not src.is_file():
            continue
        out.append((str(src.relative_to(base_dir)).replace("\\", "/"), src))
    return out


def _is_under(base: Path, target: Path) -> bool:
    """target 是否在 base 之内(路径穿越的最后一道护栏)。"""
    try:
        b = base.resolve()
        t = target.resolve()
    except OSError:
        return False
    return t == b or b in t.parents


def _safe_rel_target(base_dir: Path, rel: str) -> Optional[Path]:
    """把备份包里的相对路径解析成目标路径,挡掉路径穿越。

    允许的两种形态:
    - 顶层数据文件:readings.json / settings.json 等
    - 门店子文件:stores/<safe_id>/<safe_name>.json
      (safe_id 要过 registry.is_valid_store_id,safe_name 要过白名单;
       store.json 是门店配置,必须能恢复)

    其它一律拒绝(返回 None)。特别是 ".." 和绝对路径。
    """
    if not rel or not isinstance(rel, str):
        return None
    if rel.startswith("/") or "\\" in rel:
        return None
    parts = rel.split("/")
    if len(parts) == 1:
        if parts[0] in set(DATA_FILES.values()) | {"settings.json"}:
            target = base_dir / parts[0]
            return target if _is_under(base_dir, target) else None
        return None
    if len(parts) == 3 and parts[0] == "stores":
        from modules.stores.registry import is_valid_store_id
        if not is_valid_store_id(parts[1]):
            return None
        if parts[2] not in set(DATA_FILES.values()) | {"store.json"}:
            return None
        target = base_dir / "stores" / parts[1] / parts[2]
        return target if _is_under(base_dir, target) else None
    return None


def _filter_settings_for_backup(settings: dict) -> dict:
    """备份 settings 时,移除与部署环境相关的字段(backup_dir 等)。

    目的:手动备份的 zip 可以安全地恢复到任何机器/Docker 容器,而不会破坏目标环境的部署配置。
    """
    return {k: v for k, v in settings.items() if k not in _BACKUP_EXCLUDED_SETTINGS_KEYS}


# ============ 门店范围闸(R1)============

class _StoreScopeDeniedError(Exception):
    """门店范围校验失败 —— 整个请求拒绝(403),不是「跳过这个文件」。

    载荷里的目标门店越界时,必须**一个文件都不写**:
    写一半再报错,用户根本不知道哪个文件已经落地了。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _scope_check_rels(handler: Any, rels: Iterable[str]) -> Tuple[bool, str]:
    """校验一批备份相对路径的**目标门店**是否都在调用方的门店范围内。
    返回 (是否通过, 错误文案)。任何一个目标门店越界 → 整个请求拒绝。
    """
    from modules.stores.handler import rel_store_scope_check
    for rel in rels:
        ok, err = rel_store_scope_check(handler, rel)
        if not ok:
            log(f"[WARN] 门店范围校验失败: {rel} → {err}")
            return (False, err)
    return (True, "")


def _backup_zip_scope_ok(handler: Any, zip_path: Path) -> Tuple[bool, str]:
    """备份包里的门店是否都在调用方的门店范围内。

    为什么下载也要过这道闸:备份包是**已经落在盘上的文件**,不经过
    backup_data(store_filter=...) 那条路 —— 自动备份永远是全量的。
    受门店范围限制的调用方只要能下载整包,就等于跨店导出了别家门店的数据。
    「新建的备份按范围过滤」不等于「下载时按范围过滤」,两头都得堵。

    - 单店布局 / 总部账号(all_stores)→ 放行
    - 受限调用方 → 包里只要有范围外的门店数据就拒绝
    - 顶层文件在多店布局下归属总店(与 backup_rel_store_id 同一口径)
    """
    from modules.stores.handler import (
        backup_rel_store_id,
        caller_store_scope,
        parse_store_target,
    )

    ok, allowed, msg = caller_store_scope(handler)
    if not ok:
        return (False, msg)
    if allowed is None:
        return (True, "")

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
    except Exception as e:
        return (False, f"读取备份包失败: {e}")

    for name in names:
        shape_ok, _sid = parse_store_target(name)
        if not shape_ok:
            # 不是数据文件形状(目录条目/其它文件)→ 不算门店数据
            continue
        owner = backup_rel_store_id(name)
        if owner not in allowed:
            return (False, f"备份包含其它门店的数据,无权下载: {owner}")
    return (True, "")


def _restore_targets(extract_dir: Path) -> List[str]:
    """备份包里将被写回的数据文件相对路径(顶层 + stores/ 子树)。"""
    rels: List[str] = []
    for name in DATA_FILES.values():
        if (extract_dir / name).exists():
            rels.append(name)
    for rel, _ in _iter_store_files(extract_dir):
        rels.append(rel)
    return rels


def _looks_like_data_root(d: Path) -> bool:
    """这个目录自己长得像「数据根」吗?

    判据:里面有顶层数据文件 / settings.json / stores/ 子目录。
    """
    if any((d / name).exists() for name in DATA_FILES.values()):
        return True
    if (d / "settings.json").exists():
        return True
    return (d / "stores").is_dir()


def _resolve_extract_dir(tmp_dir: Path) -> Path:
    """找到解压出来的数据目录。

    ZIP 里可能有 YYYYMMDD_HHMMSS/ 子目录(自动备份格式)或根目录。

    ⚠️ 只有当**唯一的**子目录自己就长得像数据根时才下钻 ——
    否则「stores/」会被误当成数据根(里面明明是 stores/s002/...,
    下钻之后就变成 stores/stores/s002/... → 找不 → 恢复了个寂寞,
    接口还报 ok:true)。
    """
    children = list(tmp_dir.iterdir())
    if len(children) == 1 and children[0].is_dir() and _looks_like_data_root(children[0]):
        return children[0]
    return tmp_dir


def _write_restore_files(handler: Any, target_dir: Path,
                         extract_dir: Path) -> Tuple[List[str], List[str]]:
    """把解压出来的备份内容写回 target_dir。

    返回 (restored 文件名列表, notes 说明列表)。

    R3:**旧格式备份的顶层数据文件必须桥接到 stores/main/**。
    多门店布局下应用读的是 stores/main/readings.json
    (modules.stores.context.resolve_store_path),只写顶层等于
    「接口报成功、总店数据纹丝不动」。崩溃恢复路径
    (storage._try_restore_from_backup)早就这么做了,这里对齐。
    """
    restored: List[str] = []
    notes: List[str] = []

    main_id = "main"
    multi = False
    try:
        from modules.stores.context import DEFAULT_STORE_ID, multi_store_layout
        main_id = DEFAULT_STORE_ID
        multi = multi_store_layout()
    except Exception as e:
        log(f"[WARN] 判不出门店布局,按单店恢复: {e}")

    # 1. 顶层数据文件(旧格式备份)
    #    桥接目标(总店)也要过门店范围闸 —— 桥接本质上是一次「写别的门店」。
    bridge_ok, bridge_err = (True, "")
    if multi:
        from modules.stores.handler import store_scope_check
        bridge_ok, bridge_err = store_scope_check(handler, [main_id])

    bridged: List[str] = []
    for name in DATA_FILES.values():
        src = extract_dir / name
        if not src.exists():
            continue
        shutil.copy2(src, target_dir / name)
        restored.append(name)
        log(f"  恢复 {name} <- {src}")
        if not multi:
            continue
        if not bridge_ok:
            note = f"旧格式备份的顶层 {name} 未桥接到 stores/{main_id}/({bridge_err})"
            notes.append(note)
            log(f"  [WARN] {note}")
            continue
        main_dir = target_dir / "stores" / main_id
        main_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, main_dir / name)
        restored.append(f"stores/{main_id}/{name}")
        bridged.append(name)
        log(f"  [RESTORE] 旧格式备份的顶层 {name} 已桥接到 stores/{main_id}/{name}")
    if bridged:
        notes.append(
            f"旧格式备份(顶层文件)已恢复到总店 stores/{main_id}/: {', '.join(bridged)}"
        )

    # 2. 恢复 stores/ 子树(路径保持)
    for rel, src_path in _iter_store_files(extract_dir):
        dest = _safe_rel_target(target_dir, rel)
        if dest is None:
            log(f"  [WARN] 跳过非法备份路径: {rel}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest)
        restored.append(rel)
        log(f"  恢复 {rel} <- {src_path}")

    # 3. 恢复 settings.json:合并业务字段,保留部署环境字段(backup_dir 等)
    settings_src = extract_dir / "settings.json"
    if settings_src.exists():
        try:
            src_settings = json.loads(settings_src.read_text(encoding="utf-8"))
            _merge_settings_after_restore(target_dir, src_settings)
            restored.append("settings.json")
        except Exception as e:
            log(f"  [WARN] 解析/合并 settings.json 失败: {e}")

    return restored, notes


def _merge_settings_after_restore(target_dir: Path, src_settings: dict) -> None:
    """恢复 settings 时,合并而非整体覆盖:保留目标环境独有的部署字段(如 backup_dir)。

    策略:
    - 目标目录没有 settings.json:直接写入(全新环境)。
    - 否则,以目标目录现有 settings.json 为准,只覆盖其中**业务字段**,
      保留 target 中部署相关字段(backup_dir、backup_retention_count 等)。
    """
    target_settings_path = target_dir / "settings.json"
    incoming = _filter_settings_for_backup(src_settings)
    if not target_settings_path.exists():
        target_settings_path.write_text(
            json.dumps(incoming, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log("  [RESTORE] 目标无 settings.json,直接写入(已剥离部署字段)")
        return
    try:
        existing = json.loads(target_settings_path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  [WARN] 读取目标 settings.json 失败 {e},直接覆盖")
        target_settings_path.write_text(
            json.dumps(incoming, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    # 合并:用 incoming 的字段覆盖 existing 中的同名业务字段,
    # 但保留 existing 中 _BACKUP_EXCLUDED_SETTINGS_KEYS 内的部署字段。
    for k, v in incoming.items():
        existing[k] = v
    target_settings_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log("  [RESTORE] 合并 settings.json:覆盖业务字段,保留部署字段(backup_dir/backup_retention_count)")



def handle_get_data_files(handler):
    """GET /api/admin/data-files — 浏览器备份: 获取所有数据文件的当前内容。

    返回 { ok: true, files: { "readings.json": "<JSON字符串>", ... } }
    多门店布局下额外包含 "stores/<id>/<name>.json" 形式的条目。

    ⚠️ **只返回调用方门店范围内的文件**(R1):
    这个接口原来把全部门店的数据都吐出来 —— 一个只管 s002 的主管
    也能拿到总店和别家分店的数据。门店范围闸在这里是「读」这一侧的闸。
    """
    from modules.stores.context import base_data_dir
    from modules.stores.handler import caller_store_scope
    try:
        target_dir = base_data_dir()
    except RuntimeError as e:
        send_json(handler, 200, {"ok": False, "error": f"数据目录未知: {e}"})
        return

    ok, allowed, err = caller_store_scope(handler)
    if not ok:
        send_json(handler, 403, {"ok": False, "error": err})
        return

    files = {}
    data_file_names = set(DATA_FILES.values()) | {"settings.json"}
    # allowed=None → 不按门店过滤(单店布局 / 总部账号)
    # settings.json 是全局配置(用户表/门店注册表/单价),不是门店数据 → 始终返回
    top_level_allowed = allowed is None or "main" in allowed

    try:
        top_entries = sorted(target_dir.iterdir())
    except OSError as e:
        log(f"[WARN] 读取数据目录失败: {e}")
        top_entries = []
    for f in top_entries:
        if f.is_file() and f.suffix == '.json' and f.name in data_file_names:
            if f.name != "settings.json" and not top_level_allowed:
                # 顶层数据文件在多门店布局下是**总店的历史位置** → 越权
                continue
            try:
                files[f.name] = f.read_text(encoding="utf-8")
            except OSError as e:
                log(f"[WARN] 读取 {f.name} 失败: {e}")

    for rel, path in _iter_store_files(target_dir):
        if allowed is not None:
            from modules.stores.handler import backup_rel_store_id
            if backup_rel_store_id(rel) not in allowed:
                continue
        try:
            files[rel] = path.read_text(encoding="utf-8")
        except OSError as e:
            log(f"[WARN] 读取 {rel} 失败: {e}")

    send_json(handler, 200, {"ok": True, "files": files})


def _get_backup_retention_count():
    """从 settings.json 读取备份保留数量，默认 5。"""
    try:
        from modules.system.settings_handler import get_settings
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
        from modules.system.settings_handler import get_settings
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

    ⚠️ **只打包调用方门店范围内的数据**(R1):
    Task 7 之后备份包含全部门店 —— 一个只管 s002 的主管点「备份」,
    拿到的 ZIP 里装着总店和别家分店的数据。总部账号(all_stores)不受限。

    返回 { ok: true, zip_path: "/data/backup/20250101_120000/meter-backup-20250101_120000.zip", backup_name: "20250101_120000" }
    """
    import datetime

    from modules.stores.context import base_data_dir
    from modules.stores.handler import backup_rel_store_id, caller_store_scope
    try:
        source_dir = base_data_dir()
    except RuntimeError as e:
        send_json(handler, 200, {"ok": False, "error": f"数据目录未知: {e}"})
        return

    # 门店范围:allowed=None → 不按门店过滤(单店布局 / 总部账号)
    ok, allowed, err = caller_store_scope(handler)
    if not ok:
        send_json(handler, 403, {"ok": False, "error": err})
        return
    # 顶层数据文件在多门店布局下是**总店的历史位置** → 越权时也不收
    top_level_allowed = allowed is None or "main" in allowed

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
            if not top_level_allowed:
                log(f"[BACKUP] 跳过 {name}: 不在门店范围内")
                continue
            src = source_dir / name
            if src.exists():
                shutil.copy2(src, backup_dir / name)
        if settings_src.exists():
            # settings.json 仅备份业务字段,不包含部署环境字段(backup_dir 等),
            # 这样手动备份 zip 可以安全恢复到任何机器/docker 容器,不破坏目标环境配置。
            try:
                settings_data = json.loads(settings_src.read_text(encoding="utf-8"))
                safe_settings = _filter_settings_for_backup(settings_data)
                (backup_dir / "settings.json").write_text(
                    json.dumps(safe_settings, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                log(f"[BACKUP] 手动备份 settings.json 已剥离部署字段: "
                    f"{_BACKUP_EXCLUDED_SETTINGS_KEYS & set(settings_data.keys())}")
            except Exception as e:
                log(f"[WARN] 读取 settings 失败,跳过剥离: {e}")

        # 1.5 多门店布局:复制 stores/ 子树(保持相对路径)
        # ⚠️ 只有 *.json 会进来(_iter_store_files 只认 JSON)——
        #    值班照片仍然不进备份,维持改造前现状。
        for rel, src in _iter_store_files(source_dir):
            if allowed is not None and backup_rel_store_id(rel) not in allowed:
                log(f"[BACKUP] 跳过 {rel}: 不在门店范围内")
                continue
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dest)
            except OSError as e:
                log(f"[WARN] 复制 {rel} 失败: {e}")

        # 2. 打包为 ZIP（递归打包,含 stores/ 子树；不包含 zip 自身 0 字节空文件）
        zip_path = backup_dir / zip_filename
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # ⚠️ 必须用 rglob:iterdir() 只拿到顶层条目,stores/ 是目录会被跳过。
            # 条目名用相对路径 —— 否则 stores/main/readings.json 会被压成
            # readings.json,恢复时找不到位置。
            for f in sorted(backup_dir.rglob("*")):
                if f.is_file() and f != zip_path:
                    zf.write(f, str(f.relative_to(backup_dir)))

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
    import zipfile

    body = read_body(handler)
    zip_path = (body or {}).get("zip_path") or ""
    zip_file = Path(zip_path)

    if not zip_file.is_file():
        send_json(handler, 200, {"ok": False, "error": f"ZIP 文件不存在: {zip_path}"})
        return

    # 恢复前自动备份当前数据(可回滚)
    from modules.stores.context import base_data_dir
    try:
        target_dir = base_data_dir()
    except RuntimeError as e:
        send_json(handler, 200, {"ok": False, "error": f"数据目录未知: {e}"})
        return

    pre_backup = backup_data(target_dir, force=True)

    try:
        # 解压到临时目录
        with tempfile.TemporaryDirectory() as tmp_dir:
            safe_dir, error = _validate_zip_safely(zip_file, tmp_dir)
            if error:
                send_json(handler, 400, {"ok": False, "error": f"ZIP 文件不安全: {error}"})
                return

            # 找到解压出的数据目录（可能是 YYYYMMDD_HHMMSS/ 子目录或根目录）
            extract_dir = _resolve_extract_dir(Path(tmp_dir))

            # R1:门店范围闸 —— ZIP 里的目标门店必须在调用方范围内。
            # 任何一个越界 → 整个请求拒绝,一个文件都不写。
            ok, err = _scope_check_rels(handler, _restore_targets(extract_dir))
            if not ok:
                send_json(handler, 403, {"ok": False, "error": err})
                return

            # 恢复数据文件 —— 顶层 + stores/ 子树
            # (R3:多门店布局下,旧格式备份的顶层文件会桥接到 stores/main/)
            restored, notes = _write_restore_files(handler, target_dir, extract_dir)

        payload = {
            "ok": True,
            "restored": restored,
            "pre_backup": str(pre_backup) if pre_backup else "无",
            "source_zip": str(zip_file),
        }
        if notes:
            # R3:让用户看得见「旧格式备份已落到 stores/main/」,别以为没生效
            payload["notes"] = notes
            payload["message"] = "；".join(notes)
        send_json(handler, 200, payload)
    except zipfile.BadZipFile:
        send_json(handler, 200, {"ok": False, "error": "ZIP 文件格式错误"})
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"恢复失败: {e}"})
    finally:
        # 清除 JSON 缓存，确保恢复后的数据立即可读（mtime 缓存未更新）
        _cache_clear()


def handle_post_upload(handler):
    """POST /api/upload — 浏览器直接上传 JSON 或 ZIP 文件恢复数据

    接受 multipart/form-data 或 JSON body:
      - multipart: 上传 readings.json, charges.json, items.json, purchases.json, settings.json,
                   或单个 ZIP 备份包(auto-bak-*.zip / meter-backup-*.zip)
      - JSON body: { "files": { "readings.json": [...], "charges.json": [...] } }
                   或 { "files": { "auto-bak-20260830.zip": { "__zip_b64": "UEsD..." } } }

    上传后:
      - JSON 文件:直接覆盖到 /data/<name>.json
      - ZIP 文件:解压后覆盖到 /data/(原 handle_post_restore 的逻辑)

    ⚠️ 安全措施: 恢复前自动备份当前数据,可随时回滚。
    """
    import base64
    import tempfile

    from modules.stores.context import base_data_dir
    from modules.stores.handler import rel_store_scope_check
    try:
        target_dir = base_data_dir()
    except RuntimeError as e:
        send_json(handler, 200, {"ok": False, "error": f"数据目录未知: {e}"})
        return

    content_type = handler.headers.get("Content-Type", "")
    uploaded = []
    restored = []
    notes: List[str] = []

    # 恢复前自动备份当前数据(可回滚)
    pre_backup = backup_data(target_dir, force=True)

    def _extract_zip_to_target(zip_bytes: bytes, tmp_dir: str) -> list:
        """解压 zip 到 target_dir,返回解压出的数据文件名列表。

        tmp_dir 由调用方传入(整个 handler 共享一个临时目录,避免 JSON 分支
        之前出现的 NameError:局部变量未定义)。

        ⚠️ R1:解压出来的**目标门店**必须都在调用方范围内,否则抛
        _StoreScopeDeniedError —— 整个请求拒绝,一个文件都不写。
        """
        names = []
        zip_path = Path(tmp_dir) / "upload.zip"
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(tmp_dir)
        # zip 里可能有 YYYYMMDD_HHMMSS/ 子目录(自动备份格式)或根目录
        extract_dir = _resolve_extract_dir(Path(tmp_dir))
        ok, err = _scope_check_rels(handler, _restore_targets(extract_dir))
        if not ok:
            raise _StoreScopeDeniedError(err)
        # 顶层 + stores/ 子树 + settings.json(R3:顶层文件会桥接到 stores/main/)
        written, zip_notes = _write_restore_files(handler, target_dir, extract_dir)
        names.extend(written)
        notes.extend(zip_notes)
        return names

    # 把 tmp_dir 提到 handler 顶层,两个分支( multipart / JSON body)共享同一个临时目录
    with tempfile.TemporaryDirectory() as tmp_dir:
        if "multipart/form-data" in content_type:
            # multipart/form-data 上传
            boundary = content_type.split("boundary=", 1)[1]
            if not boundary:
                send_json(handler, 200, {"ok": False, "error": "无法解析 multipart boundary"})
                return

            data = handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
            # 解析每个 part
            parts = data.split(boundary.encode())
            for raw in parts:
                raw_str = raw.decode("utf-8", errors="replace")
                fname_match = re.search(r'filename="([^"]+)"', raw_str)
                if not fname_match:
                    continue
                fname = fname_match.group(1)
                content_parts = raw.split(b"\r\n\r\n", 1)
                if len(content_parts) != 2:
                    continue
                file_content = content_parts[1].rstrip(b"\r\n")
                if fname == "--":
                    continue
                uploaded.append(fname)
                if fname.lower().endswith('.zip'):
                    try:
                        restored.extend(_extract_zip_to_target(file_content, tmp_dir))
                    except _StoreScopeDeniedError as e:
                        # 门店越权 → 整个请求拒绝(不是「跳过这个文件」)
                        send_json(handler, 403, {"ok": False, "error": e.message})
                        return
                    except zipfile.BadZipFile:
                        log(f"[WARN] 上传的 {fname} 不是有效的 ZIP")
                    except Exception as e:
                        log(f"[WARN] 解压 {fname} 失败: {e}")
                elif fname in DATA_FILES.values() or fname == "settings.json" \
                        or _safe_rel_target(target_dir, fname) is not None:
                    # 门店子路径(stores/<id>/<name>.json)也要能上传 ——
                    # 目标路径一律由 _safe_rel_target 解析,挡掉路径穿越。
                    dest = _safe_rel_target(target_dir, fname)
                    if dest is None:
                        continue
                    # R1:目标门店必须在调用方范围内(载荷里的门店,不是 ?store= 参数)
                    ok, err = rel_store_scope_check(handler, fname)
                    if not ok:
                        send_json(handler, 403, {"ok": False, "error": err})
                        return
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(file_content)
                    log(f"  上传 {fname} → {dest}")

        else:
            # JSON body: { "files": { "<filename>": <json|base64 zip wrapper> } }
            body = read_body(handler)
            files = (body or {}).get("files")
            if not files:
                send_json(handler, 200, {"ok": False, "error": "请提供 files 字段"})
                return

            for i, (fname, content) in enumerate(files.items()):
                uploaded.append(fname)
                # ZIP 文件(以 base64 wrapper 形式传入)
                if isinstance(content, dict) and "__zip_b64" in content:
                    try:
                        zip_bytes = base64.b64decode(content["__zip_b64"])
                        zip_tmp = Path(tmp_dir) / f"upload_{i}.zip"
                        zip_tmp.write_bytes(zip_bytes)
                        safe_dir, error = _validate_zip_safely(zip_tmp, tmp_dir)
                        if error:
                            log(f"[WARN] 上传的 ZIP 不安全: {error}")
                            continue
                        restored.extend(_extract_zip_to_target(zip_bytes, tmp_dir))
                    except _StoreScopeDeniedError as e:
                        # 门店越权 → 整个请求拒绝(不是「跳过这个文件」)
                        send_json(handler, 403, {"ok": False, "error": e.message})
                        return
                    except Exception as e:
                        log(f"[WARN] 解码/解压 {fname} 失败: {e}")
                        continue
                elif fname in DATA_FILES.values() or fname == "settings.json" \
                        or _safe_rel_target(target_dir, fname) is not None:
                    # 门店子路径(stores/<id>/<name>.json)也要能上传 ——
                    # 目标路径一律由 _safe_rel_target 解析,挡掉路径穿越。
                    dest = _safe_rel_target(target_dir, fname)
                    if dest is None:
                        continue
                    # R1:目标门店必须在调用方范围内(载荷里的门店,不是 ?store= 参数)
                    ok, err = rel_store_scope_check(handler, fname)
                    if not ok:
                        send_json(handler, 403, {"ok": False, "error": err})
                        return
                    # settings.json 走合并分支:保留目标环境的部署字段(backup_dir 等)
                    if fname == "settings.json":
                        try:
                            if isinstance(content, (list, dict)):
                                src_settings = content
                            elif isinstance(content, str):
                                src_settings = json.loads(content)
                            else:
                                raise ValueError(f"settings.json 内容类型不支持: {type(content)}")
                            _merge_settings_after_restore(target_dir, src_settings)
                            log(f"  合并 settings.json → {dest}")
                        except Exception as e:
                            log(f"  [WARN] 合并 settings.json 失败,降级为直接覆盖: {e}")
                            if isinstance(content, (list, dict)):
                                dest.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
                            elif isinstance(content, str):
                                dest.write_text(content, encoding="utf-8")
                        restored.append("settings.json")
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(content, (list, dict)):
                        dest.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
                    elif isinstance(content, str):
                        dest.write_text(content, encoding="utf-8")
                    log(f"  上传 {fname} → {dest}")

    payload = {
        "ok": True,
        "uploaded": uploaded,
        "restored": restored,
        "pre_backup": str(pre_backup) if pre_backup else None,
    }
    if notes:
        payload["notes"] = notes
        payload["message"] = "；".join(notes)
    send_json(handler, 200, payload)
    # 清除 JSON 缓存，确保上传/恢复后的数据立即可读
    _cache_clear()
