
// ===== 月份选择器 =====
/**
 * 收集有数据的月份,填充"历史对比"下拉
 */
function refreshMonthSelectors() {
  const monthsSet = new Set();
  CURRENT_READINGS.forEach(r => monthsSet.add(r.date.slice(0, 7)));
  const months = [...monthsSet].sort();
  const opts = months.length === 0
    ? '<option value="">(暂无数据)</option>'
    : months.map(m => `<option value="${m}">${m}</option>`).join('');

  // 当月统计:月份下拉(默认最新月),切换时重渲染统计卡
  const statsSel = document.getElementById('stats-month');
  if (statsSel) {
    const prev = statsSel.value;
    statsSel.innerHTML = opts;
    const newVal = prev && months.includes(prev) ? prev : (months.length > 0 ? months[months.length - 1] : '');
    if (statsSel.value !== newVal) {
      statsSel.value = newVal;
      renderStats(CURRENT_READINGS, CURRENT_CHARGES);
    }
  }

  // 月度报告:有数据月份下拉,默认最后月;值变化时重新加载
  const reportSel = document.getElementById('report-month');
  if (reportSel) {
    const prev = reportSel.value;
    reportSel.innerHTML = opts;
    const newVal = prev && months.includes(prev) ? prev : (months.length > 0 ? months[months.length - 1] : '');
    if (reportSel.value !== newVal) {
      reportSel.value = newVal;
      loadMonthlyReport();
    }
    // 当前如果月度报告页可见,触发当月占比渲染
    if (document.getElementById('section-report-monthly')?.style.display !== 'none' && reportSel.value) {
      renderMonthlyPie(reportSel.value);
    }
  }

  // 年度汇总:有数据年份下拉,默认最后年;首次填充后加载
  const years = [...new Set(months.map(m => m.slice(0, 4)))].sort();
  const yearSel = document.getElementById('yearly-year');
  if (yearSel) {
    const prev = yearSel.value;
    const yopts = years.length === 0
      ? '<option value="">(暂无数据)</option>'
      : years.map(y => `<option value="${y}">${y} 年</option>`).join('');
    yearSel.innerHTML = yopts;
    const newVal = prev && years.includes(prev) ? prev : (years.length > 0 ? years[years.length - 1] : '');
    if (yearSel.value !== newVal) {
      yearSel.value = newVal;
      loadYearlyReport();
    }
  }

  // 录入历史:月份筛选下拉,默认最后月;值变化时重新渲染
  const histSel = document.getElementById('history-month');
  if (histSel) {
    const prev = histSel.value;
    histSel.innerHTML = opts;
    const newVal = prev && months.includes(prev) ? prev : (months.length > 0 ? months[months.length - 1] : '');
    if (histSel.value !== newVal) {
      histSel.value = newVal;
      renderHistory(CURRENT_READINGS);
    }
  }

  // 水电表底月份筛选下拉,默认最后月;值变化时重新渲染(复用renderHistory)
  const waterHistSel = document.getElementById('water-history-month');
  if (waterHistSel) {
    const wMonths = [...new Set((CURRENT_WATER_READINGS || [])
      .map(r => r.date.slice(0, 7)))].sort();
    const wopts = wMonths.length === 0
      ? '<option value="">(暂无数据)</option>'
      : wMonths.map(m => `<option value="${m}">${m}</option>`).join('');
    const prev = waterHistSel.value;
    waterHistSel.innerHTML = wopts;
    const newVal = prev && wMonths.includes(prev) ? prev : (wMonths.length > 0 ? wMonths[wMonths.length - 1] : '');
    if (waterHistSel.value !== newVal) {
      waterHistSel.value = newVal;
      renderHistory(CURRENT_READINGS);
    }
  }

  // 充值记录:月份筛选下拉(用充值的月份,独立于抄表月份)
  const chargeSel = document.getElementById('charge-month');
  if (chargeSel) {
    const cMonths = [...new Set((CURRENT_CHARGES || []).map(c => c.date.slice(0, 7)))].sort();
    const copts = cMonths.length === 0
      ? '<option value="">(暂无数据)</option>'
      : cMonths.map(m => `<option value="${m}">${m}</option>`).join('');
    const prev = chargeSel.value;
    chargeSel.innerHTML = copts;
    const newVal = prev && cMonths.includes(prev) ? prev : (cMonths.length > 0 ? cMonths[cMonths.length - 1] : '');
    if (chargeSel.value !== newVal) {
      chargeSel.value = newVal;
      renderChargeLog(CURRENT_CHARGES);
    }
  }

  // 月度水电:月份下拉(有水电表底的月份)
  const utilSel = document.getElementById('utilities-month');
  if (utilSel) {
    const uMonths = [...new Set((CURRENT_WATER_READINGS || [])
      .map(r => r.date.slice(0, 7)))].sort();
    const uopts = uMonths.length === 0
      ? '<option value="">(暂无数据)</option>'
      : uMonths.map(m => `<option value="${m}">${m}</option>`).join('');
    const prev = utilSel.value;
    utilSel.innerHTML = uopts;
    // 默认选择最新有数据的月份
    const newVal = prev && uMonths.includes(prev) ? prev : (uMonths.length > 0 ? uMonths[uMonths.length - 1] : '');
    if (utilSel.value !== newVal) {
      utilSel.value = newVal;
      loadMonthlyUtilities();
    }
  }
}


/**
 * 历史对比:计算并显示两个月份的对比
 * 已并入「用电占比」模块 — 从 pie-month-a/b 读值,渲染到占比卡下方
 */
async function applyCompare(a, b) {
  const container = document.getElementById('pie-compare-result');
  if (!container) return;
  if (!a || !b) {
    container.innerHTML = '<div class="empty">请选择两个月份</div>';
    return;
  }
  if (a === b) {
    container.innerHTML = '<div class="empty">请选择不同的月份</div>';
    return;
  }
  container.innerHTML = '<div class="empty">计算中...</div>';

  // 计算两月各自的 4 块表用电(复用月度报告引擎:全月用电含跨月段)
  const calcFor = async (m) => {
    const rep = await fetchMonthlyReport(m);
    if (!rep || !rep.summary || rep.summary.reading_days < 2) return null;
    // 已覆盖天数:该月最后有值的天(1-based)。
    // 完整月(下月已有抄表)= 自然月天数;进行中的月(如 8 月只到 8/15)= 实际覆盖天数。
    // 不能一律用自然月天数 — 否则进行中的月日均被稀释(用户反馈)。
    let covered = 0;
    const dArr = rep.days || [];
    for (let i = dArr.length - 1; i >= 0; i--) {
      const dd = dArr[i];
      // 只认「至少一块表用电 > 0」的天;V4 对无下次抄表的末段补 0,不能算覆盖
      if ((dd.hall || 0) > 0 || (dd.fire || 0) > 0 || (dd.private_room || 0) > 0 || (dd.ac || 0) > 0) {
        covered = i + 1;
        break;
      }
    }
    const days = Math.max(covered, 1);
    return CHARGE_METERS.map(({ key, label }) => {
      const total = rep.summary.by_meter[key];
      return { label, total, daily: total / days, days };
    });
  };

  const [dataA, dataB] = await Promise.all([calcFor(a), calcFor(b)]);
  if (!dataA || !dataB) {
    const missing = !dataA ? a : b;
    container.innerHTML = `<div class="empty">${missing} 至少需要 2 次抄表</div>`;
    return;
  }

  // 渲染对比表:一行一块表,两月日均并排 + 变化列(涨红跌绿)
  const totalDailyA = dataA.reduce((s, d) => s + d.daily, 0);
  const totalDailyB = dataB.reduce((s, d) => s + d.daily, 0);
  const pct = (x, y) => {
    if (y <= 0) return '<span style="opacity:0.5;">—</span>';
    const v = ((x - y) / y) * 100;
    const up = v > 0;
    return `<span style="color:${up ? 'var(--danger)' : 'var(--success)'};font-weight:600;">${up ? '▲' : '▼'} ${Math.abs(v).toFixed(1)}%</span>`;
  };
  const meterRows = dataA.map((dA, i) => {
    const dB = dataB[i];
    return `
      <tr>
        <td class="c-name">${dA.label}</td>
        <td>${dA.daily.toFixed(1)} <span class="c-sub">${dA.total.toFixed(0)} 度</span></td>
        <td>${dB.daily.toFixed(1)} <span class="c-sub">${dB.total.toFixed(0)} 度</span></td>
        <td class="c-chg">${pct(dB.daily, dA.daily)}</td>
      </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="compare-table-wrap">
      <table class="compare-table">
        <thead>
          <tr>
            <th class="c-name">表</th>
            <th>${a} <span class="badge">${dataA[0].days} 天</span></th>
            <th>${b} <span class="badge">${dataB[0].days} 天</span></th>
            <th class="c-chg">变化</th>
          </tr>
        </thead>
        <tbody>
          <tr class="c-total">
            <td class="c-name">总日均</td>
            <td>${totalDailyA.toFixed(1)}</td>
            <td>${totalDailyB.toFixed(1)}</td>
            <td class="c-chg">${pct(totalDailyB, totalDailyA)}</td>
          </tr>
          ${meterRows}
        </tbody>
      </table>
    </div>
    <div class="sub" style="color:var(--text-muted);font-size:12px;margin-top:8px;">
      日均 = 月总用电 ÷ 已覆盖天数(完整月 = 整月;进行中的月 = 实际有数据的天数)。变化 = 后月较前月日均涨跌。
    </div>
  `;
}

/**
 * 计算指定月份每块表的"用电总量"和"日均用电量"
 * 用电总量 = (月初读数 - 月末读数) × 倍率 + 月内充值 × 倍率
 * 日均 = 用电总量 / 月内天数
 */
function calcMonthlyReport(readings, charges, monthKey) {
  const monthData = readings.filter(r => r.date.startsWith(monthKey));
  if (monthData.length < 2) return null;

  const sorted = [...monthData].sort((a, b) => a.date.localeCompare(b.date));
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const days = Math.max(1, (new Date(last.date) - new Date(first.date)) / 86400000);

  const rows = [];
  let totalUsage = 0;
  for (const key of ['hall', 'fire', 'private_room', 'ac']) {
    const delta = realKwh(first[key] - last[key], key);
    const charged = sumChargesBetween(charges, key, first.date, last.date);
    const usage = delta + charged;
    const daily = usage / days;
    totalUsage += usage;
    rows.push({
      meter: key,
      label: LABELS(key),
      multiplier: MULTIPLIER(key),
      firstReading: first[key],
      lastReading: last[key],
      chargedKwh: charged,
      usageKwh: usage,
      dailyKwh: daily,
    });
  }
  return {
    month: monthKey,
    firstDate: first.date,
    lastDate: last.date,
    days,
    rows,
    totalUsageKwh: totalUsage,
    totalDailyKwh: totalUsage / days,
    // 本月充值金额(¥)
    monthChargeYuan: rows.reduce((s, r) => s + r.chargedKwh * ELECTRICITY_PRICE, 0),
  };
}

/**
 * 把月报转成 CSV 字符串(带 BOM,Excel 打开不乱码)
 */
function buildMonthlyReportCSV(report) {
  const lines = [];
  lines.push(`工程部管理系统月度统计报表`);
  lines.push(`统计月份,${report.month}`);
  lines.push(`统计区间,${report.firstDate} 至 ${report.lastDate} (${report.days.toFixed(1)} 天)`);
  lines.push(``);
  lines.push(`表号,倍率,月初读数,月末读数,本月充电(度),用电总量(度),日均用电(度/天),折合金额(元)`);
  const meterNo = { hall: '1#', fire: '2#', private_room: '3#', ac: '4#' };
  for (const r of report.rows) {
    lines.push([
      `${meterNo[r.meter]}${r.label}`,
      `×${r.multiplier}`,
      r.firstReading.toFixed(2),
      r.lastReading.toFixed(2),
      r.chargedKwh.toFixed(1),
      r.usageKwh.toFixed(1),
      r.dailyKwh.toFixed(2),
      (r.usageKwh * ELECTRICITY_PRICE).toFixed(2),
    ].join(','));
  }
  lines.push(`合计,,,—,—,${report.rows.reduce((s, r) => s + r.chargedKwh, 0).toFixed(1)},${report.totalUsageKwh.toFixed(1)},${report.totalDailyKwh.toFixed(2)},${(report.totalUsageKwh * ELECTRICITY_PRICE).toFixed(2)}`);
  lines.push(``);
  lines.push(`本月充值总金额(元),${report.monthChargeYuan.toFixed(2)}`);
  return lines.join('\n');
}

function downloadCSV(filename, content) {
  const blob = new Blob(['\uFEFF' + content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// 当月统计:月份切换重渲染
const statsMonthSel = document.getElementById('stats-month');
if (statsMonthSel) statsMonthSel.addEventListener('change', () => renderStats(CURRENT_READINGS, CURRENT_CHARGES));

// 用电占比:已合并到每日趋势/月度报告页面,这里不再需要独立的月份下拉事件

// 物品管理:共用提交函数（侧栏录入页 + 物品记录页弹窗 都用）