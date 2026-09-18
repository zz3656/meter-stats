// ===== 每周汇报工具函数 =====
// 从 render_weekly.js 拆出,负责周/日期计算与用电统计。
// 依赖:无(纯算法,只用 utils_helpers.js 的 formatDate + window.realKwh/sumChargesBetween)。

/**
 * 获取从 A 到 B 之间(不含 A,含 B)的抄表记录,按日期排序
 * 用于计算特定时间段用电
 */
function _readingsBetween(readings, startExclusive, endInclusive) {
  if (!readings) return [];
  return readings
    .filter(r => r.date > startExclusive && r.date <= endInclusive && r.hall != null)
    .sort((a, b) => a.date.localeCompare(b.date));
}

/**
 * 计算某段时间内某块表的用电度数(表底差+充值,考虑倍率)
 * startExclusive: 开始日期(不包含)
 * endInclusive: 结束日期(包含)
 */
function calcPeriodUsage(readings, charges, meterKey, startExclusive, endInclusive) {
  const filtered = _readingsBetween(readings, startExclusive, endInclusive);
  if (filtered.length < 2) return { kwh: 0, chargeKwh: 0, segments: 0 };

  const sorted = filtered.sort((a, b) => a.date.localeCompare(b.date));
  let totalKwh = 0;
  let totalCharge = 0;
  let segments = 0;

  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1];
    const b = sorted[i];
    const delta = realKwh(a[meterKey] - b[meterKey], meterKey);
    const charged = sumChargesBetween(charges, meterKey, a.date, b.date);
    totalKwh += delta + charged;
    totalCharge += charged;
    segments++;
  }

  return { kwh: Math.max(totalKwh, 0), chargeKwh: totalCharge, segments };
}

/**
 * 计算某段时间的排练/编程次数
 */
function countTags(readings, startExclusive, endInclusive) {
  const filtered = _readingsBetween(readings, startExclusive, endInclusive);
  let rehearsal = 0;
  let programming = 0;
  filtered.forEach(r => {
    if (r.rehearsal) rehearsal++;
    if (r.programming) programming++;
  });
  return { rehearsal, programming };
}

/**
 * 计算两个日期之间的天数
 */
function daysInPeriod(start, end) {
  return Math.round((new Date(end) - new Date(start)) / 86400000);
}

/**
 * 生成 ISO 周标识 YYYY-Www
 */
function weekKey(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  // 设定为周一
  const dayOfWeek = d.getDay();
  const diffToMon = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
  const monday = new Date(d);
  monday.setDate(d.getDate() + diffToMon);
  const year = monday.getFullYear();
  const startOfYear = new Date(year, 0, 1);
  const dayOfYear = Math.floor((monday - startOfYear) / 86400000);
  const week = Math.ceil((dayOfYear + 1) / 7);
  return `${year}-W${String(week).padStart(2, '0')}`;
}

/**
 * 获取某 ISO 周的起始日(周一)和结束日(周日)
 */
function weekDateRange(weekStr) {
  const [year, week] = weekStr.split('-W').map(Number);
  const startOfYear = new Date(year, 0, 1);
  const mondayOfWeek1 = new Date(startOfYear);
  mondayOfWeek1.setDate(1 + (1 - startOfYear.getDay() + 7) % 7 + (week - 1) * 7);
  const monday = new Date(mondayOfWeek1);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return { start: formatDate(monday), end: formatDate(sunday), monday: monday };
}

/**
 * 生成上周和上上周的 weekKey
 */
function getLastTwoWeekKeys() {
  const today = new Date();
  const dow = today.getDay();
  const diffToMon = dow === 0 ? -6 : 1 - dow;
  const thisMonday = new Date(today);
  thisMonday.setDate(today.getDate() + diffToMon);

  const lastMonday = new Date(thisMonday);
  lastMonday.setDate(thisMonday.getDate() - 7);

  const lastLastMonday = new Date(thisMonday);
  lastLastMonday.setDate(thisMonday.getDate() - 14);

  return {
    targetMonday: formatDate(lastMonday),
    targetSunday: formatDate(new Date(lastMonday.getFullYear(), lastMonday.getMonth(), lastMonday.getDate() + 6)),
    prevMonday: formatDate(lastLastMonday),
    prevSunday: formatDate(new Date(lastLastMonday.getFullYear(), lastLastMonday.getMonth(), lastLastMonday.getDate() + 6)),
    lastWeekKey: weekKey(formatDate(lastMonday)),
    lastLastWeekKey: weekKey(formatDate(lastLastMonday)),
  };
}

/**
 * 计算上一周的起始/结束日期(YYYY-MM-DD)。
 * 上周 = 输入日期所在周的周一 -7 ~ +6 天范围。
 */
function _prevWeekRange(anyDateInWeek) {
  const monday = new Date(anyDateInWeek);
  // 调整为该周的周一
  const dayOfWeek = monday.getDay();
  const diffToMon = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
  monday.setDate(monday.getDate() + diffToMon - 7);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return { start: formatDate(monday), end: formatDate(sunday) };
}
