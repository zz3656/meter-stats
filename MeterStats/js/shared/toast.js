/**
 * Toast / Alert —— 轻提示的**全局唯一实现**。
 *
 * ⚠️ 这个文件曾经是「什么都能往里塞」的垃圾桶:数据管理弹窗、备份目录选择、
 *    文件选择、base64 互转、自动备份开关全住在里面(348 行里约 300 行是死代码 ——
 *    `datamgmt*` 那套弹窗早被独立页面取代,index.html 里连对应节点都没有)。
 *    2026-11 C 批按「引用可达性」清掉了死函数,末尾那段没有函数体的 showModal
 *    JSDoc 也一并删除(真身在 js/shared/modals.js)。
 *
 * 往里加新东西之前先问一句:它真的属于「轻提示」吗?
 */

let _toastTimer = null;
function showToast(msg, type = 'success') {
  const overlay = document.getElementById('toast-overlay');
  const box = document.getElementById('toast-content');
  if (!box) { console.warn('toast-content not found'); return; }
  clearTimeout(_toastTimer);
  overlay.style.display = 'flex';
  box.className = `toast-content ${type}`;
  box.textContent = msg;
  // 强制重排以触发过渡动画
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      box.classList.add('show');
    });
  });
  _toastTimer = setTimeout(() => {
    box.classList.remove('show');
    setTimeout(() => { overlay.style.display = 'none'; }, 250);
  }, 3000);
}

function showAlert(msg, type = 'success') {
  showToast(msg, type);
}

// 注: 原 showItemAlert 别名已废弃(2025-09 重构)。所有调用点已改为 showAlert。
//   本函数已删除。如发现遗留调用会报 ReferenceError，便于发现遗留问题。

function pickBackupDir() {
  return new Promise(resolve => {
    const hasSwiftBridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pickBackupDir;
    if (hasSwiftBridge) {
      // macOS 原生 App: 调用 Swift 文件选择器
      window.__backupDirChosen = dir => {
        window.__backupDirChosen = null;
        resolve(dir);
      };
      window.webkit.messageHandlers.pickBackupDir.postMessage('pick');
    } else {
      // Docker / Web 浏览器环境: 直接弹文件选择器
      pickBackupFiles().then(resolve);
    }
  });
}

// 浏览器/Docker 环境:直接弹文件选择器(不再需要中间确认模态框)
// 返回 { files: { "readings.json": "..." } } 或 null(用户取消)
function pickBackupFiles() {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.json,.zip';
    input.style.display = 'none';
    document.body.appendChild(input);
    let resolved = false;
    const cleanup = () => {
      if (input.parentNode) input.parentNode.removeChild(input);
    };
    input.addEventListener('change', async () => {
      resolved = true;
      cleanup();
      const files = Array.from(input.files);
      if (!files.length) {
        resolve(null);
        return;
      }
      const fileContents = {};
      for (const file of files) {
        // zip 文件用 arrayBuffer,JSON 文件用 text
        if (file.name.toLowerCase().endsWith('.zip')) {
          const buf = await file.arrayBuffer();
          fileContents[file.name] = { __zip_b64: arrayBufferToBase64(buf) };
        } else {
          fileContents[file.name] = await file.text();
        }
      }
      resolve({ files: fileContents, _browser: true });
    });
    // 用户关掉文件选择器(没选)→ focus 回到页面,但 change 不触发
    // 用 blur 兜底清理(可能误触发,但 cleanup 已加守护)
    input.addEventListener('blur', () => {
      setTimeout(() => {
        if (!resolved) {
          resolved = true;
          cleanup();
          resolve(null);
        }
      }, 300);
    });
    input.click();
  });
}

// ArrayBuffer → base64(用于在 JSON body 传 zip)
function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
