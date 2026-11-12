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


# ============ 充值与抄表的一致性校验 ============

# 允许"单区间用电"超出该表历史日均的倍数(留 3 倍余量,避免正常波动被误判)
CHARGE_CONFLICT_FACTOR = 3.0
# 阈值下限(度):消防这类小表历史日均只有几十度,给个绝对下限兜底
CHARGE_CONFLICT_FLOOR_KWH = 300.0


def _days_between(d1: str, d2: str) -> int:
    """两个日期之间隔了几天(非法日期返回 0)。"""
    try:
        return (datetime.strptime(d2, "%Y-%m-%d")
                - datetime.strptime(d1, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return 0


def _attributed_segment(rows: list, key: str, cdate: str):
    """这笔充值会被归属到哪个区间 —— 归属口径与一致性校验的唯一事实来源。

    逐表独立判断(每笔只归属一次;L = 实际到账日):
      1. L 当天正好抄了表,且表底相对上一次**上升** → 归属"上一次 → 这一次" → (i-1, i)
      2. L 当天抄了表但没上升 → 归属"终点晚于 L 的第一个区间" → (i, i+1)
      3. L 落在两条读数正中间(当天没抄表) → 归属该区间 → (prev, next)
      4. L 之后还没有任何抄表 → 不归属任何区间 → None

    返回 (start_idx, end_idx);None = 不归属。
    """
    date_index = {r["date"]: i for i, r in enumerate(rows)}
    if cdate in date_index:
        i = date_index[cdate]
        cur = rows[i].get(key)
        prev = rows[i - 1].get(key) if i >= 1 else None
        if i >= 1 and cur is not None and prev is not None and float(cur) > float(prev):
            return (i - 1, i)
        if i + 1 < len(rows):
            return (i, i + 1)
        return None
    prev_idx = None
    for i, r in enumerate(rows):
        if r["date"] > cdate:
            if prev_idx is not None:
                return (prev_idx, i)
            return None
        prev_idx = i
    return None


def _landing_transition(rows: list, key: str, from_idx: int):
    """从 from_idx 起找第一个"表底上升"的读数区间 —— 充值真正进表的地方。

    返回 (start_idx, end_idx);None = 后面的读数里表底再没跳过(钱始终没进表)。
    """
    for j in range(from_idx, len(rows) - 1):
        a = rows[j].get(key)
        b = rows[j + 1].get(key)
        if a is None or b is None:
            continue
        if float(b) > float(a):
            return (j, j + 1)
    return None


def _segment_plausible(rows: list, key: str, seg, amt: float, mult: float, cap: float):
    """这个区间"若这笔钱真的到账",用电量是否还算合理。

    返回 (implied_kwh, threshold_kwh, ok)。
    """
    si, ei = seg
    s_val = rows[si].get(key)
    e_val = rows[ei].get(key)
    if s_val is None or e_val is None:
        return (0.0, 0.0, True)
    days = _days_between(rows[si]["date"], rows[ei]["date"])
    if days <= 0:
        return (0.0, 0.0, True)
    implied = (float(s_val) + amt - float(e_val)) * mult
    threshold = max(cap * days * CHARGE_CONFLICT_FACTOR, CHARGE_CONFLICT_FLOOR_KWH)
    return (implied, threshold, implied <= threshold)


def _resolve_charge(rows: list, key: str, cdate: str, amt: float, mult: float, cap: float):
    """这笔充值最终归属哪个区间,以及它是否与抄表对不上。

    返回 (seg, conflict);seg 为 None = 不归属任何区间;conflict 非 None = 与抄表矛盾。

    归属口径(逐表独立判断,每笔只归属一次;L = 实际到账日):
      1. L 当天正好抄了表,且表底相对上一次**上升** → 归属"上一次 → 这一次"。
      2. L 当天抄了表但没上升 → 先看"终点晚于 L 的第一个区间"。
      3. L 落在两条读数正中间(当天没抄表) → 归属包含它的那个区间。
      4. 上面两个区间里表底没上升时:该区间的用电量 =(表底差 + 充值额)。
         算出来的数合理 → 钱确实在这个区间进表(可能当天就用光了);
         离谱 → 钱是更晚才进表的 → 往后找第一个表底上升的区间;再找不到,
         就是这笔记录与抄表对不上(多半是把抄表读数填进了充值栏)。
      5. L 之后还没有任何抄表 → 钱还没反映进表底,暂不归属(等下次抄表再算)。
    """
    seg = _attributed_segment(rows, key, cdate)
    if seg is None:
        return (None, None)
    si, ei = seg
    s_val = rows[si].get(key)
    e_val = rows[ei].get(key)
    if s_val is None or e_val is None:
        return (seg, None)
    if float(e_val) > float(s_val):
        return (seg, None)   # 表底上升 → 钱确实在这个区间进表了

    implied, threshold, ok = _segment_plausible(rows, key, seg, amt, mult, cap)
    if ok:
        return (seg, None)   # 用电量算得通 → 钱在这个区间进表(可能当天就用光了)

    # 这个区间的用电量离谱 —— 钱多半是更晚才进表的,往后找表底真正跳升的区间
    later = _landing_transition(rows, key, ei)
    if later is not None:
        l_implied, l_threshold, l_ok = _segment_plausible(rows, key, later, amt, mult, cap)
        if l_ok and l_implied >= 0:
            return (later, None)   # 钱在后面的区间进的表 → 改归属到那一段

    conflict = {
        "implied_kwh": round(implied, 1),
        "threshold_kwh": round(threshold, 1),
        "start_date": rows[si]["date"],
        "end_date": rows[ei]["date"],
        "start_val": float(s_val),
        "end_val": float(e_val),
    }
    return (None, conflict)


def _daily_cap_kwh(rows: list, key: str, mult: float) -> float:
    """该表历史"单日用电"上限(度/天) —— 原始表底差按区间天数摊平。

    只取表底**下降**的区间:表底上升说明刚到账,表底差不代表用电。
    """
    best = 0.0
    for i in range(len(rows) - 1):
        a = rows[i].get(key)
        b = rows[i + 1].get(key)
        if a is None or b is None:
            continue
        days = _days_between(rows[i]["date"], rows[i + 1]["date"])
        if days <= 0:
            continue
        d = (float(a) - float(b)) * mult
        if d > 0 and d / days > best:
            best = d / days
    return best


def find_pasted_reading_charges(readings: list, charges: list) -> list:
    """找出「充值额和当天抄表读数一模一样」的记录 —— 八成是把抄表读数填进了充值栏。

    几乎零误报:充值额恰好等于当前表底,意味着充完钱表底要翻倍;而这类表一天只用
    几个表字,不可能当天把一整份余额用光。真出现这种巧合,表底必然是跳升的(钱已经
    进表、抄表已体现),所以**只在"当天表底没上升"时**才判定为填错。

    返回 [{charge_id, date, meter, label, amount, reading, reason}]
    """
    rows = sorted(
        [r for r in readings if r.get("date") and r.get("hall") is not None],
        key=lambda r: r["date"],
    )
    if not rows:
        return []
    date_index = {r["date"]: i for i, r in enumerate(rows)}
    out: list = []

    for t in TABLES:
        key, label = t["key"], t["label"]
        for c in charges:
            if c.get("status", "confirmed") == "pending":
                continue
            try:
                amt = float(c.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            cdate = _landing_date(c)
            if cdate not in date_index:
                continue
            i = date_index[cdate]
            cur = rows[i].get(key)
            prev = rows[i - 1].get(key) if i >= 1 else None
            if cur is None or prev is None:
                continue
            if float(cur) > float(prev):
                continue  # 当天表底跳升 → 钱已进表,读数里已经体现了
            if abs(amt - float(cur)) >= 0.01:
                continue
            out.append({
                "charge_id": c.get("id"),
                "date": cdate,
                "meter": key,
                "label": label,
                "amount": amt,
                "reading": float(cur),
                "reason": (
                    f"{label} {cdate} 的充值额 {amt:g} 和当天抄表读数一模一样 —— "
                    f"是不是把抄表读数填进充值栏了?充值额应该是**新充进去的表字数**,"
                    f"不是当前表底(充完表底会翻倍)。"
                ),
            })
    return out


def find_charge_conflicts(readings: list, charges: list) -> list:
    """找出与抄表对不上的充值记录 —— 多半是把抄表读数填进了充值栏。

    预付费表的物理事实:表底下降 = 用电,表底上升 = 刚到账。一笔 X 表字的充值如果
    真的到账了,它被归属的那个区间里表底必然"净升";否则该区间需要出现
    (表底差 + X) 的用电量 —— 一旦这个数离谱(超过该表历史日均的 3 倍),就说明
    这笔钱根本没进表,记录本身是错的。

    实测事故:2026-11-11 有人把当天抄表读数(205.7 / 1706.5 / 197.6 / 138.9)填进
    了充值栏,系统照单全收,大厅凭空多出 205.7 × 160 = 32912 度,一天总用电被顶到
    89588.8 度(真实 1130.3 度),月报被顶到 102700.7 度(真实 14242.2 度)。

    返回 [{charge_id, date, meter, label, amount, implied_kwh, threshold_kwh, reason}]
    """
    rows = sorted(
        [r for r in readings if r.get("date") and r.get("hall") is not None],
        key=lambda r: r["date"],
    )
    if len(rows) < 2:
        return []
    date_index = {r["date"]: i for i, r in enumerate(rows)}
    conflicts: list = []

    for t in TABLES:
        key, mult, label = t["key"], t["mult"], t["label"]
        cap = _daily_cap_kwh(rows, key, mult)
        for c in charges:
            if c.get("status", "confirmed") == "pending":
                continue  # 待确认的充值申请不计入任何统计
            try:
                amt = float(c.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            cdate = _landing_date(c)
            seg, conflict = _resolve_charge(rows, key, cdate, amt, mult, cap)
            if conflict is None:
                continue  # 钱进表了(或者还没抄表,无法证伪)

            implied = conflict["implied_kwh"]
            threshold = conflict["threshold_kwh"]
            s_val = conflict["start_val"]
            e_val = conflict["end_val"]

            # 充值额和当天抄表读数一模一样 → 八成是把抄表读数填进了充值栏
            landing_val = rows[date_index[cdate]].get(key) if cdate in date_index else None
            same_as_reading = (
                landing_val is not None and abs(amt - float(landing_val)) < 0.01
            )
            if same_as_reading:
                reason = (
                    f"{label} {cdate} 的充值额 {amt:g} 和当天抄表读数一模一样 —— "
                    f"是不是把抄表读数填进充值栏了?充值额应该是**新充进去的表字数**,"
                    f"不是当前表底。这笔记录已从所有用电统计中排除。"
                )
            else:
                reason = (
                    f"{label} {cdate} 的充值额 {amt:g} 表字与抄表对不上:"
                    f"表底 {s_val:g} → {e_val:g} 没有上升,若这笔钱真的到账,"
                    f"{conflict['start_date']}→{conflict['end_date']} 得用掉 {implied:.0f} 度"
                    f"(历史日均 {cap:.0f} 度/天),钱没有进表。"
                    f"这笔记录已从所有用电统计中排除。"
                )
            conflicts.append({
                "charge_id": c.get("id"),
                "date": cdate,
                "meter": key,
                "label": label,
                "amount": amt,
                "implied_kwh": implied,
                "threshold_kwh": threshold,
                "reason": reason,
            })
    return conflicts


def _charge_attribution(readings: list, charges: list, skip: set | None = None) -> dict:
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

    `skip` 是 {(charge_id, meter_key)} 集合 —— 命中即跳过该表的这笔充值。
    月报用它排除"与抄表对不上"的充值(见 find_charge_conflicts)。
    """
    rows = sorted(
        [r for r in readings if r.get("date") and r.get("hall") is not None],
        key=lambda r: r["date"],
    )
    out: dict = {}
    caps = {t["key"]: _daily_cap_kwh(rows, t["key"], t["mult"]) for t in TABLES}

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
            if skip and (c.get("id"), key) in skip:
                continue  # 与抄表对不上,不计入用电量
            # _resolve_charge 会把"钱晚点才进表"的充值改归属到表底真正跳升的那一段,
            # 把与抄表对不上的记录剔掉(seg=None)
            seg, _conflict = _resolve_charge(rows, key, cdate, amt, t["mult"], caps[key])
            if seg is None:
                continue  # 规则 4:到账日之后还没有任何抄表 → 暂不归属
            _add((rows[seg[0]]["date"], rows[seg[1]]["date"]), key, amt)
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
    # 与抄表对不上的充值(多半是把抄表读数填进了充值栏)先排除,否则用电量会被顶飞
    conflicts = find_charge_conflicts(readings, charges)
    skip = {(c["charge_id"], c["meter"]) for c in conflicts}
    attribution = _charge_attribution(readings, charges, skip=skip)

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
        # 与抄表对不上的充值(界面用来提示"有一条充值记录填错了")
        "conflicts": conflicts,
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
