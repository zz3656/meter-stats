
// ===== 充值计算弹窗 =====
// 注意:.modal-backdrop 默认 opacity:0 + pointer-events:none,必须加 .show 类才可见可点
function openTopupModal() {
  const backdrop = document.getElementById('topup-modal-backdrop');
  if (!backdrop) return;
  backdrop.classList.add('show');
  recalcTopup();
  const daysEl = document.getElementById('topup-days-modal');
  if (daysEl) { daysEl.focus(); daysEl.select(); }
}
function closeTopupModal() {
  const backdrop = document.getElementById('topup-modal-backdrop');
  if (backdrop) backdrop.classList.remove('show');
}

// 充值计算摘要卡片 — 充值录入页内联显示
function refreshChargeTopupSummary() {
  const container = document.getElementById('charge-topup-container');
  const card = document.getElementById('charge-topup-summary');
  if (!container || !card) return;

  const rs = (CURRENT_READINGS || []).filter(r => r.hall != null);
  if (!rs || rs.length === 0) {
    container.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:12px;">录入抄表数据后显示计算结果</div>';
    card.style.display = '';  // 始终显示(空数据提示)
    return;
  }

  const latest = rs[rs.length - 1];
  let items = [];

  for (const m of CHARGE_METERS) {
    const multiplier = MULTIPLIER(m.key);
    const remaining = latest[m.key] * multiplier;
    const usage = calcMonthlyDailyUsage(rs, CURRENT_CHARGES, m.key);
    let daysLeft = Infinity;
    let dailyUsage = null;
    let basisLabel = '';
    let hasUsage = false;

    if (usage) {
      dailyUsage = usage.daily;
      daysLeft = dailyUsage > 0 ? remaining / dailyUsage : Infinity;
      basisLabel = usage.basisLabel;
      hasUsage = true;
    }

    items.push({ m, multiplier, remaining, daysLeft, dailyUsage, basisLabel, hasUsage });
  }

  // 颜色 + 图标
  function getStatusInfo(item) {
    const { hasUsage, daysLeft } = item;
    if (!hasUsage) return { level: 'pending', dotColor: 'var(--text-muted)', statusText: '等待数据' };
    if (daysLeft < 3) return { level: 'danger', dotColor: '#dc2626', statusText: '紧急' };
    if (daysLeft < 7) return { level: 'warn', dotColor: '#f59e0b', statusText: '注意' };
    return { level: 'ok', dotColor: '#10b981', statusText: '充足' };
  }

  card.style.display = '';
  container.innerHTML = `<div class="stat-grid" style="grid-template-columns:repeat(4, 1fr);">
    ${items.map(({ m, multiplier, remaining, daysLeft, dailyUsage, basisLabel, hasUsage }) => {
      const { level, dotColor, statusText } = getStatusInfo({ hasUsage, daysLeft });
      const cls = m.key === 'private_room' ? 'private' : m.key;
      const daysText = hasUsage ? `${daysLeft.toFixed(1)} 天` : '—';
      const multiplierHint = multiplier > 1 ? `<span style="opacity:0.6;font-size:10px;">×${multiplier}</span>` : '';
      return `
        <div class="stat-card ${cls} alert-stat-${level}" style="cursor:pointer;" onclick="openTopupForMeter('${m.key}')">
          <div class="label">${m.icon} ${m.label} ${multiplierHint}</div>
          <div class="value">${remaining.toFixed(0)}<small>度</small></div>
          <div class="sub">
            <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${dotColor};margin-right:5px;vertical-align:middle;"></span>${daysText} · ${statusText}</span>
          </div>
          <div style="font-size:10px;color:var(--text-muted);margin-top:4px;">点击计算充值</div>
        </div>
      `;
    }).join('')}
  </div>
  <div style="font-size:11px;color:var(--text-muted);margin-top:8px;text-align:center;">
    💡 点击任意卡片可快速计算该表的充值金额
  </div>`;
}

// 从摘要卡片打开弹窗并预填某块表的值
function openTopupForMeter(meterKey) {
  openTopupModal();
  // 弹窗打开后预填该表的值
  setTimeout(() => {
    const daysEl = document.getElementById('topup-days-modal');
    const resultEl = document.getElementById('topup-result-modal');
    if (!daysEl || !resultEl) return;
    // 找到对应表的输入框
    const meterInput = resultEl.querySelector(`.topup-meter[data-mult="${MULTIPLIER(meterKey)}"]`);
    if (meterInput) {
      meterInput.focus();
      meterInput.select();
    }
  }, 100);
}
// 按预充天数 × 本月日均,算出每块表需充值表读数 + 金额(实时)
function recalcTopup() {
  const daysEl = document.getElementById('topup-days-modal');
  const resultEl = document.getElementById('topup-result-modal');
  const totalEl = document.getElementById('topup-total-modal');
  if (!daysEl || !resultEl || !totalEl) return;
  const days = parseFloat(daysEl.value);
  const rs = (CURRENT_READINGS || []).filter(r => r.hall != null);
  if (!days || days <= 0 || rs.length === 0) {
    resultEl.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">请输入预充天数(≥1)</div>';
    totalEl.value = '';
    return;
  }
  let totalMeter = 0, totalActual = 0, totalYuan = 0;
  const rows = CHARGE_METERS.map(m => {
    const usage = calcMonthlyDailyUsage(rs, CURRENT_CHARGES, m.key);
    const daily = usage ? usage.daily : 0;  // 实际度数/天
    const actualKwh = daily * days;          // 实际度数(读数 × 倍率)
    const meterVal = actualKwh / MULTIPLIER(m.key);  // 表读数(充值录入值)
    const yuan = actualKwh * ELECTRICITY_PRICE;
    totalMeter += meterVal;
    totalActual += actualKwh;
    totalYuan += yuan;
    const basis = usage ? `<span style="opacity:.7">${usage.basisLabel || '本月日均'}</span>` : '暂无日均数据';
    const mult = MULTIPLIER(m.key);
    const daysLeft = daily > 0 ? (actualKwh / daily) : 0;
    return `
      <div class="topup-meter-card" data-daily="${daily.toFixed(4)}">
        <div class="topup-meter-row">
          <span class="topup-meter-name">${m.meterNo}${m.label}</span>
          <input type="number" class="field-control topup-meter" value="${Math.round(meterVal)}" step="1" data-mult="${mult}"
                 title="表读数(充值录入值,可输入取整,自动反算其他值)">
          <span class="topup-mult">×${mult}</span>
          <input type="number" class="field-control topup-actual" value="${Math.round(actualKwh)}" step="1" data-mult="${mult}"
                 title="实际度数(可输入取整充值,自动反算其他值)">
          <span class="topup-yuan">≈ ¥${Math.round(yuan)}</span>
        </div>
        <div class="topup-meter-meta">
          日均 ${Math.round(daily)} 度/天 ${basis}
          <span class="topup-daysleft">≈ 可用 ${Math.round(daysLeft)} 天</span>
        </div>
      </div>`;
  }).join('');
  resultEl.innerHTML = rows;
  updateTopupTotal();
}

// 更新某块表的"可用天数"显示: 实际度数 ÷ 本月日均
function updateTopupDaysLeft(row) {
  const daysSpan = row.querySelector('.topup-daysleft');
  if (!daysSpan) return;
  const actual = parseFloat(row.querySelector('.topup-actual').value) || 0;
  const daily = parseFloat(row.getAttribute('data-daily')) || 0;
  daysSpan.textContent = daily > 0 ? `≈ 可用 ${Math.round(actual / daily)} 天` : '≈ 可用 — 天';
}

// 用户输入表读数(取整充值)→ 反向计算该块表的实际度数 + 金额,并刷新合计
function onTopupMeterInput(inputEl) {
  const row = inputEl.closest('div[style*="background"]');
  const actualInput = row.querySelector('.topup-actual');
  const yuanSpan = row.querySelector('.topup-yuan');
  const mult = parseFloat(inputEl.getAttribute('data-mult'));
  const meter = parseFloat(inputEl.value) || 0;
  const actual = Math.round(meter * mult);
  actualInput.value = actual;
  yuanSpan.textContent = `≈ ¥${Math.round(actual * ELECTRICITY_PRICE)}`;
  updateTopupDaysLeft(row);
  updateTopupTotal();
}
// 用户输入实际度数(取整充值)→ 反向计算该块表的表读数 + 金额,并刷新合计
function onTopupActualInput(inputEl) {
  const row = inputEl.closest('div[style*="background"]');
  const meterInput = row.querySelector('.topup-meter');
  const yuanSpan = row.querySelector('.topup-yuan');
  const mult = parseFloat(inputEl.getAttribute('data-mult'));
  const actual = parseFloat(inputEl.value) || 0;
  meterInput.value = Math.round(actual / mult);
  yuanSpan.textContent = `≈ ¥${Math.round(actual * ELECTRICITY_PRICE)}`;
  updateTopupDaysLeft(row);
  updateTopupTotal();
}
// 遍历所有行累加合计(实际度数 + 表读数 + 金额)
function updateTopupTotal() {
  const totalEl = document.getElementById('topup-total-modal');
  if (!totalEl) return;
  let totalActual = 0, totalMeter = 0, totalYuan = 0;
  document.querySelectorAll('.topup-actual').forEach(inp => {
    const mult = parseFloat(inp.getAttribute('data-mult'));
    const actual = parseFloat(inp.value) || 0;
    totalActual += actual;
    totalMeter += actual / mult;
    totalYuan += actual * ELECTRICITY_PRICE;
  });
  totalEl.value = `合计 ${Math.round(totalActual)} 度(实际) ≈ ¥ ${Math.round(totalYuan)}  (表读数 ${Math.round(totalMeter)})`;
}

// 充值计算弹窗绑定:点击「余量预警」卡片内的按钮打开弹窗
document.addEventListener('click', e => {
  if (e.target.id === 'btn-topup-calc' || e.target.id === 'btn-topup-calc-reading') openTopupModal();
});
document.getElementById('topup-close').addEventListener('click', closeTopupModal);
const topupDaysModal = document.getElementById('topup-days-modal');
if (topupDaysModal) topupDaysModal.addEventListener('input', recalcTopup);
// 实际度数输入框(动态生成)→ 事件委托,输入时反向计算
const topupResultModal = document.getElementById('topup-result-modal');
if (topupResultModal) {
  topupResultModal.addEventListener('input', e => {
    if (!e.target.classList) return;
    if (e.target.classList.contains('topup-actual')) {
      onTopupActualInput(e.target);
    } else if (e.target.classList.contains('topup-meter')) {
      onTopupMeterInput(e.target);
    }
  });
}
document.getElementById('topup-modal-backdrop').addEventListener('click', e => {
  if (e.target === document.getElementById('topup-modal-backdrop')) closeTopupModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('topup-modal-backdrop').classList.contains('show')) closeTopupModal();
});

// 借出弹窗事件
document.getElementById('lend-close').addEventListener('click', closeLendModal);
document.getElementById('lend-modal-backdrop').addEventListener('click', e => {
  if (e.target === document.getElementById('lend-modal-backdrop')) closeLendModal();
});
document.getElementById('return-close')?.addEventListener('click', closeReturnModal);
document.getElementById('return-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('return-modal-backdrop')) closeReturnModal();
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (document.getElementById('lend-modal-backdrop')?.classList.contains('show')) closeLendModal();
  else if (document.getElementById('return-modal-backdrop')?.classList.contains('show')) closeReturnModal();
  else if (document.getElementById('item-add-modal-backdrop')?.classList.contains('show')) closeItemAddModal();
  else if (document.getElementById('purchase-add-modal-backdrop')?.classList.contains('show')) closePurchaseAddModal();
  else if (document.getElementById('duty-add-modal-backdrop')?.classList.contains('show')) closeDutyAddModal();
  else if (document.getElementById('reading-add-modal-backdrop')?.classList.contains('show')) closeReadingAddModal();
  else if (document.getElementById('charge-add-modal-backdrop')?.classList.contains('show')) closeChargeAddModal();
});
document.getElementById('lend-confirm').addEventListener('click', async () => {
  const id = document.getElementById('lend-item-id').value;
  const qty = parseInt(document.getElementById('lend-qty').value);
  const borrower = document.getElementById('lend-borrower').value.trim();
  const note = document.getElementById('lend-note').value.trim();

  if (!qty || qty <= 0) {
    showItemAlert('请输入有效的借出数量', 'error');
    return;
  }
  if (!borrower) {
    showItemAlert('请输入借出人', 'error');
    return;
  }

  try {
    await api('PUT', `/api/items/${id}/lend`, { qty, borrower, note });
    showItemAlert('✓ 借出成功', 'success');
    closeLendModal();
    await refreshAll();
  } catch (e) {
    showItemAlert('借出失败:' + e.message, 'error');
  }
});
document.getElementById('return-confirm')?.addEventListener('click', async () => {
  const id = document.getElementById('return-item-id').value;
  const qty = parseFloat(document.getElementById('return-qty').value);
  const note = document.getElementById('return-note').value.trim();

  if (!qty || qty <= 0) {
    showItemAlert('请输入有效的归还数量', 'error');
    return;
  }

  try {
    await api('PUT', `/api/items/${id}/return`, { qty, note });
    showItemAlert('✓ 已归还', 'success');
    closeReturnModal();
    await refreshAll();
  } catch (e) {
    showItemAlert('归还失败:' + e.message, 'error');
  }
});

// 月度报告复制:点击后按钮变「已复制」禁用,3秒后恢复(与每日/每月用电同款反馈)
const btnCopyReport = document.getElementById('btn-copy-report');
btnCopyReport.addEventListener('click', () => {
  if (!_currentReport) return;
  const original = btnCopyReport.textContent;
  btnCopyReport.disabled = true;
  btnCopyReport.textContent = '✓ 已复制';
  copyReportTSV(_currentReport);
  setTimeout(() => {
    btnCopyReport.disabled = false;
    btnCopyReport.textContent = original;
  }, 3000);
});

// 每月用电复制:点击后按钮变「已复制」禁用,3秒后恢复
const btnCopyMonth = document.getElementById('btn-copy-month');
btnCopyMonth.addEventListener('click', () => {
  const original = btnCopyMonth.textContent;
  btnCopyMonth.disabled = true;
  btnCopyMonth.textContent = '✓ 已复制';
  copyMonthUsage();
  setTimeout(() => {
    btnCopyMonth.disabled = false;
    btnCopyMonth.textContent = original;
  }, 3000);
});

// 单天用电复制(群里汇报前天数据用):点击后按钮变「已复制」禁用,3秒后恢复
const btnCopyDay = document.getElementById('btn-copy-day');
btnCopyDay?.addEventListener('click', () => {
  const original = btnCopyDay.textContent;
  btnCopyDay.disabled = true;
  btnCopyDay.textContent = '✓ 已复制';
  copyDayUsage();
  setTimeout(() => {
    btnCopyDay.disabled = false;
    btnCopyDay.textContent = original;
  }, 3000);
});

// 单天汇报下拉切换 → 重渲染单日占比饼图
document.getElementById('day-copy-date')?.addEventListener('change', (e) => {
  renderDailyPie(e.target.value);
});