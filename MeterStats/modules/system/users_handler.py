"""用户管理 + 电表设置 + 角色查询 API。
从原 handlers.admin.py 拆分而来,保持 API 行为完全一致。
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from modules.system.settings_handler import (
    get_settings, save_settings, add_user, update_user, delete_user, save_users_verified, ROLES,
)


# ============ 用户管理 CRUD ============

def handle_get_users(handler):
    """GET /api/admin/users → [users](不含密码)"""
    settings = get_settings()
    # 不返回密码
    users = [{k: v for k, v in u.items() if k != "password"} for u in settings.get("users", [])]
    send_json(handler, 200, users)


def handle_post_users(handler):
    """POST /api/admin/users {username, password, name, role, store_ids?, all_stores?} → {ok, user}"""
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    users = settings.get("users", [])
    username = (body or {}).get("username", "")
    password = (body or {}).get("password", "")
    name = (body or {}).get("name", username)
    role = (body or {}).get("role", "employee")
    store_ids = (body or {}).get("store_ids")
    all_stores = (body or {}).get("all_stores")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    err = _check_store_ids(store_ids, settings)
    if err:
        send_json(handler, 200, {"ok": False, "error": err})
        return

    result = add_user(users, username, password, name, role,
                      store_ids=store_ids if isinstance(store_ids, list) else None,
                      all_stores=all_stores if isinstance(all_stores, bool) else None)
    if not isinstance(result, dict):
        send_json(handler, 200, {"ok": False, "error": "创建用户失败"})
        return
    if "error" in result:
        send_json(handler, 200, {"ok": False, "error": result["error"]})
        return

    settings["users"] = users
    try:
        # 写完回读校验 —— 写盘失败绝不能报成功(见 save_users_verified 的说明)
        save_users_verified(settings, result["id"])
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"保存用户失败,门店归属未生效: {e}"})
        return
    send_json(handler, 200, {"ok": True, "user": _public_user(result)})


def handle_put_users(handler, path_clean: str):
    """PUT /api/admin/users?id=<uid> {fields} → {ok, user}"""
    qs = parse_qs(urlparse(handler.path).query)
    uid_str = qs.get("id", [None])[0]
    if not uid_str or not uid_str.isdigit():
        send_json(handler, 200, {"ok": False, "error": "无效的用户ID"})
        return

    uid = int(uid_str)
    settings = get_settings()
    users = settings.get("users", [])
    body = read_body(handler)
    body = body or {}

    err = _check_store_ids(body.get("store_ids"), settings)
    if err:
        send_json(handler, 200, {"ok": False, "error": err})
        return

    result = update_user(users, uid, body)
    if result is None:
        send_json(handler, 200, {"ok": False, "error": "用户不存在"})
        return

    settings["users"] = users
    try:
        # 写完回读校验 —— 写盘失败绝不能报成功(见 save_users_verified 的说明)
        save_users_verified(settings, uid)
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"保存用户失败,门店归属未生效: {e}"})
        return
    send_json(handler, 200, {"ok": True, "user": _public_user(result)})


def handle_delete_users(handler, path_clean: str):
    """DELETE /api/admin/users?id=<uid> → {ok}"""
    qs = parse_qs(urlparse(handler.path).query)
    uid_str = qs.get("id", [None])[0]
    if not uid_str or not uid_str.isdigit():
        send_json(handler, 200, {"ok": False, "error": "无效的用户ID"})
        return

    uid = int(uid_str)
    settings = get_settings()
    users = settings.get("users", [])
    deleted = delete_user(users, uid)
    if not deleted:
        send_json(handler, 200, {"ok": False, "error": "用户不存在"})
        return

    settings["users"] = users
    save_settings(settings)
    send_json(handler, 200, {"ok": True})


# ============ 门店归属辅助 ============

def _check_store_ids(store_ids: Any, settings: Dict[str, Any]) -> Optional[str]:
    """校验 store_ids 里的每个门店 ID 都在注册表里。返回错误文案,None = 通过。

    不校验的后果:用户的 store_ids 里躺着一个永远匹配不上的 ID(手打错了、
    门店已被删)→ 门店闸永远 403「无权访问门店」,用户看不到任何数据,
    而且看不出原因。这里是可用性/数据一致性问题 —— 接口是 /api/admin/users,
    仅管理员可访问,鉴权闸已经挡住了越权。

    用内存里的 settings 查注册表,不额外读盘。
    """
    if not isinstance(store_ids, list) or not store_ids:
        return None
    from modules.stores import registry
    known = {str(s.get("id")) for s in registry.list_stores(settings)}
    unknown = [str(x) for x in store_ids if str(x) not in known]
    if unknown:
        return f"门店不存在: {', '.join(unknown)}"
    return None


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """返回给前端的用户信息 —— 不含密码哈希。"""
    return {k: v for k, v in user.items() if k != "password"}


# ============ 电表设置 ============

def handle_get_meter_settings(handler):
    """GET /api/admin/meter → {meter, config}"""
    settings = get_settings()
    send_json(handler, 200, {
        "meter": settings.get("meter", {}),
        "config": settings.get("config", {}),
    })


def handle_get_meters_public(handler):
    """GET /api/meters → {meters, config} (非管理员也可访问)"""
    settings = get_settings()
    send_json(handler, 200, {
        "meters": settings.get("meter", {}),
        "config": settings.get("config", {}),
    })


def handle_put_meter_settings(handler):
    """PUT /api/admin/meter → {meter, config}"""
    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    if "meter" in body:
        settings["meter"] = body["meter"]
    if "config" in body:
        settings["config"] = body["config"]
    save_settings(settings)
    send_json(handler, 200, {"ok": True, "meter": settings["meter"], "config": settings["config"]})


# ============ 权限管理 ============

def handle_get_roles(handler):
    """GET /api/admin/roles → [roles]"""
    send_json(handler, 200, [{"key": k, "name": v} for k, v in ROLES.items()])
