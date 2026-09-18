// ===== 占比饼图(单日/月度) =====
// 从 render_charts.js 拆出,负责 4 块表占比饼图渲染。
// 依赖:render_charts.js(必须在之前加载,因为 dailyPieChart 等全局变量在此处定义与使用)。
//   - renderTrendChart() 中也会触发 renderDailyPie()
//   - renderMonthlyPie() 由 features_utilities.js 调用

// 饼图实例
let dailyPieChart = null;
let _monthlyPieChart = null;
let monthlyPieChart = null;

// 计算某月饼图数据(某月内首/末抄表 + 期间充电)
function calcMonthPie(monthReadings, charges) {
  if (!monthReadings || monthReadings.length < 2) return null;
  const first = monthReadings[0], last = monthReadings[monthReadings.length - 1];
  const usage = ['hall', 'fire', 'private_room', 'ac'].map(k => {
    const delta = realKwh(first[k] - last[k], k);
    const charged = sumChargesBetween(charges, k, first.date, last.date);
    return Math.max(delta + charged, 0);
  });
  const total = usage.reduce((a, b) => a + b, 0);
  if (total <= 0) return null;
  return { usage, total, first, last };
}

// 通用:画一个饼图到 canvasId,setChart 回调保存 chart 引用
function drawPieChart(canvasId, data, setChart) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const labels = ['hall', 'fire', 'private_room', 'ac'].map((k, i) => {
    const pct = data.total > 0 ? (data.usage[i] / data.total * 100).toFixed(1) : 0;
    return `${LABELS(k)} (${pct}%)`;
  });
  const chart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: data.usage,
        backgroundColor: [COLORS('hall'), COLORS('fire'), COLORS('private_room'), COLORS('ac')],
        borderWidth: 2,
        borderColor: 'rgba(0,0,0,0.08)',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { boxWidth: 12, font: { size: 12 } } },
        tooltip: {
          callbacks: {
            label: (c) => {
              const v = c.parsed;
              const pct = data.total > 0 ? (v / data.total * 100).toFixed(1) : 0;
              return `${c.label.split(' (')[0]}: ${v.toFixed(1)} 度 (${pct}%)`;
            },
          },
        },
      },
    },
  });
  if (setChart) setChart(chart);
  return chart;
}

// 单日占比饼图:从单天汇报下拉联动
function renderDailyPie(dateStr) {
  const wrap = document.getElementById('daily-pie-wrap');
  const summaryEl = document.getElementById('daily-pie-summary');
  if (!wrap || !summaryEl) return;

  const readings = CURRENT_READINGS.filter(r => r.hall != null);
  if (!dateStr || readings.length < 2) {
    wrap.style.display = 'none';
    return;
  }

  // 找到包含该日的前后两次抄表
  const sorted = [...readings].sort((a, b) => a.date.localeCompare(b.date));
  let prev = null, next = null;
  for (let i = 0; i < sorted.length; i++) {
    if (sorted[i].date <= dateStr) prev = sorted[i];
    if (sorted[i].date > dateStr) { next = sorted[i]; break; }
  }
  if (!prev || !next) {
    wrap.style.display = 'none';
    return;
  }

  // 计算 prev → next 区间,按天数均摊到 prev 日(与单天汇报口径一致)
  const days = Math.max(1, Math.round((new Date(next.date) - new Date(prev.date)) / 86400000));
  const usage = ['hall', 'fire', 'private_room', 'ac'].map(k => {
    const delta = realKwh(prev[k] - next[k], k);
    const charged = sumChargesBetween(CURRENT_CHARGES, k, prev.date, next.date);
    return Math.max((delta + charged) / days, 0);
  });
  const total = usage.reduce((a, b) => a + b, 0);

  wrap.style.display = '';
  const pct = (i) => total > 0 ? (usage[i] / total * 100).toFixed(1) : '0';
  summaryEl.innerHTML = `
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('hall')}"></span>大厅 ${usage[0].toFixed(1)} 度 (${pct(0)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('fire')}"></span>消防 ${usage[1].toFixed(1)} 度 (${pct(1)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('private_room')}"></span>包厢 ${usage[2].toFixed(1)} 度 (${pct(2)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('ac')}"></span>空调 ${usage[3].toFixed(1)} 度 (${pct(3)}%)</div>
  `;

  if (dailyPieChart) { dailyPieChart.destroy(); dailyPieChart = null; }
  drawPieChart('chart-daily-pie', { usage, total }, c => dailyPieChart = c);
}

// 月度占比饼图(月度报告页):从「选择月份」下拉联动
function renderMonthlyPie(monthKey) {
  const wrap = document.getElementById('monthly-pie-wrap');
  const summaryEl = document.getElementById('monthly-pie-summary');
  if (!wrap || !summaryEl) return;

  const readings = CURRENT_READINGS.filter(r => r.hall != null);
  const data = calcMonthPie(readings.filter(r => r.date.startsWith(monthKey)), CURRENT_CHARGES);

  if (!data) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = '';

  const pct = (i) => data.total > 0 ? (data.usage[i] / data.total * 100).toFixed(1) : '0';
  summaryEl.innerHTML = `
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('hall')}"></span>大厅 ${data.usage[0].toFixed(1)} 度 (${pct(0)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('fire')}"></span>消防 ${data.usage[1].toFixed(1)} 度 (${pct(1)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('private_room')}"></span>包厢 ${data.usage[2].toFixed(1)} 度 (${pct(2)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('ac')}"></span>空调 ${data.usage[3].toFixed(1)} 度 (${pct(3)}%)</div>
  `;

  if (monthlyPieChart) { monthlyPieChart.destroy(); monthlyPieChart = null; }
  drawPieChart('chart-monthly-pie', data, c => monthlyPieChart = c);
}

// 兼容旧入口(旧代码可能仍引用)
function renderPieChart() {
  // 旧的独立占比页已删除,不再做任何事
}
