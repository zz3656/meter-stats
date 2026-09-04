"""水电表底相关 API handler (总表/分表/水表)。

独立于电表抄表数据，存在 readings_water.json。
每条记录按 date 键控：同一日期只能有一条水电记录。
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from utils import send_json, opt_float, read_body
from storage import log, load_json, save_json, get_lock
from handlers._base import get_data_paths


def _load_water():
    return load_json(get_data_paths()["readings_water"], [])


def _save_water(data):
    lock = get_lock("readings_water")
    with lock:
        save_json(get_data_paths()["readings_water"], data)


# ==================== GET ====================

def handle_get_readings_water(handler):
    """GET /api/readings-water"""
    send_json(handler, 200, _load_water())


def handle_get_readings_water_monthly(handler):
    """GET /api/readings-water/monthly?month=2026-08"""
    from datetime import datetime
    qs = parse_qs(urlparse(handler.path).query)
    month = qs.get("month", [datetime.now().strftime("%Y-%m")])[0]
    water = _load_water()
    filtered = [r for r in water if r.get("date", "").startswith(month)]
    filtered.sort(key=lambda r: r["date"])
    send_json(handler, 200, filtered)


# ==================== POST ====================

def handle_post_readings_water(handler):
    """POST /api/readings-water

    新增或覆盖水电表底。
    不触碰电表抄表数据(readings.json)。
    """
    body = read_body(handler)
    if not body.get("date"):
        send_json(handler, 400, {"error": "日期不能为空"})
        return
    date = body["date"]

    main_meter = opt_float(body, "main_meter")
    sub_meter = opt_float(body, "sub_meter")
    water = opt_float(body, "water")
    note = body.get("note", "")

    if all(v is None for v in [main_meter, sub_meter, water]):
        send_json(handler, 400, {"error": "请至少填写总表/分表/水表一项"})
        return

    water_data = _load_water()

    # 查找已有记录
    idx = next((i for i, r in enumerate(water_data) if r.get("date") == date), None)

    if idx is not None:
        # 覆盖：用新值替换
        water_data[idx] = {
            "date": date,
            "main_meter": main_meter,
            "sub_meter": sub_meter,
            "water": water,
            "note": note,
        }
        log(f"  >> 覆盖水电表底 {date}")
    else:
        water_data.append({
            "date": date,
            "main_meter": main_meter,
            "sub_meter": sub_meter,
            "water": water,
            "note": note,
        })
        log(f"  ++ 新增水电表底 {date}")

    _save_water(water_data)
    send_json(handler, 200, {"ok": True, "row": water_data[idx] if idx is not None else water_data[-1]})


# ==================== PUT ====================

def handle_put_readings_water(handler, path_clean: str):
    """PUT /api/readings-water/{date}"""
    date = path_clean[len("/api/readings-water/"):]
    body = read_body(handler)
    if not date:
        send_json(handler, 400, {"error": "日期不能为空"})
        return

    water_data = _load_water()
    existing = next((r for r in water_data if r.get("date") == date), None)
    if not existing:
        send_json(handler, 404, {"error": f"未找到 {date}"})
        return

    for key in ["main_meter", "sub_meter", "water", "note"]:
        val = body.get(key)
        if val is not None:
            if key in ("main_meter", "sub_meter", "water"):
                existing[key] = opt_float(body, key)
            else:
                existing[key] = val
    _save_water(water_data)
    log(f"  OK 更新水电表底 {date}")
    send_json(handler, 200, {"ok": True, "row": existing})


# ==================== DELETE ====================

def handle_delete_readings_water(handler, path_clean: str):
    """DELETE /api/readings-water/{date}"""
    date = path_clean[len("/api/readings-water/"):]
    water_data = _load_water()
    new = [r for r in water_data if r.get("date") != date]
    if len(new) == len(water_data):
        send_json(handler, 404, {"error": f"未找到 {date}"})
        return
    _save_water(new)
    log(f"  -- 删除水电表底 {date}")
    send_json(handler, 200, {"ok": True})
