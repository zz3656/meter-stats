function renderItemTable(items) {
  const tbody = document.querySelector('#item-table tbody');
  if (!tbody) return;
  if (!items || items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">还没有物品,点击上方表单添加</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(it => {
    const safeName = escapeHtml(it.name);
    const safeUnit = escapeHtml(it.unit || '');
    const safeNote = escapeHtml(it.note || '');
    const totalQty = it.qty || 0;
    const lentQty = it.lent_qty || 0;
    const availableQty = totalQty - lentQty;
    const canLend = availableQty > 0;
    const canReturn = lentQty > 0;
    const actionBtns = [];
    if (canLend) {
      actionBtns.push(`<button class="save-btn" data-action="lend-item" data-id="${it.id}" data-name="${safeName}" data-available="${availableQty}" data-unit="${safeUnit}">借出</button>`);
    }
    if (canReturn) {
      actionBtns.push(`<button class="btn btn-secondary btn-sm" data-action="return-item" data-id="${it.id}" data-name="${safeName}" data-lent="${lentQty}" data-unit="${safeUnit}">归还</button>`);
    }
    actionBtns.push(`<button class="del-btn" data-action="del-item" data-id="${it.id}">删除</button>`);
    return `<tr>
      <td>${safeName}</td>
      <td><strong>${totalQty}</strong></td>
      <td>${availableQty}</td>
      <td>${lentQty}</td>
      <td>${safeUnit}</td>
      <td>${safeNote}</td>
      <td>${actionBtns.join(' ')}</td>
    </tr>`;
  }).join('');

  // 绑定删除按钮
  tbody.querySelectorAll('[data-action="del-item"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const ok = await showModal({
        title: '删除物品',
        body: `确定删除该物品?这会从列表移除(已申购入库的不影响)。`,
        icon: '⚠',
        iconKind: 'warn',
        confirmText: '删除',
        confirmKind: 'danger',
      });
      if (!ok) return;
      try {
        await api('DELETE', `/api/items/${id}`);
        showItemAlert('✓ 已删除', 'success');
        await refreshAll();
      } catch (e) {
        showItemAlert('删除失败:' + e.message, 'error');
      }
    });
  });

  // 绑定借出按钮
  tbody.querySelectorAll('[data-action="lend-item"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      const name = btn.dataset.name;
      const available = parseInt(btn.dataset.available);
      const unit = btn.dataset.unit;
      openLendModal(id, name, available, unit);
    });
  });

  // 绑定归还按钮
  tbody.querySelectorAll('[data-action="return-item"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const name = btn.dataset.name;
      const lent = parseInt(btn.dataset.lent);
      const unit = btn.dataset.unit;
      // 打开归还弹窗（可填数量，默认为全部）
      openReturnModal(id, name, lent, unit);
    });
  });
}

// 借出 / 归还 历史记录表（按借出时间倒序，含未归还的在最上面）
function renderLendHistory(items) {
  const tbody = document.querySelector('#lend-history-table tbody');
  const empty = document.getElementById('lend-history-empty');
  if (!tbody) return;

  // 把所有 lend_records 收集成扁平记录，并附上物品名/单位
  const rows = [];
  (items || []).forEach(it => {
    const records = it.lend_records || [];
    records.forEach(r => {
      rows.push({
        ...r,
        item_name: it.name,
        item_unit: it.unit || '',
      });
    });
  });

  if (rows.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  // 借出时间倒序
  rows.sort((a, b) => (b.lend_date || '').localeCompare(a.lend_date || ''));

  const statusText = { lent: '借用中', returned: '已归还' };
  const statusColor = { lent: 'var(--warn)', returned: 'var(--success)' };

  tbody.innerHTML = rows.map(r => {
    const returnQty = (typeof r.return_qty === 'number') ? r.return_qty : 0;
    const returnDate = r.return_date || (r.status === 'returned' ? '—' : '');
    return `<tr>
      <td>${escapeHtml(r.lend_date || '—')}</td>
      <td>${escapeHtml(r.item_name || '—')}</td>
      <td>${escapeHtml(r.borrower || '—')}</td>
      <td>${r.qty ?? 0} ${escapeHtml(r.item_unit || '')}</td>
      <td>${returnQty} ${escapeHtml(r.item_unit || '')}</td>
      <td>${escapeHtml(returnDate || '—')}</td>
      <td><span style="color:${statusColor[r.status] || 'var(--text-muted)'};font-weight:510;">${statusText[r.status] || r.status || '—'}</span></td>
      <td>${escapeHtml(r.note || r.return_note || '—')}</td>
    </tr>`;
  }).join('');
}

// 打开借出弹窗
function openLendModal(id, name, available, unit) {
  document.getElementById('lend-item-id').value = id;
  document.getElementById('lend-item-name').textContent = name;
  document.getElementById('lend-available-qty').textContent = `${available} ${unit}`;
  document.getElementById('lend-qty').value = '';
  document.getElementById('lend-qty').max = available;
  document.getElementById('lend-borrower').value = '';
  document.getElementById('lend-note').value = '';
  document.getElementById('lend-modal-backdrop').classList.add('show');
}

// 关闭借出弹窗
function closeLendModal() {
  document.getElementById('lend-modal-backdrop').classList.remove('show');
}

// 打开归还弹窗（不强制要求借出人）
function openReturnModal(id, name, lent, unit) {
  document.getElementById('return-item-id').value = id;
  document.getElementById('return-item-name').textContent = name;
  document.getElementById('return-lent-qty').textContent = `${lent} ${unit}`;
  document.getElementById('return-qty').value = lent;  // 默认全还
  document.getElementById('return-qty').max = lent;
  document.getElementById('return-note').value = '';
  document.getElementById('return-modal-backdrop').classList.add('show');
}

// 关闭归还弹窗
function closeReturnModal() {
  document.getElementById('return-modal-backdrop').classList.remove('show');
}

// 申购记录表格
function renderPurchaseTable(purchases) {
  const tbody = document.querySelector('#purchase-table tbody');
  if (!tbody) return;
  if (!purchases || purchases.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">还没有申购记录,点击左侧「申购」添加</td></tr>';
    return;
  }
  const statusText = { pending: '待购', purchased: '已购', stocked: '已购买' };
  const statusColor = { pending: 'var(--warn)', purchased: '#2563eb', stocked: 'var(--success)' };

  const sorted = [...purchases].sort((a, b) => b.date.localeCompare(a.date));
  tbody.innerHTML = sorted.map(p => {
    const total = (p.qty || 0) * (p.est_price || 0);
    // 未购买的申购 → 「确认购买」按钮;已购买 → ✓ 标签
    const actionCell = p.status === 'stocked'
      ? '<span style="color:var(--success);font-size:12px;font-weight:600;">✓ 已购买</span>'
      : `<button class="save-btn" data-action="confirm-purchase" data-id="${p.id}">确认购买</button>`;
    return `<tr>
      <td>${p.date}</td>
      <td>${escapeHtml(p.name)}</td>
      <td><strong>${p.qty}</strong> ${escapeHtml(p.unit || '')}</td>
      <td>${total > 0 ? '¥ ' + total.toFixed(2) : '—'}</td>
      <td>${escapeHtml(p.supplier || '—')}</td>
      <td><span style="color:${statusColor[p.status] || 'var(--text-muted)'};font-weight:510;">${statusText[p.status] || p.status}</span></td>
      <td>
        ${actionCell}
        <button class="del-btn" data-action="del-purchase" data-id="${p.id}" style="margin-left:4px;">删除</button>
      </td>
    </tr>`;
  }).join('');

  // 绑定操作按钮
  tbody.querySelectorAll('[data-action="confirm-purchase"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const name = btn.closest('tr').cells[1].textContent;
      const qty = btn.closest('tr').cells[2].textContent.trim();
      const ok = await showModal({
        title: '确认购买',
        body: `确认已购买「<strong>${escapeHtml(name)}</strong>」(${escapeHtml(qty)})?<br><br>确认后:该记录打上「已购买」标签,物品<strong>自动累加</strong>到物品记录。`,
        icon: '🛒',
        iconKind: 'info',
        confirmText: '确认购买',
        confirmKind: 'primary',
      });
      if (!ok) return;
      try {
        await api('PUT', `/api/purchases/${id}/stock`);
        showItemAlert('✓ 已确认购买,数量已自动加入物品记录', 'success');
        await refreshAll();
      } catch (e) {
        showItemAlert('失败:' + e.message, 'error');
      }
    });
  });
  tbody.querySelectorAll('[data-action="del-purchase"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const ok = await showModal({
        title: '删除申购',
        body: '确定删除这条申购记录?',
        icon: '🗑',
        iconKind: 'warn',
        confirmText: '删除',
        confirmKind: 'danger',
      });
      if (!ok) return;
      try {
        await api('DELETE', `/api/purchases/${id}`);
        showItemAlert('✓ 已删除', 'success');
        await refreshAll();
      } catch (e) {
        showItemAlert('删除失败:' + e.message, 'error');
      }
    });
  });
}

// 工作记录表格
function renderDutyTable(dutyList, filterMonth) {
  const tbody = document.querySelector('#duty-table tbody');
  const empty = document.getElementById('duty-list-empty');
  if (!tbody) return;

  if (!dutyList || dutyList.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }

  // 过滤月份
  let filtered = dutyList;
  if (filterMonth && filterMonth !== '') {
    filtered = dutyList.filter(d => d.record_time && d.record_time.startsWith(filterMonth));
  }

  // 按时间倒序
  const sorted = [...filtered].sort((a, b) => (b.record_time || '').localeCompare(a.record_time || ''));

  if (sorted.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }

  if (empty) empty.style.display = 'none';

  tbody.innerHTML = sorted.map(d => {
    const statusColor = d.status === '已处理' ? 'var(--success)' : 'var(--warn)';
    return `<tr>
      <td>${d.record_time || '—'}</td>
      <td>${escapeHtml(d.duty_type || '—')}</td>
      <td>${escapeHtml(d.shift || '—')}</td>
      <td>${escapeHtml(d.fault_area || '—')}</td>
      <td><span style="color:${statusColor};font-weight:510;">${escapeHtml(d.status || '—')}</span></td>
      <td>${escapeHtml(d.note || '—')}</td>
      <td>
        ${d.status === '未处理' ? `<button class="save-btn" data-action="handle-duty" data-id="${d.id}">处理</button>` : ''}
        <button class="del-btn" data-action="del-duty" data-id="${d.id}">删除</button>
      </td>
    </tr>`;
  }).join('');

  // 绑定删除按钮
  tbody.querySelectorAll('[data-action="del-duty"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const ok = await showModal({
        title: '删除记录',
        body: '确定删除这条工作记录?',
        icon: '🗑',
        iconKind: 'warn',
        confirmText: '删除',
        confirmKind: 'danger',
      });
      if (!ok) return;
      try {
        await api('DELETE', `/api/duty/${id}`);
        showAlert('✓ 已删除', 'success');
        await refreshDuty();
      } catch (e) {
        showAlert('删除失败:' + e.message, 'error');
      }
    });
  });

  // 绑定处理按钮
  tbody.querySelectorAll('[data-action="handle-duty"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      const duty = dutyList.find(d => d.id === id);
      if (!duty) return;
      openDutyHandleModal(id, duty);
    });
  });
}

// 刷新工作记录
async function refreshDuty() {
  await fetchDuty();
  const filterMonth = document.getElementById('duty-record-month')?.value || '';
  renderDutyTable(CURRENT_DUTY, filterMonth);
}

// 填充工作记录月份下拉
function populateDutyMonthSelector() {
  const sel = document.getElementById('duty-record-month');
  if (!sel) return;

  const months = new Set();
  CURRENT_DUTY.forEach(d => {
    if (d.record_time) {
      const month = d.record_time.substring(0, 7);
      months.add(month);
    }
  });

  const sorted = [...months].sort().reverse();
  const currentValue = sel.value;
  sel.innerHTML = '<option value="">全部</option>' + sorted.map(m => `<option value="${m}">${m}</option>`).join('');
  if (currentValue && [...months].includes(currentValue)) {
    sel.value = currentValue;
  }
}

// 历史表格(抄表记录)
// 渲染历史表格(抄表记录 + 水电表底合并显示)