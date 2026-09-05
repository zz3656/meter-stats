"""值班录入相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from storage import log, load_json, save_json, get_lock
from handlers._base import JsonModelHandler

_now = datetime.now


class _DutyHandler(JsonModelHandler):
    model = "duty"

    def _create_row(self, body: dict):
        duty_type = body.get("duty_type", "").strip()
        shift = body.get("shift", "").strip()
        status = body.get("status", "").strip()
        fault_area = body.get("fault_area", "").strip()
        note = body.get("note", "").strip()

        if not duty_type:
            return None, "类型不能为空"
        if not shift:
            return None, "班次不能为空"
        if not status:
            return None, "处理状态不能为空"

        # 自动添加时间（如果未提供）
        record_time = body.get("record_time", "").strip()
        if not record_time:
            record_time = _now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            "id": _now().strftime("%Y%m%d%H%M%S"),
            "duty_type": duty_type,
            "record_time": record_time,
            "shift": shift,
            "status": status,
            "fault_area": fault_area,
            "note": note,
        }, None

    def _update_fields(self, existing: dict, body: dict) -> None:
        for key in ["duty_type", "shift", "status", "fault_area", "note"]:
            val = body.get(key)
            if val is not None:
                existing[key] = val
        # 处理时间（可选）
        if body.get("handle_time"):
            existing["handle_time"] = body["handle_time"]
        # 处理班次（可选）
        if body.get("handle_shift"):
            existing["handle_shift"] = body["handle_shift"]
        # 处理方案（可选）
        if body.get("handle_method"):
            existing["handle_method"] = body["handle_method"]
        # 记录时间更新（可选）
        if body.get("record_time"):
            existing["record_time"] = body["record_time"]


_h = _DutyHandler()


# ==================== 路由函数 ====================

def handle_get_duty(handler):
    """GET /api/duty"""
    _h.handle_get(handler)


def handle_post_duty(handler):
    """POST /api/duty"""
    _h.handle_post(handler)


def handle_put_duty(handler, path_clean: str):
    """PUT /api/duty/{id}"""
    _h.handle_put(handler, path_clean)


def handle_delete_duty(handler, path_clean: str):
    """DELETE /api/duty/{id}"""
    _h.handle_delete(handler, path_clean)


def handle_post_duty_handle(handler, path_clean: str):
    """POST /api/duty/{id}/handle — 处理一条未处理的工作记录。

    两步操作：
    1. 将原始报修记录标记为"已处理"，记录 handle_record_id 关联
    2. 创建一条新的处理记录（duty_type="处理"），携带处理时间、班次、方案、备注
    """
    # 提取 id: /api/duty/xxx/handle → xxx
    parts = path_clean.split("/")
    # 期望: ["", "api", "duty", "<id>", "handle"]
    if len(parts) < 5 or parts[-1] != "handle":
        from utils import send_json
        send_json(handler, 400, {"error": "路径不正确"})
        return
    rid = parts[3]
    body = read_body(handler)

    handle_time = body.get("handle_time", "").strip()
    handle_shift = body.get("handle_shift", "").strip()
    handle_method = body.get("handle_method", "").strip()
    note = body.get("note", "").strip()

    if not handle_shift or not handle_method:
        send_json(handler, 400, {"error": "处理班次和处理方案不能为空"})
        return

    if not handle_time:
        handle_time = _now().strftime("%Y-%m-%d %H:%M:%S")

    data = _h._load()
    existing, idx = _h._find_by_id(data, rid)
    if existing is None:
        send_json(handler, 404, {"error": f"未找到 {rid}"})
        return

    # 1) 标记原始记录为已处理
    existing["status"] = "已处理"
    handle_id = _h._gen_id("HL")
    existing["handle_record_id"] = handle_id
    data[idx] = existing

    # 2) 创建处理记录
    handle_row = {
        "id": handle_id,
        "duty_type": "处理",
        "record_time": handle_time,
        "shift": handle_shift,
        "status": "已处理",
        "fault_area": existing.get("fault_area", ""),
        "note": handle_method,
        "original_id": rid,
    }
    if note:
        handle_row["note"] = f"{handle_method}\n备注: {note}"
    data.append(handle_row)

    _h._save(data)
    log(f"  OK 处理工作记录 {rid} → 新记录 {handle_id}")
    send_json(handler, 200, {"ok": True, "handle_id": handle_id})
