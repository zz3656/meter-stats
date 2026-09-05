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
  // 3) 老的独立 #charge-alerts 容器(兼容外部调用)
  renderInto(document.getElementById('charge-alerts'));
}

// 统计卡片 — 用新算法(读数差 + 期间充值)