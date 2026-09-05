
'use strict';

// ===== 工具函数 =====
/** 安全获取 DOM 元素，不存在返回 null */
const el = (id) => document.getElementById(id);

// ===== 数据模型 =====
// 数据存在后端 server.py,LocalStorage 只作为离线兜底(后端不可用时)
const STORAGE_KEY_READINGS = 'meter_readings_v1';
const STORAGE_KEY_CHARGES = 'meter_charges_v1';

// ===== 元数据（从 /api/meters 动态获取，含 fallback 默认值）=====
let METER_CONFIG = {
  hall:   { label: '大厅',   icon: '🎤', multiplier: 160, color: '#2563eb' },
  fire:   { label: '消防',   icon: '🧯', multiplier: 1,   color: '#dc2626' },
  private_room: { label: '包厢', icon: '🛋️', multiplier: 160, color: '#059669' },
  ac:     { label: '空调',   icon: '❄️', multiplier: 160, color: '#d97706' },
};

// 快捷访问数组（保持顺序不变）
const METER_KEYS = ['hall', 'fire', 'private_room', 'ac'];
const METER_META = (key) => METER_CONFIG[key] || { label: key, icon: '', multiplier: 1, color: '#888' };
const MULTIPLIER = (key) => METER_META(key).multiplier;
const LABELS = (key) => METER_META(key).label;
const COLORS = (key) => METER_META(key).color;

// 加载元数据（异步，不阻塞页面加载）
async function loadMeterConfig() {
  try {
    const resp = await fetch('/api/meters', { credentials: 'same-origin' });
    if (resp.ok) {
      const data = await resp.json();
      if (data.meters) {
        for (const [key, val] of Object.entries(data.meters)) {
          METER_CONFIG[key] = { ...METER_CONFIG[key], ...val };
        }
        // 更新快捷访问
      }
    }
  } catch (e) {
    // 静默失败，使用默认值
  }
}

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
  // 当前可见的 section 触发对应的占比
  triggerVisiblePie();
  if (_yearlyChart) {
    setTimeout(() => _yearlyChart.resize(), 60);
  }
}

// 当前可见 section 的占比饼图(每日/月度)
function triggerVisiblePie() {
  const trendVisible = document.getElementById('section-report-trend')?.style.display !== 'none';
  const monthlyVisible = document.getElementById('section-report-monthly')?.style.display !== 'none';
  if (trendVisible) {
    const sel = document.getElementById('day-copy-date');
    if (sel && sel.value) renderDailyPie(sel.value);
  } else if (monthlyVisible) {
    const sel = document.getElementById('report-month');
    if (sel && sel.value) renderMonthlyPie(sel.value);
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
let CURRENT_DUTY = [];

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

async function fetchDuty() {
  try {
    const data = await api('GET', '/api/duty');
    CURRENT_DUTY = data;
    return data;
  } catch (e) {
    console.warn('后端不可用,duty 用空数组:', e);
    CURRENT_DUTY = [];
    return [];
  }
}

// 一次拉全部数据(5 个 GET → 1 个 GET,启动时调用)
async function fetchSnapshot() {
  try {
    const data = await api('GET', '/api/snapshot');
    CURRENT_READINGS = data.readings || [];
    CURRENT_CHARGES = data.charges || [];
    CURRENT_WATER_READINGS = data.readings_water || [];
    CURRENT_ITEMS = data.items || [];
    CURRENT_PURCHASES = data.purchases || [];
    CURRENT_DUTY = data.duty || [];
    cacheReadings(CURRENT_READINGS);
    cacheCharges(CURRENT_CHARGES);
    return data;
  } catch (e) {
    console.warn('snapshot 失败,回退到本地缓存:', e);
    CURRENT_READINGS = loadReadingsCache();
    CURRENT_CHARGES = loadChargesCache();
    CURRENT_ITEMS = [];
    CURRENT_PURCHASES = [];
    CURRENT_DUTY = [];
    return null;
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

// ===== 水电数据迁移 =====
let MIGRATION_CHECKED = false;

async function checkMigrateStatus() {
  try {
    const data = await api('GET', '/api/admin/migrate-water-status');
    return data;
  } catch (e) {
    console.warn('迁移检测失败:', e);
    return null;
  }
}

async function executeMigration() {
  try {
    const data = await api('POST', '/api/admin/migrate-water');
    return data;
  } catch (e) {
    console.warn('迁移执行失败:', e);
    return { ok: false, error: e.message };
  }
}

async function checkAndPromptMigration() {
  if (MIGRATION_CHECKED) return;
  MIGRATION_CHECKED = true;

  const status = await checkMigrateStatus();
  if (!status || !status.needs_migration) return;

  const { water_in_readings, water_dates, conflicts_with_existing, existing_water_count } = status;
  const datesText = water_dates.length <= 5
    ? water_dates.join('、')
    : `${water_dates.length} 个日期`;

  const confirm = await showModal({
    title: '🔄 数据升级提示',
    icon: '⬆️',
    iconKind: 'warn',
    body: `
      <p>检测到 <strong>${water_in_readings} 条抄表记录</strong>包含水电字段（总表/分表/水表）。</p>
      <p>涉及日期：<strong>${datesText}</strong></p>
      <p>本次升级将水电数据分离到独立文件，保证：</p>
      <ul style="text-align:left;font-size:13px;color:var(--text-muted);">
        <li>总表/分表/水表可以独立增删，不干扰电表抄表</li>
        <li>每月水电费用计算完全准确</li>
        <li>自动备份当前数据（可随时回滚）</li>
      </ul>
      ${conflicts_with_existing > 0
        ? `<p style="color:var(--warning);font-size:13px;">⚠️ 已有 ${conflicts_with_existing} 条独立水电记录将被覆盖</p>`
        : ''}
      <p style="margin-top:12px;">是否立即执行升级？</p>
    `,
    confirmText: '立即升级',
    confirmKind: 'primary',
    cancelText: '稍后再说',
  });

  if (!confirm) return;

  // 显示迁移中
  const overlay = el('toast-overlay');
  const content = el('toast-content');
  if (overlay && content) {
    overlay.style.display = 'flex';
    content.className = 'toast-content info';
    content.innerHTML = '⏳ 正在迁移数据，请稍候...';
  }

  const result = await executeMigration();

  // 隐藏 toast
  if (overlay && content) {
    setTimeout(() => {
      overlay.style.display = 'none';
    }, 500);
  }

  if (result.ok) {
    showAlert(
      `✅ 迁移完成！${result.migrated_count} 条水电记录已分离。`,
      'success'
    );
    // 刷新数据
    await refreshAndRender();
  } else {
    showAlert(`迁移失败：${result.error}`, 'error');
  }
}

// ===== 全局数据 =====
let CURRENT_WATER_READINGS = []; // 水电表底数据 (main_meter/sub_meter/water)

async function fetchWaterReadings() {
  try {
    const data = await api('GET', '/api/readings-water');
    CURRENT_WATER_READINGS = data;
    return data;
  } catch (e) {
    console.warn('fetchWaterReadings 失败:', e);
    CURRENT_WATER_READINGS = [];
    return [];
  }
}

async function saveWaterReadingRemote(row) {
  return api('POST', '/api/readings-water', row);
}
async function deleteWaterReadingRemote(date) {
  return api('DELETE', `/api/readings-water/${date}`);
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
async function saveDutyRemote(row) {
  return api('POST', '/api/duty', row);
}
async function updateDutyRemote(id, fields) {
  return api('PUT', `/api/duty/${id}`, fields);
}
async function deleteDutyRemote(id) {
  return api('DELETE', `/api/duty/${id}`);
}

// 同步本地缓存(写入成功后调)
function realKwh(value, key) {
  return value * MULTIPLIER(key);
}

// ===== 渲染 =====
Chart.defaults.color = '#7a818c';
Chart.defaults.borderColor = 'rgba(0, 0, 0, 0.08)';
Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
Chart.defaults.font.size = 11;

let trendChart = null;
let pieChart = null;        // 月度报告饼图(独立页面删除后保留兼容)
let pieChartB = null;       // 双月对比(已无人调用,保留占位)
let dailyPieChart = null;    // 每日趋势页的单日饼图
let monthlyPieChart = null;  // 月度报告页的当月饼图

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

// 数据管理弹窗(已废弃:数据管理改为独立页面,统一通过 admin.js 实现)
// 保留函数以防有外部代码还在调用,内部用 null check 防止报错
function openDataMgmtModal() {
  initAutoBackupToggle();
  loadDataMgmtBackupDir();
  const backdrop = document.getElementById('datamgmt-modal-backdrop');
  if (backdrop) backdrop.classList.add('show');
}
function closeDataMgmtModal() {
  const backdrop = document.getElementById('datamgmt-modal-backdrop');
  if (backdrop) backdrop.classList.remove('show');
}

// 数据管理弹窗: 加载备份目录配置
function loadDataMgmtBackupDir() {
  fetch('/api/admin/backup-config?token=' + encodeURIComponent(localStorage.getItem('meter_token') || ''))
    .then(r => r.json()).then(res => {
      const display = document.getElementById('datamgmt-backup-dir-display');
      if (!display) return;
      if (res.customizable === false) {
        display.textContent = '🔒 ' + (res.backup_dir || res.data_dir);
      } else {
        const dir = res.backup_dir || '默认: ' + res.data_dir + '/backup';
        display.textContent = dir;
      }
    }).catch(() => {});
}

// 数据管理弹窗: 选择备份目录
async function datamgmtSetBackupDir() {
  const dir = await pickBackupDir();
  if (!dir) {
    showAlert('未选择目录', 'info');
    return;
  }
  try {
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: dir });
    if (!res.ok) {
      showAlert('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showAlert('✅ 备份目录已更新', 'success');
    loadDataMgmtBackupDir();
  } catch (e) {
    showAlert('保存失败: ' + e.message, 'error');
  }
}

// 数据管理弹窗: 恢复默认备份目录
async function datamgmtResetBackupDir() {
  try {
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: null });
    if (!res.ok) {
      showAlert('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showAlert('✅ 已恢复默认备份目录', 'success');
    loadDataMgmtBackupDir();
  } catch (e) {
    showAlert('保存失败: ' + e.message, 'error');
  }
}

// 手动备份(从数据管理弹窗调用,已废弃:数据管理改为独立页面,统一走 adminBackup)
async function datamgmtBackup() {
  const btn = document.getElementById('datamgmt-backup-btn');
  if (!btn) return;  // 元素不存在(已迁移到独立页面),静默返回
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
    // 备份成功后刷新备份列表
    setTimeout(() => { if (typeof loadBackupList === 'function') loadBackupList(); }, 500);
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
      // Docker / Web 浏览器环境: 直接弹文件选择器
      pickBackupFiles().then(resolve);
    }
  });
}

// 浏览器/Docker 环境:直接弹文件选择器(不再需要中间确认模态框)
// 返回 { files: { "readings.json": "..." } } 或 null(用户取消)
function pickBackupFiles() {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.json,.zip';
    input.style.display = 'none';
    document.body.appendChild(input);
    let resolved = false;
    const cleanup = () => {
      if (input.parentNode) input.parentNode.removeChild(input);
    };
    input.addEventListener('change', async () => {
      resolved = true;
      cleanup();
      const files = Array.from(input.files);
      if (!files.length) {
        resolve(null);
        return;
      }
      const fileContents = {};
      for (const file of files) {
        // zip 文件用 arrayBuffer,JSON 文件用 text
        if (file.name.toLowerCase().endsWith('.zip')) {
          const buf = await file.arrayBuffer();
          fileContents[file.name] = { __zip_b64: arrayBufferToBase64(buf) };
        } else {
          fileContents[file.name] = await file.text();
        }
      }
      resolve({ files: fileContents, _browser: true });
    });
    // 用户关掉文件选择器(没选)→ focus 回到页面,但 change 不触发
    // 用 blur 兜底清理(可能误触发,但 cleanup 已加守护)
    input.addEventListener('blur', () => {
      setTimeout(() => {
        if (!resolved) {
          resolved = true;
          cleanup();
          resolve(null);
        }
      }, 300);
    });
    input.click();
  });
}

// ArrayBuffer → base64(用于在 JSON body 传 zip)
function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

// base64 → ArrayBuffer
function base64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
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

// 恢复数据(从数据管理弹窗调用,已废弃:统一走 adminRestore,通过 admin.js 实现)
async function datamgmtRestore() {
  const btn = document.getElementById('datamgmt-restore-btn');
  if (!btn) return;  // 元素不存在(已迁移到独立页面),静默返回
  const original = btn.textContent;
  try {
    const dir = await pickBackupDir();
    if (!dir) {
      showAlert('未选择文件,已取消恢复', 'info');
      return;
    }

    let res;
    if (dir._browser) {
      // 浏览器/Docker 环境: 上传文件 — JSON 单文件 或 ZIP 备份包
      const hasZip = Object.keys(dir.files).some(n => n.toLowerCase().endsWith('.zip'));
      const fileNames = Object.keys(dir.files).join(', ');
      const ok = await showModal({
        icon: '⚠️',
        iconKind: 'warn',
        title: '确认恢复数据？',
        body: `将从 <b>${fileNames}</b> 恢复${hasZip ? '(zip 备份包将自动解压)' : ''}。<br><br>⚠️ 当前数据会被覆盖,但恢复前系统会自动备份当前数据到 backup/ 目录,可随时回滚。`,
        confirmText: '确认恢复',
        cancelText: '取消',
        confirmKind: 'danger',
      });
      if (!ok) return;
      btn.textContent = '⏳ 恢复中…';
      btn.disabled = true;
      res = await api('POST', '/api/upload', { files: dir.files });
      if (!res.ok) {
        showAlert('恢复失败: ' + (res.error || '未知错误'), 'error');
        return;
      }
      const restoredCount = (res.restored || []).length;
      if (restoredCount > 0) {
        showAlert(`✅ 已恢复 ${restoredCount} 个数据文件${res.pre_backup ? ';恢复前数据已备份到 ' + res.pre_backup : ''}`, 'success');
      } else {
        showAlert(`✅ 已上传 ${(res.uploaded || []).length} 个文件`, 'success');
      }
      // 用 renderAll() 全量刷新: readings/charges/items/purchases/duty + 所有页面渲染,
      // 旧的 refreshAll() 只刷 items/purchases,会导致 readings/charges 页面不更新。
      await renderAll();
    } else {
      // macOS 原生 App: 用目录路径恢复
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
      // 同样改用 renderAll() 全量刷新(macOS 路径)
      await renderAll();
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
  // 一次拉全部数据(snapshot 优先,失败回退到 5 个独立 GET)
  await fetchSnapshot();
  CURRENT_READINGS = (CURRENT_READINGS || []).slice().sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_CHARGES = (CURRENT_CHARGES || []).slice().sort((a, b) => a.date.localeCompare(b.date));

  renderStats(CURRENT_READINGS, CURRENT_CHARGES);
  renderChargeAlert(CURRENT_READINGS, CURRENT_CHARGES);
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  triggerVisiblePie();
  renderHistory(CURRENT_READINGS);
  renderChargeLog(CURRENT_CHARGES);
  renderItemTable(CURRENT_ITEMS);
  renderLendHistory(CURRENT_ITEMS);
  renderPurchaseTable(CURRENT_PURCHASES);
  renderDutyTable(CURRENT_DUTY, '');
  populateDutyMonthSelector();
  refreshMonthSelectors();
  refreshDayCopySelect(CURRENT_READINGS, CURRENT_CHARGES);
  updateStatusBar(CURRENT_READINGS, CURRENT_CHARGES);
  // 水电数据迁移检测（只在首次加载时检查一次）
  if (!MIGRATION_CHECKED) {
    setTimeout(checkAndPromptMigration, 1500);
  }
}

// 通用:写入后端 → 重新拉数据 → 重渲染
async function refreshAndRender() {
  CURRENT_READINGS = (await fetchReadings()).sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_CHARGES = (await fetchCharges()).sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_WATER_READINGS = (await fetchWaterReadings()).sort((a, b) => a.date.localeCompare(b.date));
  await fetchItems();
  await fetchPurchases();
  renderStats(CURRENT_READINGS, CURRENT_CHARGES);
  renderChargeAlert(CURRENT_READINGS, CURRENT_CHARGES);
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  triggerVisiblePie();
  renderHistory(CURRENT_READINGS);
  renderChargeLog(CURRENT_CHARGES);
  renderItemTable(CURRENT_ITEMS);
  renderLendHistory(CURRENT_ITEMS);
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
    const remaining = last[m.key] * MULTIPLIER(m.key);
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
  renderLendHistory(CURRENT_ITEMS);
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
      const used = (a[meterKey] - b[meterKey]) * MULTIPLIER(meterKey) + charged;
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
    const readingDelta = (a[meterKey] - b[meterKey]) * MULTIPLIER(meterKey);
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
    { label: LABELS('hall'), data: dailyUsage.hall, borderColor: COLORS('hall'), backgroundColor: COLORS('hall') + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: LABELS('fire'), data: dailyUsage.fire, borderColor: COLORS('fire'), backgroundColor: COLORS('fire') + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: LABELS('private_room'), data: dailyUsage.private_room, borderColor: COLORS('private_room'), backgroundColor: COLORS('private_room') + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: LABELS('ac'), data: dailyUsage.ac, borderColor: COLORS('ac'), backgroundColor: COLORS('ac') + '20',
      tension: 0.3, borderWidth: 2.5, pointRadius: 2, pointHoverRadius: 5,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '充值', data: dailyCharge, borderColor: 'var(--warn)', backgroundColor: 'var(--warn)',
      borderWidth: 0, pointRadius: 6, pointHoverRadius: 8, pointStyle: 'rectRot',
      showLine: false, yAxisID: 'y2' },
    // 整月日均虚线 — 让短区间波动有参照基准
    { label: '大厅日均', data: avgLineData(avgLines.hall), borderColor: COLORS('hall'),
      borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '消防日均', data: avgLineData(avgLines.fire), borderColor: COLORS('fire'),
      borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '包厢日均', data: avgLineData(avgLines.private_room), borderColor: COLORS('private_room'),
      borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0,
      fill: false, spanGaps: true, yAxisID: 'y' },
    { label: '空调日均', data: avgLineData(avgLines.ac), borderColor: COLORS('ac'),
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

// 占比饼图 — 通用:传入 canvasId + 持有 chart 实例的变量 holder
// 用法:drawPieChart('chart-monthly-pie', data, c => monthlyPieChart = c)
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

// 占比饼图 — 通用:传入 canvasId + 持有 chart 实例的变量 holder
// 用法:drawPieChart('chart-monthly-pie', data, c => monthlyPieChart = c)
function drawPieChart(canvasId, data, setChart) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const labels = ['hall', 'fire', 'private_room', 'ac'].map((k, i) => {
    const pct = data.total > 0 ? (data.usage[i] / data.total * 100).toFixed(1) : 0;
    return `${LABELS(k)} (${pct}%)`;
  });
  const chart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: data.usage,
        backgroundColor: [COLORS('hall'), COLORS('fire'), COLORS('private_room'), COLORS('ac')],
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
            label: (c) => {
              const v = c.parsed;
              const pct = data.total > 0 ? (v / data.total * 100).toFixed(1) : 0;
              return `${c.label.split(' (')[0]}: ${v.toFixed(1)} 度 (${pct}%)`;
            },
          },
        },
      },
    },
  });
  if (setChart) setChart(chart);
  return chart;
}

// 单日占比(每日趋势页):从单天汇报下拉联动
function renderDailyPie(dateStr) {
  const wrap = document.getElementById('daily-pie-wrap');
  const summaryEl = document.getElementById('daily-pie-summary');
  if (!wrap || !summaryEl) return;

  const readings = CURRENT_READINGS.filter(r => r.hall != null);
  if (!dateStr || readings.length < 2) {
    wrap.style.display = 'none';
    return;
  }

  // 找到包含该日的前后两次抄表
  const sorted = [...readings].sort((a, b) => a.date.localeCompare(b.date));
  let prev = null, next = null;
  for (let i = 0; i < sorted.length; i++) {
    if (sorted[i].date <= dateStr) prev = sorted[i];
    if (sorted[i].date > dateStr) { next = sorted[i]; break; }
  }
  if (!prev || !next) {
    wrap.style.display = 'none';
    return;
  }

  // 计算 prev → next 区间,按天数均摊到 prev 日(与单天汇报口径一致)
  const days = Math.max(1, Math.round((new Date(next.date) - new Date(prev.date)) / 86400000));
  const usage = ['hall', 'fire', 'private_room', 'ac'].map(k => {
    const delta = realKwh(prev[k] - next[k], k);
    const charged = sumChargesBetween(CURRENT_CHARGES, k, prev.date, next.date);
    return Math.max((delta + charged) / days, 0);
  });
  const total = usage.reduce((a, b) => a + b, 0);

  wrap.style.display = '';
  // summary 文字
  const pct = (i) => total > 0 ? (usage[i] / total * 100).toFixed(1) : '0';
  summaryEl.innerHTML = `
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('hall')}"></span>大厅 ${usage[0].toFixed(1)} 度 (${pct(0)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('fire')}"></span>消防 ${usage[1].toFixed(1)} 度 (${pct(1)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('private_room')}"></span>包厢 ${usage[2].toFixed(1)} 度 (${pct(2)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('ac')}"></span>空调 ${usage[3].toFixed(1)} 度 (${pct(3)}%)</div>
  `;

  if (dailyPieChart) { dailyPieChart.destroy(); dailyPieChart = null; }
  drawPieChart('chart-daily-pie', { usage, total }, c => dailyPieChart = c);
}

// 月度占比(月度报告页):从「选择月份」下拉联动
function renderMonthlyPie(monthKey) {
  const wrap = document.getElementById('monthly-pie-wrap');
  const summaryEl = document.getElementById('monthly-pie-summary');
  if (!wrap || !summaryEl) return;

  const readings = CURRENT_READINGS.filter(r => r.hall != null);
  const data = calcMonthPie(readings.filter(r => r.date.startsWith(monthKey)), CURRENT_CHARGES);

  if (!data) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = '';

  const pct = (i) => data.total > 0 ? (data.usage[i] / data.total * 100).toFixed(1) : '0';
  summaryEl.innerHTML = `
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('hall')}"></span>大厅 ${data.usage[0].toFixed(1)} 度 (${pct(0)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('fire')}"></span>消防 ${data.usage[1].toFixed(1)} 度 (${pct(1)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('private_room')}"></span>包厢 ${data.usage[2].toFixed(1)} 度 (${pct(2)}%)</div>
    <div class="daily-pie-row"><span class="dot" style="background:${COLORS('ac')}"></span>空调 ${data.usage[3].toFixed(1)} 度 (${pct(3)}%)</div>
  `;

  if (monthlyPieChart) { monthlyPieChart.destroy(); monthlyPieChart = null; }
  drawPieChart('chart-monthly-pie', data, c => monthlyPieChart = c);
}

// 兼容旧入口(已被删除,但 admin.js 等可能引用)
function renderPieChart() {
  // 旧的独立占比页已删除,不再做任何事
}

// 物品管理表格
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

  // 合并抄表和水电表底数据用于显示
  // 水电表底和抄表记录是独立存储的，分别按日期键控
  const waterByDate = {};
  for (const w of (CURRENT_WATER_READINGS || [])) {
    waterByDate[w.date] = w;
  }

  // 合并所有有数据的日期：抄表记录 + 水电表底（独立、互不干扰）
  const allDates = new Set();
  for (const r of filtered) allDates.add(r.date);
  for (const w of CURRENT_WATER_READINGS || []) {
    if (waterByDate[w.date] && filtered.some(fr => fr.date === w.date)) {
      // 水电日期有对应抄表记录 → 抄表记录行中已包含水电列
    } else if (!filtered.some(fr => fr.date === w.date)) {
      // 水电日期没有对应抄表记录 → 补充为只含水电的虚拟行
      const waterRow = waterByDate[w.date];
      allDates.add(w.date);
    }
  }
  const sorted = [...allDates].sort((a, b) => b.localeCompare(a));

  if (sorted.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    empty.textContent = `${month ? month : '全部'} 暂无任何数据`;
    return;
  }
  empty.style.display = 'none';

  // 渲染日期列表
  tbody.innerHTML = sorted.map(date => {
    const r = readings.find(x => x.date === date);
    const waterRow = waterByDate[date] || {};
    const hasElectric = !!r;
    const hasWater = waterRow.main_meter != null || waterRow.sub_meter != null || waterRow.water != null;
    if (!hasElectric && !hasWater) return ''; // 双空，跳过

    // 抄表数据（可能不存在）
    const h = r?.hall ?? null, f = r?.fire ?? null, pr = r?.private_room ?? null, ac = r?.ac ?? null;
    const note = r?.note || '';

    // 水电表底
    const mm = waterRow.main_meter, sm = waterRow.sub_meter, wt = waterRow.water;

    return `
      <tr data-date="${date}" style="${!hasElectric ? 'background:var(--bg-surface);' : ''}">
        <td>${date}</td>
        <td>${h == null ? '—' : h.toFixed(2)}</td>
        <td>${f == null ? '—' : f.toFixed(2)}</td>
        <td>${pr == null ? '—' : pr.toFixed(2)}</td>
        <td>${ac == null ? '—' : ac.toFixed(2)}</td>
        <td>${mm == null ? '—' : mm.toFixed(1)}</td>
        <td>${sm == null ? '—' : sm.toFixed(1)}</td>
        <td>${wt == null ? '—' : wt.toFixed(1)}</td>
        <td style="color:var(--text-muted);font-size:12px;">${note || '—'}</td>
        <td>
          <button class="edit-btn" data-action="edit" data-date="${date}">编辑</button>
          <button class="delete-btn" data-action="delete" data-date="${date}" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;">删除</button>
        </td>
      </tr>
    `;
  }).filter(Boolean).join('');

  // 编辑
  tbody.querySelectorAll('[data-action="edit"]').forEach(btn => {
    btn.addEventListener('click', () => enterEditMode(btn.dataset.date));
  });
  // 删除
  tbody.querySelectorAll('[data-action="delete"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const date = btn.dataset.date;
      const ok = await showModal({
        title: '删除数据',
        icon: '🗑️',
        body: `确认删除 <strong>${date}</strong> 的记录?<br><span style="opacity:0.7">此操作不可恢复。</span>`,
        confirmText: '删除',
      });
      if (!ok) return;
      try {
        // 同时删除关联的水电表底(如果存在)
        if (CURRENT_WATER_READINGS.some(w => w.date === date)) {
          await deleteWaterReadingRemote(date);
        }
        // 同时删除抄表记录(如果存在)
        if (CURRENT_READINGS.some(r => r.date === date)) {
          await deleteReadingRemote(date);
        }
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

// 进入行内编辑模式(抄表 + 水电表底)
async function enterEditMode(date) {
  const allData = await fetchReadings();
  const row = allData.find(r => r.date === date);
  if (!row) return;

  // 加载关联的水电表底数据
  const waterAll = await fetchWaterReadings();
  const waterRow = waterAll.find(w => w.date === date) || {};

  // 记录编辑前是否已有水电记录（用于区分"删除"和"不创建"）
  const hasExistingWater = waterRow.main_meter != null || waterRow.sub_meter != null || waterRow.water != null;

  const tr = document.querySelector(`#history-table tbody tr[data-date="${date}"]`);
  if (!tr) return;

  tr.classList.add('edit-row');
  tr.innerHTML = `
    <td><input type="date" class="cell-input" id="edit-date" value="${row.date}" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-hall" value="${row.hall ?? ''}" placeholder="大厅" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-fire" value="${row.fire ?? ''}" placeholder="消防" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-private_room" value="${row.private_room ?? ''}" placeholder="包厢" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-ac" value="${row.ac ?? ''}" placeholder="空调" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-main_meter" value="${waterRow.main_meter ?? ''}" placeholder="总表" title="总表" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-sub_meter" value="${waterRow.sub_meter ?? ''}" placeholder="分表" title="分表" /></td>
    <td><input type="number" step="0.01" class="cell-input" id="edit-water" value="${waterRow.water ?? ''}" placeholder="水表" title="水表" /></td>
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

    // 水电表底字段
    const mainMeter = numE('#edit-main_meter');
    const subMeter = numE('#edit-sub_meter');
    const waterVal = numE('#edit-water');

    // 水电字段校验
    const waterInputEmpty = [mainMeter, subMeter, waterVal].every(v => v === null);
    const waterInputInvalid = [mainMeter, subMeter, waterVal].some(v => v !== null && isNaN(v));
    if (waterInputInvalid) {
      showAlert('读数必须是数字', 'error'); return;
    }

    if (!newDate) { showAlert('日期不能为空', 'error'); return; }

    // 抄表校验：四表必须至少填一个（水电字段不参与此校验，因为它们独立）
    const editVals = [newHall, newFire, newPrivate, newAc];
    if (editVals.every(v => v === null)) {
      showAlert('至少填写一块电表的读数', 'error'); return;
    }

    // 如果改了日期,检查新日期是否已存在抄表记录
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
      // 1. 更新抄表记录（仅四表，完全独立于水电表底）
      const fourMeterData = {};
      for (const k of ['hall', 'fire', 'private_room', 'ac']) {
        const v = { hall: newHall, fire: newFire, private_room: newPrivate, ac: newAc }[k];
        fourMeterData[k] = v === null ? undefined : v;
      }
      fourMeterData.date = newDate;
      fourMeterData.note = newNote;
      await updateReadingRemote(date, fourMeterData);

      // 2. 独立更新水电表底（与抄表记录互不干扰）
      if (hasExistingWater) {
        // 原来有水电记录
        if (waterInputEmpty) {
          // 用户清空了所有水电字段 → 删除该水电记录
          await deleteWaterReadingRemote(date);
        } else {
          // 用户修改了水电字段 → 覆盖更新
          const waterAll = await fetchWaterReadings();
          const existingWater = waterAll.find(w => w.date === date);
          if (existingWater && existingWater.date !== newDate) {
            // 日期变了，先删旧再新建
            await deleteWaterReadingRemote(existingWater.date);
          }
          const waterData = {
            date: newDate,
            main_meter: mainMeter,
            sub_meter: subMeter,
            water: waterVal,
            note: newNote,
          };
          // POST 会自动处理覆盖
          await saveWaterReadingRemote(waterData);
        }
      } else {
        // 原来没有水电记录
        if (!waterInputEmpty) {
          // 用户新增填入了水电字段 → 创建新记录
          const waterData = {
            date: newDate,
            main_meter: mainMeter,
            sub_meter: subMeter,
            water: waterVal,
            note: newNote,
          };
          await saveWaterReadingRemote(waterData);
        }
        // 用户也没填 → 什么都不做（正确行为）
      }

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

// ===== 提交按钮（侧栏录入页 form submit） =====
document.getElementById('entry-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  await submitReadingAdd('sidebar');
});
document.getElementById('charge-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  await submitChargeAdd('sidebar');
});
document.getElementById('utility-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  await submitUtilityAdd('sidebar');
});

// ===== 弹窗 confirm 按钮 — 根据当前 tab 路由 =====
document.getElementById('reading-add-confirm')?.addEventListener('click', () => {
  if (currentReadingTab === 'utility') {
    submitUtilityAdd('modal');
  } else {
    submitReadingAdd('modal');
  }
});
document.getElementById('charge-add-confirm')?.addEventListener('click', () => submitChargeAdd('modal'));

// ===== 弹窗 open 按钮（在记录页面 header） =====
document.getElementById('btn-open-reading-add')?.addEventListener('click', openReadingAddModal);
document.getElementById('btn-open-charge-add')?.addEventListener('click', openChargeAddModal);

// ===== Tab 切换(抄表/水电 合并弹窗内) =====
document.querySelectorAll('#reading-add-tabs .tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchReadingTab(btn.dataset.tab));
});

// ===== 弹窗 close =====
document.getElementById('reading-add-close')?.addEventListener('click', closeReadingAddModal);
document.getElementById('charge-add-close')?.addEventListener('click', closeChargeAddModal);
document.getElementById('reading-add-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('reading-add-modal-backdrop')) closeReadingAddModal();
});
document.getElementById('charge-add-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('charge-add-modal-backdrop')) closeChargeAddModal();
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
    // 当前如果月度报告页可见,触发当月占比渲染
    if (document.getElementById('section-report-monthly')?.style.display !== 'none' && reportSel.value) {
      renderMonthlyPie(reportSel.value);
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
    const uMonths = [...new Set((CURRENT_WATER_READINGS || [])
      .map(r => r.date.slice(0, 7)))].sort();
    const uopts = uMonths.length === 0
      ? '<option value="">(暂无数据)</option>'
      : uMonths.map(m => `<option value="${m}">${m}</option>`).join('');
    const prev = utilSel.value;
    utilSel.innerHTML = uopts;
    // 默认选择最新有数据的月份
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
      label: LABELS(key),
      multiplier: MULTIPLIER(key),
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

// 用电占比:已合并到每日趋势/月度报告页面,这里不再需要独立的月份下拉事件

// 物品管理:共用提交函数（侧栏录入页 + 物品记录页弹窗 都用）
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
  // 月度报告页可见时,触发当月占比饼图
  if (document.getElementById('section-report-monthly')?.style.display !== 'none') {
    renderMonthlyPie(month);
  }
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
        { label: '1#' + LABELS('hall'), data: data.months.map(m => m.by_meter.hall), backgroundColor: COLORS('hall') },
        { label: '2#' + LABELS('fire'), data: data.months.map(m => m.by_meter.fire), backgroundColor: COLORS('fire') },
        { label: '3#' + LABELS('private_room'), data: data.months.map(m => m.by_meter.private_room), backgroundColor: COLORS('private_room') },
        { label: '4#' + LABELS('ac'), data: data.months.map(m => m.by_meter.ac), backgroundColor: COLORS('ac') },
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

// 侧栏切换
const SIDEBAR_VISIBLE_SECTIONS = new Set([
  'reading', 'charge', 'utility',
  'reading-record', 'charge-record', 'charge-alert',
  'item-record', 'purchase-record',
  'item-add', 'purchase-add',
  'report-monthly', 'report-trend', 'report-pie', 'report-utilities', 'report-yearly',
  'overview'
]);

function switchSection(sectionId) {
  // 隐藏所有 section
  document.querySelectorAll('.content-section').forEach(s => s.style.display = 'none');
  // 显示目标 section（.content-section 默认 display:none，需显式 flex）
  const target = document.getElementById('section-' + sectionId);
  if (target) target.style.display = 'flex';

  // 自动展开所属分组:找到点击项所在的 group,如果不是 collapsed 则展开
  const activeBtn = document.querySelector(`.sidebar-item[data-section="${sectionId}"]`);
  if (activeBtn) {
    const group = activeBtn.closest('.sidebar-group');
    if (group && group.classList.contains('collapsed')) {
      group.classList.remove('collapsed');
    }
  }

  // 更新侧栏高亮
  document.querySelectorAll('.sidebar-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.section === sectionId);
  });

  // 状态条可见性
  const bar = document.getElementById('status-bar');
  if (SIDEBAR_VISIBLE_SECTIONS.has(sectionId)) {
    bar.style.display = '';
  } else {
    bar.style.display = 'none';
  }

  // 移动端:自动关闭侧栏
  const sidebar = document.getElementById('sidebar');
  if (window.innerWidth <= 900) {
    sidebar.classList.remove('mobile-open');
    document.getElementById('sidebar-overlay')?.classList.remove('show');
  }

  // 隐藏容器里初始化的 Chart 尺寸为 0,切回报表时重新计算
  if (sectionId === 'report-trend' && trendChart) {
    setTimeout(() => trendChart.resize(), 60);
  }
  if (sectionId === 'report-pie' && pieChart) {
    setTimeout(() => pieChart.resize(), 60);
  }
  if (sectionId === 'report-yearly' && _yearlyChart) {
    setTimeout(() => _yearlyChart.resize(), 60);
  }
}

// 侧栏分组折叠
function toggleGroup(el) {
  const group = el.parentElement;
  if (group) group.classList.toggle('collapsed');
}

// 系统设置页面切换（独立section）
function switchSettingsPage(page) {
  // 隐藏所有 section
  document.querySelectorAll('.content-section').forEach(s => s.style.display = 'none');
  // 显示对应的独立 section
  const target = document.getElementById('section-settings-' + page);
  if (target) target.style.display = 'flex';

  // 更新侧栏高亮:找到 settings-xxx 的按钮
  document.querySelectorAll('.sidebar-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.section === 'settings-' + page);
  });

  // 自动展开设置分组
  const settingsBtn = document.querySelector('.sidebar-item[data-section="settings-' + page + '"]');
  if (settingsBtn) {
    const group = settingsBtn.closest('.sidebar-group');
    if (group && group.classList.contains('collapsed')) {
      group.classList.remove('collapsed');
    }
  }

  // 状态条:设置页面不显示
  document.getElementById('status-bar').style.display = 'none';

  // 加载对应页面数据
  if (page === 'users') loadAdminUsers();
  if (page === 'meter') loadMeterSettings();
  if (page === 'data') loadBackupStatus();
  if (page === 'roles') loadRolesInfo();
}

// 侧栏点击事件
document.querySelectorAll('.sidebar-item').forEach(btn => {
  btn.addEventListener('click', () => {
    // settings 子菜单使用 switchSettingsPage（已有 onclick），这里跳过
    if (btn.dataset.section.startsWith('settings-')) return;
    switchSection(btn.dataset.section);
  });
});

// 侧栏折叠(桌面端)
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (window.innerWidth <= 900) {
    // 移动端:切换抽屉
    sidebar.classList.toggle('mobile-open');
    overlay?.classList.toggle('show');
  } else {
    // 桌面端:折叠/展开
    sidebar.classList.toggle('collapsed');
    const content = document.querySelector('.content');
    if (content) content.style.maxWidth = sidebar.classList.contains('collapsed') ? '100%' : '';
  }
}

// 移动端遮罩点击关闭侧栏
document.getElementById('sidebar-overlay')?.addEventListener('click', () => {
  document.getElementById('sidebar').classList.remove('mobile-open');
  document.getElementById('sidebar-overlay').classList.remove('show');
});

// 初始化:默认显示抄表记录
document.addEventListener('DOMContentLoaded', () => {
  applyTheme();
  loadMeterConfig().then(() => {
    loadMonthlyReport();
  });
  switchSection('reading-record');
});

// Tab 切换
function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.body.classList.remove('show-meter', 'show-item', 'show-history');
  document.body.classList.add('show-' + tab);
  if (tab === 'history' && _yearlyChart) {
    setTimeout(() => _yearlyChart.resize(), 60);
  }
}

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

// 设置值班时间字段为当前时间
function nowDateTimeStr() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${y}-${m}-${day} ${h}:${mi}:${s}`;
}
// datetime-local 格式: YYYY-MM-DDTHH:MM(浏览器会按本地时区解释)
function nowDateTimeLocalStr() {
  const d = new Date();
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${mo}-${day}T${h}:${mi}`;
}
const dutyTimeEl = document.getElementById('duty-time');
if (dutyTimeEl) {
  dutyTimeEl.value = nowDateTimeLocalStr();
  // 每分钟自动更新默认值(用户没改过时跟随)
  setInterval(() => {
    if (document.activeElement !== dutyTimeEl) {
      dutyTimeEl.value = nowDateTimeLocalStr();
    }
  }, 60_000);
}

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

// 把关键函数暴露到 window,让 admin.js(strict mode 单独作用域)能调用恢复后刷新整个页面
window.renderAll = renderAll;
window.refreshAll = refreshAll;  // 兼容旧的调用
