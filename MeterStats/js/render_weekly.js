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

  // 确保下拉已填充
  if (!sel.value) populateWeeklyWeekSelector();

  const weekStr = sel.value;
  if (!weekStr) return;

  const range = weekDateRange(weekStr);
  // 目标周的上周 = 目标周本身
  const targetStart = range.start;
  const targetEnd = range.end;

  // 上上周 = 目标周之前一周
  const _prev = _prevWeekRange(targetStart);
  const prevStart = _prev.start;
  const prevEnd = _prev.end;

  const readings = CURRENT_READINGS || [];
  const charges = CURRENT_CHARGES || [];

  // ============ 区域电费对比 ============
  const compareTbody = document.querySelector('#weekly-compare-table tbody');
  const compareWrap = document.getElementById('weekly-electricity');

  if (readings.length < 2) {
    compareWrap.style.display = 'none';
    document.getElementById('weekly-report-empty').style.display = '';
    return;
  }

  document.getElementById('weekly-report-empty').style.display = 'none';
  compareWrap.style.display = '';

  const mKeys = ['hall', 'fire', 'private_room', 'ac'];
  let totalTarget = 0, totalPrev = 0;
  const rows = mKeys.map(k => {
    const t = calcPeriodUsage(readings, charges, k, targetStart, targetEnd);
    const p = calcPeriodUsage(readings, charges, k, prevStart, prevEnd);

    const tCost = t.kwh * ELECTRICITY_PRICE;
    const pCost = p.kwh * ELECTRICITY_PRICE;
    let changeStr = '—';
    let changeClass = '';
    if (p.kwh > 0) {
      const pct = ((t.kwh - p.kwh) / p.kwh) * 100;
      if (pct > 0) {
        changeStr = `▲ ${pct.toFixed(1)}%`;
        changeClass = 'style="color:var(--danger);"';
      } else if (pct < 0) {
        changeStr = `▼ ${Math.abs(pct).toFixed(1)}%`;
        changeClass = 'style="color:var(--success);"';
      } else {
        changeStr = '—';
      }
    } else if (t.kwh > 0) {
      changeStr = '▲ 新增';
      changeClass = 'style="color:var(--danger);"';
    }

    totalTarget += t.kwh;
    totalPrev += p.kwh;

    return `
      <tr>
        <td>${METER_META(k).icon} ${METER_META(k).label}</td>
        <td>${t.kwh.toFixed(1)} 度</td>
        <td>${p.kwh.toFixed(1)} 度</td>
        <td ${changeClass}>${changeStr}</td>
        <td>¥${tCost.toFixed(2)}</td>
        <td>¥${pCost.toFixed(2)}</td>
        <td ${changeClass}>¥${(tCost - pCost).toFixed(2)}</td>
      </tr>`;
  }).join('');

  compareTbody.innerHTML = rows;

  // 合计
  const totalChange = totalPrev > 0 ? ((totalTarget - totalPrev) / totalPrev * 100) : 0;
  const totalChangeStr = totalTarget > totalPrev
    ? `▲ ${(totalTarget - totalPrev).toFixed(1)} 度 (+${totalChange.toFixed(1)}%)`
    : totalTarget < totalPrev
    ? `▼ ${(totalPrev - totalTarget).toFixed(1)} 度 (${totalChange.toFixed(1)}%)`
    : '—';
  const totalChangeClass = totalTarget > totalPrev ? 'style="color:var(--danger);"' : totalTarget < totalPrev ? 'style="color:var(--success);"' : '';

  const summaryRow = document.getElementById('weekly-summary-row');
  summaryRow.style.display = 'flex';
  summaryRow.innerHTML = `
    <div class="summary-item">
      <div class="summary-label">合计用电</div>
      <div class="summary-value">上周 ${totalTarget.toFixed(1)} 度 vs 上上周 ${totalPrev.toFixed(1)} 度</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">费用合计</div>
      <div class="summary-value" id="">¥ ${(totalTarget * ELECTRICITY_PRICE).toFixed(2)} vs ¥ ${(totalPrev * ELECTRICITY_PRICE).toFixed(2)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">变化</div>
      <div class="summary-value" ${totalChangeClass}>${totalChangeStr}</div>
    </div>
  `;

  // ============ 排练/编程统计 ============
  const tagTbody = document.querySelector('#weekly-tag-table tbody');
  const tagWrap = document.getElementById('weekly-tags');

  const tTags = countTags(readings, targetStart, targetEnd);
  const pTags = countTags(readings, prevStart, prevEnd);

  tagTbody.innerHTML = `
    <tr>
      <td>上周</td>
      <td style="color:#6366f1;font-weight:600;">${tTags.rehearsal} 次</td>
      <td style="color:#a855f7;font-weight:600;">${tTags.programming} 次</td>
    </tr>
    <tr>
      <td>上上周</td>
      <td style="color:#6366f1;font-weight:600;">${pTags.rehearsal} 次</td>
      <td style="color:#a855f7;font-weight:600;">${pTags.programming} 次</td>
    </tr>
  `;
  tagWrap.style.display = '';

  // ============ 空调电费趋势 ============
  const acResult = document.getElementById('weekly-ac-result');
  const acTrendWrap = document.getElementById('weekly-ac-trend');

  const acT = calcPeriodUsage(readings, charges, 'ac', targetStart, targetEnd);
  const acP = calcPeriodUsage(readings, charges, 'ac', prevStart, prevEnd);
  const acDaysT = daysInPeriod(prevStart, targetEnd);
  const acDaysP = daysInPeriod(prevStart, prevEnd);
  const acDailyT = acDaysT > 0 ? acT.kwh / acDaysT : 0;
  const acDailyP = acDaysP > 0 ? acP.kwh / acDaysP : 0;

  let acTrendStr = '';
  if (acP.kwh > 0) {
    const acChangePct = ((acT.kwh - acP.kwh) / acP.kwh) * 100;
    if (acChangePct > 5) {
      acTrendStr = `⚠️ 空调电费同比上上周 <strong style="color:var(--danger);">上涨 ${Math.abs(acChangePct).toFixed(1)}%</strong> (${acP.kwh.toFixed(1)} 度 → ${acT.kwh.toFixed(1)} 度),请关注。`;
    } else if (acChangePct < -5) {
      acTrendStr = `✅ 空调电费同比上上周 <strong style="color:var(--success);">下降 ${Math.abs(acChangePct).toFixed(1)}%</strong> (${acP.kwh.toFixed(1)} 度 → ${acT.kwh.toFixed(1)} 度)。`;
    } else {
      acTrendStr = `➡️ 空调电费与上上周基本持平 (${acP.kwh.toFixed(1)} 度 → ${acT.kwh.toFixed(1)} 度),变化 ${acChangePct > 0 ? '+' : ''}${acChangePct.toFixed(1)}%。`;
    }
  } else if (acT.kwh > 0) {
    acTrendStr = `🆕 上上周无数据,上周空调用电 ${acT.kwh.toFixed(1)} 度(¥${(acT.kwh * ELECTRICITY_PRICE).toFixed(2)})。`;
  } else {
    acTrendStr = `❄️ 两周内空调未用电。`;
  }

  acResult.innerHTML = `${acTrendStr}
    <br><span style="font-size:12px;color:var(--text-muted);">
    上周日均 ${acDailyT.toFixed(1)} 度/天(¥${(acDailyT * ELECTRICITY_PRICE).toFixed(2)}),
    上上周日均 ${acDailyP.toFixed(1)} 度/天(¥${(acDailyP * ELECTRICITY_PRICE).toFixed(2)})
    </span>`;
  acTrendWrap.style.display = '';

  // ============ 4 块表详细电费趋势 ============
  if (typeof renderWeeklyMeterTrend === 'function') {
    renderWeeklyMeterTrend(targetStart, targetEnd, prevStart, prevEnd);
  }

  // ============ 简易柱状图 ============
  const ctx = document.getElementById('chart-weekly-bar');
  if (ctx && readings.length >= 2) {
    if (_weeklyChart) _weeklyChart.destroy();
    const datasets = mKeys.map(k => ({
      label: METER_META(k).label,
      data: [
        calcPeriodUsage(readings, charges, k, targetStart, targetEnd).kwh,
        calcPeriodUsage(readings, charges, k, prevStart, prevEnd).kwh,
      ],
      backgroundColor: METER_META(k).color + 'cc',
      borderRadius: 4,
    }));
    _weeklyChart = new Chart(ctx.getContext('2d'), {
      type: 'bar',
      data: {
        labels: ['上周', '上上周'],
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, font: { size: 12 } } },
        },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, title: { display: true, text: '用电 (度)' } },
        },
      },
    });
  }
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
    lines.push(`❄️ 空调电费: 上周${acT.kwh.toFixed(1)}度 → 上上周${acP.kwh.toFixed(1)}度,同比${trend}${acChange > 0 ? '+' : ''}${acChange.toFixed(1)}%`);
  } else {
    lines.push(`❄️ 空调电费: 上周${acT.kwh.toFixed(1)}度(上上周无数据)`);
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
