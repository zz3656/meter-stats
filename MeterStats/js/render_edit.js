function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
}

// 充值记录行内编辑
async function enterChargeEditMode(id) {
  const charges = await fetchCharges();
  const c = charges.find(x => x.id === id);
  if (!c) return;
  const tr = document.querySelector(`#charge-table tbody tr[data-charge-id="${id}"]`);
  if (!tr) return;

  tr.classList.add('edit-row');
  tr.innerHTML = `
    <td><input type="date" class="cell-input" id="ce-date" value="${c.date}" /></td>
    ${CHARGE_METERS.map(m => `<td><input type="number" step="0.01" min="0" class="cell-input" id="ce-${m.key}" value="${c[m.key] || ''}" placeholder="0" /></td>`).join('')}
    <td>—</td>
    <td><input type="text" class="cell-input" id="ce-note" value="${escapeHtml(c.note || '')}" placeholder="备注" style="min-width:120px;" /></td>
    <td>
      <button class="save-btn" data-action="save-charge" data-id="${id}">保存</button>
      <button class="cancel-btn" data-action="cancel-charge">取消</button>
    </td>
  `;

  tr.querySelector('[data-action="save-charge"]').addEventListener('click', async () => {
    const newDate = tr.querySelector('#ce-date').value;
    if (!newDate) { showAlert('日期不能为空', 'error'); return; }
    const updated = { date: newDate, note: tr.querySelector('#ce-note').value.trim() };
    for (const m of CHARGE_METERS) {
      const v = parseFloat(tr.querySelector(`#ce-${m.key}`).value);
      updated[m.key] = isNaN(v) ? 0 : v;
    }
    try {
      await updateChargeRemote(id, updated);
      showAlert(`✓ ${id} 已更新`, 'success');
      await refreshAndRender();
    } catch (err) {
      showAlert(`更新失败: ${err.message}`, 'error');
    }
  });

  tr.querySelector('[data-action="cancel-charge"]').addEventListener('click', () => {
    renderAll();
  });
}

// 进入行内编辑模式(抄表 — 仅四表)
async function enterEditMode(date, type = 'reading') {
  const row = CURRENT_READINGS.find(r => r.date === date);
  if (!row) return;

  const tr = document.querySelector(`#history-table tbody tr[data-date="${date}"][data-type="reading"]`);
  if (!tr) return;

  tr.classList.add('edit-row');
  tr.innerHTML = `
    <td><input type="date" class="cell-input" id="edit-date" value="${row.date}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-hall" value="${row.hall ?? ''}" placeholder="大厅" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-fire" value="${row.fire ?? ''}" placeholder="消防" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-private_room" value="${row.private_room ?? ''}" placeholder="包厢" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-ac" value="${row.ac ?? ''}" placeholder="空调" /></td>
    <td><input type="text" class="cell-input" id="edit-note" value="${row.note || ''}" placeholder="备注" /></td>
    <td>
      <button class="save-btn" data-action="save" data-old-date="${date}">保存</button>
      <button class="cancel-btn" data-action="cancel">取消</button>
    </td>
  `;

  // 保存
  tr.querySelector('[data-action="save"]').addEventListener('click', async () => {
    const numE = (id) => {
      const v = tr.querySelector(id).value;
      return v === '' ? null : parseFloat(v);
    };
    const newDate = tr.querySelector('#edit-date').value;
    const newHall = numE('#edit-hall');
    const newFire = numE('#edit-fire');
    const newPrivate = numE('#edit-private_room');
    const newAc = numE('#edit-ac');
    const newNote = tr.querySelector('#edit-note').value.trim();

    if (!newDate) { showAlert('日期不能为空', 'error'); return; }
    const editVals = [newHall, newFire, newPrivate, newAc];
    if (editVals.every(v => v === null)) {
      showAlert('至少填写一块电表的读数', 'error'); return;
    }
    if (editVals.some(v => v !== null && isNaN(v))) {
      showAlert('读数必须是数字', 'error'); return;
    }

    // 如果改了日期,检查新日期是否已存在抄表记录
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
      await updateReadingRemote(date, {
        date: newDate,
        hall: newHall === null ? undefined : newHall,
        fire: newFire === null ? undefined : newFire,
        private_room: newPrivate === null ? undefined : newPrivate,
        ac: newAc === null ? undefined : newAc,
        note: newNote,
      });
      showAlert(`✓ ${date} 抄表已更新为 ${newDate}`, 'success');
      await refreshAndRender();
    } catch (err) {
      showAlert(`更新失败: ${err.message}`, 'error');
    } finally {
      setSubmitting(false);
    }
  });

  // 取消
  tr.querySelector('[data-action="cancel"]').addEventListener('click', () => {
    renderAll();
  });

  // 键盘快捷键:Enter 保存,Esc 取消
  tr.querySelectorAll('.cell-input').forEach(input => {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        tr.querySelector('[data-action="save"]').click();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        tr.querySelector('[data-action="cancel"]').click();
      }
    });
  });
}

// 进入行内编辑模式(水电表底 — 仅总表/分表/水表)
async function enterWaterEditMode(date) {
  const waterAll = await fetchWaterReadings();
  const waterRow = waterAll.find(w => w.date === date);
  if (!waterRow) return;

  // 记录编辑前是否已有水电记录（用于区分"删除"和"不创建"）
  const hasExistingWater = waterRow.main_meter != null || waterRow.sub_meter != null || waterRow.water != null;

  const tr = document.querySelector(`#water-history-table tbody tr[data-date="${date}"][data-type="water"]`);
  if (!tr) return;

  tr.classList.add('edit-row');
  tr.innerHTML = `
    <td><input type="date" class="cell-input" id="edit-date" value="${waterRow.date}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-main_meter" value="${waterRow.main_meter ?? ''}" placeholder="总表" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-sub_meter" value="${waterRow.sub_meter ?? ''}" placeholder="分表" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-water" value="${waterRow.water ?? ''}" placeholder="水表" /></td>
    <td><input type="text" class="cell-input" id="edit-note" value="${waterRow.note || ''}" placeholder="备注" /></td>
    <td>
      <button class="save-btn" data-action="save" data-old-date="${date}">保存</button>
      <button class="cancel-btn" data-action="cancel">取消</button>
    </td>
  `;

  // 保存
  tr.querySelector('[data-action="save"]').addEventListener('click', async () => {
    const numE = (id) => {
      const v = tr.querySelector(id).value;
      return v === '' ? null : parseFloat(v);
    };
    const newDate = tr.querySelector('#edit-date').value;
    const mainMeter = numE('#edit-main_meter');
    const subMeter = numE('#edit-sub_meter');
    const waterVal = numE('#edit-water');
    const newNote = tr.querySelector('#edit-note').value.trim();

    const waterInputEmpty = [mainMeter, subMeter, waterVal].every(v => v === null);
    const waterInputInvalid = [mainMeter, subMeter, waterVal].some(v => v !== null && isNaN(v));
    if (waterInputInvalid) {
      showAlert('读数必须是数字', 'error'); return;
    }
    if (!newDate) { showAlert('日期不能为空', 'error'); return; }

    try {
      if (hasExistingWater) {
        if (waterInputEmpty) {
          // 清空了所有水电字段 → 删除该水电记录
          await deleteWaterReadingRemote(date);
        } else {
          // 修改了水电字段 → 覆盖更新
          const waterData = {
            date: newDate,
            main_meter: mainMeter,
            sub_meter: subMeter,
            water: waterVal,
            note: newNote,
          };
          await saveWaterReadingRemote(waterData);
        }
      } else {
        // 原来没有水电记录，用户新增了 → 创建
        if (!waterInputEmpty) {
          const waterData = {
            date: newDate,
            main_meter: mainMeter,
            sub_meter: subMeter,
            water: waterVal,
            note: newNote,
          };
          await saveWaterReadingRemote(waterData);
        }
      }

      showAlert(`✓ ${date} 水电表底已更新`, 'success');
      await refreshAndRender();
    } catch (err) {
      showAlert(`更新失败: ${err.message}`, 'error');
    } finally {
      setSubmitting(false);
    }
  });

  // 取消
  tr.querySelector('[data-action="cancel"]').addEventListener('click', () => {
    renderAll();
  });

  // 键盘快捷键:Enter 保存,Esc 取消
  tr.querySelectorAll('.cell-input').forEach(input => {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        tr.querySelector('[data-action="save"]').click();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        tr.querySelector('[data-action="cancel"]').click();
      }
    });
  });
}