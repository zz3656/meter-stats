
// ===== Tab 切换(抄表/水电 合并弹窗内) =====
document.querySelectorAll('#reading-add-tabs .tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchReadingTab(btn.dataset.tab));
});