"""申购相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from utils import send_json, read_body

_now = datetime.now
from storage import log, load_json, save_json
from modules._base import get_data_paths, get_lock
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
    name = (body.get("name") or "").strip()
    # 物品名称：写名字 或 直接拍张照片（不知道叫什么的时候），满足其一即可
    name_imgs = [
        str(f).replace("\\", "/").split("/")[-1].strip()
        for f in (body.get("name_image_filenames") or [])
        if isinstance(f, str) and f.strip()
    ]
    if not name and not name_imgs:
        send_json(handler, 400, {"error": "请填写物品名称，或上传一张照片"})
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
        "name_image_filenames": name_imgs,
        "qty": float(qty),
        "unit": body.get("unit", ""),
        "est_price": float(est_price),
        "supplier": body.get("supplier", ""),
        "note": body.get("note", ""),
        # 备注栏的图片：拍下旧件/位置，下一个班次一看就知道买什么
        "note_image_filenames": [
            str(f).replace("\\", "/").split("/")[-1].strip()
            # ⚠️ 键是 note_image_filenames（前端传这个），兼容旧的 image_filenames
            for f in ((body.get("note_image_filenames") or body.get("image_filenames") or []))
            if isinstance(f, str) and f.strip()
        ],
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
    """PUT /api/purchases/{id}/stock — 确认购买。

    购买后保留两条记录：
      1) 原申购记录 → status='purchased'（申请过什么，留档）
      2) 新增购买记录 kind='purchase' → 实际买了什么（含图片、金额、供应商）
    body: { add_to_items: bool, image_filenames: [...], note: str }
    """
    from modules.items.handler import _load_items, _save_items
    pid = path_clean[len("/api/purchases/"):-len("/stock")]
    body = read_body(handler) or {}
    add_to_items = bool(body.get("add_to_items", False))
    images = [str(f).replace("\\", "/").split("/")[-1].strip()
              for f in (body.get("image_filenames") or []) if isinstance(f, str) and f.strip()]
    note = body.get("note", "").strip()

    purchases = _load_purchases()
    idx = next((i for i, p in enumerate(purchases) if p.get("id") == pid), None)
    if idx is None:
        send_json(handler, 404, {"error": f"未找到 {pid}"})
        return
    p = purchases[idx]
    if p.get("kind") == "purchase":
        send_json(handler, 400, {"error": "这已经是一条购买记录了"})
        return
    if p.get("status") in ("purchased", "stocked"):
        send_json(handler, 400, {"error": "这条申购已经购买过了"})
        return

    now = _now()

    # 1) 原申购记录标记完成（保留在列表里，可以追溯"申请过什么"）
    purchases[idx]["status"] = "purchased"
    purchases[idx]["purchased_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

    # 2) 新增一条购买记录
    buy_row = {
        "id": f"buy-{int(now.timestamp() * 1000)}",
        "kind": "purchase",
        "ref_id": pid,
        "date": body.get("date") or now.strftime("%Y-%m-%d"),
        "name": p.get("name", ""),
        "qty": float(p.get("qty", 0)),
        "unit": p.get("unit", ""),
        "est_price": float(p.get("est_price", 0)),
        "supplier": p.get("supplier", ""),
        "note": note or p.get("note", ""),
        "note_image_filenames": images,
        "added_to_items": add_to_items,
        "status": "purchased",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    purchases.append(buy_row)

    # 3) 勾选了才累加到物品记录
    if add_to_items:
        items = _load_items()
        existing = next((it for it in items if it["name"] == buy_row["name"]), None)
        if existing:
            existing["qty"] = float(existing.get("qty", 0)) + buy_row["qty"]
            if buy_row["unit"]:
                existing["unit"] = buy_row["unit"]
            log(f"  OK 累加 {buy_row['name']}: -> {existing['qty']} {existing.get('unit', '')}")
        else:
            items.append({
                "id": f"item-{int(now.timestamp() * 1000)}",
                "name": buy_row["name"],
                "qty": buy_row["qty"],
                "unit": buy_row["unit"],
                "note": f"从申购 {pid} 自动入库",
                "created_at": now.isoformat(),
            })
            log(f"  OK 新增 {buy_row['name']}: {buy_row['qty']} {buy_row['unit']}")
        _save_items(items)

    _save_purchases(purchases)
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "purchase_row": purchases[idx], "buy_row": buy_row})


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

from modules._storage import ModuleStorage
_storage = ModuleStorage('purchases')
