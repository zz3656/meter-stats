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
  // Chart.js 是 defer 加载的:CDN 没回来时这里没有任何图表可调,直接跳过
  if (typeof Chart === 'undefined') return;
  const isDark = getEffectiveTheme() === 'dark';
  Chart.defaults.color = isDark ? '#6b7280' : '#7a818c';
  Chart.defaults.borderColor = isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)';
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  // 当前可见的 section 触发对应的占比
  triggerVisiblePie();
  // ⚠️ 实例叫 window._yearlyBarChart(reports.js 里创建),不是 _yearlyChart ——
  //    本文件原来读的是一个**从不赋值**的 `var _yearlyChart = null`,
  //    于是「切换深色/大字模式后年度柱图重排」这段保修代码从来没生效过。
  if (window._yearlyBarChart) {
    setTimeout(() => window._yearlyBarChart.resize(), 60);
  }
}

/**
 * Chart.js 现在用 `defer` 加载(不再阻塞首屏解析)。
 *
 * 副作用:本文件的绘图函数在本文件执行时可能还看不到 `Chart`(defer 脚本要等
 * HTML 解析完才跑),那些函数会主动跳过而不是抛错 —— 但"跳过"不等于稍后补画,
 * 所以这里守一个有限次轮询:Chart 一到位就补画一次首屏图表。
 *
 * 为什么用轮询而不是 DOMContentLoaded:defer 脚本在 DOMContentLoaded **之前**执行,
 * 但顺序由下载完成时间决定,监听事件可能与 Chart 到位错开。轮询 100ms × 100 次
 * (=10 秒)足够覆盖慢网络,超时就当 CDN 挂了,保持无图(和从前一样)。
 */
(function waitForChartJs() {
  // 定时器在最小测试沙箱里可能不存在 —— 缺了就不轮询,别让整个文件加载失败
  if (typeof setInterval !== 'function' || typeof clearInterval !== 'function') return;
  var tries = 0;
  function done() {
    if (typeof renderCharts === 'function') {
      try { renderCharts(); } catch (e) { /* 图表非关键,失败不影响页面 */ }
    }
  }
  if (typeof Chart !== 'undefined') { done(); return; }
  var timer = setInterval(function () {
    if (typeof Chart !== 'undefined') { clearInterval(timer); done(); return; }
    if (++tries >= 100) clearInterval(timer);
  }, 100);
})();

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
function cacheReadings(data) {
  localStorage.setItem(STORAGE_KEY_READINGS, JSON.stringify(data));
}
// 异步加载数据 (通过 Api.* 封装,带 LocalStorage 缓存回退)
async function api(method, path, body) {
  const opts = { method, cache: 'no-store', headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const token = (typeof currentAuthToken === 'function')
    ? currentAuthToken()
    : ((typeof ADMIN_TOKEN !== 'undefined' && ADMIN_TOKEN) ? ADMIN_TOKEN : (localStorage.getItem('token') || ''));
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  if (token && path.indexOf('token=') === -1) {
    const separator = path.includes('?') ? '&' : '?';
    path = path + separator + 'token=' + encodeURIComponent(token);
  }
  // 拼当前门店 —— 规则在 StoreContext.isStoreFreePath()
  // (js/core/storeContext.js,门店参数规则的唯一真相源)。
  // 这里不复用 api.js 的私有函数(它在 IIFE 里,外部拿不到),
  // 但**规则**只有一份 —— 改一处就够(测试会盯住)。
  if (!isStoreFreePath(path) && !hasStoreParam(path)) {
    let store = '';
    try {
      if (typeof StoreContext !== 'undefined' && StoreContext) store = StoreContext.getStoreId() || '';
    } catch (e) { store = ''; }
    if (isValidStoreId(store)) {   // 口径见 js/helpers/utils.js::isValidStoreId
      const separator = path.includes('?') ? '&' : '?';
      path = path + separator + 'store=' + encodeURIComponent(store);
    }
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    const txt = await res.text();
    // 门店失效(被删 / 权限被收回)→ 交给门店上下文恢复,与 api.js::_request 同一套口径。
    // 不处理的话:state.storeId 不清、缓存不清、不重新引导 → UI 停在失效门店上。
    if (typeof StoreContext !== 'undefined' && StoreContext
        && typeof StoreContext.handleStoreError === 'function') {
      try {
        let msg = txt;
        try {
          const parsed = JSON.parse(txt);
          if (parsed && parsed.error) msg = parsed.error;
        } catch (e) { /* 不是 JSON —— 原样传 */ }
        StoreContext.handleStoreError(res.status, msg);
      } catch (e) { /* 恢复失败不掩盖原始错误 */ }
    }
    throw new Error(`HTTP ${res.status}: ${txt}`);
  }
  return res.json();
}

/**
 * 这个路径带不带门店参数 —— 转发给 StoreContext.isStoreFreePath()
 * (js/core/storeContext.js,规则的唯一真相源)。
 *
 * 兜底的 4 个守卫与真规则**逐字一致**(测试会盯住):
 * 兜底存在的意义是「StoreContext 还没加载时也能工作」
 * (Task 4 把 <script> 加进 index.html 之前)。Task 4 之后兜底是死代码,
 * 但在那之前它得是对的 —— 三份实现必须一致,否则改一份漏一份,
 * 就会出现「api.js 认为该带 store、accessibility.js 认为不该带」的分叉。
 */
function isStoreFreePath(path) {
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext
        && typeof StoreContext.isStoreFreePath === 'function') {
      return !!StoreContext.isStoreFreePath(path);
    }
  } catch (e) { /* StoreContext 没加载 */ }
  const p = String(path || '').split('?')[0];
  if (p === '/api/health' || p === '/api/version') return true;
  if (p.indexOf('/api/auth/') === 0) return true;
  if (p === '/api/stores' || p.indexOf('/api/stores/') === 0) return true;
  return false;
}

/** query 里是不是已经有 store 参数了(别用 includes('store=') —— 会把 ?x=store=1 误判)。 */
function hasStoreParam(path) {
  const q = String(path || '').split('?')[1];
  if (!q) return false;
  for (const kv of q.split('&')) {
    let name = kv.split('=')[0];
    try { name = decodeURIComponent(name); } catch (e) { /* 原样比 */ }
    if (name === 'store') return true;
  }
  return false;
}


// 这些函数通过 Api.* 调用后端,失败时回退到 LocalStorage 缓存
// (保持全局函数名以兼容其他模块)
async function fetchReadings() {
  try { const data = await Api.readings.list(); cacheReadings(data); return data; }
  catch (e) { console.warn('后端不可用,使用本地缓存:', e); return loadReadingsCache(); }
}
// 水电表底（重构时丢失，admin.js 的水电页依赖）
async function fetchWaterReadings() {
  try {
    const data = await Api.utilities.list();
    CURRENT_WATER_READINGS = Array.isArray(data) ? data : (data.data || []);
    return CURRENT_WATER_READINGS;
  } catch (e) {
    console.warn('fetchWaterReadings 失败:', e);
    CURRENT_WATER_READINGS = [];
    return [];
  }
}

// ===== 最近一次拉取的全量数据（模块间共享）=====
// ⚠️ CURRENT_ITEMS/PURCHASES/DUTY 原本就有，READINGS/CHARGES/WATER_READINGS 在
// 模块化重构时丢失 → init.js / reports.js / admin.js 读取时报 ReferenceError。
window.CURRENT_READINGS = [];
window.CURRENT_CHARGES = [];
window.CURRENT_WATER_READINGS = [];
window.CURRENT_ITEMS = [];
window.CURRENT_PURCHASES = [];
window.CURRENT_DUTY = [];

// 离线缓存 key（与历史版本保持一致，避免已缓存数据读不到）
const STORAGE_KEY_READINGS = 'meter_readings_v1';
const STORAGE_KEY_CHARGES = 'meter_charges_v1';

// 年度汇总图表实例（renderCharts 里 resize 用，由报表模块赋值）

async function fetchDuty() {
  try { const data = await Api.duty.list(); CURRENT_DUTY = Array.isArray(data) ? data : (data.data || []); return CURRENT_DUTY; }
  catch (e) { console.warn('后端不可用,duty 用空数组:', e); CURRENT_DUTY = []; return []; }
}

