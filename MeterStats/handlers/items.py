"""物品相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from storage import log, load_json, save_json, get_lock
from handlers.permissions import check_permission

def _get_data_paths():
    import app_handler as _h
    return _h.DATA_PATHS

def _get(model: str):
    return load_json(_get_data_paths().get(model), [])

def _save(model: str, data):
    lock = get_lock(model)
    with lock:
        save_json(_get_data_paths().get(model), data)


def handle_get_items(handler, path_clean: str = ""):
    """GET /api/items"""
    send_json(handler, 200, _get("items"))


def handle_post_items(handler, path_clean: str = ""):
    """POST /api/items — 添加物品/申购记录（无鉴权，向后兼容）"""

    body = read_body(handler)
    name = body.get("name")
    if not name:
        send_json(handler, 400, {"error": "name 不能为空"})
        return
    qty = body.get("qty")
    if qty is not None and qty < 0:
        send_json(handler, 400, {"error": "数量不能为负数"})
        return
    items = _get("items")
    new_item = {
        "id": f"item-{int(datetime.now().timestamp() * 1000)}",
        "name": name,
        "qty": float(qty) if qty is not None else 0,
        "unit": body.get("unit", ""),
        "note": body.get("note", ""),
        "created_at": datetime.now().isoformat(),
    }
    items.append(new_item)
    _save("items", items)
    log(f"  OK 新增 {name}")
    send_json(handler, 200, {"ok": True, "row": new_item})


def handle_put_items(handler, path_clean: str = ""):
    """PUT /api/items 或 /api/items/{id} — 无 id 时兼容为添加"""
    iid = path_clean[len("/api/items/"):] if path_clean and path_clean != "/api/items" else ""
    body = read_body(handler)

    items = _get("items")

    # 兼容旧语义: PUT /api/items(无id) = 添加
    if not iid:
        name = body.get("name")
        if not name:
            send_json(handler, 400, {"error": "name 不能为空"})
            return
        qty = body.get("qty")
        if qty is not None and qty < 0:
            send_json(handler, 400, {"error": "数量不能为负数"})
            return
        new_item = {
            "id": f"item-{int(datetime.now().timestamp() * 1000)}",
            "name": name,
            "qty": float(qty) if qty is not None else 0,
            "unit": body.get("unit", ""),
            "note": body.get("note", ""),
            "created_at": datetime.now().isoformat(),
        }
        items.append(new_item)
        _save("items", items)
        log(f"  OK 新增 {name}")
        send_json(handler, 200, {"ok": True, "row": new_item})
        return

    # 有 id = 编辑
    found = False
    for item in items:
        if item.get("id") == iid:
            if "name" in body:
                item["name"] = body["name"]
            if "qty" in body:
                item["qty"] = float(body["qty"])
            if "unit" in body:
                item["unit"] = body["unit"]
            if "note" in body:
                item["note"] = body["note"]
            found = True
            log(f"  OK 编辑 {item['name']}")
            break

    if not found:
        send_json(handler, 404, {"error": f"未找到 {iid}"})
        return

    _save("items", items)
    send_json(handler, 200, {"ok": True})


def handle_delete_items(handler, path_clean: str):
    """DELETE /api/items/{id}"""
    _check_delete(handler)

    iid = path_clean[len("/api/items/"):]
    items = _get("items")
    new = [it for it in items if it.get("id") != iid]
    if len(new) == len(items):
        send_json(handler, 404, {"error": f"未找到 {iid}"})
        return
    _save("items", new)
    log(f"  OK 删除 {iid}")
    send_json(handler, 200, {"ok": True})


def handle_put_items_lend(handler, path_clean: str):
    """PUT /api/items/{id}/lend — 借出物品"""
    iid = path_clean[len("/api/items/"):].replace("/lend", "")
    body = read_body(handler)

    borrower = body.get("borrower", "").strip()
    qty = float(body.get("qty", 0))
    note = body.get("note", "").strip()

    if not borrower:
        send_json(handler, 400, {"error": "借出人不能为空"})
        return
    if qty <= 0:
        send_json(handler, 400, {"error": "借出数量必须大于0"})
        return

    items = _get("items")
    item = None
    for it in items:
        if it.get("id") == iid:
            item = it
            break

    if not item:
        send_json(handler, 404, {"error": f"未找到物品 {iid}"})
        return

    # 计算可借出数量
    total_qty = float(item.get("qty", 0))
    lent_qty = float(item.get("lent_qty", 0))
    available_qty = total_qty - lent_qty

    if qty > available_qty:
        send_json(handler, 400, {"error": f"可借出数量不足，当前可借出 {available_qty} {item.get('unit', '个')}"})
        return

    # 初始化借出记录数组
    if "lend_records" not in item:
        item["lend_records"] = []

    # 添加借出记录
    lend_record = {
        "id": f"lend-{int(datetime.now().timestamp() * 1000)}",
        "borrower": borrower,
        "qty": qty,
        "lend_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "return_date": None,
        "status": "lent",
        "note": note,
    }
    item["lend_records"].append(lend_record)
    item["lent_qty"] = lent_qty + qty

    _save("items", items)
    log(f"  OK 借出 {item['name']} x{qty} 给 {borrower}")
    send_json(handler, 200, {"ok": True, "row": item})


def handle_put_items_return(handler, path_clean: str):
    """PUT /api/items/{id}/return — 归还物品"""
    iid = path_clean[len("/api/items/"):].replace("/return", "")
    body = read_body(handler)

    qty = body.get("qty")
    note = body.get("note", "").strip()

    items = _get("items")
    item = None
    for it in items:
        if it.get("id") == iid:
            item = it
            break

    if not item:
        send_json(handler, 404, {"error": f"未找到物品 {iid}"})
        return

    lent_qty = float(item.get("lent_qty", 0))
    if lent_qty <= 0:
        send_json(handler, 400, {"error": "该物品没有借出记录，无需归还"})
        return

    # 如果没有指定数量，默认归还全部
    if qty is None:
        qty = lent_qty
    else:
        qty = float(qty)

    if qty <= 0:
        send_json(handler, 400, {"error": "归还数量必须大于0"})
        return
    if qty > lent_qty:
        send_json(handler, 400, {"error": f"归还数量超过借出数量，当前借出 {lent_qty}"})
        return

    # 初始化借出记录数组
    if "lend_records" not in item:
        item["lend_records"] = []

    # 查找未归还的记录，按时间倒序，先归还最早的
    unlent_records = [r for r in item["lend_records"] if r.get("status") == "lent"]
    unlent_records.sort(key=lambda r: r.get("lend_date", ""))

    remaining_return = qty
    for record in unlent_records:
        if remaining_return <= 0:
            break
        record_qty = float(record.get("qty", 0))
        returned_from_this = min(record_qty, remaining_return)
        record["return_qty"] = record.get("return_qty", 0) + returned_from_this
        remaining_return -= returned_from_this
        if record_qty <= returned_from_this:
            record["status"] = "returned"
            record["return_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if note:
                record["return_note"] = note

    item["lent_qty"] = lent_qty - qty
    _save("items", items)
    log(f"  OK 归还 {item['name']} x{qty}")
    send_json(handler, 200, {"ok": True, "row": item})


# ===== 权限检查 =====
def _check_write(handler):
    """检查写权限（所有人）"""
    from handlers.permissions import _get_token, _SESSIONS, ROLE_LEVEL, ROLE_EMPLOYEE, ROLE_ADMIN
    from handlers.settings import ROLE_SUPERVISOR, ROLE_EMPLOYEE as RE

    token = _get_token(handler)
    sess = _SESSIONS.get(token) if token else None
    if not sess:
        send_json(handler, 401, {"error": "未登录"})
        return
    # 所有用户都可以写（员工/主管/管理员）

def _check_delete(handler):
    """检查删除权限（仅管理员和主管）。无 token 时放行(前端兼容)。"""
    from handlers.permissions import _get_token, _SESSIONS
    from handlers.settings import ROLE_ADMIN, ROLE_SUPERVISOR

    token = _get_token(handler)
    if not token:
        return  # 无 token → 无认证 → 前端直接删(向后兼容)
    sess = _SESSIONS.get(token) if token else None
    if not sess:
        send_json(handler, 401, {"error": "未登录"})
        return
    if sess.get("role") not in (ROLE_ADMIN, ROLE_SUPERVISOR):
        send_json(handler, 403, {"error": "权限不足: 需要管理员或主管权限"})
        return
