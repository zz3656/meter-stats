async function submitItemAdd(source) {
  // source: 'sidebar' | 'modal'
  const ids = source === 'sidebar'
    ? { name: 'item-name', qty: 'item-qty', unit: 'item-unit', note: 'item-note' }
    : { name: 'item-add-name', qty: 'item-add-qty', unit: 'item-add-unit', note: 'item-add-note' };
  const name = document.getElementById(ids.name).value.trim();
  const qty = parseFloat(document.getElementById(ids.qty).value);
  const unit = document.getElementById(ids.unit).value.trim();
  const note = document.getElementById(ids.note).value.trim();
  if (!name) { showItemAlert('请填写物品名称', 'error'); return; }
  if (isNaN(qty) || qty < 0) { showItemAlert('数量必须 ≥ 0', 'error'); return; }
  try {
    await api('POST', '/api/items', { name, qty, unit, note });
    showItemAlert(`✓ ${name} 已添加`, 'success');
    // 清空两个入口的表单
    ['sidebar', 'modal'].forEach(s => {
      const p = s === 'sidebar'
        ? { name: 'item-name', qty: 'item-qty', unit: 'item-unit', note: 'item-note' }
        : { name: 'item-add-name', qty: 'item-add-qty', unit: 'item-add-unit', note: 'item-add-note' };
      document.getElementById(p.name).value = '';
      document.getElementById(p.qty).value = '';
      document.getElementById(p.unit).value = '';
      document.getElementById(p.note).value = '';
    });
    if (source === 'modal') closeItemAddModal();
    await refreshAll();
  } catch (e) {
    showItemAlert('添加失败:' + e.message, 'error');
  }
}

// 申购:共用提交函数
async function submitPurchaseAdd(source) {
  const ids = source === 'sidebar'
    ? { date: 'purchase-date', name: 'purchase-name', qty: 'purchase-qty', unit: 'purchase-unit', price: 'purchase-price', supplier: 'purchase-supplier', note: 'purchase-note' }
    : { date: 'purchase-add-date', name: 'purchase-add-name', qty: 'purchase-add-qty', unit: 'purchase-add-unit', price: 'purchase-add-price', supplier: 'purchase-add-supplier', note: 'purchase-add-note' };
  const date = document.getElementById(ids.date).value;
  const name = document.getElementById(ids.name).value.trim();
  const qty = parseFloat(document.getElementById(ids.qty).value);
  const unit = document.getElementById(ids.unit).value.trim();
  const est_price = parseFloat(document.getElementById(ids.price).value);
  const supplier = document.getElementById(ids.supplier).value.trim();
  const note = document.getElementById(ids.note).value.trim();
  if (!name) { showItemAlert('请填写物品名称', 'error'); return; }
  if (isNaN(qty) || qty <= 0) { showItemAlert('数量必须 > 0', 'error'); return; }
  try {
    await api('POST', '/api/purchases', { date, name, qty, unit, est_price, supplier, note });
    showItemAlert(`✓ 申购已记录,去「申购记录」确认购买`, 'success');
    ['sidebar', 'modal'].forEach(s => {
      const p = s === 'sidebar'
        ? { date: 'purchase-date', name: 'purchase-name', qty: 'purchase-qty', unit: 'purchase-unit', price: 'purchase-price', supplier: 'purchase-supplier', note: 'purchase-note' }
        : { date: 'purchase-add-date', name: 'purchase-add-name', qty: 'purchase-add-qty', unit: 'purchase-add-unit', price: 'purchase-add-price', supplier: 'purchase-add-supplier', note: 'purchase-add-note' };
      document.getElementById(p.date).value = '';
      document.getElementById(p.name).value = '';
      document.getElementById(p.qty).value = '';
      document.getElementById(p.unit).value = '';
      document.getElementById(p.price).value = '';
      document.getElementById(p.supplier).value = '';
      document.getElementById(p.note).value = '';
    });
    if (source === 'modal') closePurchaseAddModal();
    await refreshAll();
  } catch (e) {
    showItemAlert('添加失败:' + e.message, 'error');
  }
}

// 物品录入弹窗
function openItemAddModal() {
  document.getElementById('item-add-modal-backdrop').classList.add('show');
  // 默认日期 / 默认值不重要，物品录入不需要
  document.getElementById('item-add-name')?.focus();
}
function closeItemAddModal() {
  document.getElementById('item-add-modal-backdrop').classList.remove('show');
}
function openPurchaseAddModal() {
  // 默认日期 = 今天
  const dateEl = document.getElementById('purchase-add-date');
  if (dateEl && !dateEl.value) dateEl.value = todayStr();
  document.getElementById('purchase-add-modal-backdrop').classList.add('show');
  document.getElementById('purchase-add-name')?.focus();
}
function closePurchaseAddModal() {
  document.getElementById('purchase-add-modal-backdrop').classList.remove('show');
}

// 侧栏录入页 + 弹窗 提交按钮
document.getElementById('btn-add-item')?.addEventListener('click', () => submitItemAdd('sidebar'));
document.getElementById('item-add-confirm')?.addEventListener('click', () => submitItemAdd('modal'));
document.getElementById('btn-add-purchase')?.addEventListener('click', () => submitPurchaseAdd('sidebar'));
document.getElementById('purchase-add-confirm')?.addEventListener('click', () => submitPurchaseAdd('modal'));

// 弹窗打开按钮（在记录页面 header 上）
document.getElementById('btn-open-item-add')?.addEventListener('click', openItemAddModal);
document.getElementById('btn-open-purchase-add')?.addEventListener('click', openPurchaseAddModal);

// 弹窗关闭按钮
document.getElementById('item-add-close')?.addEventListener('click', closeItemAddModal);
document.getElementById('purchase-add-close')?.addEventListener('click', closePurchaseAddModal);
document.getElementById('item-add-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('item-add-modal-backdrop')) closeItemAddModal();
});
document.getElementById('purchase-add-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('purchase-add-modal-backdrop')) closePurchaseAddModal();
});

// 值班录入:共用提交函数(侧栏录入页 + 工作记录页弹窗 都用)
async function submitDutyAdd(source) {
  // source: 'sidebar' | 'modal'
  const ids = source === 'sidebar'
    ? { type: 'duty-type', time: 'duty-time', shift: 'duty-shift', status: 'duty-status', fault_area: 'duty-fault-area', note: 'duty-note' }
    : { type: 'duty-add-type', time: 'duty-add-time', shift: 'duty-add-shift', status: 'duty-add-status', fault_area: 'duty-add-fault-area', note: 'duty-add-note' };

  const duty_type = document.getElementById(ids.type).value;
  const raw_time = document.getElementById(ids.time).value;
  const shift = document.getElementById(ids.shift).value;
  const status = document.querySelector(`input[name="${ids.status}"]:checked`)?.value;
  const fault_area = document.getElementById(ids.fault_area).value.trim();
  const note = document.getElementById(ids.note).value.trim();

  if (!duty_type) { showAlert('请选择类型', 'error'); return; }
  if (!shift) { showAlert('请选择班次', 'error'); return; }
  if (!status) { showAlert('请选择处理状态', 'error'); return; }

  // datetime-local → 后端期望格式 "YYYY-MM-DD HH:MM:SS"
  let record_time = raw_time ? raw_time.replace('T', ' ') + ':00' : nowDateTimeStr();

  try {
    await api('POST', '/api/duty', { duty_type, record_time, shift, status, fault_area, note });
    showAlert('✓ 值班记录已添加', 'success');
    // 重置两个入口的表单
    ['sidebar', 'modal'].forEach(s => {
      const p = s === 'sidebar'
        ? { type: 'duty-type', time: 'duty-time', shift: 'duty-shift', status: 'duty-status', fault_area: 'duty-fault-area', note: 'duty-note' }
        : { type: 'duty-add-type', time: 'duty-add-time', shift: 'duty-add-shift', status: 'duty-add-status', fault_area: 'duty-add-fault-area', note: 'duty-add-note' };
      document.getElementById(p.type).value = '';
      document.getElementById(p.shift).value = '';
      document.querySelectorAll(`input[name="${p.status}"]`).forEach(r => r.checked = false);
      document.getElementById(p.fault_area).value = '';
      document.getElementById(p.note).value = '';
      const t = document.getElementById(p.time);
      if (t) t.value = nowDateTimeLocalStr();
    });
    if (source === 'modal') closeDutyAddModal();
    if (source === 'sidebar') document.getElementById('duty-type')?.focus();
    await refreshDuty();
    populateDutyMonthSelector();
  } catch (e) {
    showAlert('添加失败:' + e.message, 'error');
  }
}

// 值班录入弹窗
function openDutyAddModal() {
  const timeEl = document.getElementById('duty-add-time');
  if (timeEl) timeEl.value = nowDateTimeLocalStr();
  document.getElementById('duty-add-modal-backdrop').classList.add('show');
  document.getElementById('duty-add-type')?.focus();
}
function closeDutyAddModal() {
  document.getElementById('duty-add-modal-backdrop').classList.remove('show');
}

// 侧栏录入页 + 弹窗 提交按钮
document.getElementById('duty-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  await submitDutyAdd('sidebar');
});
document.getElementById('duty-add-confirm')?.addEventListener('click', () => submitDutyAdd('modal'));

// 弹窗打开按钮(在工作记录页面 header 上)
document.getElementById('btn-open-duty-add')?.addEventListener('click', openDutyAddModal);

// 弹窗关闭
document.getElementById('duty-add-close')?.addEventListener('click', closeDutyAddModal);
document.getElementById('duty-add-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('duty-add-modal-backdrop')) closeDutyAddModal();
});

// 工作记录:月份筛选
document.getElementById('duty-record-month')?.addEventListener('change', (e) => {
  renderDutyTable(CURRENT_DUTY, e.target.value);
});

// ===== 工作记录处理弹窗 =====
function openDutyHandleModal(id, duty) {
  document.getElementById('duty-handle-id').value = id;
  document.getElementById('duty-handle-original-type').textContent = duty.duty_type || '—';
  document.getElementById('duty-handle-original-area').textContent = duty.fault_area || '—';
  // 处理时间默认当前
  const timeEl = document.getElementById('duty-handle-time');
  if (timeEl) timeEl.value = nowDateTimeLocalStr();
  document.getElementById('duty-handle-shift').value = ''; // 重置为选择
  document.getElementById('duty-handle-method').value = '';
  document.getElementById('duty-handle-note').value = '';
  document.getElementById('duty-handle-modal-backdrop').classList.add('show');
  document.getElementById('duty-handle-method')?.focus();
}
function closeDutyHandleModal() {
  document.getElementById('duty-handle-modal-backdrop').classList.remove('show');
}

async function submitDutyHandle() {
  const id = document.getElementById('duty-handle-id').value;
  const raw_time = document.getElementById('duty-handle-time').value;
  const handle_shift = document.getElementById('duty-handle-shift').value;
  const handle_method = document.getElementById('duty-handle-method').value.trim();
  const note = document.getElementById('duty-handle-note').value.trim();

  if (!handle_shift) { showAlert('请选择处理班次', 'error'); return; }
  if (!handle_method) { showAlert('请填写处理方案', 'error'); return; }

  let handle_time = raw_time ? raw_time.replace('T', ' ') + ':00' : nowDateTimeStr();

  try {
    await api('POST', `/api/duty/${id}/handle`, {
      handle_time,
      handle_shift,
      handle_method,
      note: note || '',
    });
    showAlert('✓ 记录已处理,已生成处理记录', 'success');
    closeDutyHandleModal();
    await refreshDuty();
  } catch (e) {
    showAlert('处理失败:' + e.message, 'error');
  }
}

// 处理弹窗: 提交按钮
document.getElementById('duty-handle-confirm')?.addEventListener('click', submitDutyHandle);
// 处理弹窗: 关闭按钮
document.getElementById('duty-handle-close')?.addEventListener('click', closeDutyHandleModal);
// 处理弹窗: 点击遮罩关闭
document.getElementById('duty-handle-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('duty-handle-modal-backdrop')) closeDutyHandleModal();
});