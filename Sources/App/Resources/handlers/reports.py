"""报表相关 API handler。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse
from report import (
    PRICE as ELECTRICITY_PRICE,
    calculate_monthly_report,
    calculate_yearly_report,
)
from utils import send_json
from storage import log, load_json, save_json, DATA_FILES, get_all_model_names, get_lock

def _get_data_paths():
    import app_handler as _h
    return _h.DATA_PATHS

def _get(model: str):
    return load_json(_get_data_paths().get(model), [])


def handle_get_health(handler):
    """GET /api/health"""
    data_dir = _get_data_paths().get("readings")
    counts = {}
    parent = None
    if data_dir:
        parent = data_dir.parent
        for name in get_all_model_names():
            fp = _get_data_paths().get(name)
            if fp:
                try:
                    counts[name] = len(load_json(fp))
                except Exception:
                    counts[name] = 0
            else:
                counts[name] = 0
    send_json(handler, 200, {
        "status": "ok",
        "version": "0.1.0",
        "data_dir": str(parent) if data_dir else None,
        "file_count": counts,
        "time": datetime.now().isoformat(),
    })


def handle_get_export(handler):
    """GET /api/export?models=readings,charges,items,purchases"""
    qs = parse_qs(urlparse(handler.path).query)
    models_str = qs.get("models", ["readings,charges"])[0]
    models = [m.strip() for m in models_str.split(",")]

    headers_map = {
        "readings": ["date", "hall", "fire", "private_room", "ac", "main_meter", "sub_meter", "water", "note"],
        "charges": ["id", "date", "hall", "fire", "private_room", "ac", "note"],
        "items": ["id", "name", "qty", "unit", "note", "created_at"],
        "purchases": ["id", "date", "name", "qty", "unit", "est_price", "supplier", "status", "note"],
    }

    for model in models:
        model = model.strip()
        if model not in DATA_FILES:
            send_json(handler, 400, {"error": f"不支持导出的模型: {model}"})
            return
        filename = f"meter_{model}_{datetime.now().strftime('%Y%m%d')}.csv"
        cols = headers_map.get(model, [])
        lock = get_lock(model)
        with lock:
            data = _get(model)
        if cols:
            rows = [[row.get(c, "") for c in cols] for row in data]
        else:
            rows = []
        from utils import send_csv
        send_csv(handler, filename, cols, rows)
        return
    send_json(handler, 400, {"error": "至少指定一个 models 参数"})


def handle_get_monthly_report(handler):
    """GET /api/monthly-report?month=2026-07"""
    qs = parse_qs(urlparse(handler.path).query)
    month = qs.get("month", [datetime.now().strftime("%Y-%m")])[0]
    readings = _get("readings")
    charges = _get("charges")
    report = calculate_monthly_report(readings, charges, month)
    send_json(handler, 200, report)


def handle_get_yearly_report(handler):
    """GET /api/yearly-report?year=2026"""
    qs = parse_qs(urlparse(handler.path).query)
    year = qs.get("year", [str(datetime.now().year)])[0]
    readings = _get("readings")
    charges = _get("charges")
    report = calculate_yearly_report(readings, charges, year)
    send_json(handler, 200, report)


def handle_get_monthly_utilities(handler):
    """GET /api/monthly-utilities?month=2026-07

    月度水电:总表/分表/厨房/水表(普通递增表,每月抄一次)。
    总表 ×50、分表 ×40 = 实际用电;厨房 = 总表实际 − 分表实际;
    电费 0.9 元/度,水费 4.5 元/吨。
    """
    qs = parse_qs(urlparse(handler.path).query)
    month = qs.get("month", [datetime.now().strftime("%Y-%m")])[0]
    if not month or len(month) != 7:
        send_json(handler, 400, {"error": "需要 month 参数,格式: 2026-07"})
        return
    readings = _get("readings")
    cur_rs = sorted([r for r in readings if str(r.get("date", "")).startswith(month)],
                    key=lambda r: r["date"])
    # 该月是否有水电表底(总表/分表/水表任一);没有 → 提示未录入而非全 — 卡片
    has_water_data = any(
        r.get("main_meter") is not None or r.get("sub_meter") is not None or r.get("water") is not None
        for r in cur_rs
    )
    if not cur_rs or not has_water_data:
        send_json(handler, 200, {"month": month, "has_data": False,
                                 "msg": "该月未录入水电表底"})
        return
    # 上月最后一条(用于算差值;递增表:本月读数 - 上月读数 = 本月用量)
    y, m = int(month[:4]), int(month[5:7])
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    prev_key = f"{py:04d}-{pm:02d}"
    prev_rs = sorted([r for r in readings if str(r.get("date", "")).startswith(prev_key)],
                     key=lambda r: r["date"])
    cur = cur_rs[-1]
    has_prev = bool(prev_rs)
    prev = prev_rs[-1] if has_prev else None

    def _diff(cur_v, prev_v):
        if cur_v is None or prev_v is None:
            return None
        return round(max(cur_v - prev_v, 0), 1)  # 防负(换表/反装)

    # 读数差 × 倍率 = 实际用电(总表 ×50,分表 ×40)
    MAIN_METER_MULT, SUB_METER_MULT = 50, 40
    WATER_PRICE = 4.5
    main_raw = _diff(cur.get("main_meter"), prev.get("main_meter") if prev else None)
    sub_raw = _diff(cur.get("sub_meter"), prev.get("sub_meter") if prev else None)
    main_kwh = round(main_raw * MAIN_METER_MULT, 1) if main_raw is not None else None
    sub_kwh = round(sub_raw * SUB_METER_MULT, 1) if sub_raw is not None else None
    kitchen_kwh = round(main_kwh - sub_kwh, 1) if main_kwh is not None and sub_kwh is not None else None
    kitchen_cost = round(kitchen_kwh * ELECTRICITY_PRICE, 2) if kitchen_kwh is not None else None
    water_usage = _diff(cur.get("water"), prev.get("water") if prev else None)
    water_cost = round(water_usage * WATER_PRICE, 2) if water_usage is not None else None

    send_json(handler, 200, {
        "month": month,
        "has_data": True,
        "has_prev": has_prev,
        "cur": {"date": cur["date"],
                "main_meter": cur.get("main_meter"),
                "sub_meter": cur.get("sub_meter"),
                "water": cur.get("water")},
        "prev_date": prev["date"] if prev else None,
        "main_kwh": main_kwh,
        "sub_kwh": sub_kwh,
        "kitchen_kwh": kitchen_kwh,
        "kitchen_cost": kitchen_cost,
        "water_usage": water_usage,
        "water_cost": water_cost,
        "price_electricity": ELECTRICITY_PRICE,
        "price_water": WATER_PRICE,
        "mult_main": MAIN_METER_MULT,
        "mult_sub": SUB_METER_MULT,
    })
