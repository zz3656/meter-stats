// ===== 工作记录图片目录管理 =====
const IMAGE_API = '/api/admin/images';

// 加载图片目录配置
function loadImageDirConfig() {
  const dirEl = document.getElementById('image-dir-display');
  const statsEl = document.getElementById('image-dir-stats');

  if (!dirEl) return;

  // 如果 API 不可用（旧版本后端），显示提示信息
  const doLoad = () => {
    fetch(IMAGE_API + getAuthParam())
      .then(r => r.json()).then(res => {
        if (!res.ok) return;
        dirEl.textContent = '📁 ' + res.image_dir + ' (默认: ' + res.default_image_dir + ')';
        if (statsEl) statsEl.textContent = '📊 图片数量: ' + res.image_count + ' 张, 总大小: ' + formatBytes(res.total_size);
      }).catch(e => {
        // API 不可用（后端未更新）时显示提示
        dirEl.textContent = '⚠️ 后端未更新，请重启服务后生效';
        if (statsEl) statsEl.textContent = '';
      });
  };

  // 首次加载时显示加载中（已有则不覆盖）
  if (dirEl.textContent === '') {
    dirEl.textContent = '加载中...';
    doLoad();
  } else {
    doLoad();
  }
}

// 选择图片目录
function pickImageDir() {
  const dirEl = document.getElementById('image-dir-display');
  // 尝试从当前文本提取已保存的路径
  let currentPath = '';
  if (dirEl) {
    const match = dirEl.textContent.match(/📁 (\S+)/);
    if (match) currentPath = match[1];
  }
  const path = prompt('请输入图片目录的完整路径:', currentPath);
  if (!path || !path.trim()) return;
  saveImageDir(path.trim());
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
