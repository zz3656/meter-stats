
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
})();

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