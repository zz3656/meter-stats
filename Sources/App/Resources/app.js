
'use strict';

// ===== 数据模型 =====
// 数据存在后端 server.py,LocalStorage 只作为离线兜底(后端不可用时)
const STORAGE_KEY_READINGS = 'meter_readings_v1';
const STORAGE_KEY_CHARGES = 'meter_charges_v1';
const MULTIPLIER = { hall: 160, fire: 1, private_room: 160, ac: 160 };
const LABELS = { hall: '大厅', fire: '消防', private_room: '包厢', ac: '空调' };
const COLORS = {
  hall: '#2563eb',
  fire: '#dc2626',
  private_room: '#059669',
  ac: '#d97706',
};

// ===== 主题管理 =====
const THEME_KEY = 'meter_theme_mode';
const THEMES = ['dark', 'light', 'auto'];
const ICONS = { dark: '🌙', light: '☀️', auto: '💻' };

function getPreferredTheme() {
  return localStorage.getItem(THEME_KEY) || 'auto';
}
function getEffectiveTheme() {
  const mode = getPreferredTheme();
  if (mode === 'auto') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return mode;
}
function applyTheme() {
  const theme = getEffectiveTheme();
  document.documentElement.setAttribute('data-theme', theme === 'dark' ? 'dark' : '');
  updateThemeIcon();
}
function updateThemeIcon() {
  const icon = ICONS[getPreferredTheme()] || ICONS.auto;
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = icon;
}
function setTheme(mode) {
  localStorage.setItem(THEME_KEY, mode);
  applyTheme();
  // 重新渲染图表(颜色可能受影响)
  renderCharts();
}
function cycleTheme() {
  const current = getPreferredTheme();
  const idx = THEMES.indexOf(current);
  const next = THEMES[(idx + 1) % THEMES.length];
  setTheme(next);
}

// 重新渲染图表(颜色可能受影响)
function renderCharts() {
  const isDark = getEffectiveTheme() === 'dark';
  Chart.defaults.color = isDark ? '#6b7280' : '#7a818c';
  Chart.defaults.borderColor = isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)';
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  renderPieChart(CURRENT_READINGS, CURRENT_CHARGES);
  if (_yearlyChart) {
    setTimeout(() => _yearlyChart.resize(), 60);
  }
}

// 监听系统主题变化(auto 模式下自动切换)
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
  if (getPreferredTheme() === 'auto') {
    applyTheme();
    renderCharts();
  }
});

// 离线缓存(后端返回后写入 LocalStorage,后端不可用时回退读取)
function loadReadingsCache() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_READINGS);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}
function loadChargesCache() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_CHARGES);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}
function cacheReadings(data) {
  localStorage.setItem(STORAGE_KEY_READINGS, JSON.stringify(data));
}
function cacheCharges(data) {
  localStorage.setItem(STORAGE_KEY_CHARGES, JSON.stringify(data));
}

// 后端 API 调用(相对路径,部署时也是这个路径)
async function api(method, path, body) {
  const opts = {
    method,
    // 禁用 HTTP 缓存:录入后立即 GET 必须拿到磁盘最新数据(否则要重启才能看到昨天数据)
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`HTTP ${res.status}: ${txt}`);
  }
  return res.json();
}

// 加载数据(优先后端,失败回退到 LocalStorage 缓存)
async function fetchReadings() {
  try {
    const data = await api('GET', '/api/readings');
    cacheReadings(data);
    return data;
  } catch (e) {
    console.warn('后端不可用,使用本地缓存:', e);
    return loadReadingsCache();
  }
}
async function fetchCharges() {
  try {
    const data = await api('GET', '/api/charges');
    cacheCharges(data);
    return data;
  } catch (e) {
    console.warn('后端不可用,使用本地缓存:', e);
    return loadChargesCache();
  }
}

let CURRENT_ITEMS = [];
let CURRENT_PURCHASES = [];

async function fetchItems() {
  try {
    const data = await api('GET', '/api/items');
    CURRENT_ITEMS = data;
    return data;
  } catch (e) {
    console.warn('后端不可用,items 用空数组:', e);
    CURRENT_ITEMS = [];
    return [];
  }
}

async function fetchPurchases() {
  try {
    const data = await api('GET', '/api/purchases');
    CURRENT_PURCHASES = data;
    return data;
  } catch (e) {
    console.warn('后端不可用,purchases 用空数组:', e);
    CURRENT_PURCHASES = [];
    return [];
  }
}

// 后端写入
async function saveReadingRemote(row) {
  return api('POST', '/api/readings', row);
}
async function updateReadingRemote(date, fields) {
  return api('PUT', `/api/readings/${date}`, fields);
}
async function deleteReadingRemote(date) {
  return api('DELETE', `/api/readings/${date}`);
}
async function saveChargeRemote(row) {
  return api('POST', '/api/charges', row);
}
async function updateChargeRemote(id, fields) {
  return api('PUT', `/api/charges/${id}`, fields);
}
async function deleteChargeRemote(id) {
  return api('DELETE', `/api/charges/${id}`);
}

// 同步本地缓存(写入成功后调)
function realKwh(value, key) {
  return value * MULTIPLIER[key];
}

// ===== 渲染 =====
Chart.defaults.color = '#7a818c';
Chart.defaults.borderColor = 'rgba(0, 0, 0, 0.08)';
Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
Chart.defaults.font.size = 11;

let trendChart = null;
let pieChart = null;

// ===== 全局 Toast 提示覆盖层 =====
let _toastTimer = null;
function showToast(msg, type = 'success') {
  const overlay = document.getElementById('toast-overlay');
  const box = document.getElementById('toast-content');
  if (!box) { console.warn('toast-content not found'); return; }
  clearTimeout(_toastTimer);
  overlay.style.display = 'flex';
  box.className = `toast-content ${type}`;
  box.textContent = msg;
  // 强制重排以触发过渡动画
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      box.classList.add('show');
    });
  });
  _toastTimer = setTimeout(() => {
    box.classList.remove('show');
    setTimeout(() => { overlay.style.display = 'none'; }, 250);
  }, 3000);
}

function showAlert(msg, type = 'success') {
  showToast(msg, type);
}

// 物品卡提示条(已改为全局 Toast)
function showItemAlert(msg, type = 'success') {
  showToast(msg, type);
}

// 数据管理:自动备份开关(localStorage 持久化)
const AUTO_BACKUP_KEY = 'meter_auto_backup';
function getAutoBackupEnabled() {
  return localStorage.getItem(AUTO_BACKUP_KEY) !== 'false'; // 默认开启
}
function saveAutoBackup(enabled) {
  localStorage.setItem(AUTO_BACKUP_KEY, enabled ? 'true' : 'false');
}
function initAutoBackupToggle() {
  const cb = document.getElementById('datamgmt-auto-backup-toggle') || document.getElementById('auto-backup-toggle');
  if (!cb) return;
  // 避免重复绑定事件
  if (!cb._backupToggleBound) {
    cb._backupToggleBound = true;
    cb.addEventListener('change', e => {
      saveAutoBackup(e.target.checked);
      showToast(e.target.checked ? '已开启自动备份' : '已关闭自动备份', 'info');
    });
  }
  cb.checked = getAutoBackupEnabled();
}

// 数据管理弹窗
function openDataMgmtModal() {
  // 初始化自动备份开关
  initAutoBackupToggle();
  document.getElementById('datamgmt-modal-backdrop').classList.add('show');
}
function closeDataMgmtModal() {
  document.getElementById('datamgmt-modal-backdrop').classList.remove('show');
}

// 手动备份(从数据管理弹窗调用)
async function datamgmtBackup() {
  const btn = document.getElementById('datamgmt-backup-btn');
  const original = btn.textContent;
  btn.textContent = '⏳ 备份中…';
  btn.disabled = true;
  try {
    showAlert('正在备份数据…', 'info');
    const res = await api('POST', '/api/backup');
    if (!res.ok) {
      showAlert('备份失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    btn.textContent = '✅ 已备份';
    showAlert('✅ 数据已备份到 ' + (res.backup_dir || 'backup/'), 'success');
  } catch (e) {
    btn.textContent = original;
    showAlert('备份失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    setTimeout(() => { btn.textContent = original; }, 2000);
  }
}
function pickBackupDir() {
  return new Promise(resolve => {
    const hasSwiftBridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pickBackupDir;
    if (hasSwiftBridge) {
      // macOS 原生 App: 调用 Swift 文件选择器
      window.__backupDirChosen = dir => {
        window.__backupDirChosen = null;
        resolve(dir);
      };
      window.webkit.messageHandlers.pickBackupDir.postMessage('pick');
    } else {
      // Docker / Web 浏览器环境: 用 prompt 让用户输入路径或使用文件选择器
      showBrowserBackupPicker(resolve);
    }
  });
}

// Docker / Web 浏览器环境下的备份目录选择
function showBrowserBackupPicker(resolve) {
  const html = `
    <div style="font-size:13px;color:var(--text-muted);margin-bottom:12px;line-height:1.6;">
      💡 Docker/浏览器环境下无法选择系统目录。请选择备份数据中的 JSON 文件上传。<br>
      <b>提示</b>: 在 macOS 原生 App 中请使用「选择备份目录」功能。
    </div>
  `;
  showModal({
    icon: 'ℹ️',
    iconKind: 'info',
    title: '备份/恢复 — 浏览器环境',
    body: html,
    confirmText: '选择文件',
    cancelText: '取消',
    confirmKind: 'primary',
  }).then(confirmed => {
    if (!confirmed) {
      resolve(null);
      return;
    }
    // 打开文件选择器
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.json';
    input.onchange = async () => {
      const files = Array.from(input.files);
      if (!files.length) {
        resolve(null);
        return;
      }
      const fileContents = {};
      for (const file of files) {
        fileContents[file.name] = await file.text();
      }
      resolve({ files: fileContents, _browser: true });
    };
    input.click();
  });
}

// 浏览器环境下的文件选择/上传
function showBrowserFilePicker(mode, callback) {
  // mode: 'pick' (选文件) | 'upload' (上传文件)
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.accept = '.json';

  input.onchange = async () => {
    const files = Array.from(input.files);
    if (!files.length) {
      callback(null);
      return;
    }

    // 收集所有文件内容
    const fileContents = {};
    for (const file of files) {
      const text = await file.text();
      fileContents[file.name] = text;
    }

    if (mode === 'upload' || files.some(f => f.name.startsWith('readings.json'))) {
      // 有数据文件 — 直接上传
      callback({ files: fileContents, _browser: true });
    } else {
      // 只是 settings.json 或其他 — 也上传
      callback({ files: fileContents, _browser: true });
    }
  };

  input.click();
}

// 恢复数据(从数据管理弹窗调用)
async function datamgmtRestore() {
  const btn = document.getElementById('datamgmt-restore-btn');
  const original = btn.textContent;
  try {
    const dir = await pickBackupDir();
    if (!dir) {
      showAlert('未选择目录,已取消恢复', 'info');
      return;
    }

    let res;
    if (dir._browser) {
      // 浏览器环境: 直接上传文件
      const ok = await showModal({
        icon: '⚠️',
        iconKind: 'warn',
        title: '确认上传文件覆盖数据？',
        body: '确认上传选中的 JSON 文件覆盖当前数据？恢复前系统会自动备份。',
        confirmText: '确认上传',
        cancelText: '取消',
        confirmKind: 'danger',
      });
      if (!ok) return;
      btn.textContent = '⏳ 上传中…';
      btn.disabled = true;
      res = await api('POST', '/api/upload', { files: dir.files });
      if (res.ok) {
        showAlert(`✅ 已上传 ${res.uploaded.length} 个文件`, 'success');
        await refreshAll();
      } else {
        showAlert('上传失败: ' + (res.error || '未知错误'), 'error');
      }
    } else {
      // 原生环境: 用目录路径恢复
      const ok = await showModal({
        icon: '⚠️',
        iconKind: 'warn',
        title: '确认恢复数据?',
        body: `将从 <b>${dir}</b> 恢复数据。<br><br>⚠️ 当前数据会被覆盖,但恢复前系统会自动备份当前数据到 backup/ 目录,可随时回滚。`,
        confirmText: '确认恢复',
        cancelText: '取消',
        confirmKind: 'danger',
      });
      if (!ok) { showAlert('已取消恢复', 'info'); return; }
      btn.textContent = '⏳ 恢复中…';
      btn.disabled = true;
      res = await api('POST', '/api/restore', { source_dir: dir });
      if (!res.ok) {
        showAlert('恢复失败: ' + (res.error || '未知错误'), 'error');
        return;
      }
      showAlert(`✅ 已恢复 ${res.restored.length} 个数据文件;恢复前数据已备份到 ${res.pre_backup}`, 'success');
      await refreshAll();
    }
  } catch (e) {
    btn.textContent = original;
    showAlert('恢复失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

/**
 * 自定义确认弹窗(替代原生 confirm)
 * @param {Object} opts
 * @param {string} opts.title       - 弹窗标题
 * @param {string} opts.body        - 弹窗正文(支持 HTML)
 * @param {string} [opts.icon]      - 图标 emoji
 * @param {string} [opts.iconKind]  - 'danger' | 'warn' | 'info'
 * @param {string} [opts.confirmText] - 确认按钮文字
 * @param {string} [opts.cancelText]  - 取消按钮文字
 * @param {string} [opts.confirmKind] - 'danger' | 'primary'
 * @returns {Promise<boolean>}
 */
function showModal(opts) {
  return new Promise(resolve => {
    const backdrop = document.getElementById('modal-backdrop');
    const icon = document.getElementById('modal-icon');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const cancelBtn = document.getElementById('modal-cancel');
    const confirmBtn = document.getElementById('modal-confirm');

    icon.textContent = opts.icon || '!';
    icon.className = 'modal-icon' + (opts.iconKind === 'warn' ? ' warn'
      : opts.iconKind === 'info' ? ' info' : '');
    title.textContent = opts.title || '确认';
    body.innerHTML = opts.body || '';
    cancelBtn.textContent = opts.cancelText || '取消';
    confirmBtn.textContent = opts.confirmText || '确认';
    confirmBtn.className = 'btn ' + (opts.confirmKind === 'primary' ? 'btn-primary' : 'btn-danger');

    backdrop.classList.add('show');

    const close = (result) => {
      backdrop.classList.remove('show');
      cancelBtn.removeEventListener('click', onCancel);
      confirmBtn.removeEventListener('click', onConfirm);
      backdrop.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    };
    const onCancel = () => close(false);
    const onConfirm = () => close(true);
    const onBackdrop = (e) => { if (e.target === backdrop) close(false); };
    const onKey = (e) => { if (e.key === 'Escape') close(false); };

    cancelBtn.addEventListener('click', onCancel);
    confirmBtn.addEventListener('click', onConfirm);
    backdrop.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);

    // 焦点放确认按钮上,Enter 直接确认
    setTimeout(() => confirmBtn.focus(), 50);
  });
}

// 全局缓存当前 readings / charges(从后端拉一次后,所有渲染都从这里读)
let CURRENT_READINGS = [];
let CURRENT_CHARGES = [];

async function renderAll() {
  // 拉取最新数据
  CURRENT_READINGS = (await fetchReadings()).sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_CHARGES = (await fetchCharges()).sort((a, b) => a.date.localeCompare(b.date));
  await fetchItems();
  await fetchPurchases();

  renderStats(CURRENT_READINGS, CURRENT_CHARGES);
  renderChargeAlert(CURRENT_READINGS, CURRENT_CHARGES);
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  renderPieChart(CURRENT_READINGS, CURRENT_CHARGES);
  renderHistory(CURRENT_READINGS);
  renderChargeLog(CURRENT_CHARGES);
  renderItemTable(CURRENT_ITEMS);
  renderPurchaseTable(CURRENT_PURCHASES);
  refreshMonthSelectors();
  refreshDayCopySelect(CURRENT_READINGS, CURRENT_CHARGES);
  updateStatusBar(CURRENT_READINGS, CURRENT_CHARGES);
}

// 通用:写入后端 → 重新拉数据 → 重渲染
async function refreshAndRender() {
  CURRENT_READINGS = (await fetchReadings()).sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_CHARGES = (await fetchCharges()).sort((a, b) => a.date.localeCompare(b.date));
  await fetchItems();
  await fetchPurchases();
  renderStats(CURRENT_READINGS, CURRENT_CHARGES);
  renderChargeAlert(CURRENT_READINGS, CURRENT_CHARGES);
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  renderPieChart(CURRENT_READINGS, CURRENT_CHARGES);
  renderHistory(CURRENT_READINGS);
  renderChargeLog(CURRENT_CHARGES);
  renderItemTable(CURRENT_ITEMS);
  renderPurchaseTable(CURRENT_PURCHASES);
  refreshMonthSelectors();
  refreshDayCopySelect(CURRENT_READINGS, CURRENT_CHARGES);
  updateStatusBar(CURRENT_READINGS, CURRENT_CHARGES);
}

// 顶部状态条:上次抄表 / 本月用电 / 本月电费 / 预警
function updateStatusBar(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行
  const bar = document.getElementById('status-bar');
  if (!readings || readings.length === 0) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';

  const sorted = [...readings].sort((a, b) => a.date.localeCompare(b.date));
  const last = sorted[sorted.length - 1];
  const gap = daysBetween(last.date, todayStr());
  document.getElementById('st-last-reading').textContent =
    gap <= 0 ? `今天已抄表(${last.date})` : `上次抄表 ${last.date} · ${gap} 天前`;

  // 本月(最后数据月)用电 + 电费
  const monthKey = last.date.slice(0, 7);
  const monthRs = sorted.filter(r => r.date.startsWith(monthKey));
  let kwh = 0;
  if (monthRs.length >= 2) {
    const f = monthRs[0], l = monthRs[monthRs.length - 1];
    for (const k of ['hall', 'fire', 'private_room', 'ac']) {
      kwh += realKwh(f[k] - l[k], k) + sumChargesBetween(charges, k, f.date, l.date);
    }
  }
  document.getElementById('st-month-kwh').textContent = `本月用电 ${kwh.toFixed(0)} 度`;
  document.getElementById('st-month-cost').textContent = `电费 ¥ ${(kwh * ELECTRICITY_PRICE).toFixed(0)}`;

  // 预警:剩余天数 < 7 的表数量
  let alertCount = 0;
  for (const m of CHARGE_METERS) {
    const remaining = last[m.key] * MULTIPLIER[m.key];
    const usage = calcMonthlyDailyUsage(readings, charges, m.key);
    if (usage && usage.daily > 0 && remaining / usage.daily < 7) alertCount++;
  }
  const el = document.getElementById('st-alerts');
  el.textContent = alertCount > 0 ? `${alertCount} 块表需关注` : '余量正常';
  el.className = alertCount > 0 ? 'em' : '';
}

// 简化:删除/标记后只重拉 items+purchases
async function refreshAll() {
  await fetchItems();
  await fetchPurchases();
  renderItemTable(CURRENT_ITEMS);
  renderPurchaseTable(CURRENT_PURCHASES);
}

// 充值预警 — 4 块表都做
const ELECTRICITY_PRICE = 0.9; // 元/度
const CHARGE_METERS = [
  { key: 'hall', label: '大厅', icon: '🎤', meterNo: '1#' },
  { key: 'fire', label: '消防', icon: '🧯', meterNo: '2#' },
  { key: 'private_room', label: '包厢', icon: '🛋️', meterNo: '3#' },
  { key: 'ac', label: '空调', icon: '❄️', meterNo: '4#' },
];

/**
 * 计算每块表的月均日耗电。
 *
 * 公式:对于抄表区间 [A, B]:
 *   实际用电度数 = (A.表底 - B.表底) + (这段期间内的充值度数之和)
 *   日均 = 实际用电度数 / 天数
 * 然后把一个月内所有相邻抄表对的日均加权平均,得到月日均。
 *
 * 优先级:
 *   1) 当月(用所有抄表对算)
 *   2) 上一个完整月
 *   3) 最近一次抄表对(兜底)
 *
 * 返回 { [meterKey]: { daily, basis, basisLabel, monthlyTotal?, monthDays? } | null }
 */
function calcMonthlyDailyUsage(readings, charges, meterKey) {
  if (!readings || readings.length === 0) return null;

  // 按月份分组
  const byMonth = {};
  readings.forEach(r => {
    const m = r.date.slice(0, 7);
    (byMonth[m] = byMonth[m] || []).push(r);
  });
  const sortedMonths = Object.keys(byMonth).sort();
  const currentMonth = sortedMonths[sortedMonths.length - 1];
  const prevMonth = sortedMonths.length >= 2 ? sortedMonths[sortedMonths.length - 2] : null;

  // 1) 当月
  let chosen = calcMonthDailyUsage(byMonth[currentMonth] || [], charges, meterKey, currentMonth);
  // 2) 上月
  if (!chosen && prevMonth) {
    chosen = calcMonthDailyUsage(byMonth[prevMonth] || [], charges, meterKey, prevMonth);
  }
  // 3) 兜底:最近一次抄表对
  if (!chosen && readings.length >= 2) {
    const a = readings[readings.length - 2];
    const b = readings[readings.length - 1];
    const days = (new Date(b.date) - new Date(a.date)) / 86400000;
    if (days > 0) {
      const charged = sumChargesBetween(charges, meterKey, a.date, b.date);
      const used = (a[meterKey] - b[meterKey]) * MULTIPLIER[meterKey] + charged;
      if (used > 0) {
        chosen = {
          daily: used / days,
          basis: 'last-interval',
          basisLabel: `${a.date} → ${b.date} (${days.toFixed(1)} 天,含 ${charged.toFixed(0)} 度充值)`,
        };
      }
    }
  }
  return chosen;
}

/**
 * 计算一组抄表(同一月)内某块表的日均用电。
 * 遍历相邻抄表对,每对用 "表底差 + 期间充值" 算日均,再加权平均。
 */
function calcMonthDailyUsage(rows, charges, meterKey, monthLabel) {
  if (!rows || rows.length < 2) return null;

  // 必须 ≥ 2 条记录,且按日期排序
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));

  let totalUsed = 0;
  let totalDays = 0;
  let segments = 0;

  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1];
    const b = sorted[i];
    const days = (new Date(b.date) - new Date(a.date)) / 86400000;
    if (days <= 0) continue;

    // 表底差(度数,考虑倍率)
    const readingDelta = (a[meterKey] - b[meterKey]) * MULTIPLIER[meterKey];
    // 这段时间内的充值度数(用户单独录入的)
    const charged = sumChargesBetween(charges, meterKey, a.date, b.date);
    // 实际用电 = 表底差 + 期间充值
    const used = readingDelta + charged;

    if (used > 0) {
      totalUsed += used;
      totalDays += days;
      segments++;
    }
  }

  if (totalDays <= 0 || segments === 0) return null;

  // 总充值度数(用于提示)
  const monthStart = sorted[0].date;
  const monthEnd = sorted[sorted.length - 1].date;
  const totalCharged = sumChargesBetween(charges, meterKey, monthStart, monthEnd);

  const hasCharge = totalCharged > 0;
  const basisLabel = hasCharge
    ? `${monthLabel} (${totalDays.toFixed(1)} 天,含 ${totalCharged.toFixed(0)} 度充值)`
    : `${monthLabel} (${totalDays.toFixed(1)} 天)`;

  return {
    daily: totalUsed / totalDays,
    basis: hasCharge ? 'current-month-with-charge' : 'current-month',
    basisLabel,
    monthlyTotal: totalUsed,
    monthDays: totalDays,
  };
}

/**
 * 统计某段时间内某块表的充值度数(实际度数)。
 * "这段时间" = (start, end],即左开右闭 — 抄表当天的充值算到下一段。
 *
 * 用户填的充值度数 = 表度数(跟抄表读数同语义),
 * 必须 ×160 才是实际度数。1/3/4 表的 MULTIPLIER=160,消防=1。
 */
function sumChargesBetween(charges, meterKey, startDate, endDate) {
  if (!charges) return 0;
  let sum = 0;
  for (const c of charges) {
    if (c.date > startDate && c.date <= endDate) {
      sum += realKwh(c[meterKey] || 0, meterKey);
    }
  }
  return sum;
}

// 余量预警 — 4 块表 1 列自适应卡,按剩余天数升序排(紧急在前)
// 本地时间日期工具(避免 toISOString 的 UTC 坑)
function addDaysToDate(dateStr, days) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + Math.ceil(days));
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}
function daysBetween(dateStrA, dateStrB) {
  const [y1, m1, d1] = dateStrA.split('-').map(Number);
  const [y2, m2, d2] = dateStrB.split('-').map(Number);
  return Math.round((new Date(y2, m2 - 1, d2) - new Date(y1, m1 - 1, d1)) / 86400000);
}
function renderChargeAlert(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行
  const container = document.getElementById('charge-alerts');

  if (!readings || readings.length === 0) {
    container.innerHTML = '<div class="empty" style="padding:20px;">录入抄表数据后开始监控 4 块表的余额。</div>';
    return;
  }

  const latest = readings[readings.length - 1];

  // 算每块表的剩余天数(用于排序)
  const items = CHARGE_METERS.map(m => {
    const multiplier = MULTIPLIER[m.key];
    const remaining = latest[m.key] * multiplier;
    const usage = calcMonthlyDailyUsage(readings, charges, m.key);

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

    return { m, multiplier, remaining, usage, daysLeft, dailyUsage, basisLabel, hasUsage };
  });

  // 固定按表号顺序排列:大厅 → 消防 → 包厢 → 空调

  container.innerHTML = `<div class="stat-grid alert-grid">${items.map(({ m, multiplier, remaining, daysLeft, dailyUsage, basisLabel, hasUsage }) => {
    // 颜色 + 图标
    let level, dotColor, statusText;
    if (!hasUsage) {
      level = 'pending';
      dotColor = 'var(--text-muted)';
      statusText = '等待数据';
    } else if (daysLeft < 3) {
      level = 'danger';
      dotColor = '#dc2626';
      statusText = '紧急';
    } else if (daysLeft < 7) {
      level = 'warn';
      dotColor = '#f59e0b';
      statusText = '注意';
    } else {
      level = 'ok';
      dotColor = '#10b981';
      statusText = '充足';
    }

    // 建议充值
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
    // 预计断电日期 = 最新抄表日 + 剩余天数(只在有日均数据时显示)
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
          ${hasUsage
            ? `日均 ${dailyUsage.toFixed(1)} 度 · ${basisLabel}`
            : `至少需要 2 次抄表 + 充值数据`
          }
        </div>
      </div>
    `;
  }).join('')}</div>`;
}

// 统计卡片 — 用新算法(读数差 + 期间充值)
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
        <div class="label">${LABELS[key]}(当月)</div>
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

// 复制单天用电(群里汇报用):下拉列每一天(从首次抄表日到最新抄表日前一天)
// 某天的用电 = 该天所在抄表区间的均摊日均(与每日用电图一致),每天都能复制
function refreshDayCopySelect(readings, charges) {
  const sel = document.getElementById('day-copy-date');
  if (!sel) return;
  const rs = (readings || []).filter(r => r.hall != null).sort((a, b) => a.date.localeCompare(b.date));
  if (rs.length < 2) {
    sel.innerHTML = '<option value="">(需至少两次抄表)</option>';
    return;
  }
  // 列出每一天:首次抄表日 → 最新抄表日前一天(最新日无当天用电,不列)
  const first = new Date(rs[0].date);
  const last = new Date(rs[rs.length - 1].date);
  const copyDates = [];
  for (let d = new Date(first); d < last; d.setDate(d.getDate() + 1)) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    copyDates.push(`${y}-${m}-${day}`);
  }
  sel.innerHTML = copyDates.map(dd => `<option value="${dd}">${dd}</option>`).join('');
  // 默认选昨天(最新抄表日的前一天;今天录入表底 → 算出的正是昨日用电)
  sel.value = copyDates.length ? copyDates[copyDates.length - 1] : '';
}

// 计算某一天的用电:找到该天所在的抄表区间 [a, b](a.date ≤ day < b.date),
// 用电 = (a读数-b读数)×倍率+充值 均摊到区间每一天(日均,与每日用电图一致)
// 同时返回"昨日"(前一天)各区域用电,用于对比
function calcDayUsage(readings, charges, day) {
  const rs = (readings || []).filter(r => r.hall != null).sort((a, b) => a.date.localeCompare(b.date));
  // 找区间:day 属于 [rs[i].date, rs[i+1].date)
  let a = null, b = null;
  for (let i = 0; i < rs.length - 1; i++) {
    if (day >= rs[i].date && day < rs[i + 1].date) { a = rs[i]; b = rs[i + 1]; break; }
  }
  if (!a || !b) return null;  // 最新抄表日之后没有区间,算不出
  const spanDays = Math.round((new Date(b.date) - new Date(a.date)) / 86400000);
  if (spanDays <= 0) return null;
  const per = {};
  let totalKwh = 0, totalCost = 0;
  for (const m of CHARGE_METERS) {
    if (a[m.key] == null || b[m.key] == null) { per[m.key] = null; continue; }
    const total = realKwh(a[m.key] - b[m.key], m.key) + sumChargesBetween(charges, m.key, a.date, b.date);
    const kwh = total / spanDays;  // 日均
    const cost = kwh * ELECTRICITY_PRICE;
    per[m.key] = { kwh, cost };
    totalKwh += kwh; totalCost += cost;
  }
  // 昨日用电 = 前一天(day-1)的均摊日均;用于对比
  let yPer = null;
  const yDateObj = new Date(day);
  yDateObj.setDate(yDateObj.getDate() - 1);
  const yDate = `${yDateObj.getFullYear()}-${String(yDateObj.getMonth() + 1).padStart(2, '0')}-${String(yDateObj.getDate()).padStart(2, '0')}`;
  let yA = null, yB = null;
  for (let i = 0; i < rs.length - 1; i++) {
    if (yDate >= rs[i].date && yDate < rs[i + 1].date) { yA = rs[i]; yB = rs[i + 1]; break; }
  }
  if (yA && yB) {
    const yDays = Math.round((new Date(yB.date) - new Date(yA.date)) / 86400000);
    if (yDays > 0) {
      yPer = {};
      for (const m of CHARGE_METERS) {
        if (yA[m.key] == null || yB[m.key] == null) { yPer[m.key] = null; continue; }
        const total = realKwh(yA[m.key] - yB[m.key], m.key) + sumChargesBetween(charges, m.key, yA.date, yB.date);
        yPer[m.key] = { kwh: total / yDays };
      }
    }
  }
  return { date: day, prevDate: a.date, nextDate: b.date, spanDays, per, totalKwh, totalCost, yPer, yPrevDate: yDate };
}

// 生成汇报文本并复制:度数 + 金额 + 对比昨日 + 对比本月日均,可直接粘贴到群
function copyDayUsage() {
  const sel = document.getElementById('day-copy-date');
  if (!sel || !sel.value) { showAlert('请先选择日期(需至少两次抄表)', 'error'); return; }
  const date = sel.value;
  const usage = calcDayUsage(CURRENT_READINGS, CURRENT_CHARGES, date);
  if (!usage) { showAlert(`${date} 没有可用的用电区间,无法计算`, 'error'); return; }
  const lines = [`【${date} 各区域用电】`];
  let hasData = false;
  // 合计的对比基数:昨日总用电 / 本月日均总用电
  let yTotal = 0, yHas = false, mTotal = 0, mHas = false;
  for (const m of CHARGE_METERS) {
    const p = usage.per[m.key];
    if (p == null) { lines.push(`${m.icon} ${m.label}: —`); continue; }
    hasData = true;
    // 较昨日:前一天(day-1)的均摊日均
    let vsY = '';
    if (usage.yPer && usage.yPer[m.key]) {
      const y = usage.yPer[m.key].kwh;
      yTotal += y; yHas = true;
      if (y > 0) {
        const diff = p.kwh - y;
        const pct = (diff / y) * 100;
        const arrow = diff >= 0 ? '↑' : '↓';
        vsY = ` 较昨日${arrow}${Math.abs(pct).toFixed(1)}%`;
      } else if (y === 0) {
        vsY = ` 较昨日↑—`;
      }
    }
    // 较本月日均:复用 calcMonthlyDailyUsage 的 daily(当月优先,含充值口径)
    let vsM = '';
    const avg = calcMonthlyDailyUsage(CURRENT_READINGS, CURRENT_CHARGES, m.key);
    if (avg && avg.daily > 0) {
      const diff = p.kwh - avg.daily;
      const pct = (diff / avg.daily) * 100;
      const arrow = diff >= 0 ? '↑' : '↓';
      vsM = ` 较本月日均${arrow}${Math.abs(pct).toFixed(1)}%`;
      mTotal += avg.daily; mHas = true;
    }
    lines.push(`${m.icon} ${m.label}: ${p.kwh.toFixed(1)} 度,¥${p.cost.toFixed(2)}${vsY}${vsM}`);
  }
  if (!hasData) { showAlert(`${date} 没有可计算的用电数据`, 'error'); return; }
  // 合计行:总度数/金额 + 较昨日 + 较本月日均
  let vsYTotal = '', vsMTotal = '';
  if (yHas && yTotal > 0) {
    const diff = usage.totalKwh - yTotal;
    const pct = (diff / yTotal) * 100;
    vsYTotal = ` 较昨日${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
  }
  if (mHas && mTotal > 0) {
    const diff = usage.totalKwh - mTotal;
    const pct = (diff / mTotal) * 100;
    vsMTotal = ` 较本月日均${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
  }
  lines.push(`— 合计: ${usage.totalKwh.toFixed(1)} 度,¥${usage.totalCost.toFixed(2)}${vsYTotal}${vsMTotal}`);
  const spanNote = usage.spanDays > 1 ? `(区间 ${usage.prevDate} → ${usage.nextDate} 共 ${usage.spanDays} 天均摊)` : `(区间 ${usage.prevDate} → ${usage.nextDate})`;
  lines.push(spanNote);
  const text = lines.join('\n');
  copyTextWithFallback(text, '✓ 单天用电已复制,可直接粘贴到群里');
}

// 复制文本:优先 Clipboard API(WKWebView 受限时 fallback 到 execCommand)
function copyTextWithFallback(text, successMsg) {
  const done = () => showAlert(successMsg, 'success');
  const fail = () => {
    // WKWebView 兼容:隐藏 textarea + execCommand('copy')
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) { done(); return; }
    } catch (e) { /* 继续走下方报错 */ }
    showAlert('复制失败,请手动选择复制', 'error');
  };
  if (navigator.clipboard && window.ClipboardItem) {
    navigator.clipboard.writeText(text).then(done, fail);
  } else {
    fail();
  }
}

// 每日用电折线图 — 4 块表各自折线 + 充电叠加
function renderTrendChart(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行
  const ctx = document.getElementById('chart-trend').getContext('2d');
  if (!readings || readings.length === 0) {
    ctx.canvas.parentElement.innerHTML = '<div class="empty">录入抄表数据后查看每日用电</div>';
    return;
  }

  // X 轴:从首次抄表日到最新抄表日,每天一个点
  const sorted = [...readings].sort((a, b) => a.date.localeCompare(b.date));
  const startDate = new Date(sorted[0].date);
  const endDate = new Date(sorted[sorted.length - 1].date);
  const dayCount = Math.round((endDate - startDate) / 86400000) + 1;
  const dayLabels = [];
  for (let i = 0; i < dayCount; i++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + i);
    // 用本地时间生成 YYYY-MM-DD
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    dayLabels.push(`${y}-${m}-${day}`);
  }

  // 预建 DateString → Index 映射,避免循环里 indexOf 的 O(n²)
  const dateToIndex = new Map();
  for (let i = 0; i < dayCount; i++) {
    dateToIndex.set(dayLabels[i], i);
  }

  // 每天的用电 = 抄表对 [a, b] 的用电均摊到 a .. b-1 的每一天
  // 语义:今天(a)抄表后,到下次抄表(b)之间的用电,属于今天及中间各天
  // (与单天复制口径一致:区间 (a→b) 的用电 = a 日的用电)
  const dailyUsage = {};
  for (const key of ['hall', 'fire', 'private_room', 'ac']) {
    dailyUsage[key] = new Array(dayCount).fill(null); // 用 null 让线断开
  }

  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1];
    const b = sorted[i];
    const aIdx = dateToIndex.get(a.date) ?? -1;
    const bIdx = dateToIndex.get(b.date) ?? -1;
    if (aIdx < 0 || bIdx < 0 || bIdx <= aIdx) continue;
    const days = bIdx - aIdx;
    if (days <= 0) continue;
    for (const key of ['hall', 'fire', 'private_room', 'ac']) {
      const delta = realKwh(a[key] - b[key], key);
      const charged = sumChargesBetween(charges, key, a.date, b.date);
      const perDay = (delta + charged) / days;
      // 均摊到 a(含) .. b-1;最新抄表日 b 没有当天的用电(要等下次抄表)
      for (let j = aIdx; j < bIdx; j++) {
        dailyUsage[key][j] = perDay;
      }
    }
  }

  // 每天的充电量(虚线 spike)
  // 用户填的充值度数 = 表度数(跟抄表读数同语义),需要 ×160 才是实际度数
  const dailyCharge = new Array(dayCount).fill(null);
  for (const c of (charges || [])) {
    const idx = dateToIndex.get(c.date);
    if (idx < 0) continue;
    const total = CHARGE_METERS.reduce((s, m) => s + realKwh(c[m.key] || 0, m.key), 0);
    dailyCharge[idx] = total;
  }

  // 整月日均水平线:每块表一条,虚线显示,作为波动参照
  const totalDays = dayCount; // first→last 的天数(已含两端)
  const avgLines = {};
  for (const key of ['hall', 'fire', 'private_room', 'ac']) {
    // 复用饼图公式:实际用电 = (first - last)*倍率 + 期间充值
    const f = sorted[0], l = sorted[sorted.length - 1];
    const totalKwh = realKwh(f[key] - l[key], key) + sumChargesBetween(charges, key, f.date, l.date);
    avgLines[key] = totalDays > 0 ? totalKwh / totalDays : 0;
  }
  const avgLineData = (val) => new Array(dayCount).fill(val);

  // 4 块表折线 + 4 条整月日均虚线 + 1 根充电点状 spike
  const datasets = [
    { label: '大厅', data: dailyUsage.hall, borderColor: COLORS.hall, backgroundColor: COLORS.hall + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '消防', data: dailyUsage.fire, borderColor: COLORS.fire, backgroundColor: COLORS.fire + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '包厢', data: dailyUsage.private_room, borderColor: COLORS.private_room, backgroundColor: COLORS.private_room + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '空调', data: dailyUsage.ac, borderColor: COLORS.ac, backgroundColor: COLORS.ac + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '充值', data: dailyCharge, borderColor: 'var(--warn)', backgroundColor: 'var(--warn)',
      borderWidth: 0, pointRadius: 6, pointHoverRadius: 8, pointStyle: 'rectRot',
      showLine: false, yAxisID: 'y2' },
    // 整月日均虚线 — 让短区间波动有参照基准
    { label: '大厅日均', data: avgLineData(avgLines.hall), borderColor: COLORS.hall,
      borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '消防日均', data: avgLineData(avgLines.fire), borderColor: COLORS.fire,
      borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '包厢日均', data: avgLineData(avgLines.private_room), borderColor: COLORS.private_room,
      borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '空调日均', data: avgLineData(avgLines.ac), borderColor: COLORS.ac,
      borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0,
      fill: false, spanGaps: true, yAxisID: 'y' },
  ];

  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: 'line',
    data: { labels: dayLabels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const v = ctx.parsed.y;
              if (v == null || v <= 0) return null;
              return `${ctx.dataset.label}: ${v.toFixed(1)} 度`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { maxRotation: 45, minRotation: 0, autoSkip: true, maxTicksLimit: 14 },
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: '每日用电 (度)' },
          ticks: { callback: v => v.toLocaleString() },
        },
        // 充值走独立右轴,避免大额充值 spike 把日常用电压扁成一条平线
        y2: {
          position: 'right',
          beginAtZero: true,
          grid: { display: false },
          title: { display: true, text: '充值 (度)' },
          ticks: { callback: v => v.toLocaleString() },
        },
      },
    },
  });
}

// 占比饼图 — 支持单月选择 + 双月对比
// 模式:仅 A 月(默认)显示一个饼图;点「对比」显示 A/B 两个饼图并排
let pieChartB = null;  // 对比用的第二个饼图实例

function calcMonthPie(monthReadings, charges) {
  // monthReadings:某月内按日期排序的抄表(hall != null 已过滤)
  if (!monthReadings || monthReadings.length < 2) return null;
  const first = monthReadings[0], last = monthReadings[monthReadings.length - 1];
  const usage = ['hall', 'fire', 'private_room', 'ac'].map(k => {
    const delta = realKwh(first[k] - last[k], k);
    const charged = sumChargesBetween(charges, k, first.date, last.date);
    return Math.max(delta + charged, 0);
  });
  const total = usage.reduce((a, b) => a + b, 0);
  if (total <= 0) return null;
  return { usage, total, first, last };
}

function drawPie(canvasId, getChart, setChart, data, label) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const labels = ['hall', 'fire', 'private_room', 'ac'].map((k, i) => {
    const pct = data.total > 0 ? (data.usage[i] / data.total * 100).toFixed(1) : 0;
    return `${LABELS[k]} (${pct}%)`;
  });
  const existing = getChart();
  if (existing) existing.destroy();
  const chart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: data.usage,
        backgroundColor: [COLORS.hall, COLORS.fire, COLORS.private_room, COLORS.ac],
        borderWidth: 2,
        borderColor: 'rgba(0,0,0,0.08)',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { boxWidth: 12, font: { size: 12 } } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const v = ctx.parsed;
              const pct = data.total > 0 ? (v / data.total * 100).toFixed(1) : 0;
              return `${ctx.label.split(' (')[0]}: ${v.toFixed(1)} 度 (${pct}%)`;
            },
          },
        },
      },
    },
  });
  setChart(chart);
}

function renderPieChart(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行
  const rangeEl = document.getElementById('pie-range');
  const bWrap = document.getElementById('chart-pie-b-wrap');
  const selA = document.getElementById('pie-month-a');
  const selB = document.getElementById('pie-month-b');

  // 没有下拉(初始化前)或没有数据 → 保持旧行为:全部区间累计
  if (!selA || !readings || readings.length < 2) {
    if (pieChart) pieChart.destroy();
    if (pieChartB) { pieChartB.destroy(); pieChartB = null; }
    if (bWrap) bWrap.style.display = 'none';
    const ctx = document.getElementById('chart-pie').getContext('2d');
    ctx.canvas.parentElement.innerHTML = '<div class="empty">需要至少 2 次抄表才能计算占比</div>';
    return;
  }

  const monthA = selA.value;
  const monthB = selB ? selB.value : '';
  const compareMode = monthB && monthB !== monthA;

  const monthA_rs = readings.filter(r => r.date.startsWith(monthA));
  const dataA = calcMonthPie(monthA_rs, charges);
  const dataB = compareMode ? calcMonthPie(readings.filter(r => r.date.startsWith(monthB)), charges) : null;

  if (!dataA && !dataB) {
    if (pieChart) pieChart.destroy();
    if (pieChartB) { pieChartB.destroy(); pieChartB = null; }
    if (bWrap) bWrap.style.display = 'none';
    document.getElementById('chart-pie').getContext('2d').canvas.parentElement.innerHTML =
      `<div class="empty">${monthA} 当月不足 2 次抄表,无法计算占比</div>`;
    return;
  }

  if (rangeEl) {
    if (compareMode && dataA && dataB) {
      rangeEl.textContent = `对比：${monthA} ${dataA.first.date}→${dataA.last.date}  vs  ${monthB} ${dataB.first.date}→${dataB.last.date}`;
    } else if (dataA) {
      rangeEl.textContent = `${monthA}：${dataA.first.date} → ${dataA.last.date}`;
    } else {
      rangeEl.textContent = `${monthB}：${dataB.first.date} → ${dataB.last.date}`;
    }
  }

  if (dataA) {
    drawPie('chart-pie', () => pieChart, (c) => pieChart = c, dataA, monthA);
  } else if (pieChart) { pieChart.destroy(); pieChart = null; }

  if (compareMode && dataB) {
    if (bWrap) bWrap.style.display = 'block';
    drawPie('chart-pie-b', () => pieChartB, (c) => pieChartB = c, dataB, monthB);
  } else {
    if (pieChartB) { pieChartB.destroy(); pieChartB = null; }
    if (bWrap) bWrap.style.display = 'none';
  }

  // 双月对比表格:选了两个不同月份时,同步渲染对比(替代原「历史对比」模块)
  const compareResult = document.getElementById('pie-compare-result');
  if (compareResult) {
    if (compareMode) {
      applyCompare(monthA, monthB);  // async,内部渲染
    } else {
      compareResult.innerHTML = '';
    }
  }
}

// 物品管理表格
function renderItemTable(items) {
  const tbody = document.querySelector('#item-table tbody');
  if (!tbody) return;
  if (!items || items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">还没有物品,点击上方表单添加</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(it => {
    const safeName = escapeHtml(it.name);
    const safeUnit = escapeHtml(it.unit || '');
    const safeNote = escapeHtml(it.note || '');
    return `<tr>
      <td>${safeName}</td>
      <td><strong>${it.qty}</strong></td>
      <td>${safeUnit}</td>
      <td>${safeNote}</td>
      <td>
        <button class="del-btn" data-action="del-item" data-id="${it.id}">删除</button>
      </td>
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

// 历史表格(抄表记录)
function renderHistory(readings) {
  const tbody = document.querySelector('#history-table tbody');
  const empty = document.getElementById('history-empty');
  if (!readings || readings.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  // 按选中的月份过滤(下拉框只有有数据的月份,默认最后月)
  const monthSel = document.getElementById('history-month');
  const month = monthSel ? monthSel.value : '';
  const filtered = month ? readings.filter(r => r.date.startsWith(month)) : readings;
  if (filtered.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    empty.textContent = `${month} 暂无抄表记录`;
    return;
  }
  empty.style.display = 'none';
  const sorted = [...filtered].sort((a, b) => b.date.localeCompare(a.date));

  tbody.innerHTML = sorted.map(r => `
      <tr data-date="${r.date}">
        <td>${r.date}</td>
        <td>${r.hall == null ? '—' : r.hall.toFixed(2)}</td>
        <td>${r.fire == null ? '—' : r.fire.toFixed(2)}</td>
        <td>${r.private_room == null ? '—' : r.private_room.toFixed(2)}</td>
        <td>${r.ac == null ? '—' : r.ac.toFixed(2)}</td>
        <td>${r.main_meter == null ? '—' : r.main_meter.toFixed(1)}</td>
        <td>${r.sub_meter == null ? '—' : r.sub_meter.toFixed(1)}</td>
        <td>${r.water == null ? '—' : r.water.toFixed(1)}</td>
        <td style="color:var(--text-muted);font-size:12px;">${r.note || '—'}</td>
        <td>
          <button class="edit-btn" data-action="edit" data-date="${r.date}">编辑</button>
          <button class="delete-btn" data-action="delete" data-date="${r.date}" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;">删除</button>
        </td>
      </tr>
    `).join('');

  // 编辑
  tbody.querySelectorAll('[data-action="edit"]').forEach(btn => {
    btn.addEventListener('click', () => enterEditMode(btn.dataset.date));
  });
  // 删除
  tbody.querySelectorAll('[data-action="delete"]').forEach(btn => {
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
        showAlert(`已删除 ${date}`, 'success');
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

// 进入行内编辑模式(抄表)
async function enterEditMode(date) {
  const allData = await fetchReadings();
  const row = allData.find(r => r.date === date);
  if (!row) return;
  const tr = document.querySelector(`#history-table tbody tr[data-date="${date}"]`);
  if (!tr) return;

  tr.classList.add('edit-row');
  tr.innerHTML = `
    <td><input type="date" class="cell-input" id="edit-date" value="${row.date}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-hall" value="${row.hall ?? ''}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-fire" value="${row.fire ?? ''}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-private_room" value="${row.private_room ?? ''}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-ac" value="${row.ac ?? ''}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-main_meter" value="${row.main_meter ?? ''}" placeholder="总表" style="min-width:64px;" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-sub_meter" value="${row.sub_meter ?? ''}" placeholder="分表" style="min-width:64px;" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-water" value="${row.water ?? ''}" placeholder="水表" style="min-width:64px;" /></td>
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
    // 水电字段(总表/分表/水表)可直接编辑;厨房 = 总表 − 分表,自动算
    const newMain = numE('#edit-main_meter');
    const newSub = numE('#edit-sub_meter');
    const newWater = numE('#edit-water');
    const newNote = tr.querySelector('#edit-note').value.trim();

    if (!newDate) { showAlert('日期不能为空', 'error'); return; }
    const editVals = [newHall, newFire, newPrivate, newAc, newMain, newSub, newWater];
    if (editVals.some(v => v !== null && isNaN(v))) {
      showAlert('读数必须是数字', 'error'); return;
    }
    if (editVals.every(v => v === null)) {
      showAlert('至少填写一块表的读数', 'error'); return;
    }

    // 如果改了日期,检查新日期是否已存在
    if (newDate !== date) {
      const all = await fetchReadings();
      const conflict = all.find(r => r.date === newDate);
      if (conflict) {
        const ok = await showModal({
          title: '覆盖已有数据',
          icon: '⚠️',
          iconKind: 'warn',
          body: `<strong>${newDate}</strong> 已存在数据,合并(覆盖)它吗?`,
          confirmText: '覆盖',
          confirmKind: 'primary',
        });
        if (!ok) return;
        // 删除冲突的旧行
        await deleteReadingRemote(newDate);
      }
    }

    try {
      await updateReadingRemote(date, {
        date: newDate,
        hall: newHall,
        fire: newFire,
        private_room: newPrivate,
        ac: newAc,
        main_meter: newMain,
        sub_meter: newSub,
        water: newWater,
        note: newNote,
      });
      showAlert(`✓ ${date} 已更新为 ${newDate}`, 'success');
      await refreshAndRender();
    } catch (err) {
      showAlert(`更新失败: ${err.message}`, 'error');
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

// ===== 表单处理 =====
document.getElementById('entry-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  // 空字段 → null(4 表可空,允许只录水电表底);至少填一项才能提交
  const num = (id) => {
    const v = document.getElementById(id).value;
    return v === '' ? null : parseFloat(v);
  };
  const hallV = num('hall'), fireV = num('fire'), prV = num('private_room'), acV = num('ac');
  // 水电字段已在独立的「💧 水电」tab 录入,抄表表单只提交 4 表
  const allVals = [hallV, fireV, prV, acV];
  if (allVals.every(v => v === null)) {
    showAlert('请至少填写一块表的读数', 'error');
    return;
  }
  if (allVals.some(v => v !== null && isNaN(v))) {
    showAlert('读数必须是数字', 'error');
    return;
  }
  const row = {
    date: document.getElementById('date').value,
    hall: hallV,
    fire: fireV,
    private_room: prV,
    ac: acV,
    note: document.getElementById('entry-note').value.trim(),
  };
  if (!row.date) { showAlert('请选择日期', 'error'); return; }

  // 检查是否已存在该日期(走 API 查询)
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
      confirmText: '覆盖',
      confirmKind: 'primary',
    });
    if (!ok) return;
  }

  try {
    await saveReadingRemote(row);
    showAlert(`✓ ${row.date} 已保存`, 'success');
    ['hall', 'fire', 'private_room', 'ac', 'entry-note'].forEach(id => document.getElementById(id).value = '');
    await refreshAndRender();
  } catch (err) {
    showAlert(`保存失败: ${err.message}`, 'error');
  }
});

// 充值表单 submit
document.getElementById('charge-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const date = document.getElementById('charge-date').value;
  if (!date) { showAlert('请选择充值日期', 'error'); return; }

  const charge = {
    date: date,
    hall: parseFloat(document.getElementById('charge-hall').value) || 0,
    fire: parseFloat(document.getElementById('charge-fire').value) || 0,
    private_room: parseFloat(document.getElementById('charge-private_room').value) || 0,
    ac: parseFloat(document.getElementById('charge-ac').value) || 0,
    note: document.getElementById('charge-note').value.trim(),
  };

  if (CHARGE_METERS.every(m => charge[m.key] === 0)) {
    showAlert('至少填写一块表的充值度数', 'error');
    return;
  }

  try {
    await saveChargeRemote(charge);
    showAlert(`✓ ${date} 充值记录已保存`, 'success');
    ['hall', 'fire', 'private_room', 'ac'].forEach(id => {
      const el = document.getElementById('charge-' + id);
      if (el) el.value = '';
    });
    document.getElementById('charge-note').value = '';
    await refreshAndRender();
  } catch (err) {
    showAlert(`保存失败: ${err.message}`, 'error');
  }
});

// 水电表单 submit(总表/分表/水表 — 独立 tab,数据仍写入抄表记录同日期)
document.getElementById('utility-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const date = document.getElementById('utility-date').value;
  if (!date) { showAlert('请选择抄表日期', 'error'); return; }
  const numU = (id) => {
    const v = document.getElementById(id).value;
    return v === '' ? null : parseFloat(v);
  };
  const mainV = numU('main_meter'), subV = numU('sub_meter'), waterV = numU('water');
  const vals = [mainV, subV, waterV];
  if (vals.every(v => v === null)) {
    showAlert('请至少填写总表/分表/水表一项', 'error');
    return;
  }
  if (vals.some(v => v !== null && isNaN(v))) {
    showAlert('读数必须是数字', 'error');
    return;
  }
  const row = {
    date: date,
    main_meter: mainV,
    sub_meter: subV,
    water: waterV,
    note: document.getElementById('utility-note').value.trim(),
  };

  // 同日期已存在 → 确认覆盖(仅更新水电字段,4 表读数保留)
  const all = await fetchReadings();
  const existing = all.find(r => r.date === row.date);
  if (existing) {
    const ok = await showModal({
      title: '覆盖已有数据',
      icon: '⚠️',
      iconKind: 'warn',
      body: `<strong>${row.date}</strong> 已有抄表记录,是否覆盖水电字段?<br><br>
        <span style="opacity:0.7">现有:</span> 总表 ${existing.main_meter ?? '—'} · 分表 ${existing.sub_meter ?? '—'} · 水表 ${existing.water ?? '—'}<br>
        <span style="opacity:0.7">新数据:</span> 总表 ${row.main_meter ?? '—'} · 分表 ${row.sub_meter ?? '—'} · 水表 ${row.water ?? '—'}`,
      confirmText: '覆盖',
      confirmKind: 'primary',
    });
    if (!ok) return;
  }

  try {
    await saveReadingRemote(row);
    showAlert(`✓ ${date} 水电已保存`, 'success');
    ['main_meter', 'sub_meter', 'water', 'utility-note'].forEach(id => document.getElementById(id).value = '');
    await refreshAndRender();
  } catch (err) {
    showAlert(`保存失败: ${err.message}`, 'error');
  }
});



// ===== 月份选择器 =====
/**
 * 收集有数据的月份,填充"历史对比"下拉
 */
function refreshMonthSelectors() {
  const monthsSet = new Set();
  CURRENT_READINGS.forEach(r => monthsSet.add(r.date.slice(0, 7)));
  const months = [...monthsSet].sort();
  const opts = months.length === 0
    ? '<option value="">(暂无数据)</option>'
    : months.map(m => `<option value="${m}">${m}</option>`).join('');

  // 当月统计:月份下拉(默认最新月),切换时重渲染统计卡
  const statsSel = document.getElementById('stats-month');
  if (statsSel) {
    const prev = statsSel.value;
    statsSel.innerHTML = opts;
    const newVal = prev && months.includes(prev) ? prev : (months.length > 0 ? months[months.length - 1] : '');
    if (statsSel.value !== newVal) {
      statsSel.value = newVal;
      renderStats(CURRENT_READINGS, CURRENT_CHARGES);
    }
  }

  // 用电占比:月份 A/B 下拉(默认 A=上月, B=本月),切换/对比时重渲染饼图
  const pieA = document.getElementById('pie-month-a');
  const pieB = document.getElementById('pie-month-b');
  if (pieA) {
    const prevA = pieA.value;
    pieA.innerHTML = opts;
    const newA = prevA && months.includes(prevA) ? prevA : (months.length > 0 ? months[months.length - 1] : '');
    if (pieA.value !== newA) pieA.value = newA;
  }
  if (pieB) {
    const prevB = pieB.value;
    pieB.innerHTML = opts;
    const newB = prevB && months.includes(prevB) ? prevB : (months.length >= 2 ? months[months.length - 2] : (months.length > 0 ? months[months.length - 1] : ''));
    if (pieB.value !== newB) pieB.value = newB;
  }
  if (pieA && pieA.value) renderPieChart(CURRENT_READINGS, CURRENT_CHARGES);

  // 月度报告:有数据月份下拉,默认最后月;值变化时重新加载
  const reportSel = document.getElementById('report-month');
  if (reportSel) {
    const prev = reportSel.value;
    reportSel.innerHTML = opts;
    const newVal = prev && months.includes(prev) ? prev : (months.length > 0 ? months[months.length - 1] : '');
    if (reportSel.value !== newVal) {
      reportSel.value = newVal;
      loadMonthlyReport();
    }
  }

  // 年度汇总:有数据年份下拉,默认最后年;首次填充后加载
  const years = [...new Set(months.map(m => m.slice(0, 4)))].sort();
  const yearSel = document.getElementById('yearly-year');
  if (yearSel) {
    const prev = yearSel.value;
    const yopts = years.length === 0
      ? '<option value="">(暂无数据)</option>'
      : years.map(y => `<option value="${y}">${y} 年</option>`).join('');
    yearSel.innerHTML = yopts;
    const newVal = prev && years.includes(prev) ? prev : (years.length > 0 ? years[years.length - 1] : '');
    if (yearSel.value !== newVal) {
      yearSel.value = newVal;
      loadYearlyReport();
    }
  }

  // 录入历史:月份筛选下拉,默认最后月;值变化时重新渲染
  const histSel = document.getElementById('history-month');
  if (histSel) {
    const prev = histSel.value;
    histSel.innerHTML = opts;
    const newVal = prev && months.includes(prev) ? prev : (months.length > 0 ? months[months.length - 1] : '');
    if (histSel.value !== newVal) {
      histSel.value = newVal;
      renderHistory(CURRENT_READINGS);
    }
  }

  // 充值记录:月份筛选下拉(用充值的月份,独立于抄表月份)
  const chargeSel = document.getElementById('charge-month');
  if (chargeSel) {
    const cMonths = [...new Set((CURRENT_CHARGES || []).map(c => c.date.slice(0, 7)))].sort();
    const copts = cMonths.length === 0
      ? '<option value="">(暂无数据)</option>'
      : cMonths.map(m => `<option value="${m}">${m}</option>`).join('');
    const prev = chargeSel.value;
    chargeSel.innerHTML = copts;
    const newVal = prev && cMonths.includes(prev) ? prev : (cMonths.length > 0 ? cMonths[cMonths.length - 1] : '');
    if (chargeSel.value !== newVal) {
      chargeSel.value = newVal;
      renderChargeLog(CURRENT_CHARGES);
    }
  }

  // 月度水电:月份下拉(有水电表底的月份)
  const utilSel = document.getElementById('utilities-month');
  if (utilSel) {
    const uMonths = [...new Set((CURRENT_READINGS || [])
      .filter(r => r.main_meter != null)
      .map(r => r.date.slice(0, 7)))].sort();
    const uopts = uMonths.length === 0
      ? '<option value="">(暂无数据)</option>'
      : uMonths.map(m => `<option value="${m}">${m}</option>`).join('');
    const prev = utilSel.value;
    utilSel.innerHTML = uopts;
    const newVal = prev && uMonths.includes(prev) ? prev : (uMonths.length > 0 ? uMonths[uMonths.length - 1] : '');
    if (utilSel.value !== newVal) {
      utilSel.value = newVal;
      loadMonthlyUtilities();
    }
  }
}


/**
 * 历史对比:计算并显示两个月份的对比
 * 已并入「用电占比」模块 — 从 pie-month-a/b 读值,渲染到占比卡下方
 */
async function applyCompare(a, b) {
  const container = document.getElementById('pie-compare-result');
  if (!container) return;
  if (!a || !b) {
    container.innerHTML = '<div class="empty">请选择两个月份</div>';
    return;
  }
  if (a === b) {
    container.innerHTML = '<div class="empty">请选择不同的月份</div>';
    return;
  }
  container.innerHTML = '<div class="empty">计算中...</div>';

  // 计算两月各自的 4 块表用电(复用月度报告引擎:全月用电含跨月段)
  const calcFor = async (m) => {
    const rep = await fetchMonthlyReport(m);
    if (!rep || !rep.summary || rep.summary.reading_days < 2) return null;
    // 已覆盖天数:该月最后有值的天(1-based)。
    // 完整月(下月已有抄表)= 自然月天数;进行中的月(如 8 月只到 8/15)= 实际覆盖天数。
    // 不能一律用自然月天数 — 否则进行中的月日均被稀释(用户反馈)。
    let covered = 0;
    const dArr = rep.days || [];
    for (let i = dArr.length - 1; i >= 0; i--) {
      const dd = dArr[i];
      // 只认「至少一块表用电 > 0」的天;V4 对无下次抄表的末段补 0,不能算覆盖
      if ((dd.hall || 0) > 0 || (dd.fire || 0) > 0 || (dd.private_room || 0) > 0 || (dd.ac || 0) > 0) {
        covered = i + 1;
        break;
      }
    }
    const days = Math.max(covered, 1);
    return CHARGE_METERS.map(({ key, label }) => {
      const total = rep.summary.by_meter[key];
      return { label, total, daily: total / days, days };
    });
  };

  const [dataA, dataB] = await Promise.all([calcFor(a), calcFor(b)]);
  if (!dataA || !dataB) {
    const missing = !dataA ? a : b;
    container.innerHTML = `<div class="empty">${missing} 至少需要 2 次抄表</div>`;
    return;
  }

  // 渲染对比表:一行一块表,两月日均并排 + 变化列(涨红跌绿)
  const totalDailyA = dataA.reduce((s, d) => s + d.daily, 0);
  const totalDailyB = dataB.reduce((s, d) => s + d.daily, 0);
  const pct = (x, y) => {
    if (y <= 0) return '<span style="opacity:0.5;">—</span>';
    const v = ((x - y) / y) * 100;
    const up = v > 0;
    return `<span style="color:${up ? 'var(--danger)' : 'var(--success)'};font-weight:600;">${up ? '▲' : '▼'} ${Math.abs(v).toFixed(1)}%</span>`;
  };
  const meterRows = dataA.map((dA, i) => {
    const dB = dataB[i];
    return `
      <tr>
        <td class="c-name">${dA.label}</td>
        <td>${dA.daily.toFixed(1)} <span class="c-sub">${dA.total.toFixed(0)} 度</span></td>
        <td>${dB.daily.toFixed(1)} <span class="c-sub">${dB.total.toFixed(0)} 度</span></td>
        <td class="c-chg">${pct(dB.daily, dA.daily)}</td>
      </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="compare-table-wrap">
      <table class="compare-table">
        <thead>
          <tr>
            <th class="c-name">表</th>
            <th>${a} <span class="badge">${dataA[0].days} 天</span></th>
            <th>${b} <span class="badge">${dataB[0].days} 天</span></th>
            <th class="c-chg">变化</th>
          </tr>
        </thead>
        <tbody>
          <tr class="c-total">
            <td class="c-name">总日均</td>
            <td>${totalDailyA.toFixed(1)}</td>
            <td>${totalDailyB.toFixed(1)}</td>
            <td class="c-chg">${pct(totalDailyB, totalDailyA)}</td>
          </tr>
          ${meterRows}
        </tbody>
      </table>
    </div>
    <div class="sub" style="color:var(--text-muted);font-size:12px;margin-top:8px;">
      日均 = 月总用电 ÷ 已覆盖天数(完整月 = 整月;进行中的月 = 实际有数据的天数)。变化 = 后月较前月日均涨跌。
    </div>
  `;
}

/**
 * 计算指定月份每块表的"用电总量"和"日均用电量"
 * 用电总量 = (月初读数 - 月末读数) × 倍率 + 月内充值 × 倍率
 * 日均 = 用电总量 / 月内天数
 */
function calcMonthlyReport(readings, charges, monthKey) {
  const monthData = readings.filter(r => r.date.startsWith(monthKey));
  if (monthData.length < 2) return null;

  const sorted = [...monthData].sort((a, b) => a.date.localeCompare(b.date));
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const days = Math.max(1, (new Date(last.date) - new Date(first.date)) / 86400000);

  const rows = [];
  let totalUsage = 0;
  for (const key of ['hall', 'fire', 'private_room', 'ac']) {
    const delta = realKwh(first[key] - last[key], key);
    const charged = sumChargesBetween(charges, key, first.date, last.date);
    const usage = delta + charged;
    const daily = usage / days;
    totalUsage += usage;
    rows.push({
      meter: key,
      label: LABELS[key],
      multiplier: MULTIPLIER[key],
      firstReading: first[key],
      lastReading: last[key],
      chargedKwh: charged,
      usageKwh: usage,
      dailyKwh: daily,
    });
  }
  return {
    month: monthKey,
    firstDate: first.date,
    lastDate: last.date,
    days,
    rows,
    totalUsageKwh: totalUsage,
    totalDailyKwh: totalUsage / days,
    // 本月充值金额(¥)
    monthChargeYuan: rows.reduce((s, r) => s + r.chargedKwh * ELECTRICITY_PRICE, 0),
  };
}

/**
 * 把月报转成 CSV 字符串(带 BOM,Excel 打开不乱码)
 */
function buildMonthlyReportCSV(report) {
  const lines = [];
  lines.push(`工程部管理系统月度统计报表`);
  lines.push(`统计月份,${report.month}`);
  lines.push(`统计区间,${report.firstDate} 至 ${report.lastDate} (${report.days.toFixed(1)} 天)`);
  lines.push(``);
  lines.push(`表号,倍率,月初读数,月末读数,本月充电(度),用电总量(度),日均用电(度/天),折合金额(元)`);
  const meterNo = { hall: '1#', fire: '2#', private_room: '3#', ac: '4#' };
  for (const r of report.rows) {
    lines.push([
      `${meterNo[r.meter]}${r.label}`,
      `×${r.multiplier}`,
      r.firstReading.toFixed(2),
      r.lastReading.toFixed(2),
      r.chargedKwh.toFixed(1),
      r.usageKwh.toFixed(1),
      r.dailyKwh.toFixed(2),
      (r.usageKwh * ELECTRICITY_PRICE).toFixed(2),
    ].join(','));
  }
  lines.push(`合计,,,—,—,${report.rows.reduce((s, r) => s + r.chargedKwh, 0).toFixed(1)},${report.totalUsageKwh.toFixed(1)},${report.totalDailyKwh.toFixed(2)},${(report.totalUsageKwh * ELECTRICITY_PRICE).toFixed(2)}`);
  lines.push(``);
  lines.push(`本月充值总金额(元),${report.monthChargeYuan.toFixed(2)}`);
  return lines.join('\n');
}

function downloadCSV(filename, content) {
  const blob = new Blob(['\uFEFF' + content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// 当月统计:月份切换重渲染
const statsMonthSel = document.getElementById('stats-month');
if (statsMonthSel) statsMonthSel.addEventListener('change', () => renderStats(CURRENT_READINGS, CURRENT_CHARGES));

// 用电占比:月份 A/B 切换或点「对比」重渲染
const pieSelA = document.getElementById('pie-month-a');
const pieSelB = document.getElementById('pie-month-b');
const pieCompareBtn = document.getElementById('pie-compare');
if (pieSelA) pieSelA.addEventListener('change', () => renderPieChart(CURRENT_READINGS, CURRENT_CHARGES));
if (pieSelB) pieSelB.addEventListener('change', () => renderPieChart(CURRENT_READINGS, CURRENT_CHARGES));
if (pieCompareBtn) pieCompareBtn.addEventListener('click', () => renderPieChart(CURRENT_READINGS, CURRENT_CHARGES));

// 物品管理:提交新物品
document.getElementById('btn-add-item').addEventListener('click', async () => {
  const name = document.getElementById('item-name').value.trim();
  const qty = parseFloat(document.getElementById('item-qty').value);
  const unit = document.getElementById('item-unit').value.trim();
  const note = document.getElementById('item-note').value.trim();
  if (!name) { showItemAlert('请填写物品名称', 'error'); return; }
  if (isNaN(qty) || qty < 0) { showItemAlert('数量必须 ≥ 0', 'error'); return; }
  try {
    await api('POST', '/api/items', { name, qty, unit, note });
    showItemAlert(`✓ ${name} 已添加`, 'success');
    document.getElementById('item-name').value = '';
    document.getElementById('item-qty').value = '';
    document.getElementById('item-unit').value = '';
    document.getElementById('item-note').value = '';
    await refreshAll();
  } catch (e) {
    showItemAlert('添加失败:' + e.message, 'error');
  }
});

// 申购:提交新申购
document.getElementById('btn-add-purchase').addEventListener('click', async () => {
  const date = document.getElementById('purchase-date').value;
  const name = document.getElementById('purchase-name').value.trim();
  const qty = parseFloat(document.getElementById('purchase-qty').value);
  const unit = document.getElementById('purchase-unit').value.trim();
  const est_price = parseFloat(document.getElementById('purchase-price').value);
  const supplier = document.getElementById('purchase-supplier').value.trim();
  const note = document.getElementById('purchase-note').value.trim();
  if (!name) { showItemAlert('请填写物品名称', 'error'); return; }
  if (isNaN(qty) || qty <= 0) { showItemAlert('数量必须 > 0', 'error'); return; }
  try {
    await api('POST', '/api/purchases', { date, name, qty, unit, est_price, supplier, note });
    showItemAlert(`✓ 申购已记录,去右侧「申购记录」确认购买`, 'success');
    document.getElementById('purchase-name').value = '';
    document.getElementById('purchase-qty').value = '';
    document.getElementById('purchase-unit').value = '';
    document.getElementById('purchase-price').value = '';
    document.getElementById('purchase-supplier').value = '';
    document.getElementById('purchase-note').value = '';
    await refreshAll();
  } catch (e) {
    showItemAlert('添加失败:' + e.message, 'error');
  }
});

// ========== 月度报告(逐日逐表用电) ==========
async function fetchMonthlyReport(month) {
  try {
    const r = await fetch(`api/monthly-report?month=${encodeURIComponent(month)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn('月度报告加载失败:', e);
    return null;
  }
}

function fmtKwh(v) {
  if (!v) return '0';
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
}

function renderMonthlyReport(data) {
  const tableEl = document.getElementById('monthly-report-table');
  const emptyEl = document.getElementById('report-empty');
  const tbody = document.getElementById('report-body');
  const summary = document.getElementById('report-summary');
  
  if (!data || !data.days || data.days.length === 0) {
    tableEl.style.display = 'none';
    emptyEl.style.display = 'block';
    emptyEl.textContent = data ? `${data.month} 当月暂无抄表数据` : '加载失败,请检查后端';
    return;
  }
  
  tableEl.style.display = 'block';
  emptyEl.style.display = 'none';
  document.getElementById('btn-export-word').style.display = 'inline-block';
  document.getElementById('btn-copy-report').style.display = 'inline-block';

  tbody.innerHTML = '';
  for (const d of data.days) {
    const tr = document.createElement('tr');
    tr.className = d.is_reading_day ? 'reading-day' : 'empty-row';
    tr.innerHTML = `
        <td class="col-date">${d.date.slice(5)}</td>
        <td>${fmtKwh(d.hall)}</td>
        <td>${fmtKwh(d.fire)}</td>
        <td>${fmtKwh(d.private_room)}</td>
        <td>${fmtKwh(d.ac)}</td>
        <td class="col-total">${fmtKwh(d.total)}</td>
      `;
    tbody.appendChild(tr);
  }
  
  // 渲染月度汇总:4 表 stat 卡 + 全宽合计大卡(与当月统计/余量预警同款)
  const s = data.summary;
  const meterCards = [
    ['hall', '1#大厅'], ['fire', '2#消防'], ['private_room', '3#包厢'], ['ac', '4#空调'],
  ].map(([key, label]) => `
    <div class="stat-card ${key === 'private_room' ? 'private' : key}">
      <div class="label">${label}</div>
      <div class="value">${fmtKwh(s.by_meter[key])}<small>度</small></div>
    </div>`).join('');
  // 日均按实际覆盖天数(有真实用电的天)
  let covered = 0;
  for (const d of data.days) {
    if ((d.hall || 0) > 0 || (d.fire || 0) > 0 || (d.private_room || 0) > 0 || (d.ac || 0) > 0) covered++;
  }
  const avg = covered > 0 ? s.total_kwh / covered : 0;
  summary.innerHTML = `
    <div class="stat-grid">
      ${meterCards}
    </div>
    <div class="stat-card total total-wide" style="margin-top:12px;">
      <div>
        <div class="label">月度合计</div>
        <div class="value">${fmtKwh(s.total_kwh)}<small>度</small></div>
      </div>
      <div class="total-info">
        <div>日均 ${avg.toFixed(1)} 度 · 覆盖 ${covered} 天</div>
        <div style="color:var(--warn);font-weight:600;">本月电费 ¥ ${s.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</div>
      </div>
    </div>
  `;
}

let _reportLoadToken = 0;
let _currentReport = null;  // 缓存当前月份的报告数据(供"复制表格"使用)
let _monthCopyData = null;  // 缓存当前月/上月用电数据(供"每月用电"复制按钮使用)

// 上一个月键:2026-08 → 2026-07
function prevMonthKey(monthKey) {
  const y = parseInt(monthKey.slice(0, 4), 10);
  const m = parseInt(monthKey.slice(5, 7), 10);
  if (m === 1) return `${y - 1}-12`;
  return `${y}-${String(m - 1).padStart(2, '0')}`;
}
async function loadMonthlyReport() {
  const month = document.getElementById('report-month').value;
  if (!month) return;
  const token = ++_reportLoadToken;
  const emptyEl = document.getElementById('report-empty');
  emptyEl.style.display = 'block';
  emptyEl.textContent = '加载中...';
  document.getElementById('monthly-report-table').style.display = 'none';
  document.getElementById('btn-export-word').style.display = 'none';

  const data = await fetchMonthlyReport(month);
  if (token !== _reportLoadToken) return;
  _currentReport = data;
  renderMonthlyReport(data);
}

// ========== 年度汇总 ==========
async function fetchYearlyReport(year) {
  try {
    const r = await fetch(`api/yearly-report?year=${encodeURIComponent(year)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn('年度汇总加载失败:', e);
    return null;
  }
}

let _yearlyChart = null;  // 年度柱状图实例(切换年份前必须 destroy)

function renderYearlyReport(data) {
  const box = document.getElementById('yearly-result');
  const copyBtn = document.getElementById('btn-copy-yearly');
  // 销毁旧图表,避免 canvas 残留/重复
  if (_yearlyChart) { _yearlyChart.destroy(); _yearlyChart = null; }
  if (!data || !data.months || data.months.length === 0) {
    box.innerHTML = '<div class="report-empty">该年暂无抄表数据</div>';
    copyBtn.style.display = 'none';
    return;
  }
  copyBtn.style.display = 'inline-block';

  // 按表累计(年度合计行)
  const keys = ['hall', 'fire', 'private_room', 'ac'];
  const totals = {};
  keys.forEach(k => totals[k] = data.months.reduce((s, m) => s + (m.by_meter[k] || 0), 0));

  const rows = data.months.map(m => `
    <tr>
      <td class="col-date">${m.month}</td>
      <td>${fmtKwh(m.by_meter.hall)}</td>
      <td>${fmtKwh(m.by_meter.fire)}</td>
      <td>${fmtKwh(m.by_meter.private_room)}</td>
      <td>${fmtKwh(m.by_meter.ac)}</td>
      <td class="col-total">${fmtKwh(m.total_kwh)}</td>
      <td class="col-total">¥ ${m.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
    </tr>`).join('');

  box.innerHTML = `
    <div class="chart-wrap" style="height:240px;margin-bottom:16px;"><canvas id="chart-yearly"></canvas></div>
    <div class="table-container">
      <table class="report-grid-table">
        <thead>
          <tr>
            <th class="col-date">月份</th><th>1#大厅</th><th>2#消防</th><th>3#包厢</th><th>4#空调</th>
            <th class="col-total">合计(度)</th><th class="col-total">电费(元)</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
          <tr class="total-row">
            <td class="col-date">年度合计</td>
            <td>${fmtKwh(totals.hall)}</td><td>${fmtKwh(totals.fire)}</td>
            <td>${fmtKwh(totals.private_room)}</td><td>${fmtKwh(totals.ac)}</td>
            <td class="col-total">${fmtKwh(data.year_total_kwh)}</td>
            <td class="col-total">¥ ${data.year_total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
          </tr>
        </tbody>
      </table>
    </div>`;

  // 12 个月 4 表堆叠柱状图(主题色,与 legend 一致)
  const canvas = document.getElementById('chart-yearly');
  _yearlyChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.months.map(m => m.month.slice(5)),
      datasets: [
        { label: '1#大厅', data: data.months.map(m => m.by_meter.hall), backgroundColor: COLORS.hall },
        { label: '2#消防', data: data.months.map(m => m.by_meter.fire), backgroundColor: COLORS.fire },
        { label: '3#包厢', data: data.months.map(m => m.by_meter.private_room), backgroundColor: COLORS.private_room },
        { label: '4#空调', data: data.months.map(m => m.by_meter.ac), backgroundColor: COLORS.ac },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label} ${fmtKwh(ctx.raw)} 度` } },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, title: { display: true, text: '用电(度)' } },
      },
    },
  });
}

function copyYearlyTSV(data) {
  const lines = ['工程部管理系统年度汇总报表', `统计年份,${data.year}`, ''];
  lines.push(['月份', '1#大厅', '2#消防', '3#包厢', '4#空调', '合计(度)', '电费(元)'].join('\t'));
  data.months.forEach(m => {
    lines.push([m.month, m.by_meter.hall, m.by_meter.fire, m.by_meter.private_room, m.by_meter.ac, m.total_kwh, m.total_cost].join('\t'));
  });
  lines.push(['年度合计', '', '', '', '', data.year_total_kwh, data.year_total_cost].join('\t'));
  copyTextWithFallback(lines.join('\n'), '✓ 年度汇总已复制,可粘贴到 Excel');
}

// 月度报告复制 TSV(粘贴到 Excel 自动成表):每日明细 + 每表总用电 + 合计 + 电费
function copyReportTSV(data) {
  const lines = ['工程部管理系统月度统计报表', `统计月份,${data.month}`, ''];
  lines.push(['日期', '1#大厅', '2#消防', '3#包厢', '4#空调', '合计(度)'].join('\t'));
  data.days.forEach(d => {
    lines.push([d.date, d.hall, d.fire, d.private_room, d.ac, d.total].join('\t'));
  });
  lines.push('');
  // 每块电表总用电(与页面汇总卡一致)
  lines.push(['各表总用电', data.summary.by_meter.hall, data.summary.by_meter.fire,
    data.summary.by_meter.private_room, data.summary.by_meter.ac, data.summary.total_kwh].join('\t'));
  lines.push(['月度合计', '', '', '', '', data.summary.total_kwh].join('\t'));
  lines.push(['本月电费', '', '', '', '', `¥ ${data.summary.total_cost.toFixed(2)}`].join('\t'));
  copyTextWithFallback(lines.join('\n'), '✓ 月度报告已复制,可粘贴到 Excel');
}

// 每月用电复制:复制当前月各区域度数 + 金额 + 对比上月,可直接粘贴到群
function copyMonthUsage() {
  if (!_monthCopyData || !_monthCopyData.monthKey) { showAlert('暂无本月用电数据可复制', 'error'); return; }
  const d = _monthCopyData;
  const lines = [`【${d.monthKey} 各区域用电】`];
  let hasData = false;
  for (const m of CHARGE_METERS) {
    const kwh = d.per[m.key];
    if (kwh == null || kwh <= 0) { lines.push(`${m.icon} ${m.label}: —`); continue; }
    hasData = true;
    // 对比上月
    let vsP = '';
    const prevKwh = d.prev[m.key];
    if (d.hasPrev && prevKwh != null && prevKwh > 0) {
      const diff = kwh - prevKwh;
      const pct = (diff / prevKwh) * 100;
      vsP = ` 较上月${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
    }
    lines.push(`${m.icon} ${m.label}: ${kwh.toFixed(1)} 度,¥${(kwh * ELECTRICITY_PRICE).toFixed(2)}${vsP}`);
  }
  if (!hasData) { showAlert('本月暂无用电数据可复制', 'error'); return; }
  // 合计行
  let vsTotal = '';
  if (d.hasPrev && d.prevTotal > 0) {
    const diff = d.monthTotal - d.prevTotal;
    const pct = (diff / d.prevTotal) * 100;
    vsTotal = ` 较上月${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
  }
  lines.push(`— 合计: ${d.monthTotal.toFixed(1)} 度,¥${(d.monthTotal * ELECTRICITY_PRICE).toFixed(2)}${vsTotal}`);
  lines.push(`(当月日均 ${(d.monthTotal / d.monthDays).toFixed(1)} 度/天)`);
  const text = lines.join('\n');
  copyTextWithFallback(text, '✓ 每月用电已复制,可直接粘贴到群里');
}

// ===== 充值计算弹窗 =====
// 注意:.modal-backdrop 默认 opacity:0 + pointer-events:none,必须加 .show 类才可见可点
function openTopupModal() {
  const backdrop = document.getElementById('topup-modal-backdrop');
  if (!backdrop) return;
  backdrop.classList.add('show');
  recalcTopup();
  document.getElementById('topup-days').focus();
  document.getElementById('topup-days').select();
}
function closeTopupModal() {
  const backdrop = document.getElementById('topup-modal-backdrop');
  if (backdrop) backdrop.classList.remove('show');
}
// 按预充天数 × 本月日均,算出每块表需充值表读数 + 金额(实时)
function recalcTopup() {
  const daysEl = document.getElementById('topup-days');
  const resultEl = document.getElementById('topup-result');
  const totalEl = document.getElementById('topup-total');
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
    const meterVal = actualKwh / MULTIPLIER[m.key];  // 表读数(充值录入值)
    const yuan = actualKwh * ELECTRICITY_PRICE;
    totalMeter += meterVal;
    totalActual += actualKwh;
    totalYuan += yuan;
    const basis = usage ? `<span style="opacity:.7">${usage.basisLabel || '本月日均'}</span>` : '暂无日均数据';
    const mult = MULTIPLIER[m.key];
    const daysLeft = daily > 0 ? (actualKwh / daily) : 0;
    return `
      <div style="background:var(--bg-subtle,#f7f7f8);border:1px solid var(--border);border-radius:8px;padding:8px 10px;" data-daily="${daily.toFixed(4)}">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <span style="font-size:13px;min-width:60px;font-weight:600;">${m.meterNo}${m.label}</span>
          <input type="number" class="field-control topup-meter" value="${Math.round(meterVal)}" step="1" data-mult="${mult}"
                 style="width:72px;padding:4px 6px;text-align:center;" title="表读数(充值录入值,可输入取整,自动反算其他值)">
          <span style="font-size:12px;color:var(--text-muted);white-space:nowrap;">×${mult}</span>
          <input type="number" class="field-control topup-actual" value="${Math.round(actualKwh)}" step="1" data-mult="${mult}"
                 style="width:88px;padding:4px 6px;text-align:center;" title="实际度数(可输入取整充值,自动反算其他值)">
          <span class="topup-yuan" style="font-size:12px;color:var(--text-muted);white-space:nowrap;">≈ ¥${Math.round(yuan)}</span>
        </div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px;padding-left:60px;line-height:1.5;">
          日均 ${Math.round(daily)} 度/天 ${basis}
          <span class="topup-daysleft" style="color:#059669;font-weight:600;">≈ 可用 ${Math.round(daysLeft)} 天</span>
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
  const totalEl = document.getElementById('topup-total');
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

document.getElementById('btn-topup-calc').addEventListener('click', openTopupModal);
document.getElementById('topup-close').addEventListener('click', closeTopupModal);
document.getElementById('topup-days').addEventListener('input', recalcTopup);
// 实际度数输入框(动态生成)→ 事件委托,输入时反向计算
document.getElementById('topup-result').addEventListener('input', e => {
  if (!e.target.classList) return;
  if (e.target.classList.contains('topup-actual')) {
    onTopupActualInput(e.target);
  } else if (e.target.classList.contains('topup-meter')) {
    onTopupMeterInput(e.target);
  }
});
document.getElementById('topup-modal-backdrop').addEventListener('click', e => {
  if (e.target === document.getElementById('topup-modal-backdrop')) closeTopupModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('topup-modal-backdrop').classList.contains('show')) closeTopupModal();
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
btnCopyDay.addEventListener('click', () => {
  const original = btnCopyDay.textContent;
  btnCopyDay.disabled = true;
  btnCopyDay.textContent = '✓ 已复制';
  copyDayUsage();
  setTimeout(() => {
    btnCopyDay.disabled = false;
    btnCopyDay.textContent = original;
  }, 3000);
});

// ========== 月度水电(总表/分表/厨房/水表)==========
async function fetchMonthlyUtilities(month) {
  try {
    const r = await fetch(`api/monthly-utilities?month=${encodeURIComponent(month)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn('月度水电加载失败:', e);
    return null;
  }
}

function renderMonthlyUtilities(data) {
  const box = document.getElementById('utilities-result');
  if (!data) { box.innerHTML = '<div class="report-empty">加载失败,请检查后端</div>'; return; }
  if (!data.has_data) { box.innerHTML = `<div class="report-empty">${data.msg || '该月未录入水电表底'}</div>`; return; }
  const fmt = (v, suffix) => v == null
    ? '—'
    : `${v.toLocaleString('zh-CN', { maximumFractionDigits: 1 })}<small>${suffix}</small>`;
  const yuan = (v) => v == null ? '—' : `¥ ${v.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
  box.innerHTML = `
    <div class="stat-grid" style="margin-top:8px;">
      <div class="stat-card hall">
        <div class="label">总表 ×${data.mult_main || 50}</div>
        <div class="value">${fmt(data.main_kwh, '度')}</div>
        <div class="sub">${data.prev_date ? `${data.prev_date} → ${data.cur.date}` : '缺上月表底'}</div>
      </div>
      <div class="stat-card fire">
        <div class="label">分表 ×${data.mult_sub || 40}</div>
        <div class="value">${fmt(data.sub_kwh, '度')}</div>
        <div class="sub">${data.cur.sub_meter == null ? '未录入' : `表底 ${data.cur.sub_meter}`}</div>
      </div>
      <div class="stat-card total">
        <div class="label">厨房(总表−分表)</div>
        <div class="value">${fmt(data.kitchen_kwh, '度')}</div>
        <div class="sub" style="color:var(--primary);font-weight:600;">电费 ${yuan(data.kitchen_cost)}</div>
      </div>
      <div class="stat-card ac">
        <div class="label">水表(用水)</div>
        <div class="value">${fmt(data.water_usage, '吨')}</div>
        <div class="sub" style="color:var(--success);font-weight:600;">水费 ${yuan(data.water_cost)}</div>
      </div>
    </div>
    <div class="sub" style="color:var(--text-muted);font-size:12px;margin-top:8px;">
      总表/分表/水表每月抄一次(读数递增),总表 ×50、分表 ×40 后为实际用电,厨房用电 = 总表实际 − 分表实际(不直接抄)。电价 ${data.price_electricity} 元/度 · 水价 ${data.price_water} 元/吨。
    </div>
  `;
}

async function loadMonthlyUtilities() {
  const month = document.getElementById('utilities-month').value;
  if (!month) return;
  renderMonthlyUtilities(await fetchMonthlyUtilities(month));
}
document.getElementById('utilities-month').addEventListener('change', loadMonthlyUtilities);

async function loadYearlyReport() {
  const year = document.getElementById('yearly-year').value;
  if (!year || year.length !== 4) { showAlert('请输入 4 位年份', 'error'); return; }
  document.getElementById('yearly-result').innerHTML = '<div class="report-empty">加载中...</div>';
  const data = await fetchYearlyReport(year);
  renderYearlyReport(data);
}
document.getElementById('yearly-apply').addEventListener('click', loadYearlyReport);
document.getElementById('btn-copy-yearly').addEventListener('click', () => {
  const year = document.getElementById('yearly-year').value;
  fetchYearlyReport(year).then(d => d && copyYearlyTSV(d));
});
// 默认加载当前年
// 年度汇总默认加载由 refreshMonthSelectors 填充默认年份后触发

// 生成 HTML 表格(粘贴到 Word/邮箱可识别为表格)
function buildReportHTML() {
  if (!_currentReport) return '';
  const d = _currentReport;
  const [yy, mm] = d.month.split('-');
  const daysInMonth = new Date(parseInt(yy), parseInt(mm), 0).getDate();

  // CSS 样式 — 内联确保 Word/Outlook 正确渲染
  const style = `
    <style>
      table.report { border-collapse: collapse; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 12pt; width: 100%; margin: 0 auto; }
      table.report caption { font-size: 18pt; font-weight: bold; padding: 12px; }
      table.report th, table.report td { border: 1px solid #000; padding: 6px 10px; text-align: right; }
      table.report th { background: #fff; font-weight: bold; text-align: center; }
      table.report td.date-col, table.report th.date-col { text-align: center; width: 50px; }
      table.report tr.empty-row td { color: #999; }
    </style>`;

  let html = style;
  html += `<table class="report">`;
  html += `<caption>${yy}年 ${parseInt(mm)}月每日用电统计</caption>`;
  html += `<thead><tr>`;
  html += `<th class="date-col">日期</th>`;
  html += `<th>1#大厅</th><th>2#消防</th><th>3#后勤包厢</th><th>4#空调</th>`;
  html += `<th>合计(度)</th>`;
  html += `</tr></thead><tbody>`;

  for (let day = 1; day <= daysInMonth; day++) {
    const d_str = `${yy}-${mm}-${String(day).padStart(2, '0')}`;
    const row = d.days.find(r => r.date === d_str);
    if (row && row.is_reading_day) {
      // 抄表日 — 显示该次用电(用户表格原样)
      html += `<tr><td class="date-col">${day}</td>`;
      html += `<td>${fmtKwh(row.hall)}</td>`;
      html += `<td>${fmtKwh(row.fire)}</td>`;
      html += `<td>${fmtKwh(row.private_room)}</td>`;
      html += `<td>${fmtKwh(row.ac)}</td>`;
      html += `<td>${fmtKwh(row.total)}</td></tr>`;
    } else if (row) {
      // 非抄表日 — 显示日均用电(每位: 段总用电 ÷ 段天数)
      html += `<tr class="empty-row"><td class="date-col">${day}</td>`;
      html += `<td>${fmtKwh(row.hall)}</td>`;
      html += `<td>${fmtKwh(row.fire)}</td>`;
      html += `<td>${fmtKwh(row.private_room)}</td>`;
      html += `<td>${fmtKwh(row.ac)}</td>`;
      html += `<td>${fmtKwh(row.total)}</td></tr>`;
    } else {
      // 月末最后一段(无下次抄表)— 显示空
      html += `<tr class="empty-row"><td class="date-col">${day}</td>`;
      html += `<td></td><td></td><td></td><td></td><td></td></tr>`;
    }
  }

  html += `</tbody></table>`;

  // 汇总区:每块电表总用电 + 月度合计 + 电费(领导要的汇总数据)
  const s = d.summary;
  const sumRow = (label, v) => `
    <tr>
      <td class="date-col" style="text-align:left;font-weight:bold;">${label}</td>
      <td>${fmtKwh(v.hall)}</td><td>${fmtKwh(v.fire)}</td>
      <td>${fmtKwh(v.private_room)}</td><td>${fmtKwh(v.ac)}</td>
      <td>${fmtKwh(v.total)}</td>
    </tr>`;
  html += `
    <table class="report" style="margin-top:16px;">
      <caption>${yy}年 ${parseInt(mm)}月汇总</caption>
      <thead><tr>
        <th class="date-col" style="text-align:left;">项目</th>
        <th>1#大厅</th><th>2#消防</th><th>3#后勤包厢</th><th>4#空调</th>
        <th>合计(度)</th>
      </tr></thead>
      <tbody>
        ${sumRow('各表总用电', { hall: s.by_meter.hall, fire: s.by_meter.fire, private_room: s.by_meter.private_room, ac: s.by_meter.ac, total: s.total_kwh })}
        <tr class="total-row">
          <td class="date-col" style="text-align:left;font-weight:bold;">月度合计</td>
          <td></td><td></td><td></td><td></td>
          <td style="font-weight:bold;">${fmtKwh(s.total_kwh)}</td>
        </tr>
        <tr>
          <td class="date-col" style="text-align:left;font-weight:bold;">本月电费</td>
          <td></td><td></td><td></td><td></td>
          <td style="font-weight:bold;">¥ ${s.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
        </tr>
      </tbody>
    </table>`;
  return html;
}

async function exportReportToWord() {
  const html = buildReportHTML();
  if (!html) {
    showAlert('暂无可导出的数据', 'error');
    return;
  }
  const btn = document.getElementById('btn-export-word');
  const origText = btn.textContent;
  const origBg = btn.style.background;
  // 立即给视觉反馈(不依赖 async):禁用 + 复制中
  btn.disabled = true;
  btn.textContent = '⏳ 复制中...';
  try {
    if (navigator.clipboard && window.ClipboardItem) {
      const blob = new Blob([html], { type: 'text/html' });
      await navigator.clipboard.write([new ClipboardItem({ 'text/html': blob })]);
    } else {
      // 回退:用临时 div + execCommand('copy')
      const div = document.createElement('div');
      div.innerHTML = html;
      div.style.position = 'fixed';
      div.style.left = '-9999px';
      document.body.appendChild(div);
      const range = document.createRange();
      range.selectNodeContents(div);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand('copy');
      sel.removeAllRanges();
      document.body.removeChild(div);
    }
    // 复制成功:绿色按钮 + 大字提示(保持禁用,3秒后恢复)
    btn.textContent = '✓ 已复制';
    btn.style.background = '#10b981';
    btn.style.borderColor = '#10b981';
    btn.style.color = '#fff';
    showAlert('✓ Word 表格已复制,去 Word 粘贴 (Cmd+V)', 'success');
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = origText;
      btn.style.background = origBg;
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 3000);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = origText;
    showAlert('导出失败:' + e.message, 'error');
  }
}

document.getElementById('btn-export-word').addEventListener('click', exportReportToWord);

document.getElementById('report-month').addEventListener('change', loadMonthlyReport);
document.getElementById('history-month').addEventListener('change', () => renderHistory(CURRENT_READINGS));
document.getElementById('charge-month').addEventListener('change', () => renderChargeLog(CURRENT_CHARGES));

// 录入卡/记录卡 内切换(📝抄表|⚡充值 / 📜抄表记录|💰充值记录)— 按卡片作用域,互不干扰
document.querySelectorAll('.entry-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    const card = btn.closest('.card');
    if (!card) return;
    card.querySelectorAll('.entry-tab').forEach(b => b.classList.toggle('active', b === btn));
    const entry = btn.dataset.entry;
    card.querySelectorAll('[data-panel]').forEach(p => {
      p.style.display = p.dataset.panel === entry ? 'block' : 'none';
    });
  });
});

// Tab 切换
function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  // 用 body class 控制显示
  document.body.classList.remove('show-meter', 'show-item', 'show-history');
  document.body.classList.add('show-' + tab);
  // 隐藏容器里初始化的 Chart 尺寸为 0,切回历史 tab 时需重新计算尺寸
  if (tab === 'history' && _yearlyChart) {
    setTimeout(() => _yearlyChart.resize(), 60);
  }
}
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});
// 默认显示电表管理
document.body.classList.add('show-meter');

// 页面打开时加载月度报告(默认月份由 refreshMonthSelectors 设定)
window.addEventListener('DOMContentLoaded', () => {
  applyTheme();
  loadMonthlyReport();
});

// ===== 初始化 =====
function todayStr() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
document.getElementById('date').value = todayStr();
document.getElementById('charge-date').value = todayStr();
document.getElementById('utility-date').value = todayStr();

// 启动时拉后端数据
(async () => {
  await renderAll();
  // 抄表提醒:距上次抄表 ≥ 3 天显示横幅
  if (CURRENT_READINGS && CURRENT_READINGS.length > 0) {
    const lastDate = CURRENT_READINGS[CURRENT_READINGS.length - 1].date;
    const gap = daysBetween(lastDate, todayStr());
    if (gap >= 3) {
      const el = document.getElementById('meter-reminder');
      document.getElementById('meter-reminder-text').textContent = `📅 距离上次抄表(${lastDate})已 ${gap} 天,记得去抄 4 块表的表底`;
      el.style.display = 'flex';
    }
  }
  // 首次访问提示
  if (CURRENT_READINGS.length === 0 && CURRENT_CHARGES.length === 0) {
    showAlert('👋 欢迎!先录入今天的抄表数据开始。', 'info');
  }
})();
