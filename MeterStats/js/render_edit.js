function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
}

// ========== 通用:检查是否当日记录 ==========
function isToday(dateStr) {
  return dateStr === todayStr();
}

// ========== 通用:非当日编辑二次确认 ==========
async function confirmNonTodayEdit(recordLabel, recordDate) {
  if (isToday(recordDate)) return true;
  const ok = await showModal({
    title: '修改非当日记录',
    icon: '⚠️',
    iconKind: 'warn',
    body: `你正在修改 <strong>${recordDate}</strong> 的记录。<br><span style="opacity:0.7">该记录不是今日录入,请确认修改内容无误后继续。</span>`,
    confirmText: '确认修改',
    confirmKind: 'primary',
  });
  return !!ok;
}

// ========== 充值记录编辑 — 弹窗形式 ==========
async function enterChargeEditMode(id) {
  const charges = await fetchCharges();
  const c = charges.find(x => x.id === id);
  if (!c) return;

  if (!(await confirmNonTodayEdit('充值记录', c.date))) return;

  const setVal = (elId, val) => { const el = document.getElementById(elId); if (el) el.value = val; };
  setVal('charge-edit-date', c.date);
  setVal('charge-edit-hall', c.hall || '');
  setVal('charge-edit-fire', c.fire || '');
  setVal('charge-edit-private_room', c.private_room || '');
  setVal('charge-edit-ac', c.ac || '');
  setVal('charge-edit-note', c.note || '');

  const modalEl = document.getElementById('charge-edit-modal-backdrop');
  const confirmBtn = document.getElementById('charge-edit-confirm');
  const cancelBtn = document.getElementById('charge-edit-close');

  const doSave = async () => {
    if (_submitting) return;
    const date = document.getElementById('charge-edit-date').value;
    if (!date) { showAlert('请选择日期', 'error'); return; }

    const num = (id) => {
      const v = document.getElementById(id).value;
      return v === '' ? 0 : parseFloat(v);
    };

    const updated = {
      date: date,
      hall: num('charge-edit-hall'),
      fire: num('charge-edit-fire'),
      private_room: num('charge-edit-private_room'),
      ac: num('charge-edit-ac'),
      note: document.getElementById('charge-edit-note').value.trim(),
    };

    if (CHARGE_METERS.every(m => updated[m.key] === 0)) {
      showAlert('至少填写一块表的充值度数', 'error');
      return;
    }

    try {
      setSubmitting(true);
      await updateChargeRemote(id, updated);
      showAlert(`✓ ${c.date} 充值记录已更新`, 'success');
      closeChargeEditModal();
      await refreshAndRender();
    } catch (err) {
      showAlert(`更新失败: ${err.message}`, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  // 解绑/绑定事件
  const newConfirm = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
  newConfirm.addEventListener('click', doSave);

  const newCancel = cancelBtn.cloneNode(true);
  cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
  newCancel.addEventListener('click', closeChargeEditModal);

  modalEl.addEventListener('click', function handler(e) {
    if (e.target === modalEl) { closeChargeEditModal(); modalEl.removeEventListener('click', handler); };
  });

  modalEl.classList.add('show');
  document.getElementById('charge-edit-hall')?.focus();
};

function closeChargeEditModal() {
  const modalEl = document.getElementById('charge-edit-modal-backdrop');
  if (modalEl) modalEl.classList.remove('show');
}

// ========== 抄表记录编辑 — 弹窗形式 ==========
async function enterEditMode(date, type = 'reading') {
  if (!(await confirmNonTodayEdit('抄表记录', date))) return;

  const row = CURRENT_READINGS.find(r => r.date === date);
  if (!row) return;

  const setVal = (elId, val) => { const el = document.getElementById(elId); if (el) el.value = val; };
  setVal('reading-edit-date', row.date);
  setVal('reading-edit-hall', row.hall ?? '');
  setVal('reading-edit-fire', row.fire ?? '');
  setVal('reading-edit-private_room', row.private_room ?? '');
  setVal('reading-edit-ac', row.ac ?? '');
  setVal('reading-edit-note', row.note || '');

  const modalEl = document.getElementById('reading-edit-modal-backdrop');
  const confirmBtn = document.getElementById('reading-edit-confirm');
  const cancelBtn = document.getElementById('reading-edit-close');

  const doSave = async () => {
    if (_submitting) return;
    const ids = {
      date: 'reading-edit-date',
      hall: 'reading-edit-hall',
      fire: 'reading-edit-fire',
      private_room: 'reading-edit-private_room',
      ac: 'reading-edit-ac',
      note: 'reading-edit-note',
    };
    const num = (id) => {
      const v = document.getElementById(id).value;
      return v === '' ? null : parseFloat(v);
    };
    const hallV = num(ids.hall), fireV = num(ids.fire), prV = num(ids.private_room), acV = num(ids.ac);
    const allVals = [hallV, fireV, prV, acV];
    if (allVals.every(v => v === null)) { showAlert('请至少填写一块表的读数', 'error'); return; }
    if (allVals.some(v => v !== null && isNaN(v))) { showAlert('读数必须是数字', 'error'); return; }

    const newDate = document.getElementById(ids.date).value;
    if (!newDate) { showAlert('请选择日期', 'error'); return; }

    if (newDate !== date) {
      const conflict = CURRENT_READINGS.find(r => r.date === newDate);
      if (conflict) {
        const ok = await showModal({
          title: '覆盖已有数据',
          icon: '⚠️',
          iconKind: 'warn',
          body: `<strong>${newDate}</strong> 已存在抄表记录,合并(覆盖)它吗?`,
          confirmText: '覆盖',
          confirmKind: 'primary',
        });
        if (!ok) return;
        await deleteReadingRemote(newDate);
      }
    }

    try {
      setSubmitting(true);
      await updateReadingRemote(date, {
        date: newDate,
        hall: hallV === null ? undefined : hallV,
        fire: fireV === null ? undefined : fireV,
        private_room: prV === null ? undefined : prV,
        ac: acV === null ? undefined : acV,
        note: document.getElementById(ids.note).value.trim(),
      });
      showAlert(`✓ ${date} 抄表已更新为 ${newDate}`, 'success');
      closeReadingEditModal();
      await refreshAndRender();
    } catch (err) {
      showAlert(`更新失败: ${err.message}`, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const newConfirm = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
  newConfirm.addEventListener('click', doSave);

  const newCancel = cancelBtn.cloneNode(true);
  cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
  newCancel.addEventListener('click', closeReadingEditModal);

  modalEl.addEventListener('click', function handler(e) {
    if (e.target === modalEl) { closeReadingEditModal(); modalEl.removeEventListener('click', handler); };
  });

  modalEl.classList.add('show');
  document.getElementById('reading-edit-hall')?.focus();
};

function closeReadingEditModal() {
  const modalEl = document.getElementById('reading-edit-modal-backdrop');
  if (modalEl) modalEl.classList.remove('show');
}

// ========== 水电表底编辑 — 弹窗形式 ==========
async function enterWaterEditMode(date) {
  if (!(await confirmNonTodayEdit('水电表底', date))) return;

  const waterAll = await fetchWaterReadings();
  const waterRow = waterAll.find(w => w.date === date);
  if (!waterRow) return;

  const hasExistingWater = waterRow.main_meter != null || waterRow.sub_meter != null || waterRow.water != null;

  const setVal = (elId, val) => { const el = document.getElementById(elId); if (el) el.value = val; };
  setVal('water-edit-date', waterRow.date);
  setVal('water-edit-main_meter', waterRow.main_meter ?? '');
  setVal('water-edit-sub_meter', waterRow.sub_meter ?? '');
  setVal('water-edit-water', waterRow.water ?? '');
  setVal('water-edit-note', waterRow.note || '');

  const modalEl = document.getElementById('water-edit-modal-backdrop');
  const confirmBtn = document.getElementById('water-edit-confirm');
  const cancelBtn = document.getElementById('water-edit-close');

  const doSave = async () => {
    if (_submitting) return;
    const numE = (id) => {
      const v = document.getElementById(id).value;
      return v === '' ? null : parseFloat(v);
    };
    const newDate = document.getElementById('water-edit-date').value;
    const mainMeter = numE('water-edit-main_meter');
    const subMeter = numE('water-edit-sub_meter');
    const waterVal = numE('water-edit-water');
    const newNote = document.getElementById('water-edit-note').value.trim();

    const waterInputEmpty = [mainMeter, subMeter, waterVal].every(v => v === null);
    const waterInputInvalid = [mainMeter, subMeter, waterVal].some(v => v !== null && isNaN(v));
    if (waterInputInvalid) { showAlert('读数必须是数字', 'error'); return; }
    if (!newDate) { showAlert('日期不能为空', 'error'); return; }

    try {
      setSubmitting(true);
      if (hasExistingWater) {
        if (waterInputEmpty) {
          await deleteWaterReadingRemote(date);
        } else {
          await saveWaterReadingRemote({
            date: newDate, main_meter: mainMeter, sub_meter: subMeter,
            water: waterVal, note: newNote,
          });
        }
      } else {
        if (!waterInputEmpty) {
          await saveWaterReadingRemote({
            date: newDate, main_meter: mainMeter, sub_meter: subMeter,
            water: waterVal, note: newNote,
          });
        }
      }
      showAlert(`✓ ${date} 水电表底已更新`, 'success');
      closeWaterEditModal();
      await refreshAndRender();
    } catch (err) {
      showAlert(`更新失败: ${err.message}`, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const newConfirm = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
  newConfirm.addEventListener('click', doSave);

  const newCancel = cancelBtn.cloneNode(true);
  cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
  newCancel.addEventListener('click', closeWaterEditModal);

  modalEl.addEventListener('click', function handler(e) {
    if (e.target === modalEl) { closeWaterEditModal(); modalEl.removeEventListener('click', handler); };
  });

  modalEl.classList.add('show');
  document.getElementById('water-edit-main_meter')?.focus();
};

function closeWaterEditModal() {
  const modalEl = document.getElementById('water-edit-modal-backdrop');
  if (modalEl) modalEl.classList.remove('show');
}
