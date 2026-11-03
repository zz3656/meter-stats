"""
电表统计 — 月报计算引擎
================================
从 readings.json + charges.json 计算月度逐日逐表用电度数。

新增：月报缓存（内存），key = month_str → report_dict，TTL = 5 分钟。
"""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from storage import _local_now
from pathlib import Path
from threading import RLock

from constants import METER_MULTIPLIERS, ELECTRICITY_PRICE as PRICE


# 4 块表定义 (key / 标签 / 倍率)
TABLES = [
    {"key": "hall", "label": "1#大厅", "mult": METER_MULTIPLIERS["hall"]},
    {"key": "fire", "label": "2#消防", "mult": METER_MULTIPLIERS["fire"]},
    {"key": "private_room", "label": "3#包厢", "mult": METER_MULTIPLIERS["private_room"]},
    {"key": "ac", "label": "4#空调", "mult": METER_MULTIPLIERS["ac"]},
]


def _landing_date(charge: dict) -> str:
    """充值**实际到账**的日期。

    已确认的取 `confirmed_at` 的日期(例:11-02 提交申请、11-03 财务打款到账 → 11-03);
    待确认、或没有该字段的历史记录(7 条老数据 status 为 null)退回记录日期本身。
    """
    if charge.get("status") == "confirmed" and charge.get("confirmed_at"):
        return str(charge["confirmed_at"])[:10]
    return charge.get("date", "")


def _charge_attribution(readings: list, charges: list) -> dict:
    """把每笔充值归属到"它真正到账的那个抄表区间"。

    预付费表:表底下降 = 用电,上升 = 刚到账。充值记录的 `date` 是当天算量提申请的日子,
    真正到账看 `confirmed_at`,两者可能差一天甚至几天。旧口径 (上次, 本次] 无条件把
    "本次抄表当天"的充值并进这一段用电量,等于把刚充进去、一度还没用的余额当成已经耗掉
    的电(实测事故:大厅真实 656 度/天被算成 34256 度/天,建议充值 ¥113 万,还提示当天断电)。

    归属规则(逐表独立判断,每笔只归属一次;下面 L = 实际到账日):
      1. L 当天正好抄了表,且这次抄表相对上一次**上升** → 钱在抄表前就进表了,
         归属"上一次 → 这一次"。
      2. L 当天抄了表但没上升(抄表在到账前,或当天就把充进去的额度用光)→ 归属
         "终点晚于 L 的第一个区间",那个终点读数必然已包含这笔充值。
      3. L 落在两条读数正中间(当天没抄表) → 必然在这个区间到账,归属该区间。
      4. L 之后还没有任何抄表 → 钱还没反映进表底,暂不归入任何区间,等下次抄表再算。

    返回 {(区间起点日期, 区间终点日期): {meter_key: 表字数}}
    """
    rows = sorted(
        [r for r in readings if r.get("date") and r.get("hall") is not None],
        key=lambda r: r["date"],
    )
    date_index = {r["date"]: i for i, r in enumerate(rows)}
    out: dict = {}

    def _add(pair, key, amt):
        slot = out.setdefault(pair, {})
        slot[key] = slot.get(key, 0.0) + amt

    for c in charges:
        if c.get("status", "confirmed") == "pending":
            continue  # 待确认的充值申请不计入任何统计
        cdate = _landing_date(c)
        for t in TABLES:
            key = t["key"]
            try:
                amt = float(c.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if amt == 0:
                continue

            if cdate in date_index:
                i = date_index[cdate]
                cur = rows[i].get(key)
                prev = rows[i - 1].get(key) if i >= 1 else None
                if i >= 1 and cur is not None and prev is not None and float(cur) > float(prev):
                    # 规则 1:到账当天就抄了表,而且表底跳升 → 这笔钱已反映在该读数里
                    _add((rows[i - 1]["date"], cdate), key, amt)
                elif i + 1 < len(rows):
                    # 规则 2:当天抄表没体现(抄表在到账前,或当天就用光了)
                    #        → 归到下一个区间,那条终点读数必然已包含这笔充值
                    _add((cdate, rows[i + 1]["date"]), key, amt)
                # 规则 4:到账日之后还没有任何抄表 → 暂不归属,等下次抄表再算
                continue

            # 规则 1:充值日期不在任何抄表日 → 找包含它的那个区间
            prev_row = None
            for r in rows:
                if r["date"] > cdate:
                    if prev_row is not None:
                        _add((prev_row["date"], r["date"]), key, amt)
                    break  # 充值早于首条读数则无法归属
                prev_row = r
    return out


def calculate_monthly_report(readings: list, charges: list, month: str) -> dict:
    """计算指定月份的逐日逐表用电度数。

    带内存缓存（5 分钟 TTL）：相同月份和数据的请求直接返回缓存。
    """
    # 尝试缓存
    cached = _get_cached_report(month)
    if cached is not None:
        return cached
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

    # 每笔充值归属到"表底真正跳升"的区间(见 _charge_attribution)
    attribution = _charge_attribution(readings, charges)

    for X, Y in pairs:
        X_dt = datetime.strptime(X["date"], "%Y-%m-%d")
        Y_dt = datetime.strptime(Y["date"], "%Y-%m-%d")
        span = (Y_dt - X_dt).days
        if span <= 0:
            continue

        credited = attribution.get((X["date"], Y["date"]), {})

        # 计算每表的"原始用电 + 本区间实际到账的充值"
        usage = {}
        for t in TABLES:
            X_val = float(X.get(t["key"], 0) or 0)
            Y_val = float(Y.get(t["key"], 0) or 0)
            charge_sum = credited.get(t["key"], 0.0)
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

    result = {
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
    _cache_report(month, result)
    return result


def calculate_yearly_report(readings: list, charges: list, year: str) -> dict:
    """计算指定年份的月度汇总(12 个月,复用月度报告引擎)。

    带内存缓存（5 分钟 TTL）。
    """
    cache_key = f"yearly:{year}"
    cached = _get_cached_report(cache_key)
    if cached is not None:
        return cached
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

    result = {
        "year": year,
        "months": months,
        "year_total_kwh": round(year_total_kwh, 1),
        "year_total_cost": round(year_total_cost, 2),
    }
    _cache_report(cache_key, result)
    return result


# ============ 月报缓存 ============

# { month_str: (cache_time, report_data) }
_report_cache: dict = {}
_report_cache_lock = RLock()
_REPORT_CACHE_TTL = 5 * 60  # 5 分钟

def _cache_report(month: str, report: dict) -> None:
    """将月报结果写入缓存。"""
    now = _local_now().timestamp()
    with _report_cache_lock:
        _report_cache[month] = (now, report)

def _get_cached_report(month: str) -> dict | None:
    """从缓存获取月报。返回 None 表示缓存未命中或已过期。"""
    now = _local_now().timestamp()
    with _report_cache_lock:
        entry = _report_cache.get(month)
        if entry is None:
            return None
        cache_time, data = entry
        if now - cache_time > _REPORT_CACHE_TTL:
            del _report_cache[month]
            return None
        return data

def _invalidate_report_cache() -> None:
    """清除月报缓存（数据更新时调用）。"""
    with _report_cache_lock:
        _report_cache.clear()


def _get_report_cache_stats() -> dict:
    """获取缓存统计（仅管理员查看）。"""
    with _report_cache_lock:
        now = _local_now().timestamp()
        entries = []
        for month, (cache_time, data) in _report_cache.items():
            age = now - cache_time
            entries.append({
                "month": month,
                "age_seconds": round(age, 0),
                "ttl_minutes": _REPORT_CACHE_TTL // 60,
                "valid": age <= _REPORT_CACHE_TTL,
            })
        return {"size": len(entries), "ttl_minutes": _REPORT_CACHE_TTL // 60, "entries": entries}


# Public API
invalidate_report_cache = _invalidate_report_cache
get_report_cache_stats = _get_report_cache_stats
