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
 * 属性值转义 —— 把值安全地放进双引号/单引号属性里。
 *
 * 为什么不能只靠 escapeHtml:自由文本(门店名称/物品名/地址/编号)一旦进了
 * 属性值,就必须连引号一起转义,否则 `value="a" onmouseover="…"` 能把属性打断。
 * escapeHtml 连引号一起转义,元素内容位置用它是安全的;但**属性值位置一律用
 * escapeAttr**,不要图省事 —— 两者的语义边界写清楚,后人就不会用错。
 */
window.escapeAttr = function escapeAttr(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c];
  });
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

/**
 * 复制文本到剪贴板。
 *
 * ⚠️ App(WKWebView) 内必须走 Swift 原生桥:`navigator.clipboard` 在 WKWebView 里
 *    常因缺少用户手势上下文而静默失败,`document.execCommand('copy')` 也可能被拦,
 *    表现为「点了复制没反应」。
 *
 * ⚠️ 本文件原来还有一份**没有原生桥**的旧版,而 render_charts.js 里另有一份带桥的
 *    —— 后者加载得晚,一直静默覆盖这里。也就是说:改这个文件是改不出任何效果的
 *    (和 escapeHtml 弱版覆盖强版是同一类事故)。已把带桥的那份收敛到此处
 *    (2026-11 B 批),render_charts.js 里的副本已删。
 */
window.copyTextWithFallback = function copyTextWithFallback(text, successMsg) {
  const w = window;
  const bridge = w.webkit && w.webkit.messageHandlers
    && w.webkit.messageHandlers.macOSCopyToClipboard;
  if (bridge) {
    const esc = String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // Swift 端的解析分支要求 html/tsv 都是 String,html 不能传 null
    const html = '<meta charset="utf-8"><pre style="font-family:inherit;white-space:pre-wrap;'
      + 'font-size:12pt;margin:0;">' + esc + '</pre>';
    bridge.postMessage({ tsv: text, html: html });
    showAlert(successMsg, 'success');
    return;
  }

  const done = () => showAlert(successMsg, 'success');
  const fail = () => {
    // 浏览器环境兜底: 隐藏 textarea + execCommand('copy')
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

/** 值班记录图片的访问地址。
 *  <img> 无法携带 Authorization 头，后端 _get_token 支持 ?token= 查询参数，
 *  所以这里把 token 拼到 URL，否则强制鉴权后所有图片会 401。 */
window.getDutyImageUrl = function getDutyImageUrl(filename) {
  var base = `/api/duty/image/${filename}`;
  var t = (typeof currentAuthToken === 'function') ? currentAuthToken() : '';
  // ⚠️ store 参数必须带:图片目录是按门店分的
  // (stores/<store_id>/images/),不带就落到后端默认店 —— 总部账号切到分店后
  // 会看到总店的图,或者 404。
  var store = '';
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) store = StoreContext.getStoreId() || '';
  } catch (e) { store = ''; }
  var url = base;
  if (t) url += '?token=' + encodeURIComponent(t);
  if (isValidStoreId(store)) url += (url.indexOf('?') !== -1 ? '&' : '?') + 'store=' + encodeURIComponent(store);
  return url;
};

/**
 * 门店 ID 合法性 —— 口径只有一处:StoreContext.isValidStoreId()
 * (与后端 registry.is_valid_store_id 等价)。
 * StoreContext 没加载时退回本地判断(等价于后端的 \A[A-Za-z0-9_-]{1,32}\Z:
 * 长度 1-32 + 逐字符白名单 —— 不能用 /^...$/,JS 的 $ 会放行尾随换行)。
 *
 * ⚠️ 本文件在 index.html 里**最先加载**(早于 storeContext.js),
 *    但这些调用都发生在**运行时** —— 不存在加载期 TDZ 问题。
 */
function isValidStoreId(id) {
  var s = String(id == null ? '' : id);
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext
        && typeof StoreContext.isValidStoreId === 'function') {
      return !!StoreContext.isValidStoreId(s);
    }
  } catch (e) { /* StoreContext 没加载 */ }
  return s.length >= 1 && s.length <= 32 && !/[^A-Za-z0-9_-]/.test(s);
}

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
  // token 只走 admin.js 的 currentAuthToken()(AGENTS.md 约定 ——
  // localStorage 里有三套历史键名,后两个是死键)
  var token = (typeof currentAuthToken === 'function') ? currentAuthToken() : '';
  var suffix = token ? '?token=' + encodeURIComponent(token) : '';
  // 上传也是按门店落盘(stores/<store_id>/images/),必须带 store
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) {
      var st = StoreContext.getStoreId() || '';
      if (isValidStoreId(st)) {
        suffix += (suffix ? '&' : '?') + 'store=' + encodeURIComponent(st);
      }
    }
  } catch (e) { /* ignore */ }
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

;

;

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

;


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
  'item-add-note': 'item-note',
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

/* ============================================================
 * 列表图片悬停预览（PC 端）
 * 带 data-hover-preview="1" 的缩略图，鼠标悬停即浮动显示大图；
 * 移动端（无 hover 能力）自动禁用，仍走点击开灯箱。
 * ============================================================ */
window.initHoverPreview = function initHoverPreview() {
  if (window.__hoverPreviewReady) return;
  // 只在有鼠标悬停能力的设备启用，避免手机上误触发
  if (!window.matchMedia || !window.matchMedia('(hover: hover)').matches) return;
  var el = document.createElement('img');
  el.id = 'hover-preview-img';
  el.style.cssText = 'position:fixed;z-index:99998;display:none;max-width:280px;max-height:280px;' +
    'border-radius:10px;border:1px solid var(--border);background:var(--bg-elevated);' +
    'box-shadow:0 8px 28px rgba(0,0,0,.3);pointer-events:none;';
  document.body.appendChild(el);
  window.__hoverPreviewReady = true;

  function current(e) {
    var t = e.target;
    while (t && t !== document) {
      if (t.tagName === 'IMG' && t.getAttribute('data-hover-preview') === '1') return t;
      t = t.parentNode;
    }
    return null;
  }
  function position(e) {
    var pad = 14, w = el.offsetWidth, h = el.offsetHeight;
    var x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - pad;
    el.style.left = Math.max(8, x) + 'px';
    el.style.top = Math.max(8, y) + 'px';
  }
  document.addEventListener('mouseover', function (e) {
    var t = current(e);
    if (t && el.src !== t.getAttribute('data-full')) el.src = t.getAttribute('data-full');
    if (t) { el.style.display = 'block'; position(e); }
  });
  document.addEventListener('mousemove', function (e) {
    if (el.style.display === 'block') position(e);
  });
  document.addEventListener('mouseout', function (e) {
    if (current(e)) el.style.display = 'none';
  });
};

/** 打开图片灯箱 */
window.openLightbox = function openLightbox(src) {  const img = document.getElementById('image-lightbox-img');
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
