// ===== 工作记录图片上传 =====
// 从 render_monthly.js 拆出,负责工作记录 3 处表单(sidebar/add/handle)的图片上传、压缩、预览。
// 依赖:render_duty_images.js(必须先加载,因为 openLightbox / getDutyImageUrl 在此文件中定义)。

const DUTY_IMAGES = { sidebar: [], add: [], handle: [] };
const MAX_IMAGES = 3;

function addDutyImage(source) {
  // source: 'sidebar' | 'add' | 'handle'
  let prefix = source === 'sidebar' ? 'duty' : `duty-${source}`;
  const input = document.getElementById(`${prefix}-image-input`);
  if (input) input.click();
}

function handleDutyImageSelect(input, source) {
  const files = Array.from(input.files);
  let prefix = source === 'sidebar' ? 'duty' : `duty-${source}`;
  const container = document.getElementById(`${prefix}-image-preview`);
  if (!container) return;

  // 限制最多3张
  const remaining = MAX_IMAGES - DUTY_IMAGES[source].length;
  const toAdd = files.slice(0, remaining);
  if (files.length > remaining) {
    showAlert(`最多上传 ${MAX_IMAGES} 张图片`, 'warn');
  }

  // 将文件转为临时 blob URL 用于预览
  toAdd.forEach(file => {
    const url = URL.createObjectURL(file);
    const id = `img_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    DUTY_IMAGES[source].push({ id, file, url, uploaded: false });
    renderDutyImagePreview(source, container);
  });

  input.value = '';
}

function removeDutyImage(source, id, container) {
  DUTY_IMAGES[source] = DUTY_IMAGES[source].filter(i => i.id !== id);
  renderDutyImagePreview(source, container);
}

function renderDutyImagePreview(source, container) {
  const images = DUTY_IMAGES[source];
  const prefix = source === 'sidebar' ? 'duty' : `duty-${source}`;
  container.innerHTML = images.map(img => `
    <div class="duty-image-preview-item">
      <img src="${img.url}" class="duty-image-thumb" style="width:60px;height:60px;" onclick="openLightbox('${img.url}')" title="点击查看大图" />
      <button type="button" class="remove-img-btn" onclick="removeDutyImage('${source}','${img.id}',document.getElementById('${prefix}-image-preview'))">✕</button>
    </div>
  `).join('');
}

// 渲染已上传的图片(用于处理弹窗显示原记录图片)
function renderUploadedImages(source, filenames, container) {
  if (!filenames || filenames.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = filenames.map(fn => {
    const imgSrc = getDutyImageUrl(fn);
    return `
      <div class="duty-image-preview-item">
        <img src="${imgSrc}" class="duty-image-thumb" style="width:60px;height:60px;" onclick="openLightbox('${imgSrc}')" title="点击查看大图" />
      </div>
    `;
  }).join('');
}

// 压缩图片(Canvas 压缩为 JPEG,降低体积)
// 最大宽度 1920px,质量 0.8,通常可将原图压缩至 100-300KB
function compressImage(file, maxWidth = 1920, quality = 0.8) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      img.onerror = () => { URL.revokeObjectURL(img.src); reject(new Error('图片加载失败')); return; };
      let w = img.naturalWidth;
      let h = img.naturalHeight;
      if (w > maxWidth) {
        h = Math.round((h * maxWidth) / w);
        w = maxWidth;
      }
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, w, h);
      canvas.toBlob(blob => {
        URL.revokeObjectURL(img.src);
        if (!blob) { reject(new Error('图片压缩失败')); return; }
        // 保持原文件名后缀
        const name = file.name.replace(/\.[^.]+$/, '') + '.jpg';
        resolve(new File([blob], name, { type: 'image/jpeg' }));
      }, 'image/jpeg', quality);
    };
    img.src = URL.createObjectURL(file);
  });
}

// 上传图片到服务器(每张照片一次请求,先压缩)
async function uploadDutyImages(source) {
  const images = DUTY_IMAGES[source].filter(i => !i.uploaded);
  const filenames = [];
  for (const img of images) {
    try {
      // 压缩图片
      const compressed = await compressImage(img.file, 1920, 0.8);
      const fd = new FormData();
      fd.append('image', compressed, compressed.name);
      const res = await fetch('/api/duty/image', {
        method: 'POST',
        body: fd,
      });
      const json = await res.json();
      if (json.ok) {
        filenames.push(json.filename);
        img.uploaded = true;
      } else {
        showAlert(`图片上传失败: ${json.error}`, 'warn');
      }
    } catch (e) {
      showAlert(`图片上传失败: ${e.message}`, 'warn');
    }
  }
  return filenames;
}
