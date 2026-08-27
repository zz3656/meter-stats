"""申购相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
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


def handle_get_purchases(handler):
    """GET /api/purchases"""
    send_json(handler, 200, _get("purchases"))


def handle_post_purchases(handler, path_clean: str = ""):
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
    purchases = _get("purchases")
    new_purchase = {
        "id": f"purchase-{int(datetime.now().timestamp() * 1000)}",
        "date": body.get("date", datetime.now().strftime("%Y-%m-%d")),
        "name": name,
        "qty": float(qty),
        "unit": body.get("unit", ""),
        "est_price": float(est_price),
        "supplier": body.get("supplier", ""),
        "note": body.get("note", ""),
        "status": "pending",
    }
    purchases.append(new_purchase)
    _save("purchases", purchases)
    log(f"  OK 新增申购 {name}")
    send_json(handler, 200, {"ok": True, "row": new_purchase})


def handle_put_purchases(handler, path_clean: str = ""):
    """PUT /api/purchases/{id} — 编辑申购记录"""
    iid = path_clean[len("/api/purchases/"):] if path_clean and path_clean != "/api/purchases" else ""
    body = read_body(handler)
    if not iid:
        send_json(handler, 400, {"error": "缺少申购记录 id"})
        return

    purchases = _get("purchases")
    found = False
    for purchase in purchases:
        if purchase.get("id") == iid:
            if "name" in body:
                purchase["name"] = body["name"]
            if "qty" in body:
                purchase["qty"] = float(body["qty"])
            if "est_price" in body:
                purchase["est_price"] = float(body["est_price"])
            if "unit" in body:
                purchase["unit"] = body["unit"]
            if "supplier" in body:
                purchase["supplier"] = body["supplier"]
            if "note" in body:
                purchase["note"] = body["note"]
            if "status" in body:
                purchase["status"] = body["status"]
            found = True
            log(f"  OK 编辑申购 {purchase['name']}")
            break

    if not found:
        send_json(handler, 404, {"error": f"未找到 {iid}"})
        return

    _save("purchases", purchases)
    send_json(handler, 200, {"ok": True, "purchases": purchases})


def handle_put_purchases_stock(handler, path_clean: str):
    """PUT /api/purchases/{id}/stock"""
    pid = path_clean[len("/api/purchases/"):-len("/stock")]
    purchases = _get("purchases")
    idx = next((i for i, p in enumerate(purchases) if p.get("id") == pid), None)
    if idx is None:
        send_json(handler, 404, {"error": f"未找到 {pid}"})
        return
    p = purchases[idx]
    if p["status"] == "stocked":
        send_json(handler, 400, {"error": "已经入库过了"})
        return
    items = _get("items")
    existing = next((it for it in items if it["name"] == p["name"]), None)
    if existing:
        existing["qty"] = float(existing["qty"]) + float(p["qty"])
        if p.get("unit"):
            existing["unit"] = p["unit"]
        log(f"  OK 累加 {p['name']}: {p['qty']} -> {existing['qty']} {existing['unit']}")
    else:
        items.append({
            "id": f"item-{int(datetime.now().timestamp() * 1000)}",
            "name": p["name"],
            "qty": float(p["qty"]),
            "unit": p.get("unit", ""),
            "note": f"从申购 {pid} 自动入库",
            "created_at": datetime.now().isoformat(),
        })
        log(f"  OK 新增 {p['name']}: {p['qty']} {p.get('unit', '')}")
    purchases[idx]["status"] = "stocked"
    _save("items", items)
    _save("purchases", purchases)
    send_json(handler, 200, {"ok": True, "purchase": purchases[idx]})


def handle_delete_purchases(handler, path_clean: str):
    """DELETE /api/purchases/{id}"""
    pid = path_clean[len("/api/purchases/"):]
    purchases = _get("purchases")
    new = [p for p in purchases if p.get("id") != pid]
    if len(new) == len(purchases):
        send_json(handler, 404, {"error": f"未找到 {pid}"})
        return
    _save("purchases", new)
    log(f"  -- 删除申购 {pid}")
    send_json(handler, 200, {"ok": True})
