
// ========== 年度汇总 ==========
async function fetchYearlyReport(year) {
  try {
    const r = await fetch(`api/yearly-report?year=${encodeURIComponent(year)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn('年度汇总加载失败:', e);
    return null;
  }
}

let _yearlyChart = null;  // 年度柱状图实例(切换年份前必须 destroy)

function renderYearlyReport(data) {
  const box = document.getElementById('yearly-result');
  const copyBtn = document.getElementById('btn-copy-yearly');
  // 销毁旧图表,避免 canvas 残留/重复
  if (_yearlyChart) { _yearlyChart.destroy(); _yearlyChart = null; }
  if (!data || !data.months || data.months.length === 0) {
    box.innerHTML = '<div class="report-empty">该年暂无抄表数据</div>';
    copyBtn.style.display = 'none';
    return;
  }
  copyBtn.style.display = 'inline-block';

  // 按表累计(年度合计行)
  const keys = ['hall', 'fire', 'private_room', 'ac'];
  const totals = {};
  keys.forEach(k => totals[k] = data.months.reduce((s, m) => s + (m.by_meter[k] || 0), 0));

  const rows = data.months.map(m => `
    <tr>
      <td class="col-date">${m.month}</td>
      <td>${fmtKwh(m.by_meter.hall)}</td>
      <td>${fmtKwh(m.by_meter.fire)}</td>
      <td>${fmtKwh(m.by_meter.private_room)}</td>
      <td>${fmtKwh(m.by_meter.ac)}</td>
      <td class="col-total">${fmtKwh(m.total_kwh)}</td>
      <td class="col-total">¥ ${m.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
    </tr>`).join('');

  box.innerHTML = `
    <div class="chart-wrap" style="height:240px;margin-bottom:16px;"><canvas id="chart-yearly"></canvas></div>
    <div class="table-container">
      <table class="report-grid-table">
        <thead>
          <tr>
            <th class="col-date">月份</th><th>1#大厅</th><th>2#消防</th><th>3#包厢</th><th>4#空调</th>
            <th class="col-total">合计(度)</th><th class="col-total">电费(元)</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
          <tr class="total-row">
            <td class="col-date">年度合计</td>
            <td>${fmtKwh(totals.hall)}</td><td>${fmtKwh(totals.fire)}</td>
            <td>${fmtKwh(totals.private_room)}</td><td>${fmtKwh(totals.ac)}</td>
            <td class="col-total">${fmtKwh(data.year_total_kwh)}</td>
            <td class="col-total">¥ ${data.year_total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
          </tr>
        </tbody>
      </table>
    </div>`;

  // 12 个月 4 表堆叠柱状图(主题色,与 legend 一致)
  const canvas = document.getElementById('chart-yearly');
  _yearlyChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.months.map(m => m.month.slice(5)),
      datasets: [
        { label: '1#' + LABELS('hall'), data: data.months.map(m => m.by_meter.hall), backgroundColor: COLORS('hall') },
        { label: '2#' + LABELS('fire'), data: data.months.map(m => m.by_meter.fire), backgroundColor: COLORS('fire') },
        { label: '3#' + LABELS('private_room'), data: data.months.map(m => m.by_meter.private_room), backgroundColor: COLORS('private_room') },
        { label: '4#' + LABELS('ac'), data: data.months.map(m => m.by_meter.ac), backgroundColor: COLORS('ac') },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label} ${fmtKwh(ctx.raw)} 度` } },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, title: { display: true, text: '用电(度)' } },
      },
    },
  });
}

function copyYearlyTSV(data) {
  const lines = ['工程部管理系统年度汇总报表', `统计年份,${data.year}`, ''];
  lines.push(['月份', '1#大厅', '2#消防', '3#包厢', '4#空调', '合计(度)', '电费(元)'].join('\t'));
  data.months.forEach(m => {
    lines.push([m.month, m.by_meter.hall, m.by_meter.fire, m.by_meter.private_room, m.by_meter.ac, m.total_kwh, m.total_cost].join('\t'));
  });
  lines.push(['年度合计', '', '', '', '', data.year_total_kwh, data.year_total_cost].join('\t'));
  copyTextWithFallback(lines.join('\n'), '✓ 年度汇总已复制,可粘贴到 Excel');
}

// 月度报告复制 TSV(粘贴到 Excel 自动成表):每日明细 + 每表总用电 + 合计 + 电费
function copyReportTSV(data) {
  const lines = ['工程部管理系统月度统计报表', `统计月份,${data.month}`, ''];
  lines.push(['日期', '1#大厅', '2#消防', '3#包厢', '4#空调', '合计(度)'].join('\t'));
  data.days.forEach(d => {
    lines.push([d.date, d.hall, d.fire, d.private_room, d.ac, d.total].join('\t'));
  });
  lines.push('');
  // 每块电表总用电(与页面汇总卡一致)
  lines.push(['各表总用电', data.summary.by_meter.hall, data.summary.by_meter.fire,
    data.summary.by_meter.private_room, data.summary.by_meter.ac, data.summary.total_kwh].join('\t'));
  lines.push(['月度合计', '', '', '', '', data.summary.total_kwh].join('\t'));
  lines.push(['本月电费', '', '', '', '', `¥ ${data.summary.total_cost.toFixed(2)}`].join('\t'));
  copyTextWithFallback(lines.join('\n'), '✓ 月度报告已复制,可粘贴到 Excel');
}

// 每月用电复制:复制当前月各区域度数 + 金额 + 对比上月,可直接粘贴到群
function copyMonthUsage() {
  if (!_monthCopyData || !_monthCopyData.monthKey) { showAlert('暂无本月用电数据可复制', 'error'); return; }
  const d = _monthCopyData;
  const lines = [`【${d.monthKey} 各区域用电】`];
  let hasData = false;
  for (const m of CHARGE_METERS) {
    const kwh = d.per[m.key];
    if (kwh == null || kwh <= 0) { lines.push(`${m.icon} ${m.label}: —`); continue; }
    hasData = true;
    // 对比上月
    let vsP = '';
    const prevKwh = d.prev[m.key];
    if (d.hasPrev && prevKwh != null && prevKwh > 0) {
      const diff = kwh - prevKwh;
      const pct = (diff / prevKwh) * 100;
      vsP = ` 较上月${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
    }
    lines.push(`${m.icon} ${m.label}: ${kwh.toFixed(1)} 度,¥${(kwh * ELECTRICITY_PRICE).toFixed(2)}${vsP}`);
  }
  if (!hasData) { showAlert('本月暂无用电数据可复制', 'error'); return; }
  // 合计行
  let vsTotal = '';
  if (d.hasPrev && d.prevTotal > 0) {
    const diff = d.monthTotal - d.prevTotal;
    const pct = (diff / d.prevTotal) * 100;
    vsTotal = ` 较上月${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
  }
  lines.push(`— 合计: ${d.monthTotal.toFixed(1)} 度,¥${(d.monthTotal * ELECTRICITY_PRICE).toFixed(2)}${vsTotal}`);
  lines.push(`(当月日均 ${(d.monthTotal / d.monthDays).toFixed(1)} 度/天)`);
  const text = lines.join('\n');
  copyTextWithFallback(text, '✓ 每月用电已复制,可直接粘贴到群里');
}