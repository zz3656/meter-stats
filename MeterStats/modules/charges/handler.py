"""充值相关 API handler。"""
from __future__ import annotations

from datetime import datetime

from utils import send_json, opt_float, read_body

_now = datetime.now
from storage import log, load_json, save_json
from modules._base import get_data_paths, get_lock
from report import invalidate_report_cache as _invalidate_report_cache
from report import find_charge_conflicts, find_pasted_reading_charges


def _load_charges() -> list:
    return load_json(get_data_paths()["charges"], [])


def _load_readings() -> list:
    return load_json(get_data_paths()["readings"], [])


def _conflict_for(readings: list, charges: list, charge_id: str):
    """找出这条充值记录与抄表对不上的地方(没有则 None)。

    物理事实:预付费表表底下降 = 用电,表底上升 = 刚到账。一笔充值真的到账了,它被
    归属的那个区间里表底必然"净升";否则该区间需要的用电量会离谱 —— 2026-11-11
    有人把当天抄表读数填进充值栏,大厅凭空多出 32912 度,一天总用电被顶到 89588.8 度。
    详见 report.find_charge_conflicts()。
    """
    for c in find_charge_conflicts(readings, charges):
        if c.get("charge_id") == charge_id:
            return c
    return None


def _pasted_reading_for(readings: list, charges: list, charge_id: str):
    """找出「充值额 = 当天抄表读数」的记录(把抄表读数填进充值栏)。"""
    for c in find_pasted_reading_charges(readings, charges):
        if c.get("charge_id") == charge_id:
            return c
    return None


def _validate_charge(readings: list, charges: list, charge_id: str):
    """录入充值前的校验,返回一条错误说明或 None。

    先看最明确的信号(充值额和当天抄表读数一模一样),再看物理上对不上的那种。
    """
    return (_pasted_reading_for(readings, charges, charge_id)
            or _conflict_for(readings, charges, charge_id))


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
    charges = _load_charges()
    new_charge = {
        "id": f"{body['date']}-{int(_now().timestamp() * 1000)}",
        "date": body["date"],
        "hall": opt_float(body, "hall"),
        "fire": opt_float(body, "fire"),
        "private_room": opt_float(body, "private_room"),
        "ac": opt_float(body, "ac"),
        "note": body.get("note", ""),
        # 充值申请流程: pending=待确认(不计入统计), confirmed=已确认(默认)
        "status": "pending" if body.get("status") == "pending" else "confirmed",
        "created_at": _now().isoformat(),
    }
    if all(v is None or v == 0 for v in [new_charge["hall"], new_charge["fire"],
                                          new_charge["private_room"], new_charge["ac"]]):
        send_json(handler, 400, {"error": "四表至少填一个非 0 值"})
        return
    # 录入时就拦住"把抄表读数填进充值栏"的记录 —— 放进去会让所有用电统计被顶飞
    conflict = _validate_charge(_load_readings(), [new_charge], new_charge["id"])
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
    for key in ["hall", "fire", "private_room", "ac"]:
        val = body.get(key)
        if val is not None:
            charge[key] = opt_float(body, key)
    if body.get("note") is not None:
        charge["note"] = str(body.get("note", "") or "")
    for key in ["hall", "fire", "private_room", "ac"]:
        if charge[key] is not None and charge[key] < 0:
            send_json(handler, 400, {"error": str(key) + " 不能为负数"})
            return
    if all(v is None or v == 0 for v in [charge["hall"], charge["fire"],
                                          charge["private_room"], charge["ac"]]):
        send_json(handler, 400, {"error": "四表至少保留一个非 0 值"})
        return
    charges[idx] = charge
    # 改完也要复核一次:改成"抄表读数"同样会把统计顶飞
    conflict = _validate_charge(_load_readings(), charges, cid)
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
    conflict = _validate_charge(_load_readings(), charges, cid)
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

from modules._storage import ModuleStorage
_storage = ModuleStorage('charges')
