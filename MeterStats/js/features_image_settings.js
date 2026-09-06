// ===== 图片目录管理 =====
const IMAGE_API = '/api/admin/images';

// 加载图片目录配置
function loadImageDirConfig() {
  const dirEl = document.getElementById('image-dir-display');
  const statsEl = document.getElementById('image-dir-stats');

  if (!dirEl) return;

  const doLoad = () => {
    fetch(IMAGE_API + getAuthParam())
      .then(r => r.json()).then(res => {
        if (!res.ok) return;
        dirEl.textContent = '📁 ' + res.image_dir + ' (默认: ' + res.default_image_dir + ')';
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

// 显示目录输入框
function pickImageDirInput() {
  const dirEl = document.getElementById('image-dir-display');
  const inputWrap = document.getElementById('image-dir-input-wrap');
  const input = document.getElementById('image-dir-input');
  if (!dirEl || !inputWrap || !input) return;

  let currentPath = '';
  const match = dirEl.textContent.match(/📁 (\S+)/);
  if (match) currentPath = match[1];

  input.value = currentPath;
  inputWrap.style.display = 'block';
  input.focus();
}

// 保存图片目录
async function saveImageDirInput() {
  const input = document.getElementById('image-dir-input');
  const inputWrap = document.getElementById('image-dir-input-wrap');
  if (!input) return;
  const path = input.value.trim();
  if (!path) {
    showToast('请输入目录路径', 'warn');
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
      showToast('图片目录已保存: ' + json.image_dir, 'success');
      inputWrap.style.display = 'none';
      loadImageDirConfig();
    } else {
      showToast('保存失败: ' + (json.error || '未知错误'), 'error');
    }
  } catch (e) {
    showToast('保存失败: ' + e.message, 'error');
  }
}
