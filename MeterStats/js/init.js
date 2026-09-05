
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