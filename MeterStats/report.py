"""
电表统计 — 月报计算引擎
================================
从 readings.json + charges.json 计算月度逐日逐表用电度数。

新增：月报缓存（内存），key = month_str → report_dict，TTL = 5 分钟。
"""
from __future__ import annotations

from bisect import bisect_left
from calendar import monthrange
from datetime import datetime, timedelta
from storage import _local_now
from threading import RLock
from typing import Any

from constants import DEFAULT_TABLES, ELECTRICITY_PRICE as PRICE
from modules.stores.meters import row_has_any_value, row_values


def _tables_of(tables: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """表定义的统一取值 —— 不传就用默认 4 表。

    所有公开函数都从这里过一道,保证「不传 tables」与「显式传 DEFAULT_TABLES」
    走的是同一条路(而不是一个走参数、另一个悄悄走模块常量)。
    """
    return tables if tables else DEFAULT_TABLES


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


def _prepare(readings: list, tables: list) -> tuple[list, dict, list]:
    """把抄表过滤+排序,并建 date → 下标索引(一次)。

    ⚠️ 这一步以前散在 5 个函数里各做一遍(`find_pasted_reading_charges` /
    `find_charge_conflicts` / `_charge_attribution` / 月报 / 年报),而最贵的是
    `_attributed_segment` 里**每笔充值 × 每块表**都重建一次索引:
    1100 行读数 × 157 笔充值 × 4 块表 ≈ 7 万次 O(R) 重建 —— 年报要跑 12 个月,
    实测直接把它顶到 2 秒。现在只建一次,往下传。
    """
    rows = sorted(
        [r for r in readings if r.get("date") and row_has_any_value(r, tables)],
        key=lambda r: r["date"],
    )
    # dates 单独留一份:按「日期不在抄表日」定位区间时要用二分,
    # 不能在每笔充值的每次调用里现造这个 list(那也是 O(R))。
    return rows, {r["date"]: i for i, r in enumerate(rows)}, [r["date"] for r in rows]


def _attributed_segment(rows: list, key: str, cdate: str,
                        date_index: dict | None = None, dates: list | None = None):
    """这笔充值会被归属到哪个区间 —— 归属口径与一致性校验的唯一事实来源。

    逐表独立判断(每笔只归属一次;L = 实际到账日):
      1. L 当天正好抄了表,且表底相对上一次**上升** → 归属"上一次 → 这一次" → (i-1, i)
      2. L 当天抄了表但没上升 → 归属"终点晚于 L 的第一个区间" → (i, i+1)
      3. L 落在两条读数正中间(当天没抄表) → 归属该区间 → (prev, next)
      4. L 之后还没有任何抄表 → 不归属任何区间 → None

    返回 (start_idx, end_idx);None = 不归属。
    """
    if date_index is None:
        date_index = {r["date"]: i for i, r in enumerate(rows)}
    if cdate in date_index:
        i = date_index[cdate]
        cur = row_values(rows[i], key)
        prev = row_values(rows[i - 1], key) if i >= 1 else None
        if i >= 1 and cur is not None and prev is not None and float(cur) > float(prev):
            return (i - 1, i)
        if i + 1 < len(rows):
            return (i, i + 1)
        return None
    # 当天没抄表:找「终点晚于 cdate 的第一个区间」。
    # rows 已按日期排序,二分即可(以前是线性扫描,O(R) / 笔 × 表)。
    if dates is None:
        dates = [r["date"] for r in rows]
    pos = bisect_left(dates, cdate)
    if pos >= 1 and pos < len(rows):
        return (pos - 1, pos)
    return None


def _landing_transition(rows: list, key: str, from_idx: int):
    """从 from_idx 起找第一个"表底上升"的读数区间 —— 充值真正进表的地方。

    返回 (start_idx, end_idx);None = 后面的读数里表底再没跳过(钱始终没进表)。
    """
    for j in range(from_idx, len(rows) - 1):
        a = row_values(rows[j], key)
        b = row_values(rows[j + 1], key)
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
    s_val = row_values(rows[si], key)
    e_val = row_values(rows[ei], key)
    if s_val is None or e_val is None:
        return (0.0, 0.0, True)
    days = _days_between(rows[si]["date"], rows[ei]["date"])
    if days <= 0:
        return (0.0, 0.0, True)
    implied = (float(s_val) + amt - float(e_val)) * mult
    threshold = max(cap * days * CHARGE_CONFLICT_FACTOR, CHARGE_CONFLICT_FLOOR_KWH)
    return (implied, threshold, implied <= threshold)


def _resolve_charge(rows: list, key: str, cdate: str, amt: float, mult: float, cap: float,
                    date_index: dict | None = None, dates: list | None = None):
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
    seg = _attributed_segment(rows, key, cdate, date_index=date_index, dates=dates)
    if seg is None:
        return (None, None)
    si, ei = seg
    s_val = row_values(rows[si], key)
    e_val = row_values(rows[ei], key)
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
        a = row_values(rows[i], key)
        b = row_values(rows[i + 1], key)
        if a is None or b is None:
            continue
        days = _days_between(rows[i]["date"], rows[i + 1]["date"])
        if days <= 0:
            continue
        d = (float(a) - float(b)) * mult
        if d > 0 and d / days > best:
            best = d / days
    return best


def find_pasted_reading_charges(readings: list, charges: list,
                                tables: list | None = None) -> list:
    """找出「充值额和当天抄表读数一模一样」的记录 —— 八成是把抄表读数填进了充值栏。

    几乎零误报:充值额恰好等于当前表底,意味着充完钱表底要翻倍;而这类表一天只用
    几个表字,不可能当天把一整份余额用光。真出现这种巧合,表底必然是跳升的(钱已经
    进表、抄表已体现),所以**只在"当天表底没上升"时**才判定为填错。

    返回 [{charge_id, date, meter, label, amount, reading, reason}]
    """
    tables = _tables_of(tables)
    rows, date_index, dates = _prepare(readings, tables)
    if not rows:
        return []
    out: list = []

    for t in tables:
        key, label = t["key"], t["label"]
        for c in charges:
            if c.get("status", "confirmed") == "pending":
                continue
            try:
                amt = float(row_values(c, key) or 0)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            cdate = _landing_date(c)
            if cdate not in date_index:
                continue
            i = date_index[cdate]
            cur = row_values(rows[i], key)
            prev = row_values(rows[i - 1], key) if i >= 1 else None
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


def _analyze_charges(rows: list, date_index: dict, dates: list, charges: list,
                     tables: list, skip: set | None = None):
    """一笔一遍地算出「与抄表对不上的充值」和「每笔充值归属哪个区间」。

    返回 (attribution, conflicts)。

    ⚠️ 为什么合在一起:这两件事的判据**完全相同** —— 都是对
    (充值 × 表) 调一次 `_resolve_charge`。以前拆成 `find_charge_conflicts()`
    和 `_charge_attribution()` 两个函数各自跑一遍同样的循环,于是这个最贵的
    内核被算了两遍(实测 27.9ms + 28.7ms @1100 行/160 笔,月报一半时间耗在这)。
    合成一遍之后两个公开函数都变成薄包装,判据只有一处 —— 不会出现
    「冲突判定改了、归属没改」这种漂移。

    口径与拆开时逐字一致:
    - conflicts 的输出顺序 = 表外层、充值内层(与改造前相同);
    - 归属累加顺序对同一个 (区间, 表) 而言仍是充值顺序,浮点结果不变;
    - `skip` 里命中的 (充值 id, 表 key) 不计入归属(月报用它剔除对不上的充值)。
    """
    caps = {t["key"]: _daily_cap_kwh(rows, t["key"], t["mult"]) for t in tables}
    attribution: dict = {}
    conflicts: list = []

    for t in tables:
        key, mult, label = t["key"], t["mult"], t["label"]
        cap = caps[key]
        for c in charges:
            if c.get("status", "confirmed") == "pending":
                continue  # 待确认的充值申请不计入任何统计
            try:
                amt = float(row_values(c, key) or 0)
            except (TypeError, ValueError):
                continue
            if amt == 0:
                continue
            cdate = _landing_date(c)
            seg, conflict = _resolve_charge(rows, key, cdate, amt, mult, cap,
                                            date_index=date_index, dates=dates)

            # ⚠️ 只有**正额**充值才进冲突清单:改造前 find_charge_conflicts 用
            #    `amt <= 0` 跳过,而归属侧用 `amt == 0` 跳过(负数会真的减掉)。
            #    两个口径不一样,合并扫描时必须分开表达,否则退款类记录会凭空多出
            #    一条"与抄表对不上"的告警。
            if conflict is not None and amt > 0:
                implied = conflict["implied_kwh"]
                threshold = conflict["threshold_kwh"]
                s_val = conflict["start_val"]
                e_val = conflict["end_val"]
                # 充值额和当天抄表读数一模一样 → 八成是把抄表读数填进了充值栏
                landing_val = (row_values(rows[date_index[cdate]], key)
                               if cdate in date_index else None)
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
                continue  # 与抄表对不上 → 不计入用电量

            if seg is None:
                continue  # 到账日之后还没有任何抄表 → 暂不归属
            if skip and (c.get("id"), key) in skip:
                continue
            pair = (rows[seg[0]]["date"], rows[seg[1]]["date"])
            slot = attribution.setdefault(pair, {})
            slot[key] = slot.get(key, 0.0) + amt

    return attribution, conflicts


def find_charge_conflicts(readings: list, charges: list,
                          tables: list | None = None,
                          _prepared: tuple[list, dict, list] | None = None) -> list:
    """找出与抄表对不上的充值记录 —— 多半是把抄表读数填进了充值栏。

    预付费表的物理事实:表底下降 = 用电,表底上升 = 刚到账。一笔 X 表字的充值如果
    真的到账了,它被归属的那个区间里表底必然"净升";否则该区间需要出现
    (表底差 + X) 的用电量 —— 一旦这个数离谱(超过该表历史日均的 3 倍),就说明
    这笔钱根本没进表,记录本身是错的。

    实测事故:2026-11-11 有人把当天抄表读数(205.7 / 1706.5 / 197.6 / 138.9)填进
    了充值栏,系统照单全收,大厅凭空多出 205.7 × 160 = 32912 度,一天总用电被顶到
    89588.8 度(真实 1130.3 度),月报被顶到 102700.7 度(真实 14242.2 度)。

    返回 [{charge_id, date, meter, label, amount, implied_kwh, threshold_kwh, reason}]

    实现见 `_analyze_charges`(与归属共用一遍扫描)。
    """
    tables = _tables_of(tables)
    rows, date_index, dates = (_prepared if _prepared is not None
                               else _prepare(readings, tables))
    if len(rows) < 2:
        return []
    _attribution, conflicts = _analyze_charges(rows, date_index, dates,
                                              charges, tables)
    return conflicts


def _charge_attribution(readings: list, charges: list, skip: set | None = None,
                        tables: list | None = None,
                        _prepared: tuple[list, dict, list] | None = None) -> dict:
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

    实现见 `_analyze_charges`(与冲突判定共用一遍扫描)。
    """
    tables = _tables_of(tables)
    rows, date_index, dates = (_prepared if _prepared is not None
                               else _prepare(readings, tables))
    attribution, _conflicts = _analyze_charges(rows, date_index, dates,
                                               charges, tables, skip=skip)
    return attribution


def _monthly_core(rows: list, date_index: dict, charges: list, month: str,
                  tables: list, unit_price: float,
                  attribution: dict, conflicts: list) -> dict:
    """月报计算主体(**不碰缓存**)。

    与 `calculate_monthly_report` 分开是为了年报:12 个月共享同一份
    「已排序读数 / 冲突清单 / 充值归属」,不必每个月从头再算一遍
    (那是原来年报 2 秒的根因)。

    `rows` 已是过滤+排序后的抄表行,`date_index` 是 date → 下标。
    """
    year, mon = int(month[:4]), int(month[5:7])
    _, days_in_month = monthrange(year, mon)

    dates = [r["date"] for r in rows]
    month_prefix_end = (f"{year + 1:04d}-01-01" if mon == 12
                        else f"{year:04d}-{mon + 1:02d}-01")
    lo = bisect_left(dates, f"{month}-01")
    hi = bisect_left(dates, month_prefix_end)
    month_readings = rows[lo:hi]           # 当月抄表(已按日期排序)

    # 上月最后一次抄表(本月第一段"前段")/ 下月第一次抄表(本月末段"末段")
    prev_reading = rows[lo - 1] if lo >= 1 else None
    next_reading = rows[hi] if hi < len(rows) else None

    # 构造 (X, Y) 配对
    pairs = []
    if prev_reading and month_readings:
        pairs.append((prev_reading, month_readings[0]))
    for i in range(len(month_readings) - 1):
        pairs.append((month_readings[i], month_readings[i + 1]))
    if month_readings and next_reading:
        pairs.append((month_readings[-1], next_reading))

    month_start_dt = datetime(year, mon, 1)
    month_next_dt = month_start_dt + timedelta(days=days_in_month)

    daily_avg_by_date = {}
    month_total_kwh = 0.0
    sum_by_meter = {t["key"]: 0.0 for t in tables}

    for X, Y in pairs:
        X_dt = datetime.strptime(X["date"], "%Y-%m-%d")
        Y_dt = datetime.strptime(Y["date"], "%Y-%m-%d")
        span = (Y_dt - X_dt).days
        if span <= 0:
            continue

        credited = attribution.get((X["date"], Y["date"]), {})

        usage = {}
        for t in tables:
            X_val = float(row_values(X, t["key"]) or 0)
            Y_val = float(row_values(Y, t["key"]) or 0)
            charge_sum = credited.get(t["key"], 0.0)
            u = (X_val - Y_val + charge_sum) * t["mult"]
            usage[t["key"]] = round(max(u, 0), 1)

        avg = {t["key"]: round(usage[t["key"]] / span, 1) for t in tables}
        d = X_dt
        while d < Y_dt:
            if d >= month_start_dt and d < month_next_dt:
                daily_avg_by_date[d.strftime("%Y-%m-%d")] = avg
            d += timedelta(days=1)

        # 这段只属于当月的天数 = 区间 ∩ 本月。
        # ⚠️ 以前是「每天 strptime 一遍再逐条比对」的 O(区间天数²) 扫描,
        #    区间互不重叠(相邻配对首尾相接),所以在区间与月份的交集上直接相减即可。
        seg_days_in_month = max(
            0, (min(Y_dt, month_next_dt) - max(X_dt, month_start_dt)).days)
        if seg_days_in_month:
            # ⚠️ 累加顺序必须与改造前**逐字一致**:先按表求和再加总,
            #    否则浮点加法顺序变了,末位会差 —— 月报 round(...,1) 看不出来,
            #    但年报 total_cost = round(kwh*price,2) 会差一分钱。
            month_total_kwh += sum(
                usage[t["key"]] * seg_days_in_month / span for t in tables)
            for t in tables:
                sum_by_meter[t["key"]] += usage[t["key"]] * seg_days_in_month / span

    reading_dates = {r["date"] for r in month_readings}
    days = []
    for day in range(1, days_in_month + 1):
        d_str = f"{month}-{day:02d}"
        # ⚠️ 键顺序 = date → 各表(按表定义顺序) → total → is_reading_day。
        # 默认 4 表时与改造前逐字节一致(缓存/快照/前端都依赖这个形状)。
        entry: dict = {"date": d_str}
        if d_str in daily_avg_by_date:
            avg = daily_avg_by_date[d_str]
            for t in tables:
                entry[t["key"]] = avg.get(t["key"], 0.0)
            entry["total"] = round(sum(avg.values()), 1)
            entry["is_reading_day"] = d_str in reading_dates
        else:
            for t in tables:
                entry[t["key"]] = 0
            entry["total"] = 0
            entry["is_reading_day"] = False
        days.append(entry)

    return {
        "month": month,
        "days": days,
        "summary": {
            "total_kwh": round(month_total_kwh, 1),
            "total_cost": round(month_total_kwh * unit_price, 2),
            "by_meter": {t["key"]: round(sum_by_meter[t["key"]], 1) for t in tables},
            "reading_days": sum(1 for d in days if d["is_reading_day"]),
            "price": unit_price,
        },
        # 与抄表对不上的充值(界面用来提示"有一条充值记录填错了")
        "conflicts": conflicts,
    }


def _attribution_inputs(readings: list, charges: list, tables: list,
                        prepared: tuple[list, dict, list] | None = None):
    """一次算好「冲突清单 + 充值归属」—— 月报与年报共用同一份输入。

    这两步是整条计算链里最贵的(find_charge_conflicts ≈ 113ms、_charge_attribution
    ≈ 115ms @1100 行/157 笔),以前**每个月都各算一遍**:年报 12 个月 = 算了 12 次
    同样的东西。
    """
    prepared3 = prepared if prepared is not None else _prepare(readings, tables)
    rows, date_index, dates = prepared3
    # ⚠️ 必须直接调 _analyze_charges(一遍扫描同时出冲突与归属),
    #    不能调上面那两个公开包装 —— 它们各自都会跑一遍完整扫描,
    #    等于把最贵的内核白算两遍(这正是改造前月报一半耗时的来源)。
    attribution, conflicts = _analyze_charges(rows, date_index, dates, charges, tables)
    return rows, date_index, conflicts, attribution


def calculate_monthly_report(readings: list, charges: list, month: str,
                             tables: list | None = None,
                             price: float | None = None) -> dict:
    """计算指定月份的逐日逐表用电度数。

    带内存缓存（5 分钟 TTL）：相同月份和数据的请求直接返回缓存。

    `tables` 是**当前门店**的表定义(不传 = 默认 4 表)。`price` 是该店电价
    (不传 = constants.ELECTRICITY_PRICE)。两者都进缓存键 —— 同店同月换了表
    集合必须重新算,否则 2 表门店会看到 4 表的数字。
    """
    tables = _tables_of(tables)
    unit_price = PRICE if price is None else price
    # 尝试缓存(键带门店维度 + 表集合签名 —— 不同门店/不同表集合互不命中)
    cache_key = _report_cache_key(month, tables)
    cached = _get_cached_report(cache_key)
    if cached is not None:
        return cached

    rows, date_index, conflicts, attribution = _attribution_inputs(readings, charges, tables)
    result = _monthly_core(rows, date_index, charges, month, tables,
                           unit_price, attribution, conflicts)
    _cache_report(cache_key, result)
    return result


def calculate_yearly_report(readings: list, charges: list, year: str,
                            tables: list | None = None,
                            price: float | None = None) -> dict:
    """计算指定年份的月度汇总(12 个月)。

    带内存缓存（5 分钟 TTL）。

    ⚠️ 这里**不再**调 12 次 `calculate_monthly_report`:那样会把
    「排序读数 + 找冲突 + 归属充值」各重算 12 遍(实测 2 秒,点一次年度报表
    就独占 GIL 两秒)。现在准备一次、算 12 次便宜的那部分。
    副作用:不再顺带填充各月缓存 —— 月报页面自己会算,不影响结果。
    """
    tables = _tables_of(tables)
    cache_key = _report_cache_key(f"yearly:{year}", tables)
    cached = _get_cached_report(cache_key)
    if cached is not None:
        return cached

    unit_price = PRICE if price is None else price
    rows, date_index, conflicts, attribution = _attribution_inputs(readings, charges, tables)

    months = []
    year_total_kwh = 0.0
    year_total_cost = 0.0

    for m in range(1, 13):
        month_str = f"{year}-{m:02d}"
        r = _monthly_core(rows, date_index, charges, month_str, tables,
                          unit_price, attribution, conflicts)
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

# { cache_key: (cache_time, report_data) },cache_key = f"{store_id}:{month}"
_report_cache: dict = {}
_report_cache_lock = RLock()
_REPORT_CACHE_TTL = 5 * 60  # 5 分钟


def _tables_signature(tables: list) -> str:
    """表集合签名 —— 参与缓存键,防止「同店同月、不同表集合」互相命中。

    key 里不能出现冒号(缓存统计靠冒号拆 store / month),而表 key 按规则不含冒号、
    倍率是整数,所以 `key_倍率` 直接连起来就够,而且可读、可直接在缓存统计里看出来。
    """
    return "-".join(f'{t["key"]}_{t["mult"]}' for t in tables)


def _report_cache_key(key: str, tables: list | None = None) -> str:
    """报表缓存键加门店维度 + 表集合签名。

    缓存原本只按月份做键 —— 多门店上线后,总店先请求的月报会被分店同月份
    的请求直接命中,拿到**总店的用电数字**(跨店数据泄漏)。
    键改成 f"{store_id}:{key}",不同门店互不干扰。

    P2 又把表定义变成了参数:同一家店同一个月份,4 表和 2 表算出来的 by_meter
    形状与数字都不同,只按 store+month 做键会让第二次调用直接拿第一次的结果。
    所以签名一并进键。

    延迟 import:report.py 已被 modules/reports/handler.py 引入,
    不在模块级引入 modules.stores 以免循环依赖。
    """
    from modules.stores.context import get_current_store
    return f"{get_current_store()}:{key}:{_tables_signature(_tables_of(tables))}"


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
        for cache_key, (cache_time, data) in _report_cache.items():
            age = now - cache_time
            # 键是 f"{store_id}:{month}:{表集合签名}" —— 首段 store、末段签名,
            # 中间全部属于 month(年报的 month 本身是 "yearly:2026",自带冒号,
            # 所以不能用 partition,必须取「首段 + 中间段」)
            parts = cache_key.split(":")
            store_id = parts[0]
            month = ":".join(parts[1:-1])
            entries.append({
                "store": store_id,
                "month": month,
                "age_seconds": round(age, 0),
                "ttl_minutes": _REPORT_CACHE_TTL // 60,
                "valid": age <= _REPORT_CACHE_TTL,
            })
        return {"size": len(entries), "ttl_minutes": _REPORT_CACHE_TTL // 60, "entries": entries}


# Public API
invalidate_report_cache = _invalidate_report_cache
get_report_cache_stats = _get_report_cache_stats
