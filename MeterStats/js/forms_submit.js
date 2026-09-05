
// ===== 表单处理 =====
// 抄表录入共用函数（侧栏录入页 + 抄表记录页弹窗 都用）
async function submitReadingAdd(source) {
  const ids = source === 'sidebar'
    ? { date: 'date', hall: 'hall', fire: 'fire', private_room: 'private_room', ac: 'ac', note: 'entry-note' }
    : { date: 'reading-add-date', hall: 'reading-add-hall', fire: 'reading-add-fire', private_room: 'reading-add-private_room', ac: 'reading-add-ac', note: 'reading-add-note' };
  const num = (id) => {
    const v = document.getElementById(id).value;
    return v === '' ? null : parseFloat(v);
  };
  const hallV = num(ids.hall), fireV = num(ids.fire), prV = num(ids.private_room), acV = num(ids.ac);
  const allVals = [hallV, fireV, prV, acV];
  if (allVals.every(v => v === null)) { showAlert('请至少填写一块表的读数', 'error'); return; }
  if (allVals.some(v => v !== null && isNaN(v))) { showAlert('读数必须是数字', 'error'); return; }
  const row = {
    date: document.getElementById(ids.date).value,
    hall: hallV, fire: fireV, private_room: prV, ac: acV,
    note: document.getElementById(ids.note).value.trim(),
  };
  if (!row.date) { showAlert('请选择日期', 'error'); return; }

  const all = await fetchReadings();
  const existing = all.find(r => r.date === row.date);
  if (existing) {
    const ok = await showModal({
      title: '覆盖已有数据',
      icon: '⚠️',
      iconKind: 'warn',
      body: `<strong>${row.date}</strong> 已存在数据,是否覆盖?<br><br>
        <span style="opacity:0.7">现有:</span> 大厅 ${existing.hall} · 消防 ${existing.fire} · 包厢 ${existing.private_room} · 空调 ${existing.ac}<br>
        <span style="opacity:0.7">新数据:</span> 大厅 ${row.hall} · 消防 ${row.fire} · 包厢 ${row.private_room} · 空调 ${row.ac}`,
      confirmText: '覆盖', confirmKind: 'primary',
    });
    if (!ok) return;
  }

  try {
    await saveReadingRemote(row);
    showAlert(`✓ ${row.date} 已保存`, 'success');
    ['sidebar', 'modal'].forEach(s => {
      const p = s === 'sidebar'
        ? { date: 'date', hall: 'hall', fire: 'fire', private_room: 'private_room', ac: 'ac', note: 'entry-note' }
        : { date: 'reading-add-date', hall: 'reading-add-hall', fire: 'reading-add-fire', private_room: 'reading-add-private_room', ac: 'reading-add-ac', note: 'reading-add-note' };
      ['hall', 'fire', 'private_room', 'ac', 'note'].forEach(k => document.getElementById(p[k]).value = '');
    });
    if (source === 'modal') closeReadingAddModal();
    await refreshAndRender();
  } catch (err) {
    showAlert(`保存失败: ${err.message}`, 'error');
  }
}

// 充值录入共用函数
async function submitChargeAdd(source) {
  const ids = source === 'sidebar'
    ? { date: 'charge-date', hall: 'charge-hall', fire: 'charge-fire', private_room: 'charge-private_room', ac: 'charge-ac', note: 'charge-note' }
    : { date: 'charge-add-date', hall: 'charge-add-hall', fire: 'charge-add-fire', private_room: 'charge-add-private_room', ac: 'charge-add-ac', note: 'charge-add-note' };
  const date = document.getElementById(ids.date).value;
  if (!date) { showAlert('请选择充值日期', 'error'); return; }

  const charge = {
    date: date,
    hall: parseFloat(document.getElementById(ids.hall).value) || 0,
    fire: parseFloat(document.getElementById(ids.fire).value) || 0,
    private_room: parseFloat(document.getElementById(ids.private_room).value) || 0,
    ac: parseFloat(document.getElementById(ids.ac).value) || 0,
    note: document.getElementById(ids.note).value.trim(),
  };
  if (CHARGE_METERS.every(m => charge[m.key] === 0)) {
    showAlert('至少填写一块表的充值度数', 'error');
    return;
  }
  try {
    await saveChargeRemote(charge);
    showAlert(`✓ ${date} 充值记录已保存`, 'success');
    ['sidebar', 'modal'].forEach(s => {
      const p = s === 'sidebar'
        ? { date: 'charge-date', hall: 'charge-hall', fire: 'charge-fire', private_room: 'charge-private_room', ac: 'charge-ac', note: 'charge-note' }
        : { date: 'charge-add-date', hall: 'charge-add-hall', fire: 'charge-add-fire', private_room: 'charge-add-private_room', ac: 'charge-add-ac', note: 'charge-add-note' };
      ['hall', 'fire', 'private_room', 'ac', 'note'].forEach(k => document.getElementById(p[k]).value = '');
    });
    if (source === 'modal') closeChargeAddModal();
    await refreshAndRender();
  } catch (err) {
    showAlert(`保存失败: ${err.message}`, 'error');
  }
}

// 水电录入共用函数
async function submitUtilityAdd(source) {
  const ids = source === 'sidebar'
    ? { date: 'utility-date', main: 'main_meter', sub: 'sub_meter', water: 'water', note: 'utility-note' }
    : { date: 'utility-add-date', main: 'utility-add-main_meter', sub: 'utility-add-sub_meter', water: 'utility-add-water', note: 'utility-add-note' };
  const date = document.getElementById(ids.date).value;
  if (!date) { showAlert('请选择抄表日期', 'error'); return; }
  const numU = (id) => {
    const v = document.getElementById(id).value;
    return v === '' ? null : parseFloat(v);
  };
  const mainV = numU(ids.main), subV = numU(ids.sub), waterV = numU(ids.water);
  const vals = [mainV, subV, waterV];
  if (vals.every(v => v === null)) { showAlert('请至少填写总表/分表/水表一项', 'error'); return; }
  if (vals.some(v => v !== null && isNaN(v))) { showAlert('读数必须是数字', 'error'); return; }
  const row = {
    date: date,
    main_meter: mainV,
    sub_meter: subV,
    water: waterV,
    note: document.getElementById(ids.note).value.trim(),
  };

  const all = await fetchWaterReadings();
  const existing = all.find(r => r.date === row.date);
  if (existing) {
    const ok = await showModal({
      title: '覆盖已有数据',
      icon: '⚠️',
      iconKind: 'warn',
      body: `<strong>${row.date}</strong> 已有水电表底,是否覆盖?<br><br>
        <span style="opacity:0.7">现有:</span> 总表 ${existing.main_meter ?? '—'} · 分表 ${existing.sub_meter ?? '—'} · 水表 ${existing.water ?? '—'}<br>
        <span style="opacity:0.7">新数据:</span> 总表 ${row.main_meter ?? '—'} · 分表 ${row.sub_meter ?? '—'} · 水表 ${row.water ?? '—'}`,
      confirmText: '覆盖', confirmKind: 'primary',
    });
    if (!ok) return;
  }
  try {
    await saveWaterReadingRemote(row);
    showAlert(`✓ ${date} 水电已保存`, 'success');
    ['sidebar', 'modal'].forEach(s => {
      const p = s === 'sidebar'
        ? { date: 'utility-date', main: 'main_meter', sub: 'sub_meter', water: 'water', note: 'utility-note' }
        : { date: 'utility-add-date', main: 'utility-add-main_meter', sub: 'utility-add-sub_meter', water: 'utility-add-water', note: 'utility-add-note' };
      ['main', 'sub', 'water', 'note'].forEach(k => document.getElementById(p[k]).value = '');
    });
    if (source === 'modal') closeReadingAddModal();
    await refreshAndRender();
  } catch (err) {
    showAlert(`保存失败: ${err.message}`, 'error');
  }
}

// 弹窗 open/close — 抄表/水电 合并到一个弹窗,通过 tab 切换
let currentReadingTab = 'reading';  // 'reading' | 'utility'

function switchReadingTab(tab) {
  currentReadingTab = tab;
  const tabs = document.querySelectorAll('#reading-add-tabs .tab-btn');
  tabs.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
  const panels = document.querySelectorAll('#reading-add-modal-backdrop .tab-panel');
  panels.forEach(p => p.style.display = (p.dataset.panel === tab ? '' : 'none'));
}

function openReadingAddModal() {
  // 默认显示「抄表录入」tab
  switchReadingTab('reading');
  const d = document.getElementById('reading-add-date');
  if (d && !d.value) d.value = todayStr();
  document.getElementById('reading-add-modal-backdrop').classList.add('show');
  document.getElementById('reading-add-hall')?.focus();
}
function closeReadingAddModal() {
  document.getElementById('reading-add-modal-backdrop').classList.remove('show');
}
function openChargeAddModal() {
  const d = document.getElementById('charge-add-date');
  if (d && !d.value) d.value = todayStr();
  document.getElementById('charge-add-modal-backdrop').classList.add('show');
  document.getElementById('charge-add-hall')?.focus();
}
function closeChargeAddModal() {
  document.getElementById('charge-add-modal-backdrop').classList.remove('show');
}