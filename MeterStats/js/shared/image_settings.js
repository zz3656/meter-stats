// ===== 图片目录管理（统一保存模式）=====
const IMAGE_API = '/api/admin/images';

// 加载图片目录配置（仅用于显示，不再单独保存）
function loadImageDirConfig() {
  const dirEl = document.getElementById('image-dir-display');
  const statsEl = document.getElementById('image-dir-stats');

  if (!dirEl) return;

  const doLoad = () => {
    fetch(IMAGE_API + getAuthParam())
      .then(r => r.json()).then(res => {
        if (!res.ok) return;
        dirEl.textContent = res.image_dir ? ('📁 ' + res.image_dir) : '📁 默认: ' + (res.data_dir || '') + '/images';
        // 当前目录填进输入框，用户可直接改（不再依赖不存在的 hidden input）
        const dirInput = document.getElementById('image-dir-input');
        if (dirInput) dirInput.value = res.image_dir || '';
        if (statsEl) statsEl.textContent = '📊 图片数量: ' + res.image_count + ' 张, 总大小: ' + formatBytes(res.total_size);

        // Docker 下由 METER_IMAGE_DIR 环境变量控制，不允许改（后端会 400）
        const locked = res.customizable === false;
        const pickBtn = document.getElementById('pick-image-dir-btn');
        const saveBtn = document.getElementById('save-image-dir-btn');
        const wrapEl = document.getElementById('image-dir-input-wrap');
        if (pickBtn) pickBtn.style.display = locked ? 'none' : '';
        if (saveBtn) saveBtn.style.display = locked ? 'none' : '';
        if (wrapEl && locked) wrapEl.style.display = 'none';
        if (locked && dirEl) dirEl.textContent = '🔒 ' + res.image_dir + '（Docker 下由 METER_IMAGE_DIR 控制）';
      }).catch(() => {
        dirEl.textContent = '⚠️ 后端未更新，请重启服务后生效';
        if (statsEl) statsEl.textContent = '';
      });
  };

  if (dirEl.textContent === '') {
    dirEl.textContent = '加载中...';
    doLoad();
  } else {
    doLoad();
  }
}

// 选择图片目录（App 内弹原生目录选择器；浏览器回退手动输入）
function pickImageDirInput() {
  const hasBridge = window.webkit && window.webkit.messageHandlers &&
    window.webkit.messageHandlers.pickBackupDir;

  if (!hasBridge) {
    // 浏览器里没有原生目录选择器
    const inputWrap = document.getElementById('image-dir-input-wrap');
    const input = document.getElementById('image-dir-input');
    if (inputWrap) inputWrap.style.display = 'block';
    if (input) input.focus();
    showToast('浏览器里请直接填写完整路径', 'info');
    return;
  }

  // ⚠️ 用独立回调：备份卡片用 __backupDirChosen，两边共用一个会被互相覆盖
  window.__imageDirChosen = function (dir) {
    window.__imageDirChosen = null;
    if (!dir) return;                       // 用户取消
    const input = document.getElementById('image-dir-input');
    const inputWrap = document.getElementById('image-dir-input-wrap');
    if (input) input.value = dir;
    if (inputWrap) inputWrap.style.display = 'block';
    showToast('已选择目录，点「保存」生效', 'info');
  };
  window.webkit.messageHandlers.pickBackupDir.postMessage({ kind: 'image' });
}

// 保存图片目录（重构时丢失，index.html 内联 onclick 依赖）
async function saveImageDirInput() {
  const input = document.getElementById('image-dir-input');
  const inputWrap = document.getElementById('image-dir-input-wrap');
  if (!input) return;
  const path = input.value.trim();
  if (!path) {
    showToast('请输入目录路径（必须是数据目录内的子目录）', 'warn');
    return;
  }
  try {
    const res = await fetch(IMAGE_API + getAuthParam(), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_dir: path }),
    });
    const json = await res.json();
    if (json.ok) {
      showToast('✅ 已保存: ' + json.image_dir, 'success');
      loadImageDirConfig();
    } else {
      showToast('保存失败: ' + (json.error || '未知错误'), 'error');
    }
  } catch (e) {
    showToast('保存失败: ' + e.message, 'error');
  }
}
