// ===== 每周汇报 =====
// 目标周:选择最近一周,自动计算上周和上上周数据用于对比。
// 工具函数(_readingsBetween / calcPeriodUsage / countTags / weekKey /
//   weekDateRange / getLastTwoWeekKeys / daysInPeriod / _prevWeekRange)
// 已迁出至 render_weekly_utils.js。

let _weeklyChart = null;


/**
 * 填充目标周下拉(最近4周)
 */
function populateWeeklyWeekSelector() {
  const sel = document.getElementById('weekly-target-week');
  if (!sel) return;

  const { targetMonday, lastWeekKey, lastLastWeekKey } = getLastTwoWeekKeys();

  // 收集有数据的周
  const weekSet = new Set();
  (CURRENT_READINGS || []).forEach(r => {
    if (r.hall != null) weekSet.add(weekKey(r.date));
  });
  const sortedWeeks = [...weekSet].sort().reverse();

  // 默认:上周(离当前日期最近一周)
  const defaultWeek = lastWeekKey;

  // 构建选项
  const allWeekKeys = [lastWeekKey, lastLastWeekKey];
  sortedWeeks.forEach(w => {
    if (!allWeekKeys.includes(w)) allWeekKeys.push(w);
  });

  sel.innerHTML = allWeekKeys.map(w => {
    const range = weekDateRange(w);
    const label = `${w} (${range.start} ~ ${range.end})`;
    const isDefault = w === defaultWeek;
    return `<option value="${w}"${isDefault ? ' selected' : ''}>${label}</option>`;
  }).join('');
}

/**
 * 加载并渲染每周汇报
 */
function loadWeeklyReport() {
  const sel = document.getElementById('weekly-target-week');
  if (!sel) return;
  if (!sel.value) populateWeeklyWeekSelector();
  const weekStr = sel.value;
  if (!weekStr) return;

  const range = weekDateRange(weekStr);
  const targetStart = range.start, targetEnd = range.end;
  const _prev = _prevWeekRange(targetStart);
  const prevStart = _prev.start, prevEnd = _prev.end;

  const readings = CURRENT_READINGS || [];
  const charges = CURRENT_CHARGES || [];
  const mKeys = ['hall', 'fire', 'private_room', 'ac'];

  const emptyEl = document.getElementById('weekly-report-empty');
  const headlineEl = document.getElementById('weekly-headline');
  const chartWrap = document.getElementById('weekly-chart-wrap');
  const detailEl = document.getElementById('weekly-detail');
  const copyBtn = document.getElementById('btn-copy-weekly');

  if (readings.length < 2) {
    [headlineEl, chartWrap, detailEl].forEach(el => { if (el) el.style.display = 'none'; });
    if (emptyEl) emptyEl.style.display = '';
    if (copyBtn) copyBtn.style.display = 'none';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  const fmt = v => v.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
  const shortD = d => d.slice(5).replace('-', '/');

  const data = mKeys.map(k => ({
    key: k,
    t: calcPeriodUsage(readings, charges, k, targetStart, targetEnd).kwh,
    p: calcPeriodUsage(readings, charges, k, prevStart, prevEnd).kwh,
  }));
  const totalT = data.reduce((s, d) => s + d.t, 0);
  const totalP = data.reduce((s, d) => s + d.p, 0);
  const diff = totalT - totalP;
  const pct = totalP > 0 ? (diff / totalP * 100) : (totalT > 0 ? 100 : 0);
  const trendColor = diff > 0 ? 'var(--danger)' : diff < 0 ? 'var(--success)' : 'var(--text-muted)';

  // ---------- 1) 一句话总结 ----------
  if (headlineEl) {
    headlineEl.style.display = '';
    headlineEl.innerHTML =
      '<div class="weekly-headline-main">上周 ' + shortD(targetStart) + '–' + shortD(targetEnd) +
      ' 共用电 <strong>' + fmt(totalT) + ' 度</strong>，电费 <strong>¥' + fmt(totalT * ELECTRICITY_PRICE) + '</strong></div>' +
      '<div class="weekly-headline-sub">上上周 ' + shortD(prevStart) + '–' + shortD(prevEnd) + ' 为 ' + fmt(totalP) + ' 度' +
      (totalP > 0 || totalT > 0
        ? ' · <span style="color:' + trendColor + ';font-weight:600;">' +
          (diff >= 0 ? '▲ 增加' : '▼ 减少') + ' ' + fmt(Math.abs(diff)) + ' 度 (' +
          (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%)</span>'
        : '') +
      '</div>';
  }

  // ---------- 2) 两周对比图（每个区域一组双柱）----------
  if (chartWrap) {
    chartWrap.style.display = '';
    const cv = document.getElementById('chart-weekly-bar');
    if (cv) {
      if (_weeklyChart) { _weeklyChart.destroy(); _weeklyChart = null; }
      _weeklyChart = new Chart(cv.getContext('2d'), {
        type: 'bar',
        data: {
          labels: mKeys.map(k => METER_META(k).label),
          datasets: [
            { label: '上上周', data: data.map(d => d.p), backgroundColor: '#cbd5e1', borderRadius: 5, maxBarThickness: 38 },
            { label: '上周', data: data.map(d => d.t), backgroundColor: mKeys.map(k => METER_META(k).color), borderRadius: 5, maxBarThickness: 38 },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { boxWidth: 12, font: { size: 12 } } },
            tooltip: { callbacks: { label: c => c.dataset.label + ': ' + c.parsed.y.toFixed(1) + ' 度' } },
          },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, title: { display: true, text: '用电 (度)' }, ticks: { callback: v => v.toLocaleString() } },
          },
        },
      });
    }
  }

  // ---------- 3) 明细表（4 列，带合计行）----------
  if (detailEl) {
    detailEl.style.display = '';
    const tbody = document.querySelector('#weekly-compare-table tbody');
    if (tbody) {
      tbody.innerHTML = data.map(d => {
        const dd = d.t - d.p;
        const pp = d.p > 0 ? (dd / d.p * 100) : null;
        const col = dd > 0 ? 'var(--danger)' : dd < 0 ? 'var(--success)' : 'var(--text-muted)';
        const chg = pp == null
          ? (d.t > 0 ? '▲ 新增' : '—')
          : ((dd > 0 ? '▲ ' : dd < 0 ? '▼ ' : '') + Math.abs(pp).toFixed(1) + '%');
        return '<tr><td>' + METER_META(d.key).icon + ' ' + METER_META(d.key).label + '</td>' +
               '<td>' + fmt(d.p) + '</td><td>' + fmt(d.t) + '</td>' +
               '<td style="color:' + col + ';font-weight:600;">' + chg + '</td></tr>';
      }).join('') +
      '<tr class="weekly-total-row"><td>合计</td><td>' + fmt(totalP) + '</td><td>' + fmt(totalT) + '</td>' +
      '<td style="color:' + trendColor + ';font-weight:700;">' +
      (diff === 0 ? '—' : (diff > 0 ? '▲ ' : '▼ ') + Math.abs(pct).toFixed(1) + '%') + '</td></tr>';
    }

    const summaryRow = document.getElementById('weekly-summary-row');
    if (summaryRow) {
      summaryRow.style.display = 'flex';
      summaryRow.innerHTML =
        '<div class="summary-item"><div class="summary-label">上周电费</div>' +
        '<div class="summary-value">¥ ' + fmt(totalT * ELECTRICITY_PRICE) + '</div></div>' +
        '<div class="summary-item"><div class="summary-label">上上周电费</div>' +
        '<div class="summary-value">¥ ' + fmt(totalP * ELECTRICITY_PRICE) + '</div></div>' +
        '<div class="summary-item"><div class="summary-label">费用变化</div>' +
        '<div class="summary-value" style="color:' + trendColor + ';">' +
        (diff >= 0 ? '+' : '−') + '¥ ' + fmt(Math.abs(diff) * ELECTRICITY_PRICE) + '</div></div>';
    }
  }

  if (copyBtn) copyBtn.style.display = '';
}

/**
 * 复制每周汇报文本(可直接粘贴到工作群)
 */
function copyWeeklyReport() {
  const weekStr = document.getElementById('weekly-target-week').value;
  if (!weekStr) { showAlert('请选择目标周', 'error'); return; }

  const range = weekDateRange(weekStr);
  const _prev = _prevWeekRange(range.start);
  const prevStart = _prev.start;
  const prevEnd = _prev.end;

  const readings = CURRENT_READINGS || [];
  const charges = CURRENT_CHARGES || [];
  const mKeys = ['hall', 'fire', 'private_room', 'ac'];

  const lines = [`【${weekStr} 每周汇报】`, `目标周: ${range.start} ~ ${range.end}`, `对比周: ${prevStart} ~ ${prevEnd}`, ''];

  // 区域用电对比
  lines.push('⚡ 区域用电对比(度):');
  let totalT = 0, totalP = 0;
  for (const k of mKeys) {
    const t = calcPeriodUsage(readings, charges, k, range.start, range.end);
    const p = calcPeriodUsage(readings, charges, k, prevStart, prevEnd);
    totalT += t.kwh; totalP += p.kwh;
    let change = '';
    if (p.kwh > 0) {
      const pct = ((t.kwh - p.kwh) / p.kwh) * 100;
      change = pct > 0 ? ` ↑${pct.toFixed(1)}%` : pct < 0 ? ` ↓${Math.abs(pct).toFixed(1)}%` : '';
    } else if (t.kwh > 0) {
      change = ' ↑新增';
    }
    lines.push(`  ${METER_META(k).icon} ${METER_META(k).label}: 上周${t.kwh.toFixed(1)} / 上上周${p.kwh.toFixed(1)}${change}`);
  }
  lines.push('');

  // 排练/编程
  const tTags = countTags(readings, range.start, range.end);
  const pTags = countTags(readings, prevStart, prevEnd);
  lines.push(`🎭 排练: 上周${tTags.rehearsal}次 / 上上周${pTags.rehearsal}次, 编程: 上周${tTags.programming}次 / 上上周${pTags.programming}次`);
  lines.push('');

  // 空调趋势
  const acT = calcPeriodUsage(readings, charges, 'ac', range.start, range.end);
  const acP = calcPeriodUsage(readings, charges, 'ac', prevStart, prevEnd);
  if (acP.kwh > 0) {
    const acChange = ((acT.kwh - acP.kwh) / acP.kwh) * 100;
    const trend = acChange > 5 ? '上涨' : acChange < -5 ? '下降' : '持平';
    lines.push(`❄️ ${LABELS('ac')}电费: 上周${acT.kwh.toFixed(1)}度 → 上上周${acP.kwh.toFixed(1)}度,同比${trend}${acChange > 0 ? '+' : ''}${acChange.toFixed(1)}%`);
  } else {
    lines.push(`❄️ ${LABELS('ac')}电费: 上周${acT.kwh.toFixed(1)}度(上上周无数据)`);
  }
  lines.push('');

  const text = lines.join('\n');
  copyTextWithFallback(text, '✓ 每周汇报已复制,可直接粘贴到群里');
}

// ===== 初始化 =====
// 目标周下拉切换时重新加载
document.getElementById('weekly-target-week')?.addEventListener('change', () => loadWeeklyReport());
// 复制按钮
document.getElementById('btn-copy-weekly')?.addEventListener('click', () => {
  copyWeeklyReport();
});

// 页面可见时重新加载
window.addEventListener('focus', () => {
  if (document.getElementById('section-report-weekly')?.style.display === 'flex') {
    loadWeeklyReport();
  }
});
