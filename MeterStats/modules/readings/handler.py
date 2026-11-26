"""抄表相关 API handler。"""
from __future__ import annotations

from typing import Any

from utils import read_body, send_json
from storage import log, load_json, save_json
from modules._base import get_data_paths, get_lock
from modules.stores.meters import LEGACY_KEYS
from report import invalidate_report_cache as _invalidate_report_cache

# 抄表记录里除表值以外的字段 —— 用于挡住「写进来但没人在看」的野字段
_NON_METER_FIELDS = frozenset({"date", "note", "rehearsal", "programming", "meters"})


def _load_readings() -> list:
    return load_json(get_data_paths()["readings"], [])


def _store_tables() -> list[dict[str, Any]]:
    """当前门店的表定义(P2:每店自己的表集合)。"""
    from modules.stores.config import get_store_meters
    return get_store_meters()


def _as_float(raw_val: Any) -> float | None:
    """请求体里的原始值 → float 或 None(空串/非法都算 None)。"""
    if raw_val is None or raw_val == "":
        return None
    try:
        return float(raw_val)
    except (TypeError, ValueError):
        return None


def _collect_meter_values(body: dict[str, Any], tables: list[dict[str, Any]],
                          ) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    """把请求体里的表值拆成 (旧 4 表顶层字段, 自定义表 meters 字典, 出现过的 key)。

    D1:旧 4 表继续写顶层字段 → 历史数据零迁移;D2:自定义表写 meters 字典。
    只认当前门店表集合里的 key —— 门店没有的表写进来就是脏数据
    (没人会显示它,但会进备份、进导入导出,事后极难清理)。

    `present` 是**请求体里出现过**的表 key —— 必须与「没传」区分开:
      - 没传 → PUT 不动旧值
      - 传了空(如 `"fire": ""`)→ PUT 明确清成 None
    这两种语义历史上就不一样(见 test_put_empty_field_keeps_null_not_zero),
    合并成「值为 None 就当没传」会把「清空某个表」这个操作整个弄丢。
    """
    legacy: dict[str, Any] = {}
    custom: dict[str, Any] = {}
    present: set[str] = set()

    def _take(key: str, raw_val: Any) -> None:
        val = _as_float(raw_val)
        if key in LEGACY_KEYS:
            legacy[key] = val
        elif val is not None:
            custom[key] = val

    for t in tables:
        key = t["key"]
        if key in body:
            present.add(key)
        _take(key, body.get(key))
    explicit = body.get("meters")
    if isinstance(explicit, dict):
        for key in explicit:
            present.add(key)
            _take(key, explicit.get(key))
    return legacy, custom, present


def _unknown_meter_keys(body: dict[str, Any], tables: list[dict[str, Any]]) -> list[str]:
    """请求体里既不是表、也不是非表字段的 key —— 说明写了一块门店没有的表。"""
    allowed = {t["key"] for t in tables} | _NON_METER_FIELDS
    return sorted(k for k in body if k not in allowed)


def _validate_body_meters(body: dict[str, Any], tables: list[dict[str, Any]]) -> str:
    """校验请求体。返回错误文案,空串表示通过。"""
    unknown = _unknown_meter_keys(body, tables)
    if unknown:
        return "该门店没有这些表: %s" % ", ".join(unknown)
    meters = body.get("meters")
    if isinstance(meters, dict):
        allowed = {t["key"] for t in tables}
        bad = sorted(k for k in meters if k not in allowed)
        if bad:
            return "该门店没有这些表: %s" % ", ".join(bad)
    return ""


# ==================== GET ====================

def handle_get_readings(handler):
    """GET /api/readings"""
    send_json(handler, 200, _load_readings())


# 注：/api/readings/monthly 与 /api/charges/monthly 曾定义过 handle_get_*_monthly，
# 但从未在 routing.py 注册，前端也未调用 — 现已删除，避免死代码。
# 月度查询请使用 /api/monthly-report(已有 handle_get_monthly_report)。
# ==================== POST ====================

def handle_post_readings(handler):
    """POST /api/readings — 电表抄表(按当前门店的表集合)。

    水电表底(总表/分表/水表)已迁移至 /api/readings-water。
    P2:旧 4 表仍写**顶层字段**(历史数据零迁移),门店自定义的新表写 `meters` 字典。
    """
    body = read_body(handler)
    if not body.get("date"):
        send_json(handler, 400, {"error": "日期不能为空"})
        return
    date = body["date"]

    tables = _store_tables()
    err = _validate_body_meters(body, tables)
    if err:
        send_json(handler, 400, {"error": err})
        return

    legacy, custom, _present = _collect_meter_values(body, tables)

    if not custom and all(v is None for v in legacy.values()):
        send_json(handler, 400, {"error": "至少填一块表"})
        return

    note = body.get("note", "")
    rehearsed = bool(body.get("rehearsal", False))
    programming = bool(body.get("programming", False))

    readings = _load_readings()
    idx = next((i for i, r in enumerate(readings) if r.get("date") == date), None)

    if idx is not None:
        # 覆盖:表单没填的字段(null)保留旧值(自定义表同理,不能把别的表清空)
        old = readings[idx]
        new_row = {"date": date}
        for k, v in legacy.items():
            new_row[k] = v if v is not None else old.get(k)
        merged_meters = dict(old.get("meters")) if isinstance(old.get("meters"), dict) else {}
        merged_meters.update(custom)
        if merged_meters:
            new_row["meters"] = merged_meters
        new_row["note"] = note if note is not None else old.get("note")
        new_row["rehearsal"] = rehearsed
        new_row["programming"] = programming
        readings[idx] = new_row
        log(f"  >> 覆盖抄表 {date}")
    else:
        new_row = {"date": date}
        for k, v in legacy.items():
            new_row[k] = v
        if custom:
            new_row["meters"] = dict(custom)
        new_row["note"] = note
        new_row["rehearsal"] = rehearsed
        new_row["programming"] = programming
        readings.append(new_row)
        log(f"  ++ 新增抄表 {date}")

    _save_readings(readings)
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "row": readings[idx] if idx is not None else readings[-1]})


# ==================== PUT ====================

def handle_put_readings(handler, path_clean: str):
    """PUT /api/readings/{date} — 仅处理电表抄表字段。
    水电字段不再支持通过此接口修改。
    """
    date = path_clean[len("/api/readings/"):]
    body = read_body(handler)
    if not date:
        send_json(handler, 400, {"error": "日期不能为空"})
        return

    readings = _load_readings()
    existing = next((r for r in readings if r.get("date") == date), None)
    if not existing:
        send_json(handler, 404, {"error": f"未找到 {date}"})
        return

    tables = _store_tables()
    err = _validate_body_meters(body, tables)
    if err:
        send_json(handler, 400, {"error": err})
        return

    # 表值:旧 4 表写顶层,自定义表写 meters 字典(只改传了的那些)
    legacy, custom, present = _collect_meter_values(body, tables)
    # 只动**请求体里出现过**的 key:没传 → 保留旧值;传了空 → 清成 None
    for k in present:
        if k in LEGACY_KEYS:
            existing[k] = legacy.get(k)
        else:
            meters_now = existing.get("meters")
            if not isinstance(meters_now, dict):
                meters_now = {}
                existing["meters"] = meters_now
            meters_now[k] = custom.get(k)

    for key in ["note", "rehearsal", "programming"]:
        val = body.get(key)
        if val is not None:
            if key in ("rehearsal", "programming"):
                existing[key] = bool(val)
            else:
                existing[key] = val
    _save_readings(readings)
    log(f"  OK 更新抄表 {date}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "row": existing})


# ==================== DELETE ====================

def handle_delete_readings(handler, path_clean: str):
    """DELETE /api/readings/{date}"""
    date = path_clean[len("/api/readings/"):]
    readings = _load_readings()
    new = [r for r in readings if r.get("date") != date]
    if len(new) == len(readings):
        send_json(handler, 404, {"error": f"未找到 {date}"})
        return
    _save_readings(new)
    log(f"  -- 删除抄表 {date}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True})


def _save_readings(data):
    lock = get_lock("readings")
    with lock:
        save_json(get_data_paths()["readings"], data)

