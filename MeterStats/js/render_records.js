function renderHistory(readings) {
  // ==================== 抄表记录表（仅四表，不含水电） ====================
  const readTbody = document.querySelector('#history-table tbody');
  const readEmpty = document.getElementById('history-empty');
  if (!readTbody) return;

  // 按选中的月份过滤
  const monthSel = document.getElementById('history-month');
  const month = monthSel ? monthSel.value : '';
  const filtered = month ? readings.filter(r => r.date.startsWith(month)) : readings;

  if (!filtered || filtered.length === 0) {
    readTbody.innerHTML = '';
    readEmpty.style.display = 'block';
    readEmpty.textContent = `${month ? month : '全部'} 暂无抄表记录`;
    return;
  }
  readEmpty.style.display = 'none';
  const sortedReadings = [...filtered].sort((a, b) => b.date.localeCompare(a.date));

  readTbody.innerHTML = sortedReadings.map(r => `
    <tr data-date="${r.date}" data-type="reading">
      <td>${r.date}</td>
      <td>${r.hall == null ? '—' : r.hall.toFixed(2)}</td>
      <td>${r.fire == null ? '—' : r.fire.toFixed(2)}</td>
      <td>${r.private_room == null ? '—' : r.private_room.toFixed(2)}</td>
      <td>${r.ac == null ? '—' : r.ac.toFixed(2)}</td>
      <td style="color:var(--text-muted);font-size:12px;">${r.note || '—'}</td>
      <td>
        <button class="edit-btn" data-action="edit-reading" data-date="${r.date}">编辑</button>
        <button class="delete-btn" data-action="delete-reading" data-date="${r.date}" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;">删除</button>
      </td>
    </tr>
  `).join('');

  // 抄表编辑
  readTbody.querySelectorAll('[data-action="edit-reading"]').forEach(btn => {
    btn.addEventListener('click', () => enterEditMode(btn.dataset.date, 'reading'));
  });
  // 抄表删除
  readTbody.querySelectorAll('[data-action="delete-reading"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const date = btn.dataset.date;
      const ok = await showModal({
        title: '删除抄表记录',
        icon: '🗑️',
        body: `确认删除 <strong>${date}</strong> 的抄表记录?<br><span style="opacity:0.7">此操作不可恢复。</span>`,
        confirmText: '删除',
      });
      if (!ok) return;
      try {
        await deleteReadingRemote(date);
        showAlert(`已删除抄表 ${date}`, 'success');
        await refreshAndRender();
      } catch (err) {
        showAlert(`删除失败: ${err.message}`, 'error');
      }
    });
  });

  // 水电表底表总是使用全局 CURRENT_WATER_READINGS（不依赖参数）
  const waterTbody = document.querySelector('#water-history-table tbody');
  const waterEmpty = document.getElementById('water-history-empty');
  if (!waterTbody) return;

  const waterHistoryMonthSel = document.getElementById('water-history-month');
  const waterMonth = waterHistoryMonthSel ? waterHistoryMonthSel.value : '';
  const waterFiltered = waterMonth
    ? (CURRENT_WATER_READINGS || []).filter(w => w.date.startsWith(waterMonth))
    : (CURRENT_WATER_READINGS || []);

  if (!waterFiltered || waterFiltered.length === 0) {
    waterTbody.innerHTML = '';
    waterEmpty.style.display = 'block';
    waterEmpty.textContent = `${waterMonth ? waterMonth : '全部'} 暂无水电表底记录`;
    return;
  }
  waterEmpty.style.display = 'none';
  const sortedWater = [...waterFiltered].sort((a, b) => b.date.localeCompare(a.date));

  waterTbody.innerHTML = sortedWater.map(w => `
    <tr data-date="${w.date}" data-type="water">
      <td>${w.date}</td>
      <td>${w.main_meter == null ? '—' : w.main_meter.toFixed(1)}</td>
      <td>${w.sub_meter == null ? '—' : w.sub_meter.toFixed(1)}</td>
      <td>${w.water == null ? '—' : w.water.toFixed(1)}</td>
      <td style="color:var(--text-muted);font-size:12px;">${w.note || '—'}</td>
      <td>
        <button class="edit-btn" data-action="edit-water" data-date="${w.date}">编辑</button>
        <button class="delete-btn" data-action="delete-water" data-date="${w.date}" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;">删除</button>
      </td>
    </tr>
  `).join('');

  // 水电编辑
  waterTbody.querySelectorAll('[data-action="edit-water"]').forEach(btn => {
    btn.addEventListener('click', () => enterWaterEditMode(btn.dataset.date));
  });
  // 水电删除
  waterTbody.querySelectorAll('[data-action="delete-water"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const date = btn.dataset.date;
      const ok = await showModal({
        title: '删除水电表底',
        icon: '🗑️',
        body: `确认删除 <strong>${date}</strong> 的水电表底记录?<br><span style="opacity:0.7">此操作不可恢复。</span>`,
        confirmText: '删除',
      });
      if (!ok) return;
      try {
        await deleteWaterReadingRemote(date);
        showAlert(`已删除水电表底 ${date}`, 'success');
        await refreshAndRender();
      } catch (err) {
        showAlert(`删除失败: ${err.message}`, 'error');
      }
    });
  });
}

// 充值记录表格(样式与录入历史一致)
function renderChargeLog(charges) {
  const tbody = document.querySelector('#charge-table tbody');
  const empty = document.getElementById('charge-list-empty');
  const summary = document.getElementById('charge-summary');

  // 按选中的月份过滤(下拉只有有充值的月份,默认最后月)
  const monthSel = document.getElementById('charge-month');
  const month = monthSel ? monthSel.value : '';
  const filtered = month ? (charges || []).filter(c => c.date.startsWith(month)) : charges;

  if (!charges || charges.length === 0 || filtered.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    empty.textContent = month ? `${month} 暂无充值记录` : '还没有充值记录';
    summary.style.display = 'none';
    return;
  }
  empty.style.display = 'none';
  summary.style.display = 'flex';

  const sorted = [...filtered].sort((a, b) => b.date.localeCompare(a.date));

  tbody.innerHTML = sorted.map(c => {
    // 用户填的充值度数 = 表度数,需要 ×160 才是实际度数
    const totalKwh = CHARGE_METERS.reduce((s, m) => s + realKwh(c[m.key] || 0, m.key), 0);
    const totalYuan = totalKwh * ELECTRICITY_PRICE;
    const cells = CHARGE_METERS.map(m => {
      const v = c[m.key] || 0;
      return `<td>${v > 0 ? v.toFixed(1) : '—'}</td>`;
    }).join('');
    const noteCell = c.note ? escapeHtml(c.note) : '—';
    return `
      <tr data-charge-id="${c.id}">
        <td>${c.date}</td>
        ${cells}
        <td>¥ ${totalYuan.toFixed(2)}</td>
        <td style="text-align:left;color:var(--text-muted);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${noteCell}">${noteCell}</td>
        <td>
          <button class="edit-btn" data-action="edit-charge" data-id="${c.id}">编辑</button>
          <button class="delete-btn" data-action="delete-charge" data-id="${c.id}" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;font-family:inherit;">删除</button>
        </td>
      </tr>
    `;
  }).join('');

  // 编辑/删除 绑定
  tbody.querySelectorAll('[data-action="edit-charge"]').forEach(btn => {
    btn.addEventListener('click', () => enterChargeEditMode(btn.dataset.id));
  });
  tbody.querySelectorAll('[data-action="delete-charge"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const charges = await fetchCharges();
      const target = charges.find(c => c.id === id);
      if (!target) return;
      const ok = await showModal({
        title: '删除充值记录',
        icon: '🗑️',
        body: `确认删除 <strong>${target.date}</strong> 的充值记录?<br><span style="opacity:0.7">此操作不可恢复。</span>`,
        confirmText: '删除',
      });
      if (!ok) return;
      try {
        await deleteChargeRemote(id);
        showAlert(`已删除 ${target.date} 的充值记录`, 'success');
        await refreshAndRender();
      } catch (err) {
        showAlert(`删除失败: ${err.message}`, 'error');
      }
    });
  });

  // 汇总(本月 = 当前自然月;当月没充值就显示 0)
  const now = new Date();
  const monthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const monthCharges = charges.filter(c => c.date.startsWith(monthKey));
  const monthCount = monthCharges.length;
  // 用户填的充值度数 = 表度数,需要 ×160 才是实际度数
  const monthKwh = monthCharges.reduce((s, c) => s + CHARGE_METERS.reduce((ss, m) => ss + realKwh(c[m.key] || 0, m.key), 0), 0);
  const monthYuan = monthKwh * ELECTRICITY_PRICE;

  document.getElementById('summary-count').textContent = monthCount;
  document.getElementById('summary-kwh').textContent = `${monthKwh.toFixed(0)} 度`;
  document.getElementById('summary-yuan').textContent = `¥ ${monthYuan.toFixed(2)}`;
}
