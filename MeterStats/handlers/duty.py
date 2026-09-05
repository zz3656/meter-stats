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
