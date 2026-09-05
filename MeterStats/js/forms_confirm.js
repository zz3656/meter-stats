
// ===== 弹窗 confirm 按钮 — 根据当前 tab 路由 =====
document.getElementById('reading-add-confirm')?.addEventListener('click', () => {
  if (currentReadingTab === 'utility') {
    submitUtilityAdd('modal');
  } else {
    submitReadingAdd('modal');
  }
});
document.getElementById('charge-add-confirm')?.addEventListener('click', () => submitChargeAdd('modal'));