"""充值相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from modules._base import get_data_paths, get_lock
from modules.stores.meters import LEGACY_KEYS
from report import find_charge_conflicts, find_pasted_reading_charges
from report import invalidate_report_cache as _invalidate_report_cache
from storage import load_json, log, save_json
from utils import read_body, send_json

_now = datetime.now


def _load_charges() -> list:
    return load_json(get_data_paths()["charges"], [])


def _load_readings() -> list:
    return load_json(get_data_paths()["readings"], [])


_NON_METER_FIELDS = frozenset({"date", "note", "status", "meters", "confirmed_at", "id",
                                "created_at"})


def _store_tables() -> list[dict[str, Any]]:
    """当前门店的表定义(P2:每店自己的表集合)。

    取 `report.py` 形状(`mult`)—— 因为这里的表定义会直接喂给
    `find_charge_conflicts` / `find_pasted_reading_charges`。
    """
    from modules.stores.config import get_report_tables
    return get_report_tables()


def _collect_charge_values(body: dict[str, Any], tables: list[dict[str, Any]],
                           ) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    """拆成 (旧 4 表顶层字段, 自定义表 meters 字典, 出现过的 key)。

    `present` 与 readings 那边同一个道理:PUT 里「传了空」= 清空,
    「没传」= 保留旧值。不区分这两者,「清掉某个表的充值」这个操作会静默失效。
    """
    allowed = {t["key"] for t in tables}
    legacy: dict[str, Any] = {}
    custom: dict[str, Any] = {}
    present: set[str] = set()

    def _take(key: str, raw_val: Any) -> None:
        val = None
        if raw_val is not None and raw_val != "":
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                val = None
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
        bad = sorted(k for k in explicit if k not in allowed)
        if bad:
            raise ValueError("该门店没有这些表: %s" % ", ".join(bad))
        for key in explicit:
            present.add(key)
            _take(key, explicit.get(key))

    unknown = sorted(k for k in body
                     if k not in allowed and k not in _NON_METER_FIELDS)
    if unknown:
        raise ValueError("该门店没有这些表: %s" % ", ".join(unknown))
    return legacy, custom, present


def _conflict_for(readings: list, charges: list, charge_id: str, tables: list[dict[str, Any]] | None = None):
    """找出这条充值记录与抄表对不上的地方(没有则 None)。

    物理事实:预付费表表底下降 = 用电,表底上升 = 刚到账。一笔充值真的到账了,它被
    归属的那个区间里表底必然"净升";否则该区间需要的用电量会离谱 —— 2026-11-11
    有人把当天抄表读数填进充值栏,大厅凭空多出 32912 度,一天总用电被顶到 89588.8 度。
    详见 report.find_charge_conflicts()。
    """
    for c in find_charge_conflicts(readings, charges, tables=tables):
        if c.get("charge_id") == charge_id:
            return c
    return None


def _pasted_reading_for(readings: list, charges: list, charge_id: str,
                        tables: list[dict[str, Any]] | None = None):
    """找出「充值额 = 当天抄表读数」的记录(把抄表读数填进充值栏)。"""
    for c in find_pasted_reading_charges(readings, charges, tables=tables):
        if c.get("charge_id") == charge_id:
            return c
    return None


def _validate_charge(readings: list, charges: list, charge_id: str,
                    tables: list[dict[str, Any]] | None = None):
    """录入充值前的校验,返回一条错误说明或 None。

    先看最明确的信号(充值额和当天抄表读数一模一样),再看物理上对不上的那种。
    """
    return (_pasted_reading_for(readings, charges, charge_id, tables)
            or _conflict_for(readings, charges, charge_id, tables))


# ==================== GET ====================

def handle_get_charges(handler):
    """GET /api/charges"""
    send_json(handler, 200, _load_charges())


# 注：handle_get_charges_monthly 已删除 — 详见 modules/readings/handler.py 同名注释。
# ==================== POST ====================

def handle_post_charges(handler):
    """POST /api/charges"""
    body = read_body(handler)
    if not body.get("date"):
        send_json(handler, 400, {"error": "日期不能为空"})
        return
    tables = _store_tables()
    try:
        legacy, custom, _present = _collect_charge_values(body, tables)
    except ValueError as e:
        send_json(handler, 400, {"error": str(e)})
        return

    charges = _load_charges()
    new_charge = {
        "id": f"{body['date']}-{int(_now().timestamp() * 1000)}",
        "date": body["date"],
    }
    new_charge.update(legacy)
    if custom:
        new_charge["meters"] = custom
    new_charge["note"] = body.get("note", "")
    # 充值申请流程: pending=待确认(不计入统计), confirmed=已确认(默认)
    new_charge["status"] = "pending" if body.get("status") == "pending" else "confirmed"
    new_charge["created_at"] = _now().isoformat()

    if not custom and all(v is None or v == 0 for v in legacy.values()):
        send_json(handler, 400, {"error": "至少填一块表的非 0 值"})
        return
    # 录入时就拦住"把抄表读数填进充值栏"的记录 —— 放进去会让所有用电统计被顶飞
    conflict = _validate_charge(_load_readings(), [new_charge], new_charge["id"], tables)
    if conflict:
        send_json(handler, 400, {"error": conflict["reason"], "conflict": conflict})
        return
    charges.append(new_charge)
    _save_charges(charges)
    log(f"  OK 充值 {body['date']} status={new_charge.get('status', 'confirmed')}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "row": new_charge})


# ==================== PUT ====================

def handle_put_charges(handler, path_clean: str):
    """PUT /api/charges/{id} 或 PUT /api/charges/{id}/confirm"""
    cid = path_clean[len("/api/charges/"):]
    if cid.endswith("/confirm"):
        _confirm_charge(handler, cid[: -len("/confirm")])
        return
    body = read_body(handler)
    charges = _load_charges()
    idx = next((i for i, c in enumerate(charges) if c.get("id") == cid), None)
    if idx is None:
        send_json(handler, 404, {"error": f"未找到 {cid}"})
        return
    charge = charges[idx]
    tables = _store_tables()
    try:
        legacy, custom, present = _collect_charge_values(body, tables)
    except ValueError as e:
        send_json(handler, 400, {"error": str(e)})
        return
    # 只动请求体里出现过的 key:没传 → 保留旧值;传了空 → 清成 None
    for k in present:
        if k in LEGACY_KEYS:
            charge[k] = legacy.get(k)
        else:
            meters_now = charge.get("meters")
            if not isinstance(meters_now, dict):
                meters_now = {}
                charge["meters"] = meters_now
            meters_now[k] = custom.get(k)
    if body.get("note") is not None:
        charge["note"] = str(body.get("note", "") or "")

    def _negative(row: dict[str, Any], key: str) -> bool:
        from modules.stores.meters import row_values
        val = row_values(row, key)
        return val is not None and val < 0

    def _zero(row: dict[str, Any], key: str) -> bool:
        from modules.stores.meters import row_values
        val = row_values(row, key)
        return val is None or val == 0

    for t in tables:
        if _negative(charge, t["key"]):
            send_json(handler, 400, {"error": t["key"] + " 不能为负数"})
            return
    if all(_zero(charge, t["key"]) for t in tables):
        send_json(handler, 400, {"error": "至少保留一块表的非 0 值"})
        return
    charges[idx] = charge
    # 改完也要复核一次:改成"抄表读数"同样会把统计顶飞
    conflict = _validate_charge(_load_readings(), charges, cid, tables)
    if conflict:
        send_json(handler, 400, {"error": conflict["reason"], "conflict": conflict})
        return
    _save_charges(charges)
    log(f"  OK 充值更新 {cid}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "row": charge})


def _confirm_charge(handler, cid: str):
    """确认充值到账: pending → confirmed,此后计入所有统计。"""
    charges = _load_charges()
    idx = next((i for i, c in enumerate(charges) if c.get("id") == cid), None)
    if idx is None:
        send_json(handler, 404, {"error": f"未找到 {cid}"})
        return
    charges[idx]["status"] = "confirmed"
    charges[idx]["confirmed_at"] = _now().isoformat()
    # 确认到账 = 开始计入统计,先复核这笔钱是否真能对上抄表
    conflict = _validate_charge(_load_readings(), charges, cid, _store_tables())
    if conflict:
        send_json(handler, 400, {"error": conflict["reason"], "conflict": conflict})
        return
    _save_charges(charges)
    log(f"  OK 充值确认 {cid}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "row": charges[idx]})


# ==================== DELETE ====================

def handle_delete_charges(handler, path_clean: str):
    """DELETE /api/charges/{id}"""
    cid = path_clean[len("/api/charges/"):]
    charges = _load_charges()
    new = [c for c in charges if c.get("id") != cid]
    if len(new) == len(charges):
        send_json(handler, 404, {"error": f"未找到 {cid}"})
        return
    _save_charges(new)
    log(f"  -- 删除充值 {cid}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True})


def _save_charges(data):
    lock = get_lock("charges")
    with lock:
        save_json(get_data_paths()["charges"], data)

