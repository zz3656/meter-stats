// ===== 大字醒目模式(辅助功能) =====
const ACCESSIBILITY_KEY = 'meter_accessibility_on';
function getAccessibilityState() {
  return localStorage.getItem(ACCESSIBILITY_KEY) === 'on';
}
function applyAccessibility() {
  const on = getAccessibilityState();
  document.documentElement.setAttribute('data-accessibility', on ? 'on' : '');
  const btn = document.getElementById('accessibility-btn');
  if (btn) {
    btn.classList.toggle('active', on);
    btn.textContent = on ? '✅ 大字' : '🔤 大字';
  }
}
// 立即执行，确保登录页可见时 data-accessibility 属性已经设置
// （登录页可能通过 JS 在 DOMContentLoaded 前显示）
if (document.readyState !== 'loading') {
  applyAccessibility();
}
// DOM 就绪后再次确保设置，并更新按钮状态
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', function initAccessibility() {
    applyAccessibility();
    document.removeEventListener('DOMContentLoaded', initAccessibility);
  });
}
function toggleAccessibility() {
  const current = getAccessibilityState();
  const next = !current;
  localStorage.setItem(ACCESSIBILITY_KEY, next ? 'on' : 'off');
  applyAccessibility();
  // 切换后重新渲染图表
  renderCharts();
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

window.CURRENT_ITEMS = [];
window.CURRENT_PURCHASES = [];
window.CURRENT_DUTY = [];

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