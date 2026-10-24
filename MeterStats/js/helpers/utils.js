// ===== 工具函数 =====

/** 安全获取 DOM 元素,不存在返回 null */
window.el = (id) => document.getElementById(id);

/**
 * HTML 转义,防止 XSS。
 * 用法: escapeHtml(userInput) 后再插入 innerHTML / 模板字符串。
 * 项目约定:所有来自用户输入(note/name/borrower/supplier/fault_area 等)
 *   拼接到 innerHTML 之前必须先经本函数处理。
 */
window.escapeHtml = function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
};

/**
 * 本地时间 YYYY-MM-DD 字符串(避免 toISOString 的 UTC 坑)。
 */
window.formatDate = function formatDate(d) {
  const dt = d instanceof Date ? d : new Date(d);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
};

/**
 * 本地时间 YYYY-MM-DD HH:MM:SS。
 */
window.formatDateTime = function formatDateTime(d) {
  const dt = d instanceof Date ? d : new Date(d);
  return `${formatDate(dt)} ${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}:${String(dt.getSeconds()).padStart(2, '0')}`;
};

/**
 * 本地时间 YYYY-MM-DDTHH:MM(datetime-local input 格式)。
 */
window.formatDateTimeLocal = function formatDateTimeLocal(d) {
  const dt = d instanceof Date ? d : new Date(d);
  return `${formatDate(dt)}T${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
};

// ===== 以下是模块化重构时丢失的工具函数（多个模块引用，缺失会抛 ReferenceError）=====

/** 两个 YYYY-MM-DD 日期相差的天数（b - a） */
window.daysBetween = function daysBetween(dateStrA, dateStrB) {
  const [y1, m1, d1] = dateStrA.split('-').map(Number);
  const [y2, m2, d2] = dateStrB.split('-').map(Number);
  return Math.round((new Date(y2, m2 - 1, d2) - new Date(y1, m1 - 1, d1)) / 86400000);
};

/** 日期的前一个月，输入/输出均为 YYYY-MM */
window.prevMonthKey = function prevMonthKey(monthKey) {
  const y = parseInt(monthKey.slice(0, 4), 10);
  const m = parseInt(monthKey.slice(5, 7), 10);
  if (m === 1) return `${y - 1}-12`;
  return `${y}-${String(m - 1).padStart(2, '0')}`;
};

/** 复制文本到剪贴板（WKWebView 下回退到 execCommand） */
window.copyTextWithFallback = function copyTextWithFallback(text, successMsg) {
  const done = () => showAlert(successMsg, 'success');
  const fail = () => {
    // WKWebView 兼容: 隐藏 textarea + execCommand('copy')
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) { done(); return; }
    } catch (e) { /* 继续走下方报错 */ }
    showAlert('复制失败,请手动选择复制', 'error');
  };
  if (navigator.clipboard && window.ClipboardItem) {
    navigator.clipboard.writeText(text).then(done, fail);
  } else {
    fail();
  }
};

/** 值班记录图片的访问地址 */
window.getDutyImageUrl = function getDutyImageUrl(filename) {
  return `/api/duty/image/${filename}`;
};

/**
 * 上传图片到服务器，返回文件名数组。
 * 复用 /api/duty/image 的存储与读取（同一 images 目录，读取走 /api/duty/image/{filename}）。
 */
/** 压缩图片：最长边缩到 maxSide，转 JPEG。压完反而更大就保留原图。 */
window.compressImage = function compressImage(file, maxSide, quality) {
  return new Promise(function (resolve) {
    if (!file || !/^image\//.test(file.type || '')) { resolve(file); return; }
    // 小图（<200KB）没必要压
    if (file.size < 200 * 1024) { resolve(file); return; }
    var img = new Image();
    var url = URL.createObjectURL(file);
    img.onload = function () {
      URL.revokeObjectURL(url);
      var w = img.naturalWidth, h = img.naturalHeight;
      var longest = Math.max(w, h);
      var cap = maxSide || 1600;
      var scale = Math.min(1, cap / longest);
      var cw = Math.round(w * scale), ch = Math.round(h * scale);
      var cv = document.createElement('canvas');
      cv.width = cw; cv.height = ch;
      var ctx = cv.getContext('2d');
      ctx.drawImage(img, 0, 0, cw, ch);
      cv.toBlob(function (blob) {
        // 压完更大说明原图已经足够小，用原图
        resolve(blob && blob.size < file.size ? blob : file);
      }, 'image/jpeg', quality || 0.82);
    };
    img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
};

/**
 * 上传图片。
 * @param {File[]} files
 * @param {number} maxCount 最多几张
 * @param {string} scope    来源标识，写进文件名前缀，例如 lend / return / purchase-note / duty-note
 *                          这样在图片目录里一眼能看出是哪张页面传上来的。
 */
window.uploadImages = function uploadImages(files, maxCount, scope, skipCompress) {
  var list = Array.prototype.slice.call(files || []).slice(0, maxCount || 3);
  var token = (typeof ADMIN_TOKEN !== 'undefined' && ADMIN_TOKEN) ||
    localStorage.getItem('token') || '';
  var suffix = token ? '?token=' + encodeURIComponent(token) : '';
  return Promise.all(list.map(function (f) {
    var prep = skipCompress ? Promise.resolve(f) : window.compressImage(f, 1600, 0.82);
    return prep.then(function (blob) {
      // 压缩后是 JPEG；没压（原图）就保持原后缀
      var isCompressed = blob !== f;
      var ext = isCompressed ? 'jpg' : ((f.name || '').split('.').pop() || 'png');
      var name = (f.name || 'image').replace(/\.[^.]+$/, '') + (isCompressed ? '.jpg' : '.' + ext);
      var out = isCompressed ? new File([blob], name, { type: 'image/jpeg' }) : f;
      var fd = new FormData();
      fd.append('image', out);
      fd.append('scope', scope || 'misc');
      return fetch('/api/duty/image' + suffix, { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j || !j.ok) throw new Error((j && j.error) || '上传失败');
          return j.filename;
        });
    });
  }));
};

/** 待提交的图片（按弹窗区分），打开弹窗时清空 */
window.__pendingImages = { lend: [], return: [], purchase: [] };

/** 点「📷 图片」按钮 */
window.pickItemImage = function pickItemImage(kind) {
  var el = document.getElementById(kind + '-image-input');
  if (el) el.click();
};

/** 选中文件后：上传 + 刷新预览 */
window.onItemImagePicked = function onItemImagePicked(input, kind) {
  if (!input.files || !input.files.length) return;
  var bucket = window.__pendingImages[kind] || (window.__pendingImages[kind] = []);
  var room = 3 - bucket.length;
  var files = Array.prototype.slice.call(input.files).slice(0, Math.max(0, room));
  input.value = '';
  if (!files.length) { showAlert('最多 3 张图片', 'warn'); return; }
  uploadImages(files, 3, kind).then(function (names) {
    window.__pendingImages[kind] = bucket.concat(names);
    renderItemImagePreview(kind);
  }).catch(function (e) {
    showAlert('图片上传失败: ' + (e && e.message ? e.message : e), 'error');
    renderItemImagePreview(kind);
  });
};

/** 重绘某个弹窗的图片预览（带删除按钮） */
window.renderItemImagePreview = function renderItemImagePreview(kind) {
  var box = document.getElementById(kind + '-image-preview');
  if (!box) return;
  var names = window.__pendingImages[kind] || [];
  box.innerHTML = names.map(function (fn) {
    return '<span style="position:relative;display:inline-block;">' +
      '<img src="' + getDutyImageUrl(fn) + '" data-full="' + getDutyImageUrl(fn) + '" ' +
      'style="width:56px;height:56px;object-fit:cover;border-radius:4px;cursor:pointer;" ' +
      'onclick="openLightbox(this.dataset.full)" />' +
      '<button type="button" title="移除" onclick="removeItemImage(\'' + kind + '\',\'' + fn + '\')" ' +
      'style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;border-radius:50%;border:none;' +
      'background:var(--danger);color:#fff;font-size:11px;line-height:1;cursor:pointer;padding:0;">×</button>' +
      '</span>';
  }).join('');
};

/** 移除一张待提交的图片 */
window.removeItemImage = function removeItemImage(kind, filename) {
  var bucket = window.__pendingImages[kind] || [];
  window.__pendingImages[kind] = bucket.filter(function (n) { return n !== filename; });
  renderItemImagePreview(kind);
};

/** 打开弹窗前清空该弹窗的待提交图片 */
window.resetItemImages = function resetItemImages(kind) {
  window.__pendingImages[kind] = [];
  renderItemImagePreview(kind);
};


/* ============================================================
 * 「文本或图片」字段组件
 * 用于：借出人 / 归还人 / 申购备注 / 工作记录备注 / 处理方案
 * 这些字段既可以手打文字，也可以直接拍/传一张图代替。
 * 图片按字段 id 暂存在 __fieldImages[fieldId] 里，提交时随表单一起发。
 * ============================================================ */

window.__fieldImages = {};

/** 点字段旁的 📷 按钮 */
window.pickFieldImage = function pickFieldImage(fieldId) {
  var scope = (window.FIELD_SCOPES && window.FIELD_SCOPES[fieldId]) || 'misc';
  // ⚠️ App(WKWebView) 里 <input type="file"> 不可靠，统一走原生桥。
  //    浏览器里没有这个 handler，自然回退到 input.click()。
  if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.macOSPickImage) {
    window.__pendingFieldPick = { fieldId: fieldId, scope: scope };
    window.webkit.messageHandlers.macOSPickImage.postMessage({ max: 3 });
    return;
  }
  var input = document.getElementById(fieldId + '-file');
  if (input) { input.click(); return; }
  if (typeof showAlert === 'function') showAlert('这个字段没有图片入口: ' + fieldId, 'error');
};

/** 原生选图回调（Swift 调） */
window.onNativeImagePicked = function onNativeImagePicked(payload) {
  var pending = window.__pendingFieldPick;
  window.__pendingFieldPick = null;
  if (!pending) return;
  if (!payload || !payload.files || !payload.files.length) return;   // 用户取消

  var files = payload.files.map(function (f) {
    var bin = atob(f.content || '');
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    var ext = (f.ext || 'jpg').toLowerCase();
    var base = (f.name || 'image').replace(/\.[^.]+$/, '');
    return new File([arr], base + '.' + ext, {
      type: ext === 'png' ? 'image/png' : (ext === 'webp' ? 'image/webp' : 'image/jpeg')
    });
  });

  window.uploadImagesRaw(files, 3, pending.scope).then(function (names) {
    if (typeof pending.custom === 'function') {
      pending.custom(names);
      return;
    }
    var cur = window.__fieldImages[pending.fieldId] || [];
    window.__fieldImages[pending.fieldId] = cur.concat(names).slice(0, 3);
    window.renderFieldImagePreview(pending.fieldId);
  }).catch(function (e) {
    showAlert('图片上传失败: ' + (e && e.message ? e.message : e), 'error');
  });
};

/** 原生桥已经压过的图，直接上传不再二次压缩 */
window.uploadImagesRaw = function uploadImagesRaw(files, maxCount, scope) {
  return window.uploadImages(files, maxCount, scope, true);
};

/** 字段 → 上传文件名前缀（图片目录里一眼看出是哪个页面传的） */
window.FIELD_SCOPES = {
  'lend-borrower': 'lend',
  'return-by': 'return',
  'purchase-add-name': 'purchase-name',
  'purchase-add-note': 'purchase-note',
  'duty-add-note': 'duty-note',
  'duty-handle-method': 'duty-handle'
};

/** 选中文件后：上传 + 预览 */
window.onFieldImagePicked = function onFieldImagePicked(input, fieldId) {
  if (!input.files || !input.files.length) return;
  var files = Array.prototype.slice.call(input.files).slice(0, 3);
  input.value = '';
  var scope = (window.FIELD_SCOPES && window.FIELD_SCOPES[fieldId]) || 'misc';
  uploadImages(files, 3, scope).then(function (names) {
    var cur = window.__fieldImages[fieldId] || [];
    window.__fieldImages[fieldId] = cur.concat(names).slice(0, 3);
    renderFieldImagePreview(fieldId);
  }).catch(function (e) {
    showAlert('图片上传失败: ' + (e && e.message ? e.message : e), 'error');
  });
};

/** 重绘字段的图片预览 */
window.renderFieldImagePreview = function renderFieldImagePreview(fieldId) {
  var box = document.getElementById(fieldId + '-preview');
  if (!box) return;
  var names = window.__fieldImages[fieldId] || [];
  box.innerHTML = names.map(function (fn) {
    return '<span style="position:relative;display:inline-block;">' +
      '<img src="' + getDutyImageUrl(fn) + '" data-full="' + getDutyImageUrl(fn) + '" ' +
      'style="width:48px;height:48px;object-fit:cover;border-radius:6px;cursor:pointer;border:1px solid var(--border);" ' +
      'onclick="openLightbox(this.dataset.full)" />' +
      '<button type="button" onclick="removeFieldImage(\'' + fieldId + '\',\'' + fn + '\')" ' +
      'style="position:absolute;top:-6px;right:-6px;width:17px;height:17px;border-radius:50%;border:none;' +
      'background:var(--danger);color:#fff;font-size:11px;line-height:1;cursor:pointer;padding:0;">×</button>' +
      '</span>';
  }).join('');
  // 有图时把输入框的"必填"观感放宽一点：提示可以只传图
  var inp = document.getElementById(fieldId);
  if (inp) {
    // 第一次进来记住原始 placeholder，删图后能还原
    if (!inp.dataset.origPlaceholder) inp.dataset.origPlaceholder = inp.placeholder || '';
    inp.placeholder = names.length ? '（已传图片）' : inp.dataset.origPlaceholder;
  }
};

window.removeFieldImage = function removeFieldImage(fieldId, filename) {
  var cur = window.__fieldImages[fieldId] || [];
  window.__fieldImages[fieldId] = cur.filter(function (n) { return n !== filename; });
  renderFieldImagePreview(fieldId);
};

/** 取某字段的图片文件名数组 */
window.getFieldImages = function getFieldImages(fieldId) {
  return window.__fieldImages[fieldId] || [];
};

/** 清空一组字段的图片（打开弹窗时调用） */
window.resetFieldImages = function resetFieldImages(fieldIds) {
  (fieldIds || []).forEach(function (id) {
    window.__fieldImages[id] = [];
    renderFieldImagePreview(id);
  });
};

/** 打开图片灯箱 */
window.openLightbox = function openLightbox(src) {
  const img = document.getElementById('image-lightbox-img');
  const backdrop = document.getElementById('image-lightbox-backdrop');
  if (!img || !backdrop) return;
  img.src = src;
  backdrop.style.display = 'flex';
};

/** 关闭图片灯箱 */
window.closeLightbox = function closeLightbox() {
  const backdrop = document.getElementById('image-lightbox-backdrop');
  if (backdrop) backdrop.style.display = 'none';
};
