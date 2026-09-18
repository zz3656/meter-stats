"""物品相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from storage import log, load_json, save_json, get_lock
from handlers._base import JsonModelHandler

_now = datetime.now


class _ItemsHandler(JsonModelHandler):
    model = "items"
    # PUT 白名单:仅这些字段可被 PUT 更新。lend_records 不能通过此接口修改。
    updatable_fields = frozenset({"name", "qty", "unit", "note"})

    def _create_row(self, body: dict):
        name = body.get("name")
        if not name:
            return None, "name 不能为空"
        qty = body.get("qty")
        if qty is not None and qty < 0:
            return None, "数量不能为负数"
        return {
            "id": f"item-{int(_now().timestamp() * 1000)}",
            "name": name,
            "qty": float(qty) if qty is not None else 0,
            "unit": body.get("unit", ""),
            "note": body.get("note", ""),
            "created_at": _now().isoformat(),
        }, None


_h = _ItemsHandler()


# ==================== 路由函数 ====================

def handle_get_items(handler, path_clean: str = ""):
    """GET /api/items"""
    _h.handle_get(handler, path_clean)


def handle_post_items(handler, path_clean: str = ""):
    """POST /api/items"""
    _h.handle_post(handler, path_clean)


def handle_put_items(handler, path_clean: str = ""):
    """PUT /api/items 或 /api/items/{id}"""
    _h.handle_put(handler, path_clean)


def handle_delete_items(handler, path_clean: str):
    """DELETE /api/items/{id}"""
    _check_delete(handler)
    _h.handle_delete(handler, path_clean)


# ==================== 借出 / 归还 子路径 ====================

def _load_items():
    return load_json(_h._path(), [])


def _save_items(data):
    lock = get_lock("items")
    with lock:
        save_json(_h._path(), data)


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

    items = _load_items()
    item, _ = _h._find_by_id(items, iid)
    if not item:
        send_json(handler, 404, {"error": f"未找到物品 {iid}"})
        return

    total_qty = float(item.get("qty", 0))
    lent_qty = float(item.get("lent_qty", 0))
    available_qty = total_qty - lent_qty

    if qty > available_qty:
        send_json(handler, 400, {
            "error": f"可借出数量不足，当前可借出 {available_qty} {item.get('unit', '个')}"
        })
        return

    if "lend_records" not in item:
        item["lend_records"] = []

    lend_record = {
        "id": f"lend-{int(_now().timestamp() * 1000)}",
        "borrower": borrower,
        "qty": qty,
        "lend_date": _now().strftime("%Y-%m-%d %H:%M:%S"),
        "return_date": None,
        "status": "lent",
        "note": note,
    }
    item["lend_records"].append(lend_record)
    item["lent_qty"] = lent_qty + qty

    _save_items(items)
    log(f"  OK 借出 {item['name']} x{qty} 给 {borrower}")
    send_json(handler, 200, {"ok": True, "row": item})


def handle_put_items_return(handler, path_clean: str):
    """PUT /api/items/{id}/return — 归还物品（不要求借出人）"""
    iid = path_clean[len("/api/items/"):].replace("/return", "")
    body = read_body(handler)

    qty = body.get("qty")
    note = body.get("note", "").strip()

    items = _load_items()
    item, _ = _h._find_by_id(items, iid)
    if not item:
        send_json(handler, 404, {"error": f"未找到物品 {iid}"})
        return

    lent_qty = float(item.get("lent_qty", 0))
    if lent_qty <= 0:
        send_json(handler, 400, {"error": "该物品没有借出记录，无需归还"})
        return

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

    if "lend_records" not in item:
        item["lend_records"] = []

    # 优先归还最早的记录
    unlent_records = [r for r in item["lend_records"] if r.get("status") == "lent"]
    unlent_records.sort(key=lambda r: r.get("lend_date", ""))

    remaining = qty
    for record in unlent_records:
        if remaining <= 0:
            break
        record_qty = float(record.get("qty", 0))
        ret_from_this = min(record_qty, remaining)
        record["return_qty"] = record.get("return_qty", 0) + ret_from_this
        remaining -= ret_from_this
        # 部分/全部归还都应记录 note (修复 bug: 之前仅在全部归还时记 note,
        # 导致部分归还时用户输入的说明丢失,最需要 note 的场景反而丢了)
        if note:
            record["return_note"] = note
        if record_qty <= ret_from_this:
            record["status"] = "returned"
            record["return_date"] = _now().strftime("%Y-%m-%d %H:%M:%S")

    item["lent_qty"] = lent_qty - qty
    _save_items(items)
    log(f"  OK 归还 {item['name']} x{qty}")
    send_json(handler, 200, {"ok": True, "row": item})


# ==================== 权限检查 ====================
def _check_delete(handler):
    """检查删除权限（仅管理员和主管）。

    行为说明：
    - 无 token 时放行(前端兼容遗留客户端,保持与原实现一致)。
    - 有 token 但会话不存在 → 401。
    - 有 token 但角色不足 → 403。
    - 有 token 且角色足够 → 放行并重置 TTL。

    实现复用 handlers.permissions._get_token 与 handlers.auth.get_session,
    不重复造轮子。
    """
    from handlers.permissions import _get_token
    from handlers.auth import get_session, _touch_session
    from handlers.settings import ROLE_ADMIN, ROLE_SUPERVISOR
    from utils import send_json

    token = _get_token(handler)
    if not token:
        return  # 无 token 时放行(前端兼容)
    sess = get_session(token)
    if sess is None:
        send_json(handler, 401, {"error": "未登录"})
        return
    _touch_session(token)  # 重置 TTL
    if sess.get("role") not in (ROLE_ADMIN, ROLE_SUPERVISOR):
        send_json(handler, 403, {"error": "权限不足: 需要管理员或主管权限"})
        return
