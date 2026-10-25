
// ===== 初始化 =====
// 日期/时间格式化为 YYYY-MM-DD / YYYY-MM-DD HH:MM:SS / YYYY-MM-DDTHH:MM,
// 复用 utils_helpers.js 的 formatDate / formatDateTime / formatDateTimeLocal。
function todayStr() {
  return formatDate(new Date());
}
const _dateEl = document.getElementById('date'); if (_dateEl) _dateEl.value = todayStr();
const _chargeDateEl = document.getElementById('charge-date'); if (_chargeDateEl) _chargeDateEl.value = todayStr();
const _utilityDateEl = document.getElementById('utility-date'); if (_utilityDateEl) _utilityDateEl.value = todayStr();

// 设置值班时间字段为当前时间
function nowDateTimeStr() {
  return formatDateTime(new Date());
}
// datetime-local 格式: YYYY-MM-DDTHH:MM(浏览器会按本地时区解释)
function nowDateTimeLocalStr() {
  return formatDateTimeLocal(new Date());
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

// 加载并显示版本号（侧栏底部）
function loadAppVersion() {
  var el = document.getElementById('sidebar-version');
  if (!el) return;
  fetch('/api/version')
    .then(function(r) { return r.json(); })
    .then(function(d) { el.textContent = 'v' + (d && d.version ? d.version : '—'); })
    .catch(function() { el.textContent = ''; });
}

// 启动时先加载数据，再检查认证状态
(async () => {
  // 无论是否有 token，都先加载数据（快照接口不需要认证）
  await renderAll();
  // 报表分析: 加载月份和年份选项，供用户切换时渲染
  const reportMonth = document.getElementById('report-month');
  if (reportMonth) {
    const months = [...new Set((CURRENT_READINGS || []).map(r => r.date.slice(0, 7)))].sort().reverse();
    reportMonth.innerHTML = months.map(m => `<option value="${m}">${m}</option>`).join('');
    if (months.length > 0) { reportMonth.value = months[0]; }
  }
  const yearlyYear = document.getElementById('yearly-year');
  if (yearlyYear) {
    const years = [...new Set((CURRENT_READINGS || []).map(r => r.date.slice(0, 4)))].sort().reverse();
    yearlyYear.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
    if (years.length > 0) { yearlyYear.value = years[0]; }
  }
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
  // 更新待处理工作记录横幅
  checkDutyReminder();

  // 侧栏底部显示版本号（/api/version 是公开接口）
  loadAppVersion();

  // 加载电表配置（电价 / 倍率 / 水价）—— ELECTRICITY_PRICE 依赖它取后端值
  try { await loadMeterConfig(); } catch (e) { console.warn('loadMeterConfig 失败:', e); }

  // 绑定报表下拉/按钮事件（重构后丢失，导致切换月份无反应）
  bindReportEvents();

  // 预加载默认月份的报表（与旧版 DOMContentLoaded 行为一致）
  try { if (typeof loadMonthlyReport === 'function') await loadMonthlyReport(); } catch (e) { console.warn('默认月报加载失败:', e); }

  // ⚠️ 必须显示默认页面：所有 .content-section 默认 display:none，
  // 不调用 switchSection 的话登录后主内容区是全空白。
  if (typeof switchSection === 'function') switchSection('reading-record');
})();

// ===== 报表/记录页的下拉与按钮事件绑定 =====
// 重构后这些绑定丢失，导致"切换月份后不显示对应数据"（选择器能选，但没人监听）。
function bindReportEvents() {
  var bind = function(id, evt, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener(evt, fn);
  };

  // 月度报告（水电已整合进本页）
  bind('report-month', 'change', function() { loadMonthlyReport(); });
  bind('btn-copy-report', 'click', function() { copyMonthlyReportTSV(); });
  bind('btn-copy-utilities', 'click', function() { copyUtilitiesTSV(); });
  // 年度汇总
  bind('yearly-year', 'change', function() { loadYearlyReport(); });
  bind('yearly-apply', 'click', function() { loadYearlyReport(); });
  bind('btn-copy-yearly', 'click', function() { copyYearlyTSV(); });
  // 每月用电统计
  bind('stats-month', 'change', function() { renderStats(CURRENT_READINGS, CURRENT_CHARGES); });
  // 每日趋势：选中日期后渲染当天占比
  bind('day-copy-date', 'change', function() {
    var sel = document.getElementById('day-copy-date');
    if (sel && sel.value) renderDailyPie(sel.value);
  });
  // 单天汇报复制（按钮一直存在但从未绑定过 handler，导致点击无反应）
  bind('btn-copy-day', 'click', function() {
    if (typeof copyDayUsage === 'function') copyDayUsage();
  });
  // 记录页月份过滤（本地过滤）
  // 用电记录页三 Tab 共用 record-month；旧的 history/charge/water 下拉已合并删除，
  // 但 renderXxxTable 内部仍保留旧 id 回退，所以这里只绑 record-month 即可。
  bind('record-month', 'change', function() {
    if (typeof renderReadingTable === 'function') renderReadingTable(State.get('readings'));
    if (typeof renderChargeTable === 'function') renderChargeTable(State.get('charges'));
    if (typeof renderWaterTable === 'function') renderWaterTable();
  });
  // 三 Tab 切换
  document.querySelectorAll('.record-tab').forEach(function(btn) {
    btn.addEventListener('click', function() { switchRecordTab(btn.dataset.tab); });
  });
  // 按 Tab 显示的新增按钮（弹窗内不再有 tab，入口直接决定表单）
  bind('btn-add-reading', 'click', function() {
    if (typeof openReadingAddModal === 'function') openReadingAddModal('reading');
  });
  bind('btn-add-charge', 'click', function() {
    if (typeof openChargeAddModal === 'function') openChargeAddModal();
  });
  bind('btn-add-water', 'click', function() {
    if (typeof openReadingAddModal === 'function') openReadingAddModal('utility');
  });
  // 物品 / 申购 / 工作记录 的新增按钮（重构时丢了绑定，点了没反应）
  bind('btn-open-item-add', 'click', function() {
    if (typeof openItemAddModal === 'function') openItemAddModal();
  });
  bind('btn-open-purchase-add', 'click', function() {
    if (typeof openPurchaseAddModal === 'function') openPurchaseAddModal();
  });
  bind('btn-open-duty-add', 'click', function() {
    if (typeof openDutyAddModal === 'function') openDutyAddModal();
  });
}


// 检查并更新待处理工作记录横幅
function checkDutyReminder() {
  const el = document.getElementById('duty-reminder');
  if (!el) return;
  const unhandledDuty = (CURRENT_DUTY || []).filter(d => d.status === '未处理');
  if (unhandledDuty.length > 0) {
    document.getElementById('duty-reminder-text').textContent = `⚠️ 还有 ${unhandledDuty.length} 条工作记录待处理`;
    el.style.display = 'flex';
  } else {
    el.style.display = 'none';
  }
}

// 把关键函数暴露到 window,让 admin.js(strict mode 单独作用域)能调用恢复后刷新整个页面
// renderAll 和 refreshAndRender 已在 readings.js 中定义，直接从 window 获取即可
if (typeof window.renderAll !== 'function') {
    // readings.js 未定义 renderAll 时的兼容处理（理论上不会发生）
    window.renderAll = function() {
        console.warn('renderAll 未定义，尝试调用 refreshAndRenderTables');
        if (typeof refreshAndRenderTables === 'function') refreshAndRenderTables();
    };
}
window.refreshAll = window.renderAll;  // 兼容旧的调用
window.switchSection = switchSection;  // Tab 切换（HTML onclick 需要全局函数）
window.switchSettingsPage = switchSettingsPage;  // 设置页面切换（HTML onclick 需要全局函数）
window.toggleGroup = toggleGroup;  // 侧栏分组折叠（HTML onclick 需要全局函数）
window.toggleSidebar = toggleSidebar;  // 侧栏折叠（HTML onclick 需要全局函数）