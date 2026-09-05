function showModal(opts) {
  return new Promise(resolve => {
    const backdrop = document.getElementById('modal-backdrop');
    const icon = document.getElementById('modal-icon');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const cancelBtn = document.getElementById('modal-cancel');
    const confirmBtn = document.getElementById('modal-confirm');

    icon.textContent = opts.icon || '!';
    icon.className = 'modal-icon' + (opts.iconKind === 'warn' ? ' warn'
      : opts.iconKind === 'info' ? ' info' : '');
    title.textContent = opts.title || '确认';
    body.innerHTML = opts.body || '';
    cancelBtn.textContent = opts.cancelText || '取消';
    confirmBtn.textContent = opts.confirmText || '确认';
    confirmBtn.className = 'btn ' + (opts.confirmKind === 'primary' ? 'btn-primary' : 'btn-danger');

    backdrop.classList.add('show');

    const close = (result) => {
      backdrop.classList.remove('show');
      cancelBtn.removeEventListener('click', onCancel);
      confirmBtn.removeEventListener('click', onConfirm);
      backdrop.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    };
    const onCancel = () => close(false);
    const onConfirm = () => close(true);
    const onBackdrop = (e) => { if (e.target === backdrop) close(false); };
    const onKey = (e) => { if (e.key === 'Escape') close(false); };

    cancelBtn.addEventListener('click', onCancel);
    confirmBtn.addEventListener('click', onConfirm);
    backdrop.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);

    // 焦点放确认按钮上,Enter 直接确认
    setTimeout(() => confirmBtn.focus(), 50);
  });
}

// 全局缓存当前 readings / charges(从后端拉一次后,所有渲染都从这里读)