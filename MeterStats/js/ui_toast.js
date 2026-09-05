// ===== 全局 Toast 提示覆盖层 =====
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

// 物品卡提示条(已改为全局 Toast)
function showItemAlert(msg, type = 'success') {
  showToast(msg, type);
}

// 数据管理:自动备份开关(localStorage 持久化)
const AUTO_BACKUP_KEY = 'meter_auto_backup';
function getAutoBackupEnabled() {
  return localStorage.getItem(AUTO_BACKUP_KEY) !== 'false'; // 默认开启
}
function saveAutoBackup(enabled) {
  localStorage.setItem(AUTO_BACKUP_KEY, enabled ? 'true' : 'false');
}
function initAutoBackupToggle() {
  const cb = document.getElementById('datamgmt-auto-backup-toggle') || document.getElementById('auto-backup-toggle');
  if (!cb) return;
  // 避免重复绑定事件
  if (!cb._backupToggleBound) {
    cb._backupToggleBound = true;
    cb.addEventListener('change', e => {
      saveAutoBackup(e.target.checked);
      showToast(e.target.checked ? '已开启自动备份' : '已关闭自动备份', 'info');
    });
  }
  cb.checked = getAutoBackupEnabled();
}

// 数据管理弹窗(已废弃:数据管理改为独立页面,统一通过 admin.js 实现)
// 保留函数以防有外部代码还在调用,内部用 null check 防止报错
function openDataMgmtModal() {
  initAutoBackupToggle();
  loadDataMgmtBackupDir();
  const backdrop = document.getElementById('datamgmt-modal-backdrop');
  if (backdrop) backdrop.classList.add('show');
}
function closeDataMgmtModal() {
  const backdrop = document.getElementById('datamgmt-modal-backdrop');
  if (backdrop) backdrop.classList.remove('show');
}

// 数据管理弹窗: 加载备份目录配置
function loadDataMgmtBackupDir() {
  fetch('/api/admin/backup-config?token=' + encodeURIComponent(localStorage.getItem('meter_token') || ''))
    .then(r => r.json()).then(res => {
      const display = document.getElementById('datamgmt-backup-dir-display');
      if (!display) return;
      if (res.customizable === false) {
        display.textContent = '🔒 ' + (res.backup_dir || res.data_dir);
      } else {
        const dir = res.backup_dir || '默认: ' + res.data_dir + '/backup';
        display.textContent = dir;
      }
    }).catch(() => {});
}

// 数据管理弹窗: 选择备份目录
async function datamgmtSetBackupDir() {
  const dir = await pickBackupDir();
  if (!dir) {
    showAlert('未选择目录', 'info');
    return;
  }
  try {
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: dir });
    if (!res.ok) {
      showAlert('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showAlert('✅ 备份目录已更新', 'success');
    loadDataMgmtBackupDir();
  } catch (e) {
    showAlert('保存失败: ' + e.message, 'error');
  }
}

// 数据管理弹窗: 恢复默认备份目录
async function datamgmtResetBackupDir() {
  try {
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: null });
    if (!res.ok) {
      showAlert('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showAlert('✅ 已恢复默认备份目录', 'success');
    loadDataMgmtBackupDir();
  } catch (e) {
    showAlert('保存失败: ' + e.message, 'error');
  }
}

// 手动备份(从数据管理弹窗调用,已废弃:数据管理改为独立页面,统一走 adminBackup)
async function datamgmtBackup() {
  const btn = document.getElementById('datamgmt-backup-btn');
  if (!btn) return;  // 元素不存在(已迁移到独立页面),静默返回
  const original = btn.textContent;
  btn.textContent = '⏳ 备份中…';
  btn.disabled = true;
  try {
    showAlert('正在备份数据…', 'info');
    const res = await api('POST', '/api/backup');
    if (!res.ok) {
      showAlert('备份失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    btn.textContent = '✅ 已备份';
    showAlert('✅ 数据已备份到 ' + (res.backup_dir || 'backup/'), 'success');
    // 备份成功后刷新备份列表
    setTimeout(() => { if (typeof loadBackupList === 'function') loadBackupList(); }, 500);
  } catch (e) {
    btn.textContent = original;
    showAlert('备份失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    setTimeout(() => { btn.textContent = original; }, 2000);
  }
}
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

// base64 → ArrayBuffer
function base64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

// 浏览器环境下的文件选择/上传
function showBrowserFilePicker(mode, callback) {
  // mode: 'pick' (选文件) | 'upload' (上传文件)
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.accept = '.json';

  input.onchange = async () => {
    const files = Array.from(input.files);
    if (!files.length) {
      callback(null);
      return;
    }

    // 收集所有文件内容
    const fileContents = {};
    for (const file of files) {
      const text = await file.text();
      fileContents[file.name] = text;
    }

    if (mode === 'upload' || files.some(f => f.name.startsWith('readings.json'))) {
      // 有数据文件 — 直接上传
      callback({ files: fileContents, _browser: true });
    } else {
      // 只是 settings.json 或其他 — 也上传
      callback({ files: fileContents, _browser: true });
    }
  };

  input.click();
}

// 恢复数据(从数据管理弹窗调用,已废弃:统一走 adminRestore,通过 admin.js 实现)
async function datamgmtRestore() {
  const btn = document.getElementById('datamgmt-restore-btn');
  if (!btn) return;  // 元素不存在(已迁移到独立页面),静默返回
  const original = btn.textContent;
  try {
    const dir = await pickBackupDir();
    if (!dir) {
      showAlert('未选择文件,已取消恢复', 'info');
      return;
    }

    let res;
    if (dir._browser) {
      // 浏览器/Docker 环境: 上传文件 — JSON 单文件 或 ZIP 备份包
      const hasZip = Object.keys(dir.files).some(n => n.toLowerCase().endsWith('.zip'));
      const fileNames = Object.keys(dir.files).join(', ');
      const ok = await showModal({
        icon: '⚠️',
        iconKind: 'warn',
        title: '确认恢复数据？',
        body: `将从 <b>${fileNames}</b> 恢复${hasZip ? '(zip 备份包将自动解压)' : ''}。<br><br>⚠️ 当前数据会被覆盖,但恢复前系统会自动备份当前数据到 backup/ 目录,可随时回滚。`,
        confirmText: '确认恢复',
        cancelText: '取消',
        confirmKind: 'danger',
      });
      if (!ok) return;
      btn.textContent = '⏳ 恢复中…';
      btn.disabled = true;
      res = await api('POST', '/api/upload', { files: dir.files });
      if (!res.ok) {
        showAlert('恢复失败: ' + (res.error || '未知错误'), 'error');
        return;
      }
      const restoredCount = (res.restored || []).length;
      if (restoredCount > 0) {
        showAlert(`✅ 已恢复 ${restoredCount} 个数据文件${res.pre_backup ? ';恢复前数据已备份到 ' + res.pre_backup : ''}`, 'success');
      } else {
        showAlert(`✅ 已上传 ${(res.uploaded || []).length} 个文件`, 'success');
      }
      // 用 renderAll() 全量刷新: readings/charges/items/purchases/duty + 所有页面渲染,
      // 旧的 refreshAll() 只刷 items/purchases,会导致 readings/charges 页面不更新。
      await renderAll();
    } else {
      // macOS 原生 App: 用目录路径恢复
      const ok = await showModal({
        icon: '⚠️',
        iconKind: 'warn',
        title: '确认恢复数据?',
        body: `将从 <b>${dir}</b> 恢复数据。<br><br>⚠️ 当前数据会被覆盖,但恢复前系统会自动备份当前数据到 backup/ 目录,可随时回滚。`,
        confirmText: '确认恢复',
        cancelText: '取消',
        confirmKind: 'danger',
      });
      if (!ok) { showAlert('已取消恢复', 'info'); return; }
      btn.textContent = '⏳ 恢复中…';
      btn.disabled = true;
      res = await api('POST', '/api/restore', { source_dir: dir });
      if (!res.ok) {
        showAlert('恢复失败: ' + (res.error || '未知错误'), 'error');
        return;
      }
      showAlert(`✅ 已恢复 ${res.restored.length} 个数据文件;恢复前数据已备份到 ${res.pre_backup}`, 'success');
      // 同样改用 renderAll() 全量刷新(macOS 路径)
      await renderAll();
    }
  } catch (e) {
    btn.textContent = original;
    showAlert('恢复失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

/**
 * 自定义确认弹窗(替代原生 confirm)
 * @param {Object} opts
 * @param {string} opts.title       - 弹窗标题
 * @param {string} opts.body        - 弹窗正文(支持 HTML)
 * @param {string} [opts.icon]      - 图标 emoji
 * @param {string} [opts.iconKind]  - 'danger' | 'warn' | 'info'
 * @param {string} [opts.confirmText] - 确认按钮文字
 * @param {string} [opts.cancelText]  - 取消按钮文字
 * @param {string} [opts.confirmKind] - 'danger' | 'primary'
 * @returns {Promise<boolean>}
 */