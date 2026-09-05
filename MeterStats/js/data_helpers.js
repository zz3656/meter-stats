// 简化:删除/标记后只重拉 items+purchases
async function refreshAll() {
  await fetchItems();
  await fetchPurchases();
  renderItemTable(CURRENT_ITEMS);
  renderLendHistory(CURRENT_ITEMS);
  renderPurchaseTable(CURRENT_PURCHASES);
}

// 充值预警 — 4 块表都做
window.ELECTRICITY_PRICE = 0.9; // 元/度
window.CHARGE_METERS = [
  { key: 'hall', label: '大厅', icon: '🎤', meterNo: '1#' },
  { key: 'fire', label: '消防', icon: '🧯', meterNo: '2#' },
  { key: 'private_room', label: '包厢', icon: '🛋️', meterNo: '3#' },
  { key: 'ac', label: '空调', icon: '❄️', meterNo: '4#' },
];

/**
 * 计算每块表的月均日耗电。
 *
 * 公式:对于抄表区间 [A, B]:
 *   实际用电度数 = (A.表底 - B.表底) + (这段期间内的充值度数之和)
 *   日均 = 实际用电度数 / 天数
 * 然后把一个月内所有相邻抄表对的日均加权平均,得到月日均。
 *
 * 优先级:
 *   1) 当月(用所有抄表对算)
 *   2) 上一个完整月
 *   3) 最近一次抄表对(兜底)
 *
 * 返回 { [meterKey]: { daily, basis, basisLabel, monthlyTotal?, monthDays? } | null }
 */
window.calcMonthlyDailyUsage = function calcMonthlyDailyUsage(readings, charges, meterKey) {
  if (!readings || readings.length === 0) return null;

  // 按月份分组
  const byMonth = {};
  readings.forEach(r => {
    const m = r.date.slice(0, 7);
    (byMonth[m] = byMonth[m] || []).push(r);
  });
  const sortedMonths = Object.keys(byMonth).sort();
  const currentMonth = sortedMonths[sortedMonths.length - 1];
  const prevMonth = sortedMonths.length >= 2 ? sortedMonths[sortedMonths.length - 2] : null;

  // 1) 当月
  let chosen = calcMonthDailyUsage(byMonth[currentMonth] || [], charges, meterKey, currentMonth);
  // 2) 上月
  if (!chosen && prevMonth) {
    chosen = calcMonthDailyUsage(byMonth[prevMonth] || [], charges, meterKey, prevMonth);
  }
  // 3) 兜底:最近一次抄表对
  if (!chosen && readings.length >= 2) {
    const a = readings[readings.length - 2];
    const b = readings[readings.length - 1];
    const days = (new Date(b.date) - new Date(a.date)) / 86400000;
    if (days > 0) {
      const charged = sumChargesBetween(charges, meterKey, a.date, b.date);
      const used = (a[meterKey] - b[meterKey]) * MULTIPLIER(meterKey) + charged;
      if (used > 0) {
        chosen = {
          daily: used / days,
          basis: 'last-interval',
          basisLabel: `${a.date} → ${b.date} (${days.toFixed(1)} 天,含 ${charged.toFixed(0)} 度充值)`,
        };
      }
    }
  }
  return chosen;
}

/**
 * 计算一组抄表(同一月)内某块表的日均用电。
 * 遍历相邻抄表对,每对用 "表底差 + 期间充值" 算日均,再加权平均。
 */
window.calcMonthDailyUsage = function calcMonthDailyUsage(rows, charges, meterKey, monthLabel) {
  if (!rows || rows.length < 2) return null;

  // 必须 ≥ 2 条记录,且按日期排序
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));

  let totalUsed = 0;
  let totalDays = 0;
  let segments = 0;

  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1];
    const b = sorted[i];
    const days = (new Date(b.date) - new Date(a.date)) / 86400000;
    if (days <= 0) continue;

    // 表底差(度数,考虑倍率)
    const readingDelta = (a[meterKey] - b[meterKey]) * MULTIPLIER(meterKey);
    // 这段时间内的充值度数(用户单独录入的)
    const charged = sumChargesBetween(charges, meterKey, a.date, b.date);
    // 实际用电 = 表底差 + 期间充值
    const used = readingDelta + charged;

    if (used > 0) {
      totalUsed += used;
      totalDays += days;
      segments++;
    }
  }

  if (totalDays <= 0 || segments === 0) return null;

  // 总充值度数(用于提示)
  const monthStart = sorted[0].date;
  const monthEnd = sorted[sorted.length - 1].date;
  const totalCharged = sumChargesBetween(charges, meterKey, monthStart, monthEnd);

  const hasCharge = totalCharged > 0;
  const basisLabel = hasCharge
    ? `${monthLabel} (${totalDays.toFixed(1)} 天,含 ${totalCharged.toFixed(0)} 度充值)`
    : `${monthLabel} (${totalDays.toFixed(1)} 天)`;

  return {
    daily: totalUsed / totalDays,
    basis: hasCharge ? 'current-month-with-charge' : 'current-month',
    basisLabel,
    monthlyTotal: totalUsed,
    monthDays: totalDays,
  };
}

/**
 * 统计某段时间内某块表的充值度数(实际度数)。
 * "这段时间" = (start, end],即左开右闭 — 抄表当天的充值算到下一段。
 *
 * 用户填的充值度数 = 表度数(跟抄表读数同语义),
 * 必须 ×160 才是实际度数。1/3/4 表的 MULTIPLIER=160,消防=1。
 */
window.sumChargesBetween = function sumChargesBetween(charges, meterKey, startDate, endDate) {
  if (!charges) return 0;
  let sum = 0;
  for (const c of charges) {
    if (c.date > startDate && c.date <= endDate) {
      sum += realKwh(c[meterKey] || 0, meterKey);
    }
  }
  return sum;
}

// 余量预警 — 4 块表 1 列自适应卡,按剩余天数升序排(紧急在前)
// 本地时间日期工具(避免 toISOString 的 UTC 坑)
window.addDaysToDate = function addDaysToDate(dateStr, days) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + Math.ceil(days));
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}
window.daysBetween = function daysBetween(dateStrA, dateStrB) {
  const [y1, m1, d1] = dateStrA.split('-').map(Number);
  const [y2, m2, d2] = dateStrB.split('-').map(Number);
  return Math.round((new Date(y2, m2 - 1, d2) - new Date(y1, m1 - 1, d1)) / 86400000);
}