// ===== 元数据（从 /api/meters 动态获取，含 fallback 默认值）=====
window.METER_CONFIG = {
  hall:   { label: '大厅',   icon: '🎤', multiplier: 160, color: '#2563eb' },
  fire:   { label: '消防',   icon: '🧯', multiplier: 1,   color: '#dc2626' },
  private_room: { label: '包厢', icon: '🛋️', multiplier: 160, color: '#059669' },
  ac:     { label: '空调',   icon: '❄️', multiplier: 160, color: '#d97706' },
};

// ===== 电费单价（元/度）=====
// ⚠️ 必须挂在 window 上：readings.js / reports.js / admin.js 都直接引用裸标识符
// ELECTRICITY_PRICE。模块化重构时该常量丢失，导致 "ELECTRICITY_PRICE is not defined"。
// 后端 constants.py / settings.json 同名字段为权威值，loadMeterConfig() 会用
// /api/meters 返回的 config.electricity_price 覆盖这里（此处仅为不依赖后端时的兜底）。
window.ELECTRICITY_PRICE = 0.9;

// 快捷访问数组（保持顺序不变）
window.METER_KEYS = ['hall', 'fire', 'private_room', 'ac'];
window.METER_META = (key) => window.METER_CONFIG[key] || { label: key, icon: '', multiplier: 1, color: '#888' };
window.MULTIPLIER = (key) => window.METER_META(key).multiplier;
window.LABELS = (key) => window.METER_META(key).label;
window.COLORS = (key) => window.METER_META(key).color;

// 加载元数据（异步，不阻塞页面加载）
async function loadMeterConfig() {
  try {
    // ⚠️ 注意两点（重构后曾错配）：
    // 1. metersPublic 在 Api.admin 下，不是 Api.system
    // 2. _request 已经返回解析好的 JSON 对象，不能再 .json()
    const data = await Api.admin.metersPublic();
    if (data && data.meters) {
      for (const [key, val] of Object.entries(data.meters)) {
        METER_CONFIG[key] = { ...METER_CONFIG[key], ...val };
      }
    }
    // 电价/水价以后端设置为权威值
    if (data && data.config && typeof data.config.electricity_price === 'number') {
      window.ELECTRICITY_PRICE = data.config.electricity_price;
    }
    if (data && data.config && typeof data.config.water_price === 'number') {
      window.WATER_PRICE = data.config.water_price;
    }
  } catch (e) {
    // 静默失败，使用默认值
  }
}

// ===== 充值计算辅助函数 (从旧版 app.js 迁移) =====

/** 充值用表配置（按固定顺序） */
window.CHARGE_METERS = [
  { key: 'hall', label: '大厅', icon: '🎤', meterNo: '1#' },
  { key: 'fire', label: '消防', icon: '🧯', meterNo: '2#' },
  { key: 'private_room', label: '包厢', icon: '🛋️', meterNo: '3#' },
  { key: 'ac', label: '空调', icon: '❄️', meterNo: '4#' },
];

/** 实际度数 = 表底差 × 倍率 */
function realKwh(value, key) {
  return value * MULTIPLIER(key);
}

/** 充值**实际到账**的日期（与后端 report.py 的 _landing_date 同一规则）。
 *  已确认的取 confirmed_at 的日期（11-02 提申请、11-03 打款到账 → 11-03）；
 *  待确认、以及没有该字段的历史记录（status 为 null）退回记录日期。
 *  归月统计与充值归属都走这里，不要再直接读 c.date。 */
function chargeEffectiveDate(c) {
  if (c && c.status === 'confirmed' && c.confirmed_at) return String(c.confirmed_at).slice(0, 10);
  return (c && c.date) || '';
}

/** 充值归属：把每笔充值归到它**真正到账**的那个抄表区间（与后端 report.py 同一套规则）。
 *
 * 预付费表表底下降=用电、上升=刚到账。充值记录的 date 是当天算量提申请的日子，真正
 * 到账看 confirmed_at。旧口径 (起, 止] 无条件把"止日当天"的充值算进本区间，等于把刚充
 * 进去、一度还没用的余额当成已经用掉的电——大厅真实 656 度/天被算成 34256 度/天，
 * 建议充值 ¥113 万、还提示当天断电。
 *
 * 规则（逐表独立，每笔只归属一次；下面 L = 实际到账日）：
 *   1. L 当天正好抄表、且表底相对上一次**上升** → 归属"上一次 → 这一次"。
 *   2. L 当天抄了表但没上升（抄表在到账前，或当天就用光了）→ 归属"终点晚于 L 的第一个区间"。
 *   3. L 落在两条读数正中间（当天没抄表）→ 必然在这个区间到账，归属该区间。
 *   4. L 之后还没有任何抄表 → 钱还没进表底，暂不归入任何区间。
 */
let _chargeAttrCache = null;

/* ===== 充值与抄表的一致性校验 =====
 *
 * 预付费表的物理事实:表底下降 = 用电,表底上升 = 刚到账。一笔 X 表字的充值如果真的
 * 到账了,它被归属的那个区间里表底必然"净升";否则该区间的用电量 =(表底差 + X) 会
 * 离谱到不可能。
 *
 * 实测事故(2026-11-11):有人把当天抄表读数(205.7 / 1706.5 / 197.6 / 138.9)填进了
 * 充值栏,系统照单全收。大厅凭空多出 205.7 × 160 = 32912 度,一天总用电被顶到
 * 89588.8 度(真实 1130.3 度),月报被顶到 102700.7 度(真实 14242.2 度)。
 *
 * 规则必须与后端 report.find_charge_conflicts() 完全一致,两边都得改。
 */
const CHARGE_CONFLICT_FACTOR = 3;        // 允许"单区间用电"超出该表历史日均的倍数
const CHARGE_CONFLICT_FLOOR_KWH = 300;   // 阈值下限(度),给小表兜底

/** 两日之间隔了几天 */
function _chargeDaysBetween(d1, d2) {
  return Math.round((new Date(d2) - new Date(d1)) / 86400000);
}

/** 该表的历史"单日用电"上限(度/天)—— 原始表底差按区间天数摊平 */
function _chargeDailyCapKwh(rows, key) {
  const mult = MULTIPLIER(key);
  let best = 0;
  for (let i = 0; i < rows.length - 1; i++) {
    const days = _chargeDaysBetween(rows[i].date, rows[i + 1].date);
    if (days <= 0) continue;
    const d = (rows[i][key] - rows[i + 1][key]) * mult;
    if (d > 0 && d / days > best) best = d / days;
  }
  return best;
}

/** 这笔充值会被归属到哪个区间 —— 与 chargeAttribution() 用同一套分支 */
function _chargeSegment(rows, key, cdate) {
  const idx = rows.findIndex(r => r.date === cdate);
  if (idx >= 0) {
    const cur = rows[idx][key];
    const prev = idx >= 1 ? rows[idx - 1][key] : null;
    if (idx >= 1 && cur != null && prev != null && cur > prev) return [idx - 1, idx]; // 规则 1
    if (idx + 1 < rows.length) return [idx, idx + 1];                                   // 规则 2
    return null;                                                                       // 规则 4
  }
  let prevIdx = null;
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].date > cdate) return prevIdx !== null ? [prevIdx, i] : null;           // 规则 3
    prevIdx = i;
  }
  return null;
}

/** 从 fromIdx 起找第一个"表底上升"的读数区间 —— 充值真正进表的地方 */
function _chargeLandingTransition(rows, key, fromIdx) {
  for (let j = fromIdx; j < rows.length - 1; j++) {
    const a = rows[j][key], b = rows[j + 1][key];
    if (a == null || b == null) continue;
    if (b > a) return [j, j + 1];
  }
  return null;
}

/** 这个区间"若这笔钱真的到账",用电量是否还算合理 */
function _chargeSegmentPlausible(rows, key, seg, amt, mult, cap) {
  const s = rows[seg[0]], e = rows[seg[1]];
  if (s[key] == null || e[key] == null) return { implied: 0, threshold: 0, ok: true };
  const days = _chargeDaysBetween(s.date, e.date);
  if (days <= 0) return { implied: 0, threshold: 0, ok: true };
  const implied = (s[key] + amt - e[key]) * mult;
  const threshold = Math.max(cap * days * CHARGE_CONFLICT_FACTOR, CHARGE_CONFLICT_FLOOR_KWH);
  return { implied: implied, threshold: threshold, ok: implied <= threshold };
}

/**
 * 这笔充值最终归属哪个区间,以及它是否与抄表对不上。
 * 与后端 report._resolve_charge() 同一套规则,两边都得改。
 */
function _resolveCharge(rows, key, cdate, amt, mult, cap) {
  const seg = _chargeSegment(rows, key, cdate);
  if (!seg) return { seg: null, conflict: null };
  const s = rows[seg[0]], e = rows[seg[1]];
  if (s[key] == null || e[key] == null) return { seg: seg, conflict: null };
  if (e[key] > s[key]) return { seg: seg, conflict: null };   // 表底上升 → 钱进表了

  const p = _chargeSegmentPlausible(rows, key, seg, amt, mult, cap);
  if (p.ok) return { seg: seg, conflict: null };              // 用电量算得通 → 就是这个区间

  // 这个区间的用电量离谱 —— 钱多半是更晚才进表的,往后找表底真正跳升的区间
  const later = _chargeLandingTransition(rows, key, seg[1]);
  if (later) {
    const lp = _chargeSegmentPlausible(rows, key, later, amt, mult, cap);
    if (lp.ok && lp.implied >= 0) return { seg: later, conflict: null };
  }
  return {
    seg: null,
    conflict: {
      implied_kwh: Math.round(p.implied * 10) / 10,
      threshold_kwh: Math.round(p.threshold * 10) / 10,
      start_date: s.date, end_date: e.date,
      start_val: s[key], end_val: e[key],
    },
  };
}

/** 单块表的矛盾充值列表(内部用) */
function _chargeConflictsForMeter(rows, list, key) {
  if (rows.length < 2) return [];
  const meta = METER_META(key);
  const mult = MULTIPLIER(key);
  const cap = _chargeDailyCapKwh(rows, key);
  const out = [];
  for (const c of list) {
    if (c.status === 'pending') continue;
    const amt = Number(c[key] || 0);
    if (!(amt > 0)) continue;
    const d = chargeEffectiveDate(c);
    const r = _resolveCharge(rows, key, d, amt, mult, cap);
    if (!r.conflict) continue;
    const implied = r.conflict.implied_kwh;
    const threshold = r.conflict.threshold_kwh;
    const landingRow = rows.find(r2 => r2.date === d);
    const sameAsReading = landingRow && Math.abs(amt - Number(landingRow[key])) < 0.01;
    const reason = sameAsReading
      ? `${meta.label} ${d} 的充值额 ${amt} 和当天抄表读数一模一样 —— 是不是把抄表读数填进充值栏了?`
        + `充值额应该是**新充进去的表字数**,不是当前表底。这笔记录已从所有用电统计中排除。`
      : `${meta.label} ${d} 的充值额 ${amt} 表字与抄表对不上:表底 ${r.conflict.start_val} → ${r.conflict.end_val} 没有上升,`
        + `若这笔钱真的到账,${r.conflict.start_date}→${r.conflict.end_date} 得用掉 ${Math.round(implied)} 度`
        + `(历史日均 ${Math.round(cap)} 度/天),钱没有进表。这笔记录已从所有用电统计中排除。`;
    out.push({
      charge_id: c.id, date: d, meter: key, label: meta.label, amount: amt,
      implied_kwh: implied, threshold_kwh: threshold, reason: reason,
    });
  }
  return out;
}

/** 「充值额 = 当天抄表读数」的记录 —— 八成是把抄表读数填进了充值栏 */
function findPastedReadingCharges(charges) {
  const list = charges || [];
  const out = [];
  for (const m of CHARGE_METERS) {
    const key = m.key;
    const meta = METER_META(key);
    const rows = (window.CURRENT_READINGS || [])
      .filter(r => r && r.date && r[key] != null)
      .slice().sort((a, b) => a.date.localeCompare(b.date));
    for (const c of list) {
      if (c.status === 'pending') continue;
      const amt = Number(c[key] || 0);
      if (!(amt > 0)) continue;
      const d = chargeEffectiveDate(c);
      const i = rows.findIndex(r => r.date === d);
      if (i < 0) continue;
      const cur = rows[i][key];
      const prev = i >= 1 ? rows[i - 1][key] : null;
      if (cur == null || prev == null) continue;
      if (cur > prev) continue;               // 当天表底跳升 → 钱已进表,读数里已体现
      if (Math.abs(amt - Number(cur)) >= 0.01) continue;
      out.push({
        charge_id: c.id, date: d, meter: key, label: meta.label,
        amount: amt, reading: Number(cur),
        reason: `${meta.label} ${d} 的充值额 ${amt} 和当天抄表读数一模一样 —— `
          + `是不是把抄表读数填进充值栏了?充值额应该是**新充进去的表字数**,`
          + `不是当前表底(充完表底会翻倍)。`,
      });
    }
  }
  return out;
}

/** 与抄表对不上的充值(全表)—— 界面用来提示"有条充值记录填错了" */
function findChargeConflicts(charges) {
  const list = charges || [];
  const out = [];
  for (const m of CHARGE_METERS) {
    const rows = (window.CURRENT_READINGS || [])
      .filter(r => r && r.date && r[m.key] != null)
      .slice().sort((a, b) => a.date.localeCompare(b.date));
    out.push.apply(out, _chargeConflictsForMeter(rows, list, m.key));
  }
  return out;
}

function _chargeAttrSignature(rows, charges, key) {
  let s = key + '|' + rows.length + '|' + charges.length;
  for (let i = 0; i < charges.length; i++) s += '|' + chargeEffectiveDate(charges[i]) + ':' + (charges[i][key] || 0);
  if (rows.length) s += '|' + rows[0].date + '~' + rows[rows.length - 1].date;
  return s;
}

function chargeAttribution(charges, key) {
  const all = (window.CURRENT_READINGS || []).filter(r => r && r.date && r[key] != null);
  const rows = all.slice().sort((a, b) => a.date.localeCompare(b.date));
  const list = charges || [];
  if (!rows.length) return null;

  const sig = _chargeAttrSignature(rows, list, key);
  if (_chargeAttrCache && _chargeAttrCache.sig === sig) return _chargeAttrCache.map;

  const map = [];  // [{start, end, meterVal}]
  const cap = _chargeDailyCapKwh(rows, key);

  const add = (start, end, amt) => {
    const hit = map.find(m => m.start === start && m.end === end);
    if (hit) hit.meterVal += amt; else map.push({ start, end, meterVal: amt });
  };

  for (const c of list) {
    if (c.status === 'pending') continue;   // 待确认的充值申请不计入统计
    const amt = Number(c[key] || 0);
    if (!amt) continue;
    const d = chargeEffectiveDate(c);       // 实际到账日，不是申请日

    // _resolveCharge 会把"钱晚点才进表"的充值改归属到表底真正跳升的那一段,
    // 把与抄表对不上的记录剔掉(seg=null) —— 与后端 report._resolve_charge 同一套规则
    const r = _resolveCharge(rows, key, d, amt, MULTIPLIER(key), cap);
    if (!r.seg) continue;
    add(rows[r.seg[0]].date, rows[r.seg[1]].date, amt);
  }

  _chargeAttrCache = { sig, map };
  return map;
}

/** 统计已反映进 [startDate, endDate] 区间的充值度数(待确认的充值申请不计入) */
function sumChargesBetween(charges, meterKey, startDate, endDate) {
  if (!charges) return 0;
  const map = chargeAttribution(charges, meterKey);

  if (map) {
    let sum = 0;
    for (const m of map) {
      if (m.start >= startDate && m.end <= endDate) sum += m.meterVal * MULTIPLIER(meterKey);
    }
    return sum;
  }

  // 兜底：没有抄表序列可判断跳变时，退回旧的 (起, 止] 日期窗口
  let sum = 0;
  for (const c of charges) {
    if (c.status === 'pending') continue;
    if (c.date > startDate && c.date <= endDate) sum += realKwh(c[meterKey] || 0, meterKey);
  }
  return sum;
}

/** 当前表显余量 = 最新抄表读数 + 已到账但还没反映进读数的充值（表字）。
 *
 * 预付费表的钱一旦打进来，表上余额立刻就是真的，但我们**每天只抄一次表**——今天到账
 * 的充值要等下次抄表才会出现在读数里。若余量只取最新读数，就会出现「钱明明充进去了，
 * 预警却显示只剩 4336 度、预计今天断电」的错误。
 *
 * 口径与 chargeAttribution() 同源，保证补录抄表后不会重复计算：
 *   候选 = 实际到账日 >= 最新抄表日 的已确认充值；
 *   再减去其中已归属到「以最新读数为终点」那个区间的部分（说明那次抄表已经体现它了）。
 *
 * 返回 { meterVal, kwh, readingMeterVal, readingDate, extraMeterVal, extraKwh, hasReading } */
function unreflectedCreditMeterVal(charges, key) {
  const list = charges || [];
  const rows = (window.CURRENT_READINGS || [])
    .filter(r => r && r.date && r[key] != null)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (!rows.length) return 0;
  const lastDate = rows[rows.length - 1].date;

  let candidate = 0;
  // 与抄表对不上的充值(钱根本没进表)不能算进余量,否则建议充值金额会被顶飞
  const skipIds = new Set(_chargeConflictsForMeter(rows, list, key).map(c => c.charge_id));
  for (const c of list) {
    if (c.status === 'pending') continue;          // 待确认的充值申请不计入任何统计
    if (skipIds.has(c.id)) continue;               // 钱没进表,不算余量
    if (chargeEffectiveDate(c) >= lastDate) candidate += Number(c[key] || 0);
  }

  // 最新那次抄表若已把这笔充值抄进读数（归属到以它为终点的区间），就不能再加第二次
  const map = chargeAttribution(list, key);
  let alreadyIn = 0;
  if (map) for (const m of map) { if (m.end === lastDate) alreadyIn += m.meterVal; }

  return Math.max(0, candidate - alreadyIn);
}

function remainingBalance(charges, key) {
  const rows = (window.CURRENT_READINGS || [])
    .filter(r => r && r.date && r[key] != null)
    .sort((a, b) => a.date.localeCompare(b.date));
  const mult = MULTIPLIER(key);
  const extraMeter = unreflectedCreditMeterVal(charges, key);
  if (!rows.length) {
    return { meterVal: null, kwh: null, readingMeterVal: null, readingDate: '',
             extraMeterVal: extraMeter, extraKwh: extraMeter * mult, hasReading: false };
  }
  const latest = rows[rows.length - 1];
  const meterVal = latest[key] + extraMeter;
  return {
    meterVal: meterVal,
    kwh: meterVal * mult,
    readingMeterVal: latest[key],
    readingDate: latest.date,
    extraMeterVal: extraMeter,
    extraKwh: extraMeter * mult,
    hasReading: true,
  };
}

/** 计算每块表的月均日耗电 */
function calcMonthlyDailyUsage(readings, charges, meterKey) {
  if (!readings || readings.length === 0) return null;

  // 按月份分组
  const byMonth = {};
  readings.forEach(function(r) {
    var m = r.date.slice(0, 7);
    (byMonth[m] = byMonth[m] || []).push(r);
  });
  var sortedMonths = Object.keys(byMonth).sort();
  var currentMonth = sortedMonths[sortedMonths.length - 1];
  var prevMonth = sortedMonths.length >= 2 ? sortedMonths[sortedMonths.length - 2] : null;

  // 1) 当月
  var chosen = calcMonthDailyUsage(byMonth[currentMonth] || [], charges, meterKey, currentMonth);
  // 2) 上月
  if (!chosen && prevMonth) {
    chosen = calcMonthDailyUsage(byMonth[prevMonth] || [], charges, meterKey, prevMonth);
  }
  // 3) 兜底:最近一次抄表对
  if (!chosen && readings.length >= 2) {
    var a = readings[readings.length - 2];
    var b = readings[readings.length - 1];
    var days = (new Date(b.date) - new Date(a.date)) / 86400000;
    if (days > 0) {
      var charged = sumChargesBetween(charges, meterKey, a.date, b.date);
      var used = (a[meterKey] - b[meterKey]) * MULTIPLIER(meterKey) + charged;
      if (used > 0) {
        chosen = {
          daily: used / days,
          basis: 'last-interval',
          basisLabel: a.date + ' → ' + b.date + ' (' + days.toFixed(1) + ' 天,含 ' + charged.toFixed(0) + ' 度充值)',
        };
      }
    }
  }
  return chosen;
}

/** 计算单月内的日均耗电 */
function calcMonthDailyUsage(rows, charges, meterKey, monthLabel) {
  if (!rows || rows.length < 2) return null;

  var sorted = rows.slice().sort(function(a, b) { return a.date.localeCompare(b.date); });

  var totalUsed = 0;
  var totalDays = 0;
  var segments = 0;

  for (var i = 1; i < sorted.length; i++) {
    var a = sorted[i - 1];
    var b = sorted[i];
    var days = (new Date(b.date) - new Date(a.date)) / 86400000;
    if (days <= 0) continue;

    var readingDelta = (a[meterKey] - b[meterKey]) * MULTIPLIER(meterKey);
    var charged = sumChargesBetween(charges, meterKey, a.date, b.date);
    var used = readingDelta + charged;

    if (used > 0) {
      totalUsed += used;
      totalDays += days;
      segments++;
    }
  }

  if (totalDays <= 0 || segments === 0) return null;

  var monthStart = sorted[0].date;
  var monthEnd = sorted[sorted.length - 1].date;
  var totalCharged = sumChargesBetween(charges, meterKey, monthStart, monthEnd);

  var hasCharge = totalCharged > 0;
  var basisLabel = hasCharge
    ? monthLabel + ' (' + totalDays.toFixed(1) + ' 天,含 ' + totalCharged.toFixed(0) + ' 度充值)'
    : monthLabel + ' (' + totalDays.toFixed(1) + ' 天)';

  return {
    daily: totalUsed / totalDays,
    basis: hasCharge ? 'current-month-with-charge' : 'current-month',
    basisLabel,
    monthlyTotal: totalUsed,
    monthDays: totalDays,
  };
}