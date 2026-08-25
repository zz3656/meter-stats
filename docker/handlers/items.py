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
