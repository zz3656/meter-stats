"""抄表相关 API handler。"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from utils import send_json, opt_float, read_body
from storage import log, load_json, save_json
from handlers._base import get_data_paths, get_lock
from report import invalidate_report_cache as _invalidate_report_cache


def _load_readings() -> list:
    return load_json(get_data_paths()["readings"], [])


# ==================== GET ====================

def handle_get_readings(handler):
    """GET /api/readings"""
    send_json(handler, 200, _load_readings())


def handle_get_readings_monthly(handler):
    """GET /api/readings/monthly?month=2026-07"""
    qs = parse_qs(urlparse(handler.path).query)
    month = qs.get("month", [datetime.now().strftime("%Y-%m")])[0]
    readings = _load_readings()
    filtered = [r for r in readings if r.get("date", "").startswith(month)]
    filtered.sort(key=lambda r: r["date"])
    send_json(handler, 200, filtered)


# ==================== POST ====================

def handle_post_readings(handler):
    """POST /api/readings"""
    body = read_body(handler)
    if not body.get("date"):
        send_json(handler, 400, {"error": "日期不能为空"})
        return
    date = body["date"]

    hall = opt_float(body, "hall")
    fire = opt_float(body, "fire")
    private_room = opt_float(body, "private_room")
    ac = opt_float(body, "ac")
    main_meter = opt_float(body, "main_meter")
    sub_meter = opt_float(body, "sub_meter")
    water = opt_float(body, "water")
    note = body.get("note", "")

    if all(v is None for v in [hall, fire, private_room, ac]) and \
       all(v is None for v in [main_meter, sub_meter, water]):
        send_json(handler, 400, {"error": "四表/水电至少填一个"})
        return

    readings = _load_readings()
    idx = next((i for i, r in enumerate(readings) if r.get("date") == date), None)

    if idx is not None:
        # 覆盖:表单没填的字段(null)保留旧值 — 补录水电时不会清掉已有 4 表读数
        old = readings[idx]
        new_row = {
            "date": date,
            "hall": hall, "fire": fire, "private_room": private_room, "ac": ac,
            "main_meter": main_meter, "sub_meter": sub_meter, "water": water,
            "note": note,
        }
        for k in ("hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water"):
            if new_row[k] is None:
                new_row[k] = old.get(k)
        readings[idx] = new_row
        log(f"  >> 覆盖抄表 {date}")
    else:
        readings.append({
            "date": date,
            "hall": hall, "fire": fire, "private_room": private_room, "ac": ac,
            "main_meter": main_meter, "sub_meter": sub_meter, "water": water,
            "note": note,
        })
        log(f"  ++ 新增抄表 {date}")

    _save_readings(readings)
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "row": readings[idx] if idx is not None else readings[-1]})


# ==================== PUT ====================

def handle_put_readings(handler, path_clean: str):
    """PUT /api/readings/{date}"""
    date = path_clean[len("/api/readings/"):]
    body = read_body(handler)
    if not date:
        send_json(handler, 400, {"error": "日期不能为空"})
        return

    readings = _load_readings()
    existing = next((r for r in readings if r.get("date") == date), None)
    if not existing:
        send_json(handler, 404, {"error": f"未找到 {date}"})
        return

    for key in ["hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water", "note"]:
        val = body.get(key)
        if val is not None:
            if key in ("hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water"):
                existing[key] = opt_float(body, key)
            else:
                existing[key] = val
    _save_readings(readings)
    log(f"  OK 更新抄表 {date}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True, "row": existing})


# ==================== DELETE ====================

def handle_delete_readings(handler, path_clean: str):
    """DELETE /api/readings/{date}"""
    date = path_clean[len("/api/readings/"):]
    readings = _load_readings()
    new = [r for r in readings if r.get("date") != date]
    if len(new) == len(readings):
        send_json(handler, 404, {"error": f"未找到 {date}"})
        return
    _save_readings(new)
    log(f"  -- 删除抄表 {date}")
    _invalidate_report_cache()
    send_json(handler, 200, {"ok": True})


def _save_readings(data):
    lock = get_lock("readings")
    with lock:
        save_json(get_data_paths()["readings"], data)
