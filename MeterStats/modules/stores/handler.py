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

本模块还提供**门店范围闸**(store_scope_check / parse_store_target /
rel_store_scope_check):备份、恢复、NAS 同步这些接口的**载荷里带目标门店**,
查询参数上的门店闸(routing._store_gate)管不到它们 —— 「请求 ?store=main 被拒」
不等于「载荷里写 stores/main/readings.json 也被拒」。这两个闸必须都在。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

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


def _multi_store_layout() -> bool:
    """是否多门店布局。判不出(数据目录未初始化)时按单店处理。

    口径与 routing._store_gate 一致:判不出布局时按单店放行,并记一条日志,
    绝不把异常冒成 500。
    """
    try:
        from modules.stores.context import multi_store_layout
        return multi_store_layout()
    except Exception as e:
        from storage import log
        log(f"[WARN] [store_scope] 判不出门店布局,按单店放行: {e}")
        return False


def _resolve_store_scope(handler: Any) -> Tuple[bool, Optional[List[str]], str]:
    """解析调用方的门店范围。

    返回 (是否通过, 允许的门店 ID 列表, 错误文案):
    - (True, None, "")    → 不按门店过滤(单店布局 / 总部账号 all_stores)
    - (True, ["s002"], "")→ 只能访问这些门店
    - (False, [], "...")  → 拒绝(fail-closed)

    **fail-closed**:settings.json 里查不到这个用户 → 拒绝,
    绝不回退成「全部门店」(账号被删但会话还在 = 权限还在)。口径与
    routing._store_gate / _visible_store_ids 完全一致。
    """
    if not _multi_store_layout():
        # 单店布局:只有一家店,无从越权 → 放行(保持改造前行为完全一致)
        return (True, None, "")

    sess = _current_session(handler)
    if not sess:
        # 取不到会话:正常路径下不可能发生(所有请求都过 routing._auth_gate,
        # 它会把 session 挂到 handler._auth_session)。只有单元测试直接调
        # handler(不经 routing)时才会走到这里 —— 那时按 routing 的合成会话
        # 口径处理(ENFORCE_AUTH=False = 测试模式)。
        try:
            import routing as _routing
            if not getattr(_routing, "ENFORCE_AUTH", True):
                return (True, None, "")
        except Exception as e:
            from storage import log
            log(f"[WARN] [store_scope] 读取鉴权开关失败: {e}")
        return (False, [], "未登录或会话已过期,请重新登录")
    if sess.get("_synthetic"):
        # 单元测试模式(ENFORCE_AUTH=False)的合成会话 —— 与 _store_gate 同口径。
        return (True, None, "")

    user_id = sess.get("user_id")
    if not isinstance(user_id, int):
        return (False, [], "账号不存在或门店权限无法确认,请重新登录")
    try:
        scope = registry.user_store_scope(user_id)
    except Exception as e:
        from storage import log
        log(f"[WARN] [store_scope] 读用户门店范围失败: {e}")
        return (False, [], "账号不存在或门店权限无法确认,请重新登录")
    if scope is None:
        # 用户不存在(账号被删 / 会话是假的)→ 一家店都不给
        return (False, [], "账号不存在或门店权限无法确认,请重新登录")
    all_stores, store_ids = scope
    if all_stores:
        return (True, None, "")
    return (True, [str(s) for s in store_ids], "")


def caller_store_scope(handler: Any) -> Tuple[bool, Optional[List[str]], str]:
    """调用方的门店范围(公开 helper)。

    返回 (是否通过, 允许的门店 ID 列表(None = 不按门店过滤), 错误文案)。
    「只列出/只打包调用方范围内的门店」这类需求用它。
    """
    return _resolve_store_scope(handler)


def store_scope_check(handler: Any, store_ids: Iterable[str]) -> Tuple[bool, str]:
    """校验一批目标门店 ID 是否都在调用方的门店范围内。

    返回 (是否通过, 错误文案)。通过时错误文案是空串。

    规则(逐条都是安全边界,不要放宽):
    - **单店布局**(数据目录下没有 stores/ 目录)→ 直接放行
      (保持改造前行为完全一致;此时只有一家店,无从越权)。
    - 取当前会话(handler._auth_session,没有就自己取 token)→ 查用户记录。
    - **查不到用户记录 → 拒绝**(fail-closed),绝不回退成「全部门店」。
    - all_stores=True(总部账号)→ 放行。
    - 否则:每个目标门店 ID 都必须在该用户的 store_ids 里 →
      **大小写敏感**比较("MAIN" != "main")。
    """
    ok, allowed, msg = _resolve_store_scope(handler)
    if not ok:
        return (False, msg)
    if allowed is None:
        return (True, "")
    targets = [str(s) for s in store_ids]
    if not targets:
        return (True, "")
    if not allowed:
        return (False, "账号未分配门店,请联系管理员")
    for sid in targets:
        if sid not in allowed:  # 大小写敏感:registry 拒绝大小写冲突的门店 ID
            return (False, f"无权访问门店: {sid}")
    return (True, "")


def parse_store_target(rel: str) -> Tuple[bool, Optional[str]]:
    """解析备份包相对路径里的「目标门店」。

    返回 (是否通过, 门店 ID):
    - (True, None)   → 顶层文件(readings.json / settings.json 等),
      没有门店维度 → 放行
    - (True, "s002") → 目标门店是 s002
    - (False, None)  → 路径形状不合法 / 门店 ID 非法 → **拒绝**(不放行)

    门店 ID 必须过 registry.is_valid_store_id —— 解析不出合法 ID 的路径
    绝不能当成「没有门店维度」放行(那等于「路径里写什么都行」)。
    """
    rel = (rel or "").strip()
    if not rel or rel.startswith("/") or "\\" in rel:
        return (False, None)
    parts = rel.split("/")
    if len(parts) == 1:
        # 顶层文件:没有门店维度
        return (True, None)
    if parts[0] != "stores":
        # 既不是顶层文件,也不是门店子路径 → 非法
        return (False, None)
    if len(parts) < 3:
        # stores/<id> 没有文件名 → 非法
        return (False, None)
    store_id = parts[1]
    if not registry.is_valid_store_id(store_id):
        return (False, None)
    return (True, store_id)


def rel_store_scope_check(handler: Any, rel: str) -> Tuple[bool, str]:
    """校验一个备份包相对路径的**目标门店**是否在调用方范围内。

    顶层文件(没有门店维度)直接放行;门店子路径按 parse_store_target
    解析出目标门店后走 store_scope_check。
    """
    ok, store_id = parse_store_target(rel)
    if not ok:
        return (False, f"非法的数据文件路径: {rel}")
    if store_id is None:
        return (True, "")
    return store_scope_check(handler, [store_id])


def backup_rel_store_id(rel: str) -> str:
    """备份相对路径归属的门店 ID。

    - "stores/<id>/xxx" → "<id>"
    - 顶层数据文件("readings.json" 等)→ 总店 ID(main):
      多门店布局下顶层文件就是总店的历史位置(迁移前的遗留),
      它不是「没有门店维度」,而是**总店的数据**。

    与 parse_store_target 的区别:那个判「这次写操作的目标门店是谁」
    (顶层文件 → 没有门店维度 → 放行);这个判「这个文件属于谁的数据」
    (打包/列举时用来决定要不要收进某个门店的备份)。
    """
    from modules.stores.context import DEFAULT_STORE_ID
    parts = (rel or "").split("/")
    if len(parts) >= 2 and parts[0] == "stores":
        return parts[1]
    return DEFAULT_STORE_ID


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
    """GET /api/stores → { ok, stores, all_stores }"""
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
    # all_stores:调用方是不是总部账号(可见全部门店)。
    # 前端据此决定要不要显示门店切换器 —— 总部账号即使只有 1 家店也要能看到
    # 「当前在哪家店」,所以不能只看 stores 的条数。
    send_json(handler, 200, {"ok": True, "stores": stores, "all_stores": all_stores})


# 月份必须严格 YYYY-MM:用 \d{2} 会把 2026-13 放进来,后面 monthrange 直接抛
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def handle_get_stores_overview(handler: Any) -> None:
    """GET /api/stores/overview?month=YYYY-MM → 各店月度汇总 + 合计。

    逐店用**自己的**表集合与电价跑一遍月报(P2 已参数化),再横向合并。
    权限:任意登录用户,但只聚合**调用方有权限**的门店 —— 员工看到自己那家,
    总部账号看到全部。这些数据本来就在他的可见范围内,不额外加主管闸。

    设计取舍(见 P3 计划):
    - 汇总只加总 total_kwh / total_cost,**不合并 by_meter** —— 各店表 key 不同,
      硬合并会得到一个四不像的键集合(每店自己的 by_meter 仍原样返回)
    - 单店失败不影响整体:那一行带 error,其余照常 ——
      一家店坏了就整页 500 等于「总部什么都看不到」
    """
    qs = parse_qs(urlparse(handler.path).query)
    month = (qs.get("month", [""])[0] or "").strip()
    if not _MONTH_RE.match(month):
        send_json(handler, 400, {"error": "month 参数格式错误,应为 YYYY-MM"})
        return

    ok, allowed_ids, msg = caller_store_scope(handler)
    if not ok:
        send_json(handler, 403, {"error": msg})
        return

    from modules.stores.context import (
        current_store_paths,
        store_scope,
    )
    from report import calculate_monthly_report
    from storage import load_json, log

    try:
        stores = registry.list_stores()
    except Exception as e:
        log(f"[WARN] [overview] 读门店注册表失败: {e}")
        send_json(handler, 200, {"month": month, "stores": [],
                                 "total": {"total_kwh": 0.0, "total_cost": 0.0}})
        return

    if allowed_ids is not None:
        stores = [s for s in stores if s.get("id") in allowed_ids]

    rows: List[Dict[str, Any]] = []
    total_kwh = 0.0
    total_cost = 0.0

    for store in stores:
        sid = str(store.get("id") or "")
        name = str(store.get("name") or sid)
        try:
            with store_scope(sid):
                from modules.stores.config import get_report_tables, get_store_prices
                prices = get_store_prices()
                tables = get_report_tables()
                paths = current_store_paths()
                readings = load_json(paths["readings"], [])
                charges = load_json(paths["charges"], [])
                rep = calculate_monthly_report(
                    readings, charges, month,
                    tables=tables, price=prices["electricity_price"],
                )
                summary = rep["summary"]
                # 水电按店取(总表/分表/水表是另一套口径)
                try:
                    from modules.reports.handler import calc_month_utilities
                    utils = calc_month_utilities(month, load_json(paths["readings_water"], []))
                except Exception:
                    utils = {}
            rows.append({
                "id": sid,
                "name": name,
                "total_kwh": summary["total_kwh"],
                "total_cost": summary["total_cost"],
                "reading_days": summary["reading_days"],
                "by_meter": summary["by_meter"],
                "utilities": {
                    "main_kwh": (utils or {}).get("main_kwh") if isinstance(utils, dict) else None,
                    "water_usage": (utils or {}).get("water_usage") if isinstance(utils, dict) else None,
                },
            })
            total_kwh += summary["total_kwh"] or 0
            total_cost += summary["total_cost"] or 0
        except Exception as e:
            log(f"[WARN] [overview] 门店 {sid} 汇总失败: {e}")
            rows.append({"id": sid, "name": name, "error": str(e)})

    send_json(handler, 200, {
        "month": month,
        "stores": rows,
        "total": {
            "total_kwh": round(total_kwh, 1),
            "total_cost": round(total_cost, 2),
        },
    })


def handle_get_current_store(handler: Any) -> None:
    """GET /api/stores/current → { ok, store_id, store, all_stores }"""
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
    all_stores, _ = _visible_store_ids(sess)
    send_json(handler, 200, {"ok": True, "store_id": store_id, "store": store,
                             "all_stores": all_stores})


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
