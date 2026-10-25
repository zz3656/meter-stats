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

    // 可选复选框：opts.checkbox = { label, defaultChecked, withImage }
    // 勾选时 close(true) 会 resolve 成 { ok: true, checked, images }，
    // 没传 checkbox 的调用方仍然拿到布尔值，不受影响。
    let cb = null;
    let imgNames = [];
    let imgPreview = null;
    if (opts.checkbox) {
      const wrap = document.createElement('label');
      wrap.className = 'modal-checkbox';
      cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.id = 'modal-checkbox';
      // 默认勾选与否由调用方决定（申购购买默认不勾）
      cb.checked = opts.checkbox.defaultChecked === true;
      wrap.appendChild(cb);
      const span = document.createElement('span');
      span.textContent = opts.checkbox.label || '';
      wrap.appendChild(span);
      body.appendChild(wrap);

      // 勾选后才出现的图片入口（比如"入库时拍张照"）
      if (opts.checkbox.withImage) {
        const imgBox = document.createElement('div');
        imgBox.id = 'modal-checkbox-image-box';
        imgBox.style.cssText = 'display:none;margin-top:10px;';
        imgBox.innerHTML =
          '<div id="modal-checkbox-image-preview" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;"></div>' +
          '<button type="button" class="btn btn-secondary btn-sm" id="modal-checkbox-image-btn">📷 传图片</button>' +
          '<input type="file" id="modal-checkbox-image-file" accept="image/*" style="display:none;" />';
        body.appendChild(imgBox);
        imgPreview = imgBox.querySelector('#modal-checkbox-image-preview');

        const fileInput = imgBox.querySelector('#modal-checkbox-image-file');
        imgBox.querySelector('#modal-checkbox-image-btn').addEventListener('click', () => {
          const scope = opts.checkbox.scope || 'purchase-buy';
          // App 内走原生桥（WKWebView 里 <input type="file"> 不可靠）
          if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.macOSPickImage) {
            window.__pendingFieldPick = {
              scope: scope,
              custom: (names) => {
                imgNames = imgNames.concat(names).slice(0, 3);
                imgPreview.innerHTML = imgNames.map((fn) =>
                  '<img src="' + getDutyImageUrl(fn) + '" style="width:44px;height:44px;object-fit:cover;border-radius:6px;border:1px solid var(--border);" />'
                ).join('');
              }
            };
            window.webkit.messageHandlers.macOSPickImage.postMessage({ max: 3 });
            return;
          }
          fileInput.click();
        });
        fileInput.addEventListener('change', () => {
          if (!fileInput.files || !fileInput.files.length) return;
          const files = Array.from(fileInput.files).slice(0, 3);
          fileInput.value = '';
          uploadImages(files, 3, opts.checkbox.scope || 'purchase-buy').then((names) => {
            imgNames = imgNames.concat(names).slice(0, 3);
            imgPreview.innerHTML = imgNames.map((fn) =>
              '<img src="' + getDutyImageUrl(fn) + '" style="width:44px;height:44px;object-fit:cover;border-radius:6px;border:1px solid var(--border);" />'
            ).join('');
          }).catch((e) => showAlert('图片上传失败: ' + (e && e.message ? e.message : e), 'error'));
        });

        const syncBox = () => { imgBox.style.display = cb.checked ? 'block' : 'none'; };
        cb.addEventListener('change', syncBox);
        syncBox();
      }
    }
    cancelBtn.textContent = opts.cancelText || '取消';
    confirmBtn.textContent = opts.confirmText || '确认';
    confirmBtn.className = 'btn ' + (opts.confirmKind === 'primary' ? 'btn-primary' : 'btn-danger');

    backdrop.classList.add('show');

    const close = (result) => {
      if (cb) result = (result === true) ? { ok: true, checked: cb.checked, images: imgNames } : result;
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