/**
 * 门店总览(总部总表) —— 横向对比各门店当月的用电与费用。
 *
 * P3:总部账号在一个页面上看清所有门店;分店员工看到的是自己那家
 * (后端按调用方的门店范围过滤,前端不需要再筛)。
 *
 * ⚠️ 这张表**不能**按 METER_KEYS 出列 —— 每家店的表集合不一样
 * (`m1`/`m2` vs `hall`/`fire`/…)。横向能比的是「总用电 / 电费 / 抄表天数 /
 * 水电」这类**跨店同构**指标;要看某家店的分表明细,去「用电报表」页切到那家店。
 */
(function () {
  'use strict';

  var _chart = null;

  function _esc(v) {
    if (typeof escapeHtml === 'function') return escapeHtml(v);
    return String(v == null ? '' : v);
  }

  function _fmt(v, digits) {
    if (v == null) return '—';
    var n = Number(v);
    if (isNaN(n)) return '—';
    return n.toLocaleString('zh-CN', { maximumFractionDigits: digits == null ? 1 : digits });
  }

  function _currentMonth() {
    var el = document.getElementById('overview-month');
    if (el && el.value) return el.value;
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  }

  /**
   * 入口可见性:总部账号(all_stores)或可见门店 ≥ 2。
   * 与门店切换器同一条件 —— 单店用户看「总览」只有一行,没有信息量。
   */
  function applyOverviewVisibility() {
    var btn = document.getElementById('nav-overview');
    if (!btn) return;
    var show = false;
    try {
      if (typeof StoreContext !== 'undefined' && StoreContext) {
        show = !!StoreContext.getAllStores()
          || (StoreContext.getStores() || []).length >= 2;
      }
    } catch (e) {
      show = false;
    }
    btn.style.display = show ? '' : 'none';
  }

  function _rowHtml(r) {
    var name = _esc(r.name || r.id || '');
    if (r.error) {
      // 单店失败不影响整体:这一行显示原因,其余行照常
      return '<tr><td>' + name + '</td>' +
        '<td colspan="5" style="color:var(--danger);">汇总失败:' + _esc(r.error) + '</td></tr>';
    }
    var u = r.utilities || {};
    return '<tr data-store-id="' + _esc(r.id) + '">' +
      '<td>' + name + '</td>' +
      '<td>' + _fmt(r.total_kwh, 1) + '</td>' +
      '<td>' + _fmt(r.total_cost, 2) + '</td>' +
      '<td>' + _fmt(r.reading_days, 0) + '</td>' +
      '<td>' + _fmt(u.main_kwh, 1) + '</td>' +
      '<td>' + _fmt(u.water_usage, 1) + '</td>' +
      '</tr>';
  }

  function renderStoresOverview(data) {
    var body = document.getElementById('overview-body');
    var wrap = document.getElementById('overview-table-wrap');
    var empty = document.getElementById('overview-empty');
    var chartWrap = document.getElementById('overview-chart-wrap');
    if (!body) return;

    var stores = (data && data.stores) || [];
    if (!stores.length) {
      body.innerHTML = '';
      if (wrap) wrap.style.display = 'none';
      if (chartWrap) chartWrap.style.display = 'none';
      if (empty) {
        empty.style.display = 'block';
        empty.textContent = ((data && data.month) || '该月') + ' 没有可汇总的门店';
      }
      return;
    }

    if (empty) empty.style.display = 'none';
    if (wrap) wrap.style.display = '';

    var html = stores.map(_rowHtml).join('');
    var total = (data && data.total) || {};
    html += '<tr class="yearly-total-row">' +
      '<td>合计(' + stores.length + ' 家店)</td>' +
      '<td>' + _fmt(total.total_kwh, 1) + '</td>' +
      '<td>' + _fmt(total.total_cost, 2) + '</td>' +
      '<td colspan="3"></td></tr>';
    body.innerHTML = html;

    _drawChart(stores, chartWrap);
  }

  function _drawChart(stores, chartWrap) {
    var cv = document.getElementById('overview-chart');
    if (!cv || typeof Chart === 'undefined') {
      if (chartWrap) chartWrap.style.display = 'none';
      return;
    }
    var ok = stores.filter(function (s) { return !s.error; });
    if (!ok.length) {
      if (chartWrap) chartWrap.style.display = 'none';
      return;
    }
    if (chartWrap) chartWrap.style.display = '';

    if (_chart && typeof _chart.destroy === 'function') _chart.destroy();
    _chart = new Chart(cv.getContext('2d'), {
      type: 'bar',
      data: {
        labels: ok.map(function (s) { return s.name || s.id; }),
        datasets: [{
          label: '本月用电(度)',
          data: ok.map(function (s) { return s.total_kwh || 0; }),
          backgroundColor: 'rgba(37, 99, 235, 0.65)',
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
  }

  async function loadStoresOverview() {
    var month = _currentMonth();
    var el = document.getElementById('overview-month');
    if (el && !el.value) el.value = month;
    try {
      var data = await Api.stores.overview(month);
      if (!data || data.ok === false) {
        showAlert('加载门店总览失败: ' + ((data && data.error) || '未知错误'), 'error');
        return;
      }
      renderStoresOverview(data);
    } catch (e) {
      showAlert('加载门店总览失败: ' + (e && e.message ? e.message : ''), 'error');
    }
  }

  // 切门店/登录状态变化时更新入口可见性
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext && StoreContext.onChange) {
      StoreContext.onChange(function () { applyOverviewVisibility(); });
    }
  } catch (e) { /* ignore */ }

  window.applyOverviewVisibility = applyOverviewVisibility;
  window.loadStoresOverview = loadStoresOverview;
  window.renderStoresOverview = renderStoresOverview;

  // 启动时定一次(单店用户看不到入口)
  try { applyOverviewVisibility(); } catch (e) { /* ignore */ }
})();
