function addDaysToDate(dateStr, days) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + Math.ceil(days));
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}

function renderChargeAlert(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行

  // 共用:三个容器的 HTML 渲染逻辑(独立预警页 / 抄表录入页内联 / 抄表记录页表格上方)
  const renderInto = (container) => {
    if (!container) return;
    if (!readings || readings.length === 0) {
      container.innerHTML = '<div class="empty" style="padding:20px;">录入抄表数据后开始监控 4 块表的余额。</div>';
      return;
    }

    const latest = readings[readings.length - 1];
    const items = CHARGE_METERS.map(m => {
      const multiplier = MULTIPLIER(m.key);
      const remaining = latest[m.key] * multiplier;
      const usage = calcMonthlyDailyUsage(readings, charges, m.key);
      let daysLeft = Infinity, dailyUsage = null, basisLabel = '', hasUsage = false;
      if (usage) {
        dailyUsage = usage.daily;
        daysLeft = dailyUsage > 0 ? remaining / dailyUsage : Infinity;
        basisLabel = usage.basisLabel;
        hasUsage = true;
      }
      return { m, multiplier, remaining, usage, daysLeft, dailyUsage, basisLabel, hasUsage };
    });

    container.innerHTML = `<div class="stat-grid alert-grid">${items.map(({ m, multiplier, remaining, daysLeft, dailyUsage, basisLabel, hasUsage }) => {
      let level, dotColor, statusText;
      if (!hasUsage) { level = 'pending'; dotColor = 'var(--text-muted)'; statusText = '等待数据'; }
      else if (daysLeft < 3) { level = 'danger'; dotColor = '#dc2626'; statusText = '紧急'; }
      else if (daysLeft < 7) { level = 'warn'; dotColor = '#f59e0b'; statusText = '注意'; }
      else { level = 'ok'; dotColor = '#10b981'; statusText = '充足'; }

      let suggestHtml = '';
      if (hasUsage && dailyUsage > 0 && daysLeft < 7) {
        const targetDays = 37;
        const targetKwh = dailyUsage * targetDays;
        const needChargeKwh = Math.max(0, targetKwh - remaining);
        const suggestAmount = needChargeKwh * ELECTRICITY_PRICE;
        suggestHtml = `<span class="suggest-chip">💡 建议充值 ¥ ${suggestAmount.toFixed(0)}</span>`;
      }
      const cls = m.key === 'private_room' ? 'private' : m.key;
      const daysText = hasUsage ? `${daysLeft.toFixed(1)} 天` : '—';
      const dueDateStr = hasUsage && dailyUsage > 0 && daysLeft !== Infinity ? addDaysToDate(latest.date, daysLeft) : '';
      const multiplierHint = multiplier > 1 ? `<span style="opacity:0.6;font-size:10px;">×${multiplier}</span>` : '';
      return `
        <div class="stat-card ${cls} alert-stat-${level}">
          <div class="label">${m.icon} ${m.label} ${multiplierHint}</div>
          <div class="value">${remaining.toFixed(0)}<small>度</small></div>
          <div class="sub" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">
            <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dotColor};margin-right:5px;vertical-align:middle;"></span>${daysText} · ${statusText}</span>
            ${dueDateStr ? `<span style="font-size:11px;opacity:0.85;">预计 ${dueDateStr} 断电</span>` : ''}
            ${suggestHtml}
          </div>
          <div class="sub" style="margin-top:6px;padding-top:6px;border-top:1px dashed var(--border-subtle);font-size:11px;opacity:0.7;">
            ${hasUsage ? `日均 ${dailyUsage.toFixed(1)} 度 · ${basisLabel}` : `至少需要 2 次抄表 + 充值数据`}
          </div>
        </div>
      `;
    }).join('')}</div>`;
  };

  // 三个位置都填充:
  // 1) 抄表录入页内联卡片(保持向后兼容)
  renderInto(document.getElementById('reading-alerts-container'));
  const readingAlertsCard = document.getElementById('reading-alerts-card');
  if (readingAlertsCard) readingAlertsCard.style.display = '';
  // 2) 抄表记录页表格上方(新增)
  renderInto(document.getElementById('reading-record-alerts-container'));
  // 底部 #charge-alerts 容器已删除（与顶部余量预警卡重复），不再渲染
}

function renderStats(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行
  const grid = document.getElementById('stat-grid');

  if (!readings || readings.length === 0) {
    grid.innerHTML = '<div class="empty" style="grid-column: 1/-1;">录入第一条数据后开始统计</div>';
    return;
  }

  // 月份从下拉读取(默认最新月份,可查看历史月份整月用电)
  const statsSel = document.getElementById('stats-month');
  let monthKey = statsSel && statsSel.value ? statsSel.value : '';
  if (!monthKey) {
    const latestDate = new Date(readings[readings.length - 1].date);
    monthKey = `${latestDate.getFullYear()}-${String(latestDate.getMonth() + 1).padStart(2, '0')}`;
  }

  // 当月抄表数据
  const monthData = readings.filter(r => r.date.startsWith(monthKey));
  if (monthData.length === 0) {
    grid.innerHTML = `<div class="empty" style="grid-column: 1/-1;">${monthKey} 当月暂无抄表数据</div>`;
    return;
  }
  // 找当月第一/最后一条
  const monthFirst = monthData[0];
  const monthLast = monthData[monthData.length - 1];

  const monthDays = monthData.length > 1
    ? Math.max(1, (new Date(monthLast.date) - new Date(monthFirst.date)) / 86400000)
    : 1;

  // 累计区间
  const first = readings[0];
  const last = readings[readings.length - 1];
  const totalDays = Math.max(1, (new Date(last.date) - new Date(first.date)) / 86400000);

  let html = '';
  // 复制每月用电用的数据(当前月 + 上月,各区域度数/金额/日均)
  _monthCopyData = { monthKey, per: {}, prev: {}, monthDays, monthTotal: 0, prevTotal: 0, hasPrev: false };
  for (const key of ['hall', 'fire', 'private_room', 'ac']) {
    // 当月用电 = 读数差(月初 - 月末)+ 期间充值
    const monthUsage = monthData.length > 1
      ? realKwh(monthFirst[key] - monthLast[key], key) + sumChargesBetween(charges, key, monthFirst.date, monthLast.date)
      : 0;
    // 累计用电 = 读数差(最早 - 最新)+ 期间充值
    const cumUsage = realKwh(first[key] - last[key], key) + sumChargesBetween(charges, key, first.date, last.date);

    // 上月用电(对比用):取上月的首条/末条,同样 = 读数差 + 期间充值
    let prevUsage = null;
    const prevMonth = prevMonthKey(monthKey);
    const prevData = prevMonth ? readings.filter(r => r.date.startsWith(prevMonth)) : [];
    if (prevData.length > 1) {
      prevUsage = realKwh(prevData[0][key] - prevData[prevData.length - 1][key], key)
        + sumChargesBetween(charges, key, prevData[0].date, prevData[prevData.length - 1].date);
      _monthCopyData.prev[key] = prevUsage;
    }

    _monthCopyData.per[key] = monthUsage;
    _monthCopyData.monthTotal += monthUsage;
    if (prevUsage != null) { _monthCopyData.prevTotal += prevUsage; _monthCopyData.hasPrev = true; }

    const cls = key === 'private_room' ? 'private' : key;
    html += `
      <div class="stat-card ${cls}">
        <div class="label">${LABELS(key)}(当月)</div>
        <div class="value">${monthUsage.toFixed(1)}<small>度</small></div>
        <div class="sub">日均 ${(monthUsage / monthDays).toFixed(1)}</div>
        <div class="sub" style="margin-top:6px; padding-top:6px; border-top:1px dashed var(--border-subtle)">
          累计 ${cumUsage.toFixed(0)} · 日均 ${(cumUsage / totalDays).toFixed(1)}
        </div>
      </div>
    `;
  }

  // 合计
  const monthTotal = monthData.length > 1
    ? ['hall', 'fire', 'private_room', 'ac'].reduce((s, k) => {
        const delta = realKwh(monthFirst[k] - monthLast[k], k);
        const charged = sumChargesBetween(charges, k, monthFirst.date, monthLast.date);
        return s + delta + charged;
      }, 0)
    : 0;
  const cumTotal = ['hall', 'fire', 'private_room', 'ac'].reduce((s, k) => {
    const delta = realKwh(first[k] - last[k], k);
    const charged = sumChargesBetween(charges, k, first.date, last.date);
    return s + delta + charged;
  }, 0);

  // 本月充值金额(从独立的 charges 表算)
  // 用户填的充值度数 = 表度数,需要 ×160 才是实际度数
  const monthCharges = charges.filter(c => c.date.startsWith(monthKey));
  const monthChargeKwh = monthCharges.reduce((s, c) =>
    s + CHARGE_METERS.reduce((ss, m) => ss + realKwh(c[m.key] || 0, m.key), 0), 0);
  const monthChargeYuan = monthChargeKwh * ELECTRICITY_PRICE;

  html += `
    <div class="stat-card total total-wide">
      <div>
        <div class="label">合计(当月)</div>
        <div class="value">${monthTotal.toFixed(1)}<small>度</small></div>
      </div>
      <div class="total-info">
        <div>日均 ${(monthTotal / monthDays).toFixed(1)} 度</div>
        <div>累计 ${cumTotal.toFixed(0)} 度 · 日均 ${(cumTotal / totalDays).toFixed(1)}</div>
        ${monthChargeKwh > 0 ? `<div style="color:var(--warn);font-weight:600;">⚡ 本月已充 ${monthChargeKwh.toFixed(0)} 度 ≈ ¥ ${monthChargeYuan.toFixed(2)}</div>` : ''}
      </div>
    </div>
  `;

  grid.innerHTML = html;
}
