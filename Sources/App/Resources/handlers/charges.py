"""充值相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

from utils import send_json, opt_float, read_body
from storage import log, load_json, save_json, get_lock

def _get_data_paths():
    import app_handler as _h
    return _h.DATA_PATHS

def _get(model: str):
    return load_json(_get_data_paths().get(model), [])

def _save(model: str, data):
    lock = get_lock(model)
    with lock:
        save_json(_get_data_paths().get(model), data)


def handle_get_charges(handler):
    """GET /api/charges"""
    send_json(handler, 200, _get("charges"))


def handle_get_charges_monthly(handler):
    """GET /api/charges/monthly?month=2026-07"""
    qs = parse_qs(urlparse(handler.path).query)
    month = qs.get("month", [datetime.now().strftime("%Y-%m")])[0]
    charges = _get("charges")
    filtered = [c for c in charges if c.get("date", "").startswith(month)]
    filtered.sort(key=lambda c: c["date"])
    send_json(handler, 200, filtered)


def handle_post_charges(handler):
    """POST /api/charges"""
    body = read_body(handler)
    if not body.get("date"):
        send_json(handler, 400, {"error": "日期不能为空"})
        return
    charges = _get("charges")
    new_charge = {
        "id": f"{body['date']}-{int(datetime.now().timestamp() * 1000)}",
        "date": body["date"],
        "hall": opt_float(body, "hall"),
        "fire": opt_float(body, "fire"),
        "private_room": opt_float(body, "private_room"),
        "ac": opt_float(body, "ac"),
        "note": body.get("note", ""),
    }
    if all(v is None or v == 0 for v in [new_charge["hall"], new_charge["fire"],
                                          new_charge["private_room"], new_charge["ac"]]):
        send_json(handler, 400, {"error": "四表至少填一个非 0 值"})
        return
    charges.append(new_charge)
    _save("charges", charges)
    log(f"  OK 充值 {body['date']}")
    send_json(handler, 200, {"ok": True, "row": new_charge})


def handle_put_charges(handler, path_clean: str):
    """PUT /api/charges/{id}"""
    cid = path_clean[len("/api/charges/"):]
    body = read_body(handler)
    charges = _get("charges")
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
    _save("charges", charges)
    log(f"  OK 充值更新 {cid}")
    send_json(handler, 200, {"ok": True, "row": charge})


def handle_delete_charges(handler, path_clean: str):
    """DELETE /api/charges/{id}"""
    cid = path_clean[len("/api/charges/"):]
    charges = _get("charges")
    new = [c for c in charges if c.get("id") != cid]
    if len(new) == len(charges):
        send_json(handler, 404, {"error": f"未找到 {cid}"})
        return
    _save("charges", new)
    log(f"  -- 删除充值 {cid}")
    send_json(handler, 200, {"ok": True})
