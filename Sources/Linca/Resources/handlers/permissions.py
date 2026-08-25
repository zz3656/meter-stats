"""权限中间件:用于装饰 handler，检查当前用户的角色和操作权限。

权限矩阵:
- 管理员(admin): 全部权限（读/写/管理/删除）
- 主管(supervisor): 读/写/删除/管理（无用户管理）
- 员工(employee): 仅读/写（不能删除，不能管理）

用法:
    @check_permission("admin")  # 仅管理员可操作
    @check_permission("write")  # 主管及以上可操作
    @check_permission("delete")  # 仅管理员和主管
    @check_permission("read")   # 所有人
"""
from __future__ import annotations

from handlers.admin import _SESSIONS, get_settings
from handlers.settings import ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_EMPLOYEE

# 角色等级
ROLE_LEVEL = {ROLE_ADMIN: 3, ROLE_SUPERVISOR: 2, ROLE_EMPLOYEE: 1}

# 操作对应的最低等级
OP_REQUIRED = {
    "admin": ROLE_ADMIN,        # 管理
    "delete": ROLE_SUPERVISOR,  # 删除
    "write": ROLE_EMPLOYEE,     # 写
    "read": ROLE_EMPLOYEE,      # 读
}


def check_permission(operation: str):
    """权限装饰器工厂。

    用法: @check_permission("delete")
    自动从 request headers 或 query token 获取当前用户，校验权限。
    """
    def decorator(fn):
        def wrapper(handler, *args, **kwargs):
            # 获取当前用户 session
            token = _get_token(handler)
            sess = _SESSIONS.get(token) if token else None

            if not sess:
                from utils import send_json
                send_json(handler, 401, {"error": "未登录，请先登录"})
                return

            # 检查角色
            user_role = sess.get("role", ROLE_EMPLOYEE)
            min_level = ROLE_LEVEL.get(OP_REQUIRED.get(operation, ROLE_EMPLOYEE), ROLE_EMPLOYEE)
            current_level = ROLE_LEVEL.get(user_role, ROLE_EMPLOYEE)

            if current_level < min_level:
                from utils import send_json
                send_json(handler, 403, {"error": f"权限不足: 需要{'管理员' if operation == 'admin' else '主管及以上'}权限"})
                return

            # 调用原 handler
            return fn(handler, *args, **kwargs)
        return wrapper
    return decorator


def _get_token(handler) -> str:
    """从 request 中提取 session token。"""
    # 优先从 cookie 或 query 参数获取
    cookie_header = handler.headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("linca_token="):
            return part.split("=", 1)[1].strip()

    # 从 query 参数获取（API 调用时用）
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(handler.path).query)
    token_list = qs.get("token", [])
    if token_list:
        return token_list[0]

    # 从 header 获取
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    return ""


def check_write_permission(fn):
    """装饰器: 仅允许读/写操作（员工及以上）。"""
    return check_permission("write")(fn)


def check_delete_permission(fn):
    """装饰器: 仅允许删除操作（主管及以上）。"""
    return check_permission("delete")(fn)


def check_admin_permission(fn):
    """装饰器: 仅允许管理操作（管理员）。"""
    return check_permission("admin")(fn)
