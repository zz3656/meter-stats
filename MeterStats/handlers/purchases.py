"""申购相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from utils import send_json, read_body

_now = datetime.now
from storage import log, load_json, save_json
from handlers._base import get_data_paths, get_lock
from report import invalidate_report_cache as _invalidate_report_cache


def _load_purchases() -> list:
    return load_json(get_data_paths()["purchases"], [])


def _save_purchases(data):
    lock = get_lock("purchases")
    with lock:
        save_json(get_data_paths()["purchases"], data)


# ==================== GET ====================

def handle_get_purchases(handler):
    """GET /api/purchases"""
    send_json(handler, 200, _load_purchases())


# ==================== POST ====================

def handle_post_purchases(handler):
    """POST /api/purchases — 添加申购记录"""
    body = read_body(handler)
    name = body.get("name")
    if not name:
        send_json(handler, 400, {"error": "name 不能为空"})
        return
    qty = body.get("qty", 0)
    if qty < 0:
        send_json(handler, 400, {"error": "数量不能为负数"})
        return
    est_price = body.get("est_price", 0)
    if est_price < 0:
        send_json(handler, 400, {"error": "预估金额不能为负数"})
        return
    purchases = _load_purchases()
    now = _now()
    new_purchase = {
        "id": f"purchase-{int(now.timestamp() * 1000)}",
        "date": body.get("date", now.strftime("%Y-%m-%d")),
        "name": name,
        "qty": float(qty),
        "unit": body.get("unit", ""),
        "est_price": float(est_price),
        "supplier": body.get("supplier", ""),
        "note": body.get("note", ""),
        "status": "pending",
    }
    purchases.append(new_purchase)
    _save_purchases(purchases)
    log(f"  OK 新增申购 {name}")
    send_json(handler, 200, {"ok": True, "row": new_purchase})


# ==================== PUT ====================

def handle_put_purchases(handler, path_clean: str):
    """PUT /api/purchases/{id} — 编辑申购记录"""
    iid = path_clean[len("/api/purchases/"):] if path_clean and path_clean != "/api/purchases" else ""
    body = read_body(handler)
    if not iid:
        send_json(handler, 400, {"error": "缺少申购记录 id"})
        return

    purchases = _load_purchases()
    found = False
    for purchase in purchases:
        if purchase.get("id") == iid:
            for key in ("name", "qty", "est_price", "unit", "supplier", "note", "status"):
                if key in body:
                    if key in ("qty", "est_price"):
                        purchase[key] = float(body[key])
                    elif key == "status":
                        purchase[key] = body[key]
                    else:
                        purchase[key] = body[key]
            found = True
            log(f"  OK 编辑申购 {purchase['name']}")
            break

    if not found:
        send_json(handler, 404, {"error": f"未找到 {iid}"})
        return

    _save_purchases(purchases)
    send_json(handler, 200, {"ok": True, "purchases": purchases})


# ==================== 入库 ====================

def handle_put_purchases_stock(handler, path_clean: str):
    """PUT /api/purchases/{id}/stock"""
    from handlers.items import _load_items, _save_items
    pid = path_clean[len("/api/purchases/"):-len("/stock")]
    purchases = _load_purchases()
    idx = next((i for i, p in enumerate(purchases) if p.get("id") == pid), None)
    if idx is None:
        send_json(handler, 404, {"error": f"未找到 {pid}"})
        return
    p = purchases[idx]
    if p["status"] == "stocked":
        send_json(handler, 400, {"error": "已经入库过了"})
        return
    now = _now()
    items = _load_items()
    existing = next((it for it in items if it["name"] == p["name"]), None)
    if existing:
        existing["qty"] = float(existing["qty"]) + float(p["qty"])
        if p.get("unit"):
            existing["unit"] = p["unit"]
        log(f"  OK 累加 {p['name']}: {p['qty']} -> {existing['qty']} {existing.get('unit', '')}")
    else:
        items.append({
            "id": f"item-{int(now.timestamp() * 1000)}",
            "name": p["name"],
            "qty": float(p["qty"]),
            "unit": p.get("unit", ""),
            "note": f"从申购 {pid} 自动入库",
            "created_at": now.isoformat(),
        })
        log(f"  OK 新增 {p['name']}: {p['qty']} {p.get('unit', '')}")
    purchases[idx]["status"] = "stocked"
    _save_items(items)
    _save_purchases(purchases)
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "purchase": purchases[idx]})


# ==================== DELETE ====================

def handle_delete_purchases(handler, path_clean: str):
    """DELETE /api/purchases/{id}"""
    pid = path_clean[len("/api/purchases/"):]
    purchases = _load_purchases()
    new = [p for p in purchases if p.get("id") != pid]
    if len(new) == len(purchases):
        send_json(handler, 404, {"error": f"未找到 {pid}"})
        return
    _save_purchases(new)
    log(f"  -- 删除申购 {pid}")
    send_json(handler, 200, {"ok": True})
