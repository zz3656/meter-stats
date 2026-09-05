
// ===== 弹窗 close =====
document.getElementById('reading-add-close')?.addEventListener('click', closeReadingAddModal);
document.getElementById('charge-add-close')?.addEventListener('click', closeChargeAddModal);
document.getElementById('reading-add-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('reading-add-modal-backdrop')) closeReadingAddModal();
});
document.getElementById('charge-add-modal-backdrop')?.addEventListener('click', e => {
  if (e.target === document.getElementById('charge-add-modal-backdrop')) closeChargeAddModal();
});

