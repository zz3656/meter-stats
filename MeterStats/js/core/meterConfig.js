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

/** 计算两个日期之间的充值度数总和 */
function sumChargesBetween(charges, meterKey, startDate, endDate) {
  if (!charges) return 0;
  let sum = 0;
  for (const c of charges) {
    if (c.date > startDate && c.date <= endDate) {
      sum += realKwh(c[meterKey] || 0, meterKey);
    }
  }
  return sum;
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