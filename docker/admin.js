// ===== 后台管理: 全局会话 =====
let ADMIN_TOKEN = localStorage.getItem('linclub_admin_token');
let ADMIN_USER = null;

const ROLE_NAMES = { admin: '管理员', supervisor: '主管', employee: '员工' };

// 权限: 管理员和主管有删除权限, 员工只有录入和编辑
const ADMIN_DELETE_ROLES = new Set(['admin', 'supervisor']);
const ADMIN_MANAGE_ROLES = new Set(['admin']);

// ===== 初始化: 有token则显示登录成功状态 =====
function initAuth() {
  if (ADMIN_TOKEN) {
    // 验证会话
    fetch('/api/auth/me?token=' + encodeURIComponent(ADMIN_TOKEN))
      .then(r => r.json()).then(res => {
        if (res.user) {
          setLoggedIn(res.user);
        } else {
          clearAuth();
        }
      }).catch(() => clearAuth());
  }
}

function setLoggedIn(user) {
  ADMIN_USER = user;
  document.getElementById('logout-btn').style.display = '';
  document.getElementById('admin-user-info').textContent = `(${user.name} · ${ROLE_NAMES[user.role]})`;
  document.getElementById('login-page').style.display = 'none';
}

function clearAuth() {
  ADMIN_TOKEN = null;
  ADMIN_USER = null;
  localStorage.removeItem('linclub_admin_token');
  document.getElementById('logout-btn').style.display = 'none';
  document.getElementById('login-page').style.display = 'flex';
}

// ===== 登录 =====
function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  errEl.style.display = 'none';

  fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }).then(r => r.json()).then(res => {
    if (!res.ok) {
      errEl.textContent = res.error || '登录失败';
      errEl.style.display = 'block';
      return;
    }
    ADMIN_TOKEN = res.token;
    setLoggedIn(res.user);
    loadData();
  }).catch(e => {
    errEl.textContent = '网络错误: ' + e.message;
    errEl.style.display = 'block';
  });
}

// Enter 键登录
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.getElementById('login-page').style.display !== 'none') {
    doLogin();
  }
});

// ===== 登出 =====
function doLogout() {
  if (ADMIN_TOKEN) {
    fetch('/api/auth/logout?token=' + encodeURIComponent(ADMIN_TOKEN)).catch(() => {});
  }
  clearAuth();
}

// ===== 后台管理弹窗 =====
function openAdminPanel() {
  // 未登录 → 先弹窗登录
  if (!ADMIN_TOKEN) {
    document.getElementById('login-page').style.display = 'flex';
    return;
  }
  // 已登录 → 打开管理弹窗 (modal)
  document.getElementById('admin-modal-backdrop').classList.add('show');
  document.getElementById('admin-user-info').textContent = `(${ADMIN_USER.name} · ${ROLE_NAMES[ADMIN_USER.role]})`;
  loadAdminUsers();
  loadMeterSettings();
  loadBackupStatus();
  loadRolesInfo();
}

function closeAdminPanel() {
  document.getElementById('admin-modal-backdrop').classList.remove('show');
}

// 切换后台页面
function switchAdminPage(page) {
  document.querySelectorAll('.admin-page').forEach(el => { el.style.display = 'none'; el.classList.remove('active'); });
  document.querySelectorAll('#admin-modal-backdrop .tab-btn').forEach(el => el.classList.remove('active'));
  const target = document.getElementById('admin-page-' + page);
  if (target) { target.style.display = 'block'; target.classList.add('active'); }
  const btn = document.querySelector(`#admin-modal-backdrop .tab-btn[data-page="${page}"]`);
  if (btn) btn.classList.add('active');
  // 切换到数据页时加载备份配置
  if (page === 'data') loadBackupConfig();
}

// ===== 用户管理 =====
function loadAdminUsers() {
  fetch('/api/admin/users' + getAuthParam())
    .then(r => r.json()).then(res => {
      const tbody = document.getElementById('users-table-body');
      if (!tbody) return;
      const users = res || [];
      tbody.innerHTML = users.map(u => `
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:6px 8px;">${u.username}</td>
          <td style="padding:6px 8px;">${u.name}</td>
          <td style="padding:6px 8px;">${ROLE_NAMES[u.role] || u.role}</td>
          <td style="padding:6px 8px;">${u.enabled ? '✅ 启用' : '❌ 禁用'}</td>
          <td style="padding:6px 8px;text-align:right;">
            <button class="btn btn-primary btn-sm" onclick="editAdminUser(${u.id},'${u.username}')" style="margin-right:4px;">编辑</button>
            ${ADMIN_DELETE_ROLES.has(ADMIN_USER?.role) && u.id !== ADMIN_USER?.id ? `<button class="btn btn-danger btn-sm" onclick="deleteAdminUser(${u.id})" style="margin-right:4px;">删除</button>` : ''}
          </td>
        </tr>
      `).join('');
    }).catch(e => showAlert('加载用户失败: ' + e.message, 'error'));
}

function addAdminUser() {
  const username = document.getElementById('new-username').value.trim();
  const password = document.getElementById('new-password').value;
  const name = document.getElementById('new-name').value.trim() || username;
  const role = document.getElementById('new-role').value;

  if (!username || !password) { showAlert('用户名和密码不能为空', 'error'); return; }
  if (!ADMIN_MANAGE_ROLES.has(ADMIN_USER?.role)) { showAlert('只有管理员可以添加用户', 'error'); return; }

  fetch('/api/admin/users' + getAuthParam(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, name, role }),
  }).then(r => r.json()).then(res => {
    if (!res.ok) { showAlert('添加失败: ' + (res.error || '未知错误'), 'error'); return; }
    showAlert('用户已添加: ' + username, 'success');
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-name').value = '';
    loadAdminUsers();
  }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
}

function editAdminUser(uid, oldUsername) {
  fetch('/api/admin/users' + getAuthParam() + '&id=' + uid)
    .then(r => r.json()).then(res => {
      if (!res.user) { showAlert('用户不存在', 'error'); return; }
      const u = res.user;
      const newName = prompt('显示名', u.name);
      if (newName === null) return;
      const newRole = prompt('角色 (admin/supervisor/employee)', u.role);
      if (newRole === null) return;
      const newPassword = prompt('新密码 (留空不修改)', '');

      const body = { name: newName, role: newRole };
      if (newPassword && newPassword.trim()) body.password = newPassword.trim();

      fetch('/api/admin/users' + getAuthParam() + '&id=' + uid, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json()).then(res2 => {
        if (!res2.ok) { showAlert('编辑失败: ' + (res2.error || '未知错误'), 'error'); return; }
        showAlert('用户已更新', 'success');
        loadAdminUsers();
      }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
    }).catch(e => showAlert('加载用户失败: ' + e.message, 'error'));
}

function deleteAdminUser(uid) {
  if (!confirm('确认删除此用户? 此操作不可恢复。')) return;
  fetch('/api/admin/users' + getAuthParam() + '&id=' + uid, { method: 'DELETE' })
    .then(r => r.json()).then(res => {
      if (!res.ok) { showAlert('删除失败: ' + (res.error || '未知错误'), 'error'); return; }
      showAlert('用户已删除', 'success');
      loadAdminUsers();
    }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
}

// ===== 电表设置 =====
function loadMeterSettings() {
  fetch('/api/admin/meter' + getAuthParam())
    .then(r => r.json()).then(res => {
      const form = document.getElementById('meter-settings-form');
      if (!form) return;
      const meter = res.meter || {};
      const config = res.config || {};

      // 填充配置
      const elecPrice = document.getElementById('config-elec-price');
      const waterPrice = document.getElementById('config-water-price');
      if (elecPrice) elecPrice.value = config.electricity_price || 0.9;
      if (waterPrice) waterPrice.value = config.water_price || 4.5;

      // 填充电表参数
      const meterKeys = ['hall', 'fire', 'private_room', 'ac'];
      const icons = { hall: '🎤', fire: '🧯', private_room: '🛋️', ac: '❄️' };
      form.innerHTML = meterKeys.map(k => {
        const m = meter[k] || {};
        return `
          <div style="background:var(--bg-subtle);padding:8px;border-radius:6px;border:1px solid var(--border);">
            <div style="font-size:12px;font-weight:510;margin-bottom:6px;">${icons[k]} ${m.label || k}</div>
            <div style="display:flex;gap:6px;align-items:center;margin-bottom:3px;">
              <label style="font-size:11px;color:var(--text-muted);min-width:50px;">倍率</label>
              <input type="number" class="meter-input" data-key="${k}" data-field="multiplier" value="${m.multiplier || 1}" style="flex:1;padding:3px 5px;">
            </div>
            <div style="display:flex;gap:6px;align-items:center;">
              <label style="font-size:11px;color:var(--text-muted);min-width:50px;">表名</label>
              <input type="text" class="meter-input" data-key="${k}" data-field="label" value="${m.label || ''}" style="flex:1;padding:3px 5px;">
            </div>
          </div>
        `;
      }).join('');
    }).catch(e => showAlert('加载电表设置失败', 'error'));
}

function saveMeterSettings() {
  const meterInputs = document.querySelectorAll('.meter-input');
  const meter = {};
  meterInputs.forEach(inp => {
    const k = inp.dataset.key;
    const f = inp.dataset.field;
    if (!meter[k]) meter[k] = {};
    const v = f === 'multiplier' ? parseInt(inp.value, 10) : inp.value;
    meter[k][f] = v;
  });

  const config = {
    electricity_price: parseFloat(document.getElementById('config-elec-price').value) || 0.9,
    water_price: parseFloat(document.getElementById('config-water-price').value) || 4.5,
  };

  fetch('/api/admin/meter' + getAuthParam(), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ meter, config }),
  }).then(r => r.json()).then(res => {
    if (!res.ok) { showAlert('保存失败', 'error'); return; }
    showAlert('电表参数已保存', 'success');
    Object.keys(meter).forEach(k => {
      if (window.MULTIPLIER) window.MULTIPLIER[k] = meter[k].multiplier;
    });
  }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
}

// ===== 数据管理 =====
function loadBackupStatus() {
  fetch('/api/admin/backup-status' + getAuthParam())
    .then(r => r.json()).then(res => {
      const cb = document.getElementById('admin-auto-backup-toggle');
      if (cb) cb.checked = res.auto_backup !== false;
      const countEl = document.getElementById('backup-count');
      if (countEl) countEl.textContent = '当前备份数: ' + (res.backup_count || 0) + ' 个';
      if (cb) cb.addEventListener('change', e => {
        fetch('/api/admin/auto-backup' + getAuthParam(), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: e.target.checked }),
        }).then(() => showAlert(e.target.checked ? '自动备份已开启' : '自动备份已关闭', 'info'));
      }, { once: true });
      // 渲染备份列表
      renderBackupList(res.backups || []);
    }).catch(() => {});
}

function loadBackupList() {
  loadBackupStatus();
}

function renderBackupList(backups) {
  // 渲染后台管理页面的备份列表
  const adminList = document.getElementById('backup-list');
  if (adminList) {
    if (!backups || backups.length === 0) {
      adminList.innerHTML = '暂无备份';
    } else {
      let html = '';
      backups.forEach(b => {
        const sizeStr = formatBytes(b.total_size || 0);
        html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);">
          <div>
            <span style="color:var(--text);font-weight:510;">${b.name}</span>
            <span style="color:var(--text-muted);margin-left:8px;">${b.file_count} 文件 · ${sizeStr}</span>
            <span style="color:var(--text-muted);margin-left:8px;font-size:10px;">${b.created_at}</span>
          </div>
          <button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.name}')" style="padding:2px 8px;font-size:11px;white-space:nowrap;">⬇️ 下载</button>
        </div>`;
      });
      adminList.innerHTML = html;
    }
  }
  // 渲染数据管理弹窗的备份列表
  const dmList = document.getElementById('datamgmt-backup-list');
  if (dmList) {
    if (!backups || backups.length === 0) {
      dmList.innerHTML = '暂无备份';
    } else {
      let html = '';
      backups.forEach(b => {
        const sizeStr = formatBytes(b.total_size || 0);
        html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);">
          <div>
            <span style="color:var(--text);font-weight:510;">${b.name}</span>
            <span style="color:var(--text-muted);margin-left:8px;">${b.file_count} 文件 · ${sizeStr}</span>
          </div>
          <button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.name}')" style="padding:2px 8px;font-size:11px;white-space:nowrap;">⬇️ 下载</button>
        </div>`;
      });
      dmList.innerHTML = html;
    }
  }
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function downloadBackup(dirName) {
  // 下载备份 zip
  const token = localStorage.getItem('linclub_token');
  const url = `/api/admin/backup-download?dir=${encodeURIComponent(dirName)}${token ? '&token=' + encodeURIComponent(token) : ''}`;
  const a = document.createElement('a');
  a.href = url;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// 备份/恢复 (浏览器环境用 app.js 中的 browser file picker)
async function adminPickBackupDir() {
  return new Promise(resolve => {
    // 尝试 swift bridge
    const hasBridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pickBackupDir;
    if (!hasBridge) { resolve(null); return; }
    window.__backupDirChosen = dir => {
      window.__backupDirChosen = null;
      resolve(dir);
    };
    window.webkit.messageHandlers.pickBackupDir.postMessage('pick');
  });
}

// 浏览器环境: 选择文件上传
function browserPickFiles() {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.json';
    input.onchange = async () => {
      const files = Array.from(input.files);
      if (!files.length) { resolve(null); return; }
      const fileContents = {};
      for (const file of files) {
        fileContents[file.name] = await file.text();
      }
      resolve({ files: fileContents, _browser: true });
    };
    input.click();
  });
}

// ===== 备份目录设置 =====
async function loadBackupConfig() {
  try {
    const res = await api('GET', '/api/admin/backup-config');
    if (res.ok) {
      loadBackupConfigInline(res);
    }
  } catch (e) {
    console.warn('加载备份目录配置失败:', e);
  }
}

function loadBackupConfigInline(res) {
  // 填充输入框
  const input = document.getElementById('backup-dir-input-path');
  const clearWrap = document.getElementById('backup-dir-clear-wrap');
  if (input) {
    if (res.backup_dir) {
      input.value = res.backup_dir;
      input.placeholder = '修改路径或留空恢复默认';
    } else {
      input.value = '';
      input.placeholder = '/path/to/backup 或留空使用默认';
    }
    if (clearWrap) {
      clearWrap.style.display = res.backup_dir ? '' : 'none';
    }
  }
}

// 在数据管理弹窗中显示备份目录状态
function updateBackupDirDisplay(backupDir, backupDirLabel, dataDir) {
  // 数据管理弹窗
  const mgmtDisplay = document.getElementById('datamgmt-backup-dir-display');
  if (mgmtDisplay) {
    if (backupDir) {
      mgmtDisplay.textContent = `当前: ${backupDirLabel || backupDir}`;
    } else {
      const displayText = dataDir ? `当前: 默认 (${dataDir}/backup/)` : '当前: 默认 (backup/ 目录)';
      mgmtDisplay.textContent = displayText;
    }
  }
}

// 点击文件夹图标 → 选择目录（macOS native 用 Swift bridge，Docker/Web 环境用 prompt）
function pickBackupDirectory() {
  return new Promise(resolve => {
    // 尝试 macOS 原生 App 的 Swift bridge
    const hasSwiftBridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pickBackupDir;
    if (hasSwiftBridge) {
      window.__backupBackupDirChosen = dir => {
        window.__backupBackupDirChosen = null;
        if (dir && dir.path) {
          resolve(dir.path);
        } else {
          resolve(null);
        }
      };
      window.webkit.messageHandlers.pickBackupDir.postMessage('pick');
      return;
    }

    // Docker / Web 浏览器环境: 用 prompt 让用户输入路径
    const resPromise = api('GET', '/api/admin/backup-config');
    resPromise.then(res => {
      const defaultPath = `${res.data_dir || '/data'}/backup/`;
      const currentPath = document.getElementById('backup-dir-input-path')?.value?.trim() || '';
      const inputPath = prompt('输入备份目录路径（默认）:', currentPath || defaultPath);
      if (inputPath !== null && inputPath.trim()) {
        resolve(inputPath.trim());
      } else {
        resolve(null);
      }
    }).catch(() => {
      // API 失败时 fallback 到简单 prompt
      const inputPath = prompt('输入备份目录路径（例如 /data/backup）:', '/data/backup/');
      if (inputPath !== null && inputPath.trim()) {
        resolve(inputPath.trim());
      } else {
        resolve(null);
      }
    });
  });
}

// 保存备份目录配置（内联按钮）
async function saveBackupDirInline() {
  const input = document.getElementById('backup-dir-input-path');
  const path = input ? input.value.trim() : '';
  const label = prompt('显示名称（可选，留空则使用路径名）:', '');

  if (path === '') {
    // 空路径 = 清除设置，恢复默认
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: null });
    if (res.ok) {
      showAlert('✅ 已恢复默认备份路径', 'success');
      loadBackupConfigInline(res);
      updateBackupDirDisplay(null, null, res.data_dir);
    } else {
      showAlert('清除失败: ' + (res.error || '未知错误'), 'error');
    }
  } else {
    const displayName = label && label.trim() ? label.trim() : path;
    const res = await api('PUT', '/api/admin/backup-config', {
      backup_dir: path,
      backup_dir_label: displayName,
    });
    if (res.ok) {
      showAlert(`✅ 备份目录已设置为: ${path}`, 'success');
      loadBackupConfigInline(res);
      updateBackupDirDisplay(res.backup_dir, res.backup_dir_label, res.data_dir);
    } else {
      showAlert('设置失败: ' + (res.error || '未知错误'), 'error');
    }
  }
}

// 清除备份目录设置（内联按钮）
async function clearBackupDirectoryInline() {
  const ok = await showModal({
    icon: '⚠️',
    iconKind: 'warn',
    title: '确认清除备份目录设置？',
    body: '清除后将恢复为默认行为（备份到数据目录的 backup/ 子目录）。',
    confirmText: '确认清除',
    cancelText: '取消',
    confirmKind: 'danger',
  });
  if (!ok) return;
  const input = document.getElementById('backup-dir-input-path');
  if (input) input.value = '';
  const res = await api('PUT', '/api/admin/backup-config', { backup_dir: null });
  if (res.ok) {
    showAlert('✅ 已清除备份目录设置，恢复默认', 'success');
    loadBackupConfigInline(res);
    updateBackupDirDisplay(null, null, res.data_dir);
  } else {
    showAlert('清除失败: ' + (res.error || '未知错误'), 'error');
  }
}

// 旧版：打开备份目录选择弹窗（已废弃，保留以兼容旧代码）
async function pickBackupDirectory() {
  // 此函数已被内联 UI 取代，但保留向下兼容
  await saveBackupDirInline();
}

async function clearBackupDirectory() {
  const ok = await showModal({
    icon: '⚠️',
    iconKind: 'warn',
    title: '确认清除备份目录设置？',
    body: '清除后将恢复为默认行为（备份到数据目录的 backup/ 子目录）。',
    confirmText: '确认清除',
    cancelText: '取消',
    confirmKind: 'danger',
  });
  if (!ok) return;
  const res = await api('PUT', '/api/admin/backup-config', { backup_dir: null });
  if (res.ok) {
    showAlert('✅ 已清除备份目录设置', 'success');
    updateBackupDirDisplay(null, null, res.data_dir);
  } else {
    showAlert('清除失败: ' + (res.error || '未知错误'), 'error');
  }
}

async function saveBackupDirConfig(path, label) {
  const res = await api('PUT', '/api/admin/backup-config', {
    backup_dir: path,
    backup_dir_label: label,
  });
  if (res.ok) {
    showAlert(`✅ 备份目录已设置为: ${path}`, 'success');
    updateBackupDirDisplay(res.backup_dir, res.backup_dir_label, res.data_dir);
  } else {
    showAlert('设置失败: ' + (res.error || '未知错误'), 'error');
  }
}

async function adminBackup() {
  showAlert('正在备份数据…', 'info');
  const res = await api('POST', '/api/backup');
  if (!res.ok) {
    showAlert('备份失败: ' + (res.error || '未知错误'), 'error');
    return;
  }
  showAlert('✅ 数据已备份到 ' + (res.backup_dir || 'backup/'), 'success');
  // 备份成功后刷新列表
  setTimeout(() => loadBackupList(), 500);
}

async function adminRestore() {
  let dir = await adminPickBackupDir();
  if (dir && dir._browser) {
    // 浏览器: 上传文件
    const ok = await showModal({
      icon: '⚠️',
      iconKind: 'warn',
      title: '确认上传文件覆盖数据？',
      body: '确认上传选中的 JSON 文件覆盖当前数据？恢复前系统会自动备份。',
      confirmText: '确认上传',
      cancelText: '取消',
      confirmKind: 'danger',
    });
    if (!ok) return;
    const res = await api('POST', '/api/upload', { files: dir.files });
    if (res.ok) {
      showAlert(`✅ 已上传 ${res.uploaded.length} 个文件`, 'success');
      closeAdminPanel();
      refreshAll && refreshAll();
    } else {
      showAlert('上传失败: ' + (res.error || '未知错误'), 'error');
    }
    return;
  }
  if (!dir) {
    // 浏览器/Docker 环境没有 Swift bridge: 提示用浏览器选择文件
    dir = await browserPickFiles();
    if (!dir) { showAlert('未选择文件', 'info'); return; }
    const ok = await showModal({
      icon: '⚠️',
      iconKind: 'warn',
      title: '确认上传文件覆盖数据？',
      body: '确认上传选中的 JSON 文件覆盖当前数据？恢复前系统会自动备份。',
      confirmText: '确认上传',
      cancelText: '取消',
      confirmKind: 'danger',
    });
    if (!ok) return;
  }
  if (dir._browser) {
    const res = await api('POST', '/api/upload', { files: dir.files });
    if (res.ok) {
      showAlert(`✅ 已上传 ${res.uploaded.length} 个文件`, 'success');
      closeAdminPanel();
      refreshAll && refreshAll();
    } else {
      showAlert('上传失败: ' + (res.error || '未知错误'), 'error');
    }
    return;
  }
  // 原生环境: 用目录路径恢复
  const ok2 = await showModal({
    icon: '⚠️',
    iconKind: 'warn',
    title: '确认恢复数据？',
    body: `确认从 <b>${dir}</b> 恢复数据？<br>恢复前会自动备份当前数据。`,
    confirmText: '确认恢复',
    cancelText: '取消',
    confirmKind: 'danger',
  });
  if (!ok2) return;
  const res = await api('POST', '/api/restore', { source_dir: dir });
  if (!res.ok) { showAlert('恢复失败: ' + (res.error || '未知错误'), 'error'); return; }
  showAlert(`✅ 已恢复 ${res.restored.length} 个文件; 已备份到 ${res.pre_backup}`, 'success');
  closeAdminPanel();
  refreshAll && refreshAll();
}

// ===== 权限管理 =====
function loadRolesInfo() {
  const tbody = document.getElementById('roles-table-body');
  if (!tbody) return;
  const permConfig = [
    { role: 'admin', name: '管理员', read: true, edit: true, delete: true, manage: true },
    { role: 'supervisor', name: '主管', read: true, edit: true, delete: true, manage: false },
    { role: 'employee', name: '员工', read: true, edit: true, delete: false, manage: false },
  ];
  tbody.innerHTML = permConfig.map(p => `
    <tr style="border-bottom:1px solid var(--border);">
      <td style="padding:6px 8px;font-weight:510;">${p.name}</td>
      <td style="padding:6px 8px;text-align:center;">${p.read ? '✅' : '❌'}</td>
      <td style="padding:6px 8px;text-align:center;">${p.edit ? '✅' : '❌'}</td>
      <td style="padding:6px 8px;text-align:center;">${p.delete ? '✅' : '❌'}</td>
      <td style="padding:6px 8px;text-align:center;">${p.manage ? '✅' : '❌'}</td>
    </tr>
  `).join('');
}

// ===== 通用工具 =====
function getAuthParam() {
  return ADMIN_TOKEN ? '?token=' + encodeURIComponent(ADMIN_TOKEN) : '';
}

// 页面加载时初始化
initAuth();