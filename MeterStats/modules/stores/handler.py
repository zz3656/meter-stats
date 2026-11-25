"""门店管理 HTTP API。

权限:
- 读(GET)  → 任何登录用户,但只返回自己有权限的门店
- 增删改   → 仅管理员

失败一律 HTTP 200 + {"ok": false, "error": "..."}(本项目约定);
只有「没有有效会话」才回 401 —— 与 routing._auth_gate 的口径一致
(前端 js/core/api.js 里 `res.ok === false` 才是业务失败的判定口径)。

**fail-closed**:settings.json 里查不到这个用户 → 一家店都不给,
绝不回退成「全部门店」。账号被删除但会话还没过期时,回退放行等于
「号删了权限还在」。口径与 routing._store_gate 一致。

会话从 routing 拿(见 _current_session):鉴权与业务看的是同一份 session,
不会出现「鉴权时还在、业务处理时已过期」的两次取 token 竞态。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from urllib.parse import unquote

from utils import read_body, send_json

from modules.stores import registry
from modules.stores.context import get_current_store


def _current_session(handler: Any) -> Dict[str, Any]:
    """当前会话(身份已由 routing._auth_gate 判定,这里只取,不重复鉴权)。

    routing 鉴权通过后会把 session 挂到 handler._auth_session ——
    同一份 session 贯穿鉴权与业务,不会在两次取 token 之间过期。

    handler 被直接调用(不经 routing)时兜底自己取 token。
    """
    sess = getattr(handler, "_auth_session", None)
    if isinstance(sess, dict):
        return sess
    from modules.system.auth_handler import get_session
    from modules.system.permissions_handler import _get_token
    token = _get_token(handler)
    found = get_session(token) if token else None
    return found if found else {}


def _is_admin(sess: Dict[str, Any]) -> bool:
    """是不是管理员。空会话 → False(fail-closed:写接口天然拒绝)。"""
    return sess.get("role") == "admin"


def _visible_store_ids(sess: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """用户可见的门店范围 (all_stores, store_ids)。

    **fail-closed**:settings.json 里查不到这个用户 → (False, [])。
    绝不回退成「全部门店」:
      - 账号被删除但会话未过期 → 旧会话照样能看到全部门店
      - 会话根本没取到(空 dict)→ 默认值 True = 看全部门店
    两种都等于「越权」。口径与 routing._store_gate 一致:查不到用户记录 = 拒绝。
    """
    if sess.get("_synthetic"):
        # 单元测试模式(ENFORCE_AUTH=False)的合成会话 —— 与 _store_gate 同口径。
        return (True, [])
    user_id = sess.get("user_id")
    if not isinstance(user_id, int):
        return (False, [])
    try:
        scope = registry.user_store_scope(user_id)
    except Exception as e:
        from storage import log
        log(f"[WARN] [stores_api] 读用户门店范围失败: {e}")
        return (False, [])
    if scope is None:
        # 用户不存在(账号被删 / 会话是假的)→ 一家店都不给
        return (False, [])
    return scope


def _read_body_dict(handler: Any) -> Dict[str, Any]:
    """读请求体。body 不是 JSON 对象(数组/标量)时按空对象处理。"""
    body = read_body(handler)
    return body if isinstance(body, dict) else {}


def _store_id_from_path(path_clean: str) -> str:
    """从 /api/stores/<id> 里取门店 ID。非法/缺失返回空串。

    路径里的 ID 会 unquote —— 但 unquote 之后还要过 is_valid_store_id(),
    "%2F" 这类编码过的穿越字符在这一步被挡住(门店 ID 不含斜杠)。
    """
    parts = path_clean.split("/")
    if len(parts) < 4:
        return ""
    store_id = unquote(parts[3]).strip()
    if not registry.is_valid_store_id(store_id):
        return ""
    return store_id


def handle_get_stores(handler: Any) -> None:
    """GET /api/stores → { ok, stores }"""
    sess = _current_session(handler)
    if not sess:
        # 没有有效会话 → 401。绝不放行成「全部门店」。
        send_json(handler, 401, {"ok": False, "error": "未登录或会话已过期,请重新登录"})
        return
    all_stores, store_ids = _visible_store_ids(sess)
    try:
        stores = registry.list_stores()
    except Exception as e:
        from storage import log
        log(f"[WARN] [stores_api] 读门店注册表失败: {e}")
        send_json(handler, 200, {"ok": False, "error": f"读门店注册表失败: {e}"})
        return
    if not all_stores:
        stores = [s for s in stores if s.get("id") in store_ids]
    send_json(handler, 200, {"ok": True, "stores": stores})


def handle_get_current_store(handler: Any) -> None:
    """GET /api/stores/current → { ok, store_id, store }"""
    sess = _current_session(handler)
    if not sess:
        send_json(handler, 401, {"ok": False, "error": "未登录或会话已过期,请重新登录"})
        return
    # 当前门店由门店闸(routing._store_gate)按用户范围解析并写进 thread-local,
    # 这里只负责报出来 —— 不再自己判权限,免得两套口径打架。
    store_id = get_current_store()
    try:
        store = registry.get_store(store_id)
    except Exception as e:
        from storage import log
        log(f"[WARN] [stores_api] 读门店注册表失败: {e}")
        store = None
    if store is None:
        store = {"id": store_id, "name": store_id}
    send_json(handler, 200, {"ok": True, "store_id": store_id, "store": store})


def handle_post_store(handler: Any) -> None:
    """POST /api/stores { id, name, code?, address? } → { ok, store }"""
    sess = _current_session(handler)
    if not _is_admin(sess):
        send_json(handler, 200, {"ok": False, "error": "仅管理员可新增门店"})
        return
    body = _read_body_dict(handler)
    store_id = str(body.get("id") or "").strip()
    name = str(body.get("name") or "").strip()
    try:
        store = registry.add_store(
            store_id, name,
            code=str(body.get("code") or ""),
            address=str(body.get("address") or ""),
        )
    except (ValueError, RuntimeError) as e:
        # RuntimeError:registry 写 settings.json 失败时会抛(回读校验不通过)。
        # 只捕 ValueError 会让它变成未捕获异常 → 500,而不是 {"ok": false}。
        send_json(handler, 200, {"ok": False, "error": str(e)})
        return
    send_json(handler, 200, {"ok": True, "store": store})


def handle_put_store(handler: Any, path_clean: str) -> None:
    """PUT /api/stores/<id> { name?, code?, address?, active? } → { ok, store }"""
    sess = _current_session(handler)
    if not _is_admin(sess):
        send_json(handler, 200, {"ok": False, "error": "仅管理员可修改门店"})
        return
    store_id = _store_id_from_path(path_clean)
    if not store_id:
        send_json(handler, 200, {"ok": False, "error": "门店 ID 非法"})
        return
    body = _read_body_dict(handler)
    # 白名单:只认这 4 个字段,body 里其它键一律忽略(不能借 PUT 注入别的字段)
    fields: Dict[str, Any] = {
        k: body[k] for k in ("name", "code", "address", "active") if k in body
    }
    try:
        store = registry.update_store(store_id, fields)
    except (ValueError, RuntimeError) as e:
        # RuntimeError:registry 写 settings.json 失败时会抛(回读校验不通过)。
        send_json(handler, 200, {"ok": False, "error": str(e)})
        return
    send_json(handler, 200, {"ok": True, "store": store})


def handle_delete_store(handler: Any, path_clean: str) -> None:
    """DELETE /api/stores/<id> → { ok }"""
    sess = _current_session(handler)
    if not _is_admin(sess):
        send_json(handler, 200, {"ok": False, "error": "仅管理员可删除门店"})
        return
    store_id = _store_id_from_path(path_clean)
    if not store_id:
        send_json(handler, 200, {"ok": False, "error": "门店 ID 非法"})
        return
    try:
        deleted = registry.delete_store(store_id)
    except (ValueError, RuntimeError) as e:
        # RuntimeError:settings.json 写失败(回读校验不通过)时 registry 会抛
        send_json(handler, 200, {"ok": False, "error": str(e)})
        return
    if not deleted:
        # 默认店 main 不可删 / 门店不存在 —— 两种情况都回错误
        send_json(handler, 200, {"ok": False, "error": f"门店不存在或不可删除: {store_id}"})
        return
    send_json(handler, 200, {"ok": True})
