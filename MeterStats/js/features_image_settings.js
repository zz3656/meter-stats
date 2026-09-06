// ===== 工作记录图片目录管理 =====
const IMAGE_API = '/api/admin/images';

// 加载图片目录配置
function loadImageDirConfig() {
  fetch(IMAGE_API + getAuthParam())
    .then(r => r.json()).then(res => {
      if (!res.ok) return;
      // 显示当前目录
      const dirEl = document.getElementById('image-dir-display');
      if (dirEl) dirEl.textContent = '📁 ' + res.image_dir + ' (默认: ' + res.default_image_dir + ')';
      // 显示统计
      const statsEl = document.getElementById('image-dir-stats');
      if (statsEl) statsEl.textContent = '📊 图片数量: ' + res.image_count + ' 张, 总大小: ' + formatBytes(res.total_size);
    }).catch(() => {
      const dirEl = document.getElementById('image-dir-display');
      if (dirEl) dirEl.textContent = '加载失败';
    });
}

// 选择图片目录
function pickImageDir() {
  // 使用浏览器文件选择API: 选择文件夹
  if (window.showDirectoryPicker) {
    window.showDirectoryPicker({ mode: 'readWrite' })
      .then(async (dirHandle) => {
        // 获取完整路径不可靠, 这里用后端 API 设置
        // 需要让用户手动输入或选择
        const path = prompt('请输入图片目录的完整路径:', document.getElementById('image-dir-display')?.textContent || '');
        if (!path) return;
        await saveImageDir(path);
      })
      .catch(() => {});
  } else {
    // 回退: 手动输入路径
    const current = document.getElementById('image-dir-display')?.textContent || '';
    const match = current.match(/📁 (.+?) \(/);
    const currentPath = match ? match[1] : '';
    const path = prompt('请输入图片目录的完整路径:', currentPath);
    if (!path) return;
    saveImageDir(path);
  }
}

async function saveImageDir(path) {
  try {
    const res = await fetch(IMAGE_API + getAuthParam(), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_dir: path }),
    });
    const json = await res.json();
    if (json.ok) {
      showToast('图片目录已更改: ' + json.image_dir, 'success');
      loadImageDirConfig();
    } else {
      alert('保存失败: ' + (json.error || '未知错误'));
    }
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}
