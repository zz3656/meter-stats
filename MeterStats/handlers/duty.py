"""值班录入相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse

from utils import send_json, read_body
from storage import log, load_json, save_json, get_lock


def _get_data_paths():
    """从 app_handler 模块读取 DATA_PATHS。"""
    import app_handler as _h
    return _h.DATA_PATHS


def _get(model: str = "duty"):
    return load_json(_get_data_paths().get(model), [])


def _save(model: str, data):
    lock = get_lock(model)
    with lock:
        save_json(_get_data_paths().get(model), data)


# ==================== GET ====================

def handle_get_duty(handler):
    """GET /api/duty"""
    send_json(handler, 200, _get("duty"))


# ==================== POST ====================

def handle_post_duty(handler):
    """POST /api/duty"""
    body = read_body(handler)

    duty_type = body.get("duty_type", "").strip()
    shift = body.get("shift", "").strip()
    status = body.get("status", "").strip()
    note = body.get("note", "").strip()

    if not duty_type:
        send_json(handler, 400, {"error": "类型不能为空"})
        return
    if not shift:
        send_json(handler, 400, {"error": "班次不能为空"})
        return
    if not status:
        send_json(handler, 400, {"error": "处理状态不能为空"})
        return

    # 自动添加时间（如果未提供）
    record_time = body.get("record_time", "").strip()
    if not record_time:
        record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    duty_list = _get("duty")

    new_record = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "duty_type": duty_type,
        "record_time": record_time,
        "shift": shift,
        "status": status,
        "note": note,
    }

    duty_list.append(new_record)
    _save("duty", duty_list)
    log(f"  ++ 新增值班记录 {new_record['id']}")
    send_json(handler, 200, {"ok": True, "row": new_record})


# ==================== PUT ====================

def handle_put_duty(handler, path_clean: str):
    """PUT /api/duty/{id}"""
    record_id = path_clean[len("/api/duty/"):]
    if not record_id:
        send_json(handler, 400, {"error": "记录ID不能为空"})
        return

    body = read_body(handler)
    duty_list = _get("duty")

    existing = None
    idx = None
    for i, r in enumerate(duty_list):
        if r.get("id") == record_id:
            existing = r
            idx = i
            break

    if not existing:
        send_json(handler, 404, {"error": f"未找到记录 {record_id}"})
        return

    # 更新字段
    for key in ["duty_type", "shift", "status", "note"]:
        val = body.get(key)
        if val is not None:
            existing[key] = val

    # 如果提供了新时间则更新
    if body.get("record_time"):
        existing["record_time"] = body["record_time"]

    duty_list[idx] = existing
    _save("duty", duty_list)
    log(f"  OK 更新值班记录 {record_id}")
    send_json(handler, 200, {"ok": True, "row": existing})


# ==================== DELETE ====================

def handle_delete_duty(handler, path_clean: str):
    """DELETE /api/duty/{id}"""
    record_id = path_clean[len("/api/duty/"):]
    duty_list = _get("duty")

    new_list = [r for r in duty_list if r.get("id") != record_id]
    if len(new_list) == len(duty_list):
        send_json(handler, 404, {"error": f"未找到记录 {record_id}"})
        return

    _save("duty", new_list)
    log(f"  -- 删除值班记录 {record_id}")
    send_json(handler, 200, {"ok": True})
