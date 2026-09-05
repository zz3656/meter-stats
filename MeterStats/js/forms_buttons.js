
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