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
        dirEl.textContent = '📁 ' + res.image_dir;
        // 缓存到 hidden input（供统一保存使用）
        const rawInput = document.getElementById('image-dir-raw');
        if (rawInput) rawInput.value = res.image_dir;
        if (statsEl) statsEl.textContent = '📊 图片数量: ' + res.image_count + ' 张, 总大小: ' + formatBytes(res.total_size);
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

// 选择图片目录（写入 hidden input，等待统一保存）
function pickImageDirInput() {
  if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pickBackupDir) {
    window.__backupDirChosen = function(dir) {
      if (dir) {
        document.getElementById('image-dir-raw').value = dir;
      }
    };
    window.webkit.messageHandlers.pickBackupDir.postMessage('pick');
  } else {
    const input = document.createElement('input');
    input.type = 'file';
    input.webkitdirectory = true;
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', () => {
      if (input.files.length > 0) {
        const firstPath = input.files[0].webkitRelativePath;
        const folderName = firstPath.split('/')[0];
        document.getElementById('image-dir-raw').value = folderName;
      }
      input.parentNode?.removeChild(input);
    });
    input.click();
  }
}
