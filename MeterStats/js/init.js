
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

// 启动时先检查认证状态，再拉后端数据
(async () => {
  // 先检查认证：无 token 则显示登录页，阻止后续渲染
  const ADMIN_TOKEN = localStorage.getItem('meter_admin_token');
  if (ADMIN_TOKEN) {
    // 有旧 token，验证是否仍有效（新容器会话已失效）
    try {
      const r = await fetch('/api/auth/me?token=' + encodeURIComponent(ADMIN_TOKEN));
      const res = await r.json();
      if (!res.user) {
        // 旧 token 无效，清除并显示登录页
        localStorage.removeItem('meter_admin_token');
        const loginPage = document.getElementById('login-page');
        if (loginPage) loginPage.style.display = 'flex';
        return;  // 不渲染数据
      }
    } catch (e) {
      // 网络错误，清除 token 并显示登录页
      localStorage.removeItem('meter_admin_token');
      const loginPage = document.getElementById('login-page');
      if (loginPage) loginPage.style.display = 'flex';
      return;  // 不渲染数据
    }
  } else {
    // 没有 token，显示登录页
    const loginPage = document.getElementById('login-page');
    if (loginPage) loginPage.style.display = 'flex';
    return;  // 不渲染数据
  }
  // 认证通过，继续渲染数据
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
window.renderAll = renderAll;
window.refreshAll = refreshAll;  // 兼容旧的调用