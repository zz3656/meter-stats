
// ========== 月度报告(逐日逐表用电) ==========
async function fetchMonthlyReport(month) {
  try {
    const r = await fetch(`api/monthly-report?month=${encodeURIComponent(month)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn('月度报告加载失败:', e);
    return null;
  }
}

function fmtKwh(v) {
  if (!v) return '0';
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
}

function renderMonthlyReport(data) {
  const tableEl = document.getElementById('monthly-report-table');
  const emptyEl = document.getElementById('report-empty');
  const tbody = document.getElementById('report-body');
  const summary = document.getElementById('report-summary');
  
  if (!data || !data.days || data.days.length === 0) {
    tableEl.style.display = 'none';
    emptyEl.style.display = 'block';
    emptyEl.textContent = data ? `${data.month} 当月暂无抄表数据` : '加载失败,请检查后端';
    return;
  }
  
  tableEl.style.display = 'block';
  emptyEl.style.display = 'none';
  document.getElementById('btn-export-word').style.display = 'inline-block';
  document.getElementById('btn-copy-report').style.display = 'inline-block';

  tbody.innerHTML = '';
  for (const d of data.days) {
    const tr = document.createElement('tr');
    tr.className = d.is_reading_day ? 'reading-day' : 'empty-row';
    tr.innerHTML = `
        <td class="col-date">${d.date.slice(5)}</td>
        <td>${fmtKwh(d.hall)}</td>
        <td>${fmtKwh(d.fire)}</td>
        <td>${fmtKwh(d.private_room)}</td>
        <td>${fmtKwh(d.ac)}</td>
        <td class="col-total">${fmtKwh(d.total)}</td>
      `;
    tbody.appendChild(tr);
  }
  
  // 渲染月度汇总:4 表 stat 卡 + 全宽合计大卡(与当月统计/余量预警同款)
  const s = data.summary;
  const meterCards = [
    ['hall', '1#大厅'], ['fire', '2#消防'], ['private_room', '3#包厢'], ['ac', '4#空调'],
  ].map(([key, label]) => `
    <div class="stat-card ${key === 'private_room' ? 'private' : key}">
      <div class="label">${label}</div>
      <div class="value">${fmtKwh(s.by_meter[key])}<small>度</small></div>
    </div>`).join('');
  // 日均按实际覆盖天数(有真实用电的天)
  let covered = 0;
  for (const d of data.days) {
    if ((d.hall || 0) > 0 || (d.fire || 0) > 0 || (d.private_room || 0) > 0 || (d.ac || 0) > 0) covered++;
  }
  const avg = covered > 0 ? s.total_kwh / covered : 0;
  summary.innerHTML = `
    <div class="stat-grid">
      ${meterCards}
    </div>
    <div class="stat-card total total-wide" style="margin-top:12px;">
      <div>
        <div class="label">月度合计</div>
        <div class="value">${fmtKwh(s.total_kwh)}<small>度</small></div>
      </div>
      <div class="total-info">
        <div>日均 ${avg.toFixed(1)} 度 · 覆盖 ${covered} 天</div>
        <div style="color:var(--warn);font-weight:600;">本月电费 ¥ ${s.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</div>
      </div>
    </div>
  `;
}

let _reportLoadToken = 0;
let _currentReport = null;  // 缓存当前月份的报告数据(供"复制表格"使用)
let _monthCopyData = null;  // 缓存当前月/上月用电数据(供"每月用电"复制按钮使用)

// 上一个月键:2026-08 → 2026-07
function prevMonthKey(monthKey) {
  const y = parseInt(monthKey.slice(0, 4), 10);
  const m = parseInt(monthKey.slice(5, 7), 10);
  if (m === 1) return `${y - 1}-12`;
  return `${y}-${String(m - 1).padStart(2, '0')}`;
}
async function loadMonthlyReport() {
  const month = document.getElementById('report-month').value;
  if (!month) return;
  const token = ++_reportLoadToken;
  const emptyEl = document.getElementById('report-empty');
  emptyEl.style.display = 'block';
  emptyEl.textContent = '加载中...';
  document.getElementById('monthly-report-table').style.display = 'none';
  document.getElementById('btn-export-word').style.display = 'none';

  const data = await fetchMonthlyReport(month);
  if (token !== _reportLoadToken) return;
  _currentReport = data;
  renderMonthlyReport(data);
  // 月度报告页可见时,触发当月占比饼图
  if (document.getElementById('section-report-monthly')?.style.display !== 'none') {
    renderMonthlyPie(month);
  }
}