
// ========== 月度水电(总表/分表/厨房/水表)==========
async function fetchMonthlyUtilities(month) {
  try {
    const r = await fetch(`api/monthly-utilities?month=${encodeURIComponent(month)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn('月度水电加载失败:', e);
    return null;
  }
}

function renderMonthlyUtilities(data) {
  const box = document.getElementById('utilities-result');
  if (!data) { box.innerHTML = '<div class="report-empty">加载失败,请检查后端</div>'; return; }
  if (!data.has_data) { box.innerHTML = `<div class="report-empty">${data.msg || '该月未录入水电表底'}</div>`; return; }
  const fmt = (v, suffix) => v == null
    ? '—'
    : `${v.toLocaleString('zh-CN', { maximumFractionDigits: 1 })}<small>${suffix}</small>`;
  const yuan = (v) => v == null ? '—' : `¥ ${v.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
  box.innerHTML = `
    <div class="stat-grid" style="margin-top:8px;">
      <div class="stat-card hall">
        <div class="label">总表 ×${data.mult_main || 50}</div>
        <div class="value">${fmt(data.main_kwh, '度')}</div>
        <div class="sub">${data.prev_date ? `${data.prev_date} → ${data.cur.date}` : '缺上月表底'}</div>
      </div>
      <div class="stat-card fire">
        <div class="label">分表 ×${data.mult_sub || 40}</div>
        <div class="value">${fmt(data.sub_kwh, '度')}</div>
        <div class="sub">${data.cur.sub_meter == null ? '未录入' : `表底 ${data.cur.sub_meter}`}</div>
      </div>
      <div class="stat-card total">
        <div class="label">厨房(总表−分表)</div>
        <div class="value">${fmt(data.kitchen_kwh, '度')}</div>
        <div class="sub" style="color:var(--primary);font-weight:600;">电费 ${yuan(data.kitchen_cost)}</div>
      </div>
      <div class="stat-card ac">
        <div class="label">水表(用水)</div>
        <div class="value">${fmt(data.water_usage, '吨')}</div>
        <div class="sub" style="color:var(--success);font-weight:600;">水费 ${yuan(data.water_cost)}</div>
      </div>
    </div>
    <div class="sub" style="color:var(--text-muted);font-size:12px;margin-top:8px;">
      总表/分表/水表每月抄一次(读数递增),总表 ×50、分表 ×40 后为实际用电,厨房用电 = 总表实际 − 分表实际(不直接抄)。电价 ${data.price_electricity} 元/度 · 水价 ${data.price_water} 元/吨。
    </div>
  `;
}

async function loadMonthlyUtilities() {
  const month = document.getElementById('utilities-month').value;
  if (!month) return;
  renderMonthlyUtilities(await fetchMonthlyUtilities(month));
}
document.getElementById('utilities-month').addEventListener('change', loadMonthlyUtilities);

async function loadYearlyReport() {
  const year = document.getElementById('yearly-year').value;
  if (!year || year.length !== 4) { showAlert('请输入 4 位年份', 'error'); return; }
  document.getElementById('yearly-result').innerHTML = '<div class="report-empty">加载中...</div>';
  const data = await fetchYearlyReport(year);
  renderYearlyReport(data);
}
document.getElementById('yearly-apply').addEventListener('click', loadYearlyReport);
document.getElementById('btn-copy-yearly').addEventListener('click', () => {
  const year = document.getElementById('yearly-year').value;
  fetchYearlyReport(year).then(d => d && copyYearlyTSV(d));
});
// 默认加载当前年
// 年度汇总默认加载由 refreshMonthSelectors 填充默认年份后触发

// 生成 HTML 表格(粘贴到 Word/邮箱可识别为表格)
function buildReportHTML() {
  if (!_currentReport) return '';
  const d = _currentReport;
  const [yy, mm] = d.month.split('-');
  const daysInMonth = new Date(parseInt(yy), parseInt(mm), 0).getDate();

  // CSS 样式 — 内联确保 Word/Outlook 正确渲染
  const style = `
    <style>
      table.report { border-collapse: collapse; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 12pt; width: 100%; margin: 0 auto; }
      table.report caption { font-size: 18pt; font-weight: bold; padding: 12px; }
      table.report th, table.report td { border: 1px solid #000; padding: 6px 10px; text-align: right; }
      table.report th { background: #fff; font-weight: bold; text-align: center; }
      table.report td.date-col, table.report th.date-col { text-align: center; width: 50px; }
      table.report tr.empty-row td { color: #999; }
    </style>`;

  let html = style;
  html += `<table class="report">`;
  html += `<caption>${yy}年 ${parseInt(mm)}月每日用电统计</caption>`;
  html += `<thead><tr>`;
  html += `<th class="date-col">日期</th>`;
  html += `<th>1#大厅</th><th>2#消防</th><th>3#后勤包厢</th><th>4#空调</th>`;
  html += `<th>合计(度)</th>`;
  html += `</tr></thead><tbody>`;

  for (let day = 1; day <= daysInMonth; day++) {
    const d_str = `${yy}-${mm}-${String(day).padStart(2, '0')}`;
    const row = d.days.find(r => r.date === d_str);
    if (row && row.is_reading_day) {
      // 抄表日 — 显示该次用电(用户表格原样)
      html += `<tr><td class="date-col">${day}</td>`;
      html += `<td>${fmtKwh(row.hall)}</td>`;
      html += `<td>${fmtKwh(row.fire)}</td>`;
      html += `<td>${fmtKwh(row.private_room)}</td>`;
      html += `<td>${fmtKwh(row.ac)}</td>`;
      html += `<td>${fmtKwh(row.total)}</td></tr>`;
    } else if (row) {
      // 非抄表日 — 显示日均用电(每位: 段总用电 ÷ 段天数)
      html += `<tr class="empty-row"><td class="date-col">${day}</td>`;
      html += `<td>${fmtKwh(row.hall)}</td>`;
      html += `<td>${fmtKwh(row.fire)}</td>`;
      html += `<td>${fmtKwh(row.private_room)}</td>`;
      html += `<td>${fmtKwh(row.ac)}</td>`;
      html += `<td>${fmtKwh(row.total)}</td></tr>`;
    } else {
      // 月末最后一段(无下次抄表)— 显示空
      html += `<tr class="empty-row"><td class="date-col">${day}</td>`;
      html += `<td></td><td></td><td></td><td></td><td></td></tr>`;
    }
  }

  html += `</tbody></table>`;

  // 汇总区:每块电表总用电 + 月度合计 + 电费(领导要的汇总数据)
  const s = d.summary;
  const sumRow = (label, v) => `
    <tr>
      <td class="date-col" style="text-align:left;font-weight:bold;">${label}</td>
      <td>${fmtKwh(v.hall)}</td><td>${fmtKwh(v.fire)}</td>
      <td>${fmtKwh(v.private_room)}</td><td>${fmtKwh(v.ac)}</td>
      <td>${fmtKwh(v.total)}</td>
    </tr>`;
  html += `
    <table class="report" style="margin-top:16px;">
      <caption>${yy}年 ${parseInt(mm)}月汇总</caption>
      <thead><tr>
        <th class="date-col" style="text-align:left;">项目</th>
        <th>1#大厅</th><th>2#消防</th><th>3#后勤包厢</th><th>4#空调</th>
        <th>合计(度)</th>
      </tr></thead>
      <tbody>
        ${sumRow('各表总用电', { hall: s.by_meter.hall, fire: s.by_meter.fire, private_room: s.by_meter.private_room, ac: s.by_meter.ac, total: s.total_kwh })}
        <tr class="total-row">
          <td class="date-col" style="text-align:left;font-weight:bold;">月度合计</td>
          <td></td><td></td><td></td><td></td>
          <td style="font-weight:bold;">${fmtKwh(s.total_kwh)}</td>
        </tr>
        <tr>
          <td class="date-col" style="text-align:left;font-weight:bold;">本月电费</td>
          <td></td><td></td><td></td><td></td>
          <td style="font-weight:bold;">¥ ${s.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
        </tr>
      </tbody>
    </table>`;
  return html;
}

async function exportReportToWord() {
  const html = buildReportHTML();
  if (!html) {
    showAlert('暂无可导出的数据', 'error');
    return;
  }
  const btn = document.getElementById('btn-export-word');
  const origText = btn.textContent;
  const origBg = btn.style.background;
  // 立即给视觉反馈(不依赖 async):禁用 + 复制中
  btn.disabled = true;
  btn.textContent = '⏳ 复制中...';
  try {
    if (navigator.clipboard && window.ClipboardItem) {
      const blob = new Blob([html], { type: 'text/html' });
      await navigator.clipboard.write([new ClipboardItem({ 'text/html': blob })]);
    } else {
      // 回退:用临时 div + execCommand('copy')
      const div = document.createElement('div');
      div.innerHTML = html;
      div.style.position = 'fixed';
      div.style.left = '-9999px';
      document.body.appendChild(div);
      const range = document.createRange();
      range.selectNodeContents(div);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand('copy');
      sel.removeAllRanges();
      document.body.removeChild(div);
    }
    // 复制成功:绿色按钮 + 大字提示(保持禁用,3秒后恢复)
    btn.textContent = '✓ 已复制';
    btn.style.background = '#10b981';
    btn.style.borderColor = '#10b981';
    btn.style.color = '#fff';
    showAlert('✓ Word 表格已复制,去 Word 粘贴 (Cmd+V)', 'success');
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = origText;
      btn.style.background = origBg;
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 3000);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = origText;
    showAlert('导出失败:' + e.message, 'error');
  }
}

document.getElementById('btn-export-word').addEventListener('click', exportReportToWord);

document.getElementById('report-month').addEventListener('change', loadMonthlyReport);
document.getElementById('history-month').addEventListener('change', () => renderHistory(CURRENT_READINGS));
document.getElementById('water-history-month').addEventListener('change', () => {
  renderHistory(CURRENT_READINGS);
  // water table is rendered inside renderHistory using CURRENT_WATER_READINGS directly
});
document.getElementById('charge-month').addEventListener('change', () => renderChargeLog(CURRENT_CHARGES));

// 侧栏切换
const SIDEBAR_VISIBLE_SECTIONS = new Set([
  'reading', 'charge', 'utility',
  'reading-record', 'charge-record', 'charge-alert',
  'item-record', 'purchase-record',
  'item-add', 'purchase-add',
  'report-monthly', 'report-trend', 'report-pie', 'report-utilities', 'report-yearly',
  'overview'
]);

function switchSection(sectionId) {
  // 隐藏所有 section
  document.querySelectorAll('.content-section').forEach(s => s.style.display = 'none');
  // 显示目标 section（.content-section 默认 display:none，需显式 flex）
  const target = document.getElementById('section-' + sectionId);
  if (target) target.style.display = 'flex';

  // 自动展开所属分组:找到点击项所在的 group,如果不是 collapsed 则展开
  const activeBtn = document.querySelector(`.sidebar-item[data-section="${sectionId}"]`);
  if (activeBtn) {
    const group = activeBtn.closest('.sidebar-group');
    if (group && group.classList.contains('collapsed')) {
      group.classList.remove('collapsed');
    }
  }

  // 更新侧栏高亮
  document.querySelectorAll('.sidebar-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.section === sectionId);
  });

  // 状态条可见性
  const bar = document.getElementById('status-bar');
  if (SIDEBAR_VISIBLE_SECTIONS.has(sectionId)) {
    bar.style.display = '';
  } else {
    bar.style.display = 'none';
  }

  // 移动端:自动关闭侧栏
  const sidebar = document.getElementById('sidebar');
  if (window.innerWidth <= 900) {
    sidebar.classList.remove('mobile-open');
    document.getElementById('sidebar-overlay')?.classList.remove('show');
  }

  // 隐藏容器里初始化的 Chart 尺寸为 0,切回报表时重新计算
  if (sectionId === 'report-trend' && trendChart) {
    setTimeout(() => trendChart.resize(), 60);
  }
  if (sectionId === 'report-pie' && pieChart) {
    setTimeout(() => pieChart.resize(), 60);
  }
  if (sectionId === 'report-yearly' && _yearlyChart) {
    setTimeout(() => _yearlyChart.resize(), 60);
  }
}

// 侧栏分组折叠
function toggleGroup(el) {
  const group = el.parentElement;
  if (group) group.classList.toggle('collapsed');
}

// 系统设置页面切换（独立section）
function switchSettingsPage(page) {
  // 隐藏所有 section
  document.querySelectorAll('.content-section').forEach(s => s.style.display = 'none');
  // 显示对应的独立 section
  const target = document.getElementById('section-settings-' + page);
  if (target) target.style.display = 'flex';

  // 更新侧栏高亮:找到 settings-xxx 的按钮
  document.querySelectorAll('.sidebar-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.section === 'settings-' + page);
  });

  // 自动展开设置分组
  const settingsBtn = document.querySelector('.sidebar-item[data-section="settings-' + page + '"]');
  if (settingsBtn) {
    const group = settingsBtn.closest('.sidebar-group');
    if (group && group.classList.contains('collapsed')) {
      group.classList.remove('collapsed');
    }
  }

  // 状态条:设置页面不显示
  document.getElementById('status-bar').style.display = 'none';

  // 加载对应页面数据
  if (page === 'users') loadAdminUsers();
  if (page === 'meter') loadMeterSettings();
  if (page === 'data') loadBackupStatus();
  if (page === 'roles') loadRolesInfo();
}

// 侧栏点击事件
document.querySelectorAll('.sidebar-item').forEach(btn => {
  btn.addEventListener('click', () => {
    // settings 子菜单使用 switchSettingsPage（已有 onclick），这里跳过
    if (btn.dataset.section.startsWith('settings-')) return;
    switchSection(btn.dataset.section);
  });
});

// 侧栏折叠(桌面端)
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (window.innerWidth <= 900) {
    // 移动端:切换抽屉
    sidebar.classList.toggle('mobile-open');
    overlay?.classList.toggle('show');
  } else {
    // 桌面端:折叠/展开
    sidebar.classList.toggle('collapsed');
    const content = document.querySelector('.content');
    if (content) content.style.maxWidth = sidebar.classList.contains('collapsed') ? '100%' : '';
  }
}

// 移动端遮罩点击关闭侧栏
document.getElementById('sidebar-overlay')?.addEventListener('click', () => {
  document.getElementById('sidebar').classList.remove('mobile-open');
  document.getElementById('sidebar-overlay').classList.remove('show');
});

// 初始化:默认显示抄表记录
document.addEventListener('DOMContentLoaded', () => {
  applyTheme();
  loadMeterConfig().then(() => {
    loadMonthlyReport();
  });
  switchSection('reading-record');
});

// Tab 切换
function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.body.classList.remove('show-meter', 'show-item', 'show-history');
  document.body.classList.add('show-' + tab);
  if (tab === 'history' && _yearlyChart) {
    setTimeout(() => _yearlyChart.resize(), 60);
  }
}