"""后台辅助工具 API — 目录浏览、审计日志、水电数据迁移。
从原 handlers.admin.py 拆分而来。
"""
from __future__ import annotations
import datetime
import json
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from utils import send_json
from storage import log, load_json
from modules._base import get_data_paths as _get_data_paths
from constants import ROLE_ADMIN, ROLE_SUPERVISOR


# ============ 目录浏览 ============

# ============ 审计日志 ============

def handle_get_audit_log(handler):
    """GET /api/admin/audit?count=100 → {logs: [...]}

    **按调用方的门店范围过滤**:本店主管只应看到本店的操作记录。
    历史记录没有 store 字段(改造前写的),按 fail-closed 处理 ——
    只有总部账号(不按门店过滤)能看到它们。
    """
    qs = parse_qs(urlparse(handler.path).query)
    try:
        count = int(qs.get("count", ["100"])[0])
    except (TypeError, ValueError):
        count = 100

    from utils.audit import get_audit_log
    logs = get_audit_log(count)

    try:
        from modules.stores.handler import caller_store_scope
        scope_ok, allowed_ids, err = caller_store_scope(handler)
    except Exception as e:
        scope_ok, allowed_ids, err = False, None, str(e)

    if not scope_ok:
        # 判不出范围就拒绝,绝不回退成"全部门店"(否则等于把全站审计泄出去)
        send_json(handler, 403, {"error": "无法确认门店范围: " + (err or "未知原因")})
        return

    if allowed_ids is not None:
        allow = {str(x) for x in allowed_ids}
        logs = [e for e in logs if str(e.get("store") or "") in allow]

    send_json(handler, 200, {"logs": logs})


# ============ 水电数据迁移 ============

def handle_get_migrate_status(handler):
    """GET /api/admin/migrate-water-status — 检测旧格式水电数据"""

    def _load(path, default=None):
        if default is None: default = []
        return load_json(path, default)

    data_paths = _get_data_paths()
    readings = _load(data_paths.get("readings"), [])
    water_file = data_paths.get("readings_water")
    existing_water = _load(water_file) if water_file else []

    # 查找包含水电字段的记录
    water_records = []
    clean_count = 0
    for r in readings:
        if r.get("main_meter") is not None or r.get("sub_meter") is not None or r.get("water") is not None:
            water_records.append(r)
        else:
            clean_count += 1

    # 检查是否有 null 字段残留
    null_water_records = [r for r in readings if any(k in r for k in ("main_meter", "sub_meter", "water")) and r not in water_records]
    needs_migration = bool(water_records or null_water_records)

    if not needs_migration:
        send_json(handler, 200, {
            "needs_migration": False,
            "readings_total": len(readings),
            "existing_water_count": len(existing_water),
            "water_in_readings": 0,
            "message": "数据已经是最新格式,无需迁移。",
        })
        return

    summary_by_date = {}
    for r in water_records:
        date = r["date"]
        fields = []
        if r.get("main_meter") is not None: fields.append("main_meter")
        if r.get("sub_meter") is not None: fields.append("sub_meter")
        if r.get("water") is not None: fields.append("water")
        summary_by_date[date] = {
            "date": date,
            "fields": fields,
        }

    # 检查是否已有同日期的 water 记录
    water_by_date = {w["date"] for w in existing_water}
    conflicts = sum(1 for d in summary_by_date if d in water_by_date)

    send_json(handler, 200, {
        "needs_migration": True,
        "readings_total": len(readings),
        "existing_water_count": len(existing_water),
        "water_in_readings": len(water_records),
        "water_dates": sorted(summary_by_date.keys()),
        "conflicts_with_existing": conflicts,
        "records_preview": list(summary_by_date.values()),
        "message": f"检测到 {len(water_records)} 条抄表记录包含水电字段,需要迁移到独立的 readings_water.json。",
    })


def handle_post_migrate_water(handler):
    """POST /api/admin/migrate-water — 执行水电数据分离"""
    readings_path = _get_data_paths().get("readings")
    water_path = _get_data_paths().get("readings_water")

    readings = load_json(readings_path, [])
    existing_water = load_json(water_path, []) if water_path else []

    # 1. 自动备份
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = readings_path.parent / f"pre-migrate-{ts}"
        backup_dir.mkdir(exist_ok=True)
        for name in ("readings.json", "readings_water.json"):
            src = readings_path.parent / name
            if src.exists():
                shutil.copy2(src, backup_dir / name)
        log(f"  [MIGRATE] 备份到 {backup_dir}")
    except Exception as e:
        log(f"  [MIGRATE] 备份失败: {e}")
        send_json(handler, 200, {"ok": False, "error": f"备份失败: {e}", "step": "backup"})
        return

    # 2. 分离数据
    water_records = []
    new_readings = []
    for r in readings:
        has_w = r.get("main_meter") is not None or r.get("sub_meter") is not None or r.get("water") is not None
        if has_w:
            water_records.append(r)
        else:
            new_readings.append(r)

    # 清理 null 字段残留
    for r in new_readings:
        for k in ("main_meter", "sub_meter", "water"):
            if k in r:
                del r[k]

    # 构建新 water 数据
    water_by_date = {w["date"]: w for w in existing_water}
    for r in water_records:
        date = r["date"]
        water_by_date[date] = {
            "date": date,
            "main_meter": r.get("main_meter"),
            "sub_meter": r.get("sub_meter"),
            "water": r.get("water"),
            "note": r.get("note", ""),
        }
    new_water = sorted(water_by_date.values(), key=lambda w: w["date"])

    # 3. 验证完整性
    errors = []
    for r in new_readings:
        for k in ("main_meter", "sub_meter", "water"):
            if k in r:
                errors.append(f"{r['date']} 仍包含 {k}")
    migrated_dates = {r["date"] for r in water_records}
    water_dates = {w["date"] for w in new_water}
    if migrated_dates - water_dates:
        errors.append(f"以下日期未迁移: {migrated_dates - water_dates}")

    if errors:
        send_json(handler, 200, {"ok": False, "error": "验证失败: " + "; ".join(errors), "step": "validation"})
        return

    # 4. 写入
    try:
        with open(readings_path, "w", encoding="utf-8") as f:
            json.dump(new_readings, f, ensure_ascii=False, indent=2)
        with open(water_path, "w", encoding="utf-8") as f:
            json.dump(new_water, f, ensure_ascii=False, indent=2)
        log(f"  [MIGRATE] 迁移完成: {len(water_records)} 条水电记录已分离")
    except Exception as e:
        log(f"  [MIGRATE] 写入失败: {e}")
        send_json(handler, 200, {"ok": False, "error": f"写入失败: {e}", "step": "write"})
        return

    send_json(handler, 200, {
        "ok": True,
        "total_readings": len(new_readings),
        "total_water": len(new_water),
        "migrated_count": len(water_records),
        "conflicts_overwritten": sum(1 for r in water_records if r["date"] in {w["date"] for w in existing_water}),
        "message": f"✅ 迁移完成!{len(water_records)} 条水电记录已从抄表记录分离到独立的 readings_water.json。",
    })
