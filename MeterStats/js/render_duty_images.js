// ===== 工作记录图片:灯箱预览 / URL 构造 =====
// 独立成文件,避免 render_tables.js / render_monthly.js 互相依赖。
// 由 index.html 在两个文件之前加载(确保 window.openLightbox 等已定义)。

/**
 * 构造后端工作记录图片的访问 URL。
 * @param {string} filename - 后端返回的图片文件名(YYYYMMDDHHMMSS.ext)
 * @returns {string} 形如 /api/duty/image/20260815143022.jpg
 */
function getDutyImageUrl(filename) {
  return `/api/duty/image/${filename}`;
}

/**
 * 打开图片灯箱(全屏查看大图)。
 * 依赖 DOM 元素: #image-lightbox-img、#image-lightbox-backdrop。
 */
function openLightbox(src) {
  const img = document.getElementById('image-lightbox-img');
  const backdrop = document.getElementById('image-lightbox-backdrop');
  if (!img || !backdrop) return;
  img.src = src;
  backdrop.style.display = 'flex';
}

/**
 * 关闭图片灯箱。
 */
function closeLightbox() {
  const backdrop = document.getElementById('image-lightbox-backdrop');
  if (backdrop) backdrop.style.display = 'none';
}

// 暴露到 window,供工作记录 / 抄表 / 任何其他需要预览的页面使用
window.getDutyImageUrl = getDutyImageUrl;
window.openLightbox = openLightbox;
window.closeLightbox = closeLightbox;
