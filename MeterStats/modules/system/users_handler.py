"""用户管理 + 电表设置 + 角色查询 API。
从原 handlers.admin.py 拆分而来,保持 API 行为完全一致。
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from constants import ROLES
from utils import read_body, send_json

from modules.system.settings_handler import (
    add_user,
    delete_user,
    get_settings,
    save_settings,
    save_users_verified,
    update_user,
)

# ============ 用户管理 CRUD ============

def handle_get_users(handler: Any) -> None:
    """GET /api/admin/users → [users](不含密码)"""
    settings = get_settings()
    # 不返回密码 —— 走 _public_user(),与 POST/PUT 的响应用同一套脱敏逻辑
    users = [_public_user(u) for u in settings.get("users", [])]
    send_json(handler, 200, users)


def handle_post_users(handler: Any) -> None:
    """POST /api/admin/users {username, password, name, role, store_ids?, all_stores?} → {ok, user}"""
    body = read_body(handler)
    # body 不是 JSON 对象(数组/标量/null)→ 按空参数处理,
    # 否则下面的 .get() 会抛 AttributeError → 500。
    if not body or not isinstance(body, dict):
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    settings = get_settings()
    users = settings.get("users", [])
    username = body.get("username", "")
    password = body.get("password", "")
    name = body.get("name", username)
    role = body.get("role", "employee")
    store_ids = body.get("store_ids")
    all_stores = body.get("all_stores")

    if not username or not password:
        send_json(handler, 200, {"ok": False, "error": "用户名和密码不能为空"})
        return

    # 只有「键存在」才校验:键不存在 = 没传门店(新用户 store_ids = [])。
    # 不能用 .get() 判 —— 显式传 store_ids: null 时 .get() 返回 None,
    # 会被当成「没传」放行,然后被 update_user 强转成 [] → 门店归属被静默清空。
    if "store_ids" in body:
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


def handle_put_users(handler: Any, path_clean: str) -> None:
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
    # body 不是 JSON 对象(数组/标量/null)→ 按空参数处理,
    # 否则下面的 body.get() 会抛 AttributeError → 500。
    if not isinstance(body, dict):
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    # 「键存在」才校验(理由同 POST):显式传 null 也必须报错,
    # 否则 update_user 会把它强转成 [] → 用户的门店归属被静默清空。
    if "store_ids" in body:
        err = _check_store_ids(body["store_ids"], settings)
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


def handle_delete_users(handler: Any, path_clean: str) -> None:
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
    try:
        # 写完回读校验 —— 写盘失败绝不能报成功(见 _verify_user_deleted 的说明)
        save_settings(settings)
        _verify_user_deleted(uid)
    except Exception as e:
        send_json(handler, 200, {"ok": False, "error": f"删除用户失败,用户未真正删除: {e}"})
        return
    send_json(handler, 200, {"ok": True})


def _verify_user_deleted(user_id: int) -> None:
    """回读 settings.json,确认被删的用户确实从盘上消失了。

    与 POST/PUT 的回读校验同一套思路:写 → 回读 → 比对 → 不通过就抛错。
    删除的校验目标与新增/修改相反 —— **这个用户必须不在盘上了**。

    为什么必须校验:_save() 会吞掉所有异常(只往 stderr 打一行
    `[settings] [WARN] _save failed:`),写失败时调用方会以为删除成功 ——
    用户还在盘上,角色与门店归属全都还在,「已删除」的假象比不删更危险。
    """
    try:
        on_disk = get_settings()
    except Exception as e:
        raise RuntimeError(f"写入 settings.json 后回读失败: {e}") from e
    for u in on_disk.get("users") or []:
        if isinstance(u, dict) and u.get("id") == user_id:
            raise RuntimeError(
                f"写入 settings.json 后回读校验不通过: 用户 {user_id} 仍然留在盘上")


# ============ 门店归属辅助 ============

def _check_store_ids(store_ids: Any, settings: Dict[str, Any]) -> Optional[str]:
    """校验 store_ids:必须是数组,且数组里的每个门店 ID 都在注册表里。

    返回错误文案,None = 通过。

    **必须是数组**:类型不对(字符串 / 数字 / dict / null)必须报错,
    不能放行 —— 放行后 update_user 会把它强转成 [] ,
    用户的门店归属被**静默清空**:管理员收到「成功」,用户当场失去门店访问权
    (门店闸 403「账号未分配有效门店」),而且盘上的原值已经没了。

    **空数组合法**:[] = 「不分配任何门店」——
    前端取消勾选全部门店、新建用户时先不选门店,都走这条路径。
    (把它一起拒掉会打断 UI 的正常操作。)

    不校验门店存在性的后果:用户的 store_ids 里躺着一个永远匹配不上的 ID
    (手打错了、门店已被删)→ 门店闸永远 403「无权访问门店」,用户看不到任何数据,
    而且看不出原因。这里是可用性/数据一致性问题 —— 接口是 /api/admin/users,
    仅管理员可访问,鉴权闸已经挡住了越权。

    用内存里的 settings 查注册表,不额外读盘。
    """
    if not isinstance(store_ids, list):
        return "store_ids 必须是数组"
    if not store_ids:
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


# ============ 电表设置(P2:按店) ============
#
# P2 之前这三处读写的是**全局** settings["meter"] —— 多店下一家店改表名,
# 全部门店跟着变。现在一律按**当前门店**读写 stores/<id>/store.json。
#
# 三个端点必须一起改:只改 PUT 不改 GET 会「保存成功但刷新变回去」;
# 只改一个 GET 会让电表设置页与抄表表单显示不同的表。

def _meters_payload() -> Dict[str, Any]:
    """当前门店的表定义与价格/倍率 —— 两个读接口共用的唯一响应构造。

    形状:`meters` 是**有序字典** {key: {label, icon, multiplier, color}}。
    刻意不用数组:前端 `meterConfig.js` 是 `Object.entries(data.meters)` 按字典
    遍历的,换成数组会让 key 变成 "0"/"1"。JSON 对象本身保序(键是非数字字符串),
    表定义顺序不需要数组来承载。
    """
    from modules.stores.config import get_store_meters, get_store_prices
    meters = get_store_meters()
    as_dict: Dict[str, Any] = {m["key"]: m for m in meters}
    return {
        "meters": as_dict,
        # 旧字段名一并带上(电表设置页历史上读的是 res.meter),同一份值
        "meter": as_dict,
        "config": get_store_prices(),
    }


def handle_get_meter_settings(handler: Any) -> None:
    """GET /api/admin/meter → {meters, meter, config}(当前门店)"""
    send_json(handler, 200, _meters_payload())


def handle_get_meters_public(handler: Any) -> None:
    """GET /api/meters → {meters, meter, config}(当前门店;非管理员也可访问)"""
    send_json(handler, 200, _meters_payload())


def _meters_as_list(raw: Any) -> list[Dict[str, Any]]:
    """把写接口收到的表定义统一成列表。

    兼容三种入参:数组(新)、有序字典 {key: {...}}(旧前端)、None。
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        out = []
        for key, val in raw.items():
            item = dict(val) if isinstance(val, dict) else {}
            item.setdefault("key", key)
            out.append(item)
        return out
    return []


def handle_put_meter_settings(handler: Any) -> None:
    """PUT /api/admin/meter → {ok, meters, meter, config}(写当前门店)"""
    from modules.stores.config import read_store_config, write_store_config
    from modules.stores.context import get_current_store
    from modules.stores.meters import normalize_tables, validate_tables_payload

    body = read_body(handler)
    if not body:
        send_json(handler, 200, {"ok": False, "error": "参数不能为空"})
        return

    meters_raw = body.get("meters", body.get("meter"))
    meters: list[Dict[str, Any]] = []
    if meters_raw is not None:
        meters = _meters_as_list(meters_raw)
        err = validate_tables_payload(meters)
        if err:
            send_json(handler, 400, {"error": err})
            return

    store_id = get_current_store()
    cfg = read_store_config(store_id)
    if meters_raw is not None:
        cfg["meters"] = normalize_tables(meters)
    if "config" in body:
        cfg["config"] = body["config"]
    write_store_config(store_id, cfg)

    # 表数/倍率/电价变了,月报缓存必须失效 —— 否则改完看到的还是旧数字
    from report import invalidate_report_cache
    invalidate_report_cache()

    payload = {"ok": True}
    payload.update(_meters_payload())
    send_json(handler, 200, payload)


# ============ 权限管理 ============

def handle_get_roles(handler: Any) -> None:
    """GET /api/admin/roles → [roles]"""
    send_json(handler, 200, [{"key": k, "name": v} for k, v in ROLES.items()])
