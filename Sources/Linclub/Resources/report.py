"""
林卡酒吧电表统计 — 月报计算引擎
================================
从 readings.json + charges.json 计算月度逐日逐表用电度数。
"""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta
from pathlib import Path


# 4 块表定义 (key / 标签 / 倍率)
TABLES = [
    {"key": "hall", "label": "1#大厅", "mult": 160},
    {"key": "fire", "label": "2#消防", "mult": 1},
    {"key": "private_room", "label": "3#包厢", "mult": 160},
    {"key": "ac", "label": "4#空调", "mult": 160},
]
PRICE = 0.9  # 元/度


def calculate_monthly_report(readings: list, charges: list, month: str) -> dict:
    """计算指定月份的逐日逐表用电度数。

    参数:
        month: "YYYY-MM" 格式

    返回:
        {"month": str, "days": [...], "summary": {...}}
    """
    # 解析月份
    year, mon = int(month[:4]), int(month[5:7])
    _, days_in_month = monthrange(year, mon)

    # 当月所有抄表(按日期排序;跳过只录水电的行 — 4 表全 null 不参与用电计算)
    month_readings = sorted(
        [r for r in readings if r.get("date", "").startswith(month)
         and r.get("hall") is not None],
        key=lambda r: r["date"],
    )

    # 上月最后一次抄表(用于本月第一段"前段")
    prev_reading = None
    for r in sorted(readings, key=lambda r: r["date"], reverse=True):
        if r["date"] < month + "-01" and r.get("hall") is not None:
            prev_reading = r
            break

    # 下月第一次抄表(用于本月末段"末段")
    month_end_str = f"{month}-{days_in_month:02d}"
    next_reading = None
    for r in sorted(readings, key=lambda r: r["date"]):
        if r["date"] > month_end_str and r.get("hall") is not None:
            next_reading = r
            break

    # 构造 (X, Y) 配对
    pairs = []
    if prev_reading and month_readings:
        pairs.append((prev_reading, month_readings[0]))
    for i in range(len(month_readings) - 1):
        pairs.append((month_readings[i], month_readings[i + 1]))
    if month_readings and next_reading:
        pairs.append((month_readings[-1], next_reading))

    # 计算每对 (X, Y) 的用电(含期间充值),分摊到区间
    daily_avg_by_date = {}  # date_str -> {key: 日均}
    month_total_kwh = 0.0
    sum_by_meter = {t["key"]: 0.0 for t in TABLES}

    for X, Y in pairs:
        X_dt = datetime.strptime(X["date"], "%Y-%m-%d")
        Y_dt = datetime.strptime(Y["date"], "%Y-%m-%d")
        span = (Y_dt - X_dt).days
        if span <= 0:
            continue

        # 找 (X_date, Y_date] 期间的充值
        charges_in_range = [
            c for c in charges
            if X["date"] < c.get("date", "") <= Y["date"]
        ]

        # 计算每表的"原始用电 + 期间充值"
        usage = {}
        for t in TABLES:
            X_val = float(X.get(t["key"], 0) or 0)
            Y_val = float(Y.get(t["key"], 0) or 0)
            charge_sum = sum(
                float(c.get(t["key"], 0) or 0) for c in charges_in_range
            )
            u = (X_val - Y_val + charge_sum) * t["mult"]
            usage[t["key"]] = round(max(u, 0), 1)

        # 分摊给 [X_dt, Y_dt) 区间内属于当月的天
        avg = {t["key"]: round(usage[t["key"]] / span, 1) for t in TABLES}
        d = X_dt
        while d < Y_dt:
            d_str = d.strftime("%Y-%m-%d")
            if d_str.startswith(month):
                daily_avg_by_date[d_str] = avg
            d += timedelta(days=1)

        # 计算这段只属于当月的部分
        days_in_month_for_seg = sum(
            1 for dd in daily_avg_by_date
            if X_dt <= datetime.strptime(dd, "%Y-%m-%d") < Y_dt
        )
        month_total_kwh += sum(
            usage[t["key"]] * days_in_month_for_seg / span
            for t in TABLES
        )
        for t in TABLES:
            sum_by_meter[t["key"]] += (
                usage[t["key"]] * days_in_month_for_seg / span
            )

    # 构造逐日数据
    reading_dates = {r["date"] for r in month_readings}
    days = []
    for day in range(1, days_in_month + 1):
        d_str = f"{month}-{day:02d}"
        if d_str in daily_avg_by_date:
            avg = daily_avg_by_date[d_str]
            total = round(sum(avg.values()), 1)
            days.append({
                "date": d_str,
                "hall": avg["hall"],
                "fire": avg["fire"],
                "private_room": avg["private_room"],
                "ac": avg["ac"],
                "total": total,
                "is_reading_day": d_str in reading_dates,
            })
        else:
            days.append({
                "date": d_str,
                "hall": 0, "fire": 0, "private_room": 0, "ac": 0,
                "total": 0,
                "is_reading_day": False,
            })

    month_total_cost = round(month_total_kwh * PRICE, 2)

    return {
        "month": month,
        "days": days,
        "summary": {
            "total_kwh": round(month_total_kwh, 1),
            "total_cost": month_total_cost,
            "by_meter": {t["key"]: round(sum_by_meter[t["key"]], 1) for t in TABLES},
            "reading_days": sum(1 for d in days if d["is_reading_day"]),
            "price": PRICE,
        },
    }


def calculate_yearly_report(readings: list, charges: list, year: str) -> dict:
    """计算指定年份的月度汇总(12 个月,复用月度报告引擎)。

    参数:
        year: "2026" 格式(4 位数字)

    返回:
        {"year": str, "months": [...], "year_total_kwh": float, "year_total_cost": float}
    """
    months = []
    year_total_kwh = 0.0
    year_total_cost = 0.0

    for m in range(1, 13):
        month_str = f"{year}-{m:02d}"
        r = calculate_monthly_report(readings, charges, month_str)
        s = r["summary"]
        if s["reading_days"] > 0:
            months.append({
                "month": month_str,
                "total_kwh": s["total_kwh"],
                "total_cost": s["total_cost"],
                "reading_days": s["reading_days"],
                "by_meter": s["by_meter"],
            })
            year_total_kwh += s["total_kwh"]
            year_total_cost += s["total_cost"]

    return {
        "year": year,
        "months": months,
        "year_total_kwh": round(year_total_kwh, 1),
        "year_total_cost": round(year_total_cost, 2),
    }
