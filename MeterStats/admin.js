// ===== 后台管理: 全局会话 =====
let ADMIN_TOKEN = localStorage.getItem('meter_admin_token');
let ADMIN_USER = null;

const ROLE_NAMES = { admin: '管理员', supervisor: '主管', employee: '员工' };

// 权限: 管理员和主管有删除权限, 员工只有录入和编辑
const ADMIN_DELETE_ROLES = new Set(['admin', 'supervisor']);
const ADMIN_MANAGE_ROLES = new Set(['admin']);

// ===== 初始化: 有token则验证, 否则显示登录页 =====
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
  } else {
    // 无 token → 显示登录页
    const loginPage = document.getElementById('login-page');
    if (loginPage) loginPage.style.display = 'flex';
  }
}

// 验证通过后: 隐藏登录页, 显示主应用
function setLoggedIn(user) {
  ADMIN_USER = user;
  document.getElementById('logout-btn').style.display = '';
  document.getElementById('login-page').style.display = 'none';
  // admin-user-info was in the removed popup modal
}

// 无权限时: 显示登录页
function clearAuth() {
  ADMIN_TOKEN = null;
  ADMIN_USER = null;
  localStorage.removeItem('meter_admin_token');
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
    if (window.renderAll) window.renderAll();
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
  // 已登录 → 打开用户管理独立页面
  switchSettingsPage('users');
}

// 弹窗已删除，不再需要关闭
function closeAdminPanel() {}

// 切换后台页面（独立section）
function switchAdminPage(page) {
  switchSettingsPage(page);
}

// ===== 用户管理 =====
function loadAdminUsers() {
  fetch('/api/admin/users' + getAuthParam())
    .then(r => r.json()).then(res => {
      const tbody = document.getElementById('users-table-body');
      if (!tbody) return;
      const users = res || [];
      tbody.innerHTML = users.map(u => `
        <tr>
          <td>${u.username}</td>
          <td>${u.name}</td>
          <td>${ROLE_NAMES[u.role] || u.role}</td>
          <td>${u.enabled ? '✅ 启用' : '❌ 禁用'}</td>
          <td class="ta-right">
            <button class="btn btn-primary btn-xs" onclick="editAdminUser(${u.id},'${u.username}')">编辑</button>
            ${ADMIN_DELETE_ROLES.has(ADMIN_USER?.role) && u.id !== ADMIN_USER?.id ? `<button class="btn btn-danger btn-xs" onclick="deleteAdminUser(${u.id})">删除</button>` : ''}
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
          <div class="meter-cell">
            <div class="meter-cell-title">${icons[k]} ${m.label || k}</div>
            <div class="meter-cell-row">
              <label>倍率</label>
              <input type="number" class="meter-input" data-key="${k}" data-field="multiplier" value="${m.multiplier || 1}">
            </div>
            <div class="meter-cell-row">
              <label>表名</label>
              <input type="text" class="meter-input" data-key="${k}" data-field="label" value="${m.label || ''}">
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

// 加载备份目录配置
function loadBackupDirConfig() {
  fetch('/api/admin/backup-config' + getAuthParam())
    .then(r => r.json()).then(res => {
      const display = document.getElementById('backup-dir-display');
      const pickBtn = document.getElementById('pick-backup-dir-btn');
      const resetBtn = document.getElementById('reset-backup-dir-btn');
      if (!display) return;

      if (res.customizable === false) {
        display.textContent = '🔒 ' + (res.backup_dir || res.data_dir);
        if (pickBtn) pickBtn.style.display = 'none';
        if (resetBtn) resetBtn.style.display = 'none';
      } else {
        const dir = res.backup_dir || '默认: ' + res.data_dir + '/backup';
        display.textContent = dir;
        if (pickBtn) pickBtn.style.display = '';
        if (resetBtn) resetBtn.style.display = '';
      }
    }).catch(() => {});
}

// 选择备份目录
async function setBackupDir() {
  const dir = await adminPickBackupDir();
  if (!dir) {
    showToast('未选择目录', 'info');
    return;
  }
  try {
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: dir });
    if (!res.ok) {
      showToast('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showToast('✅ 备份目录已更新', 'success');
    loadBackupDirConfig();
  } catch (e) {
    showToast('保存失败: ' + e.message, 'error');
  }
}

// 恢复默认备份目录
async function resetBackupDir() {
  try {
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: null });
    if (!res.ok) {
      showToast('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showToast('✅ 已恢复默认备份目录', 'success');
    loadBackupDirConfig();
  } catch (e) {
    showToast('保存失败: ' + e.message, 'error');
  }
}

function loadBackupStatus() {
  fetch('/api/admin/backup-status' + getAuthParam())
    .then(r => r.json()).then(res => {
      const cb = document.getElementById('admin-auto-backup-toggle');
      if (cb) {
        cb.checked = res.auto_backup !== false;
        // 避免重复绑定事件
        if (!cb._backupToggleBound) {
          cb._backupToggleBound = true;
          cb.addEventListener('change', e => {
            fetch('/api/admin/auto-backup' + getAuthParam(), {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ enabled: e.target.checked }),
            }).then(() => showToast(e.target.checked ? '自动备份已开启' : '自动备份已关闭', 'info'));
          });
        }
      }
      const countEl = document.getElementById('backup-count');
      if (countEl) countEl.textContent = '当前备份数: ' + (res.backup_count || 0) + ' 个';
      // 填充保留数量输入框
      const retention = res.retention_count || 5;
      const adminRet = document.getElementById('admin-backup-retention');
      if (adminRet) adminRet.value = retention;
      const dmRet = document.getElementById('datamgmt-backup-retention');
      if (dmRet) dmRet.value = retention;
      // 加载备份目录配置
      loadBackupDirConfig();
      // 加载图片目录配置
      if (typeof loadImageDirConfig === 'function') loadImageDirConfig();
      // 渲染备份列表
      renderBackupList(res.backups || []);
    }).catch(() => {});
}

function loadBackupList() {
  loadBackupStatus();
}

// 保存备份保留数量
function saveBackupRetention() {
  const val = parseInt(document.getElementById('admin-backup-retention').value || document.getElementById('datamgmt-backup-retention').value, 10);
  if (!val || val < 1) {
    showAlert('保留数量必须 ≥ 1', 'error');
    return;
  }
  fetch('/api/admin/backup-retention' + getAuthParam(), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ retention_count: val }),
  }).then(r => r.json()).then(res => {
    if (!res.ok) {
      showAlert('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showAlert('已保存: 保留 ' + val + ' 天', 'success');
    // 同步更新两个输入框
    const adminRet = document.getElementById('admin-backup-retention');
    if (adminRet) adminRet.value = val;
    const dmRet = document.getElementById('datamgmt-backup-retention');
    if (dmRet) dmRet.value = val;
  }).catch(e => showAlert('保存失败: ' + e.message, 'error'));
}

function backupTypeTag(b) {
  // 手动备份 meter-backup- 前缀 / 自动备份 auto-bak- 前缀,列表明确标注
  const isAuto = b.type === 'auto' || (b.zip_name || '').startsWith('auto-bak-');
  const isManual = b.type === 'manual' || (b.zip_name || '').startsWith('meter-backup-');
  if (isAuto) return '<span class="b-type b-type-auto">自动</span>';
  if (isManual) return '<span class="b-type b-type-manual">手动</span>';
  return '';
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
        const isZip = b.format === 'zip' || b.zip_name;
        const fmtLabel = b.format === 'dir' ? '（旧格式）' : '';
        html += `<div class="backup-item">
          <div>
            <span class="b-name">${b.name}</span>
            ${backupTypeTag(b)}
            <span class="b-meta">${fmtLabel}${b.file_count} 文件 · ${sizeStr}</span>
            <span class="b-meta">${b.created_at}</span>
          </div>
          <div class="b-actions">
            ${isZip ? `<button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.zip_name}')">⬇️ 下载</button>` : '<span style="font-size:11px;color:var(--text-muted);">旧格式</span>'}
            <button class="btn btn-danger btn-xs" onclick="restoreBackup('${b.zip_name}')">↩️ 恢复</button>
            ${isZip ? `<button class="btn btn-danger btn-xs" onclick="deleteBackup('${b.zip_name}')">🗑️ 删除</button>` : ''}
          </div>
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
        const isZip = b.format === 'zip' || b.zip_name;
        const fmtLabel = b.format === 'dir' ? '（旧格式）' : '';
        html += `<div class="backup-item">
          <div>
            <span class="b-name">${b.name}</span>
            ${backupTypeTag(b)}
            <span class="b-meta">${fmtLabel}${b.file_count} 文件 · ${sizeStr}</span>
          </div>
          <div class="b-actions">
            ${isZip ? `<button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.zip_name}')">⬇️ 下载</button>` : '<span style="font-size:11px;color:var(--text-muted);">旧格式</span>'}
            <button class="btn btn-danger btn-xs" onclick="restoreBackup('${b.zip_name}')">↩️ 恢复</button>
            ${isZip ? `<button class="btn btn-danger btn-xs" onclick="deleteBackup('${b.zip_name}')">🗑️ 删除</button>` : ''}
          </div>
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

function downloadBackup(zipName) {
  // 下载备份 zip（使用 zip_name 参数）
  const token = localStorage.getItem('meter_token');
  const url = `/api/admin/backup-download?zip_name=${encodeURIComponent(zipName)}${token ? '&token=' + encodeURIComponent(token) : ''}`;
  const a = document.createElement('a');
  a.href = url;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// 删除备份
async function deleteBackup(zipName) {
  const ok = await showModal({
    icon: '🗑️',
    iconKind: 'warn',
    title: '确认删除备份？',
    body: `将从备份目录中永久删除 <b>${zipName}</b>，此操作不可撤销。`,
    confirmText: '确认删除',
    cancelText: '取消',
    confirmKind: 'danger',
  });
  if (!ok) return;

  const token = localStorage.getItem('meter_token');
  const url = `/api/admin/backup-delete?zip_name=${encodeURIComponent(zipName)}${token ? '&token=' + encodeURIComponent(token) : ''}`;
  try {
    const res = await fetch(url, { method: 'GET' });
    const data = await res.json();
    if (!data.ok) {
      showAlert('删除失败: ' + (data.error || '未知错误'), 'error');
      return;
    }
    showAlert('✅ 已删除备份', 'success');
    // 刷新备份列表
    setTimeout(() => loadBackupList(), 300);
  } catch (e) {
    showAlert('删除失败: ' + e.message, 'error');
  }
}

// 统一备份恢复（后台管理和数据管理弹窗共用）
async function restoreBackup(zipName) {
  showAlert('正在下载备份文件…', 'info');
  const token = localStorage.getItem('meter_token');
  const url = `/api/admin/backup-download?zip_name=${encodeURIComponent(zipName)}${token ? '&token=' + encodeURIComponent(token) : ''}`;

  try {
    const response = await fetch(url);
    if (!response.ok) {
      showAlert('下载失败', 'error');
      return;
    }
    const blob = await response.blob();
    const file = new File([blob], zipName, { type: 'application/zip' });

    const ok = await showModal({
      icon: '⚠️',
      iconKind: 'warn',
      title: '确认恢复数据？',
      body: `将从 <b>${zipName}</b> 恢复数据？<br>恢复前系统会自动备份当前数据，可随时回滚。`,
      confirmText: '确认恢复',
      cancelText: '取消',
      confirmKind: 'danger',
    });
    if (!ok) return;

    const formData = new FormData();
    formData.append('zip_file', file);

    const res = await fetch('/api/admin/restore-upload' + getAuthParam(), {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();

    if (!data.ok) {
      showAlert('恢复失败: ' + (data.error || '未知错误'), 'error');
      return;
    }

    showAlert('✅ 已恢复 ' + data.restored.length + ' 个文件', 'success');
    closeAdminPanel();
    if (window.renderAll) window.renderAll();
  } catch (e) {
    showAlert('恢复失败: ' + e.message, 'error');
  }
}

// 从备份列表恢复（下载 ZIP 到本地后恢复，保留原函数用于向后兼容）
async function adminRestoreFromZip(zipName) {
  // 先下载到本地
  showAlert('正在下载备份文件…', 'info');
  const token = localStorage.getItem('meter_token');
  const url = `/api/admin/backup-download?zip_name=${encodeURIComponent(zipName)}${token ? '&token=' + encodeURIComponent(token) : ''}`;

  const btn = document.querySelector('#admin-page-data button[onclick^="adminRestore"]');
  const original = btn ? btn.textContent : '恢复数据';
  if (btn) { btn.textContent = '⏳ 恢复中…'; btn.disabled = true; }

  try {
    const response = await fetch(url);
    if (!response.ok) {
      showAlert('下载失败', 'error');
      return;
    }
    const blob = await response.blob();
    const file = new File([blob], zipName, { type: 'application/zip' });

    // 确认恢复
    const ok = await showModal({
      icon: '⚠️',
      iconKind: 'warn',
      title: '确认恢复数据？',
      body: `将从 <b>${zipName}</b> 恢复数据？<br>恢复前系统会自动备份当前数据，可随时回滚。`,
      confirmText: '确认恢复',
      cancelText: '取消',
      confirmKind: 'danger',
    });
    if (!ok) return;

    // 上传并恢复
    const formData = new FormData();
    formData.append('zip_file', file);

    const res = await fetch('/api/admin/restore-upload' + getAuthParam(), {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();

    if (!data.ok) {
      showAlert('恢复失败: ' + (data.error || '未知错误'), 'error');
      return;
    }

    showAlert('✅ 已恢复 ' + data.restored.length + ' 个文件', 'success');
    closeAdminPanel();
    if (window.renderAll) window.renderAll();
  } catch (e) {
    showAlert('恢复失败: ' + e.message, 'error');
  } finally {
    if (btn) { btn.textContent = original; btn.disabled = false; }
  }
}

// 数据管理弹窗中从备份列表恢复
async function datamgmtRestoreFromZip(zipName) {
  showAlert('正在下载备份文件…', 'info');
  const token = localStorage.getItem('meter_token');
  const url = `/api/admin/backup-download?zip_name=${encodeURIComponent(zipName)}${token ? '&token=' + encodeURIComponent(token) : ''}`;

  const btn = document.getElementById('datamgmt-restore-btn');
  const original = btn ? btn.textContent : '恢复数据';
  if (btn) { btn.textContent = '⏳ 恢复中…'; btn.disabled = true; }

  try {
    const response = await fetch(url);
    if (!response.ok) {
      showAlert('下载失败', 'error');
      return;
    }
    const blob = await response.blob();
    const file = new File([blob], zipName, { type: 'application/zip' });

    const ok = await showModal({
      icon: '⚠️',
      iconKind: 'warn',
      title: '确认恢复数据？',
      body: `将从 <b>${zipName}</b> 恢复数据？<br>恢复前系统会自动备份当前数据，可随时回滚。`,
      confirmText: '确认恢复',
      cancelText: '取消',
      confirmKind: 'danger',
    });
    if (!ok) return;

    const formData = new FormData();
    formData.append('zip_file', file);

    const res = await fetch('/api/admin/restore-upload' + getAuthParam(), {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();

    if (!data.ok) {
      showAlert('恢复失败: ' + (data.error || '未知错误'), 'error');
      return;
    }

    showAlert('✅ 已恢复 ' + data.restored.length + ' 个文件', 'success');
    closeAdminPanel();
    if (window.renderAll) window.renderAll();
  } catch (e) {
    showAlert('恢复失败: ' + e.message, 'error');
  } finally {
    if (btn) { btn.textContent = original; btn.disabled = false; }
  }
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

async function adminBackup() {
  showAlert('正在备份数据…', 'info');
  const res = await api('POST', '/api/backup');
  if (!res.ok) {
    showAlert('备份失败: ' + (res.error || '未知错误'), 'error');
    return;
  }
  showAlert('✅ 数据已打包备份: ' + (res.backup_name || '成功'), 'success');
  // 备份成功后刷新列表
  setTimeout(() => loadBackupList(), 500);
}

async function adminRestore() {
  // 弹出文件选择器(三端统一:macOS 用 Swift 桥,web/docker 用 <input>)
  const zipFile = await pickZipFile();
  if (!zipFile) {
    showAlert('未选择文件', 'info');
    return;
  }

  // 确认恢复
  const ok = await showModal({
    icon: '⚠️',
    iconKind: 'warn',
    title: '确认恢复数据？',
    body: `将从 <b>${zipFile.name}</b> 恢复数据？<br>恢复前系统会自动备份当前数据，可随时回滚。`,
    confirmText: '确认恢复',
    cancelText: '取消',
    confirmKind: 'danger',
  });
  if (!ok) return;

  const btn = document.querySelector('#admin-page-data button[onclick="adminRestore()"]');
  const original = btn ? btn.textContent : '恢复数据';
  if (btn) { btn.textContent = '⏳ 恢复中…'; btn.disabled = true; }

  try {
    // base64 zip → 转成 Blob → 用 multipart/form-data 上传(后端 /api/admin/restore-upload 期望 File/Blob)
    const byteChars = atob(zipFile.content);
    const bytes = new Uint8Array(byteChars.length);
    for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'application/zip' });
    const file = new File([blob], zipFile.name, { type: 'application/zip' });

    const formData = new FormData();
    formData.append('zip_file', file);

    const res = await fetch('/api/admin/restore-upload' + getAuthParam(), {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();

    if (!data.ok) {
      showAlert('恢复失败: ' + (data.error || '未知错误'), 'error');
      return;
    }

    showAlert('✅ 已恢复 ' + data.restored.length + ' 个文件', 'success');
    closeAdminPanel();
    if (window.renderAll) window.renderAll();
  } catch (e) {
    showAlert('恢复失败: ' + e.message, 'error');
  } finally {
    if (btn) { btn.textContent = original; btn.disabled = false; }
  }
}

// 选择 ZIP 文件(三端统一)
// - macOS 原生 App: WKWebView + Swift 桥(macOSPickFile)弹 NSOpenPanel 选 zip
// - Web/Docker: 标准 <input type="file">
// 返回 Promise<{name, content} | null>;失败/取消 resolve(null)
function pickZipFile() {
  return new Promise(resolve => {
    // macOS App: 通过 Swift 桥弹原生文件选择器(避免 WKWebView input.click 静默失败)
    const hasSwiftBridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.macOSPickFile;
    if (hasSwiftBridge) {
      window.__macOSFileChosen = info => {
        window.__macOSFileChosen = null;
        resolve(info);  // {name, content: base64} 或 null
      };
      window.webkit.messageHandlers.macOSPickFile.postMessage({ accept: '.zip' });
      return;
    }
    // Web/Docker: 标准 <input type="file">
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.zip';
    input.style.display = 'none';
    document.body.appendChild(input);
    const cleanup = () => {
      if (input.parentNode) input.parentNode.removeChild(input);
    };
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      cleanup();
      if (!file) { resolve(null); return; }
      // 读为 ArrayBuffer → base64,与 macOS 桥返回的格式保持一致
      const reader = new FileReader();
      reader.onload = () => {
        const bytes = new Uint8Array(reader.result);
        let bin = '';
        for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
        resolve({ name: file.name, content: btoa(bin) });
      };
      reader.onerror = () => resolve(null);
      reader.readAsArrayBuffer(file);
    });
    input.addEventListener('cancel', () => { cleanup(); resolve(null); });
    input.click();
  });
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
    <tr>
      <td style="font-weight:510;">${p.name}</td>
      <td class="ta-center">${p.read ? '✅' : '—'}</td>
      <td class="ta-center">${p.edit ? '✅' : '—'}</td>
      <td class="ta-center">${p.delete ? '✅' : '—'}</td>
      <td class="ta-center">${p.manage ? '✅' : '—'}</td>
    </tr>
  `).join('');
}

// ===== 通用工具 =====
function getAuthParam() {
  return ADMIN_TOKEN ? '?token=' + encodeURIComponent(ADMIN_TOKEN) : '';
}

// 页面加载时初始化
initAuth();
// ===== CSV 数据导入 =====
async function doImport() {
  const btn = document.getElementById('import-btn');
  const resultEl = document.getElementById('import-result');
  const fileInput = document.getElementById('import-file');
  const model = document.getElementById('import-model').value;
  const token = localStorage.getItem('meter_token');

  if (!fileInput.files || fileInput.files.length === 0) {
    resultEl.innerHTML = '<span style="color:#ef4444;">⚠️ 请选择 CSV 文件</span>';
    return;
  }
  if (!token) {
    resultEl.innerHTML = '<span style="color:#ef4444;">⚠️ 未登录</span>';
    return;
  }

  btn.disabled = true;
  btn.textContent = '⏳ 导入中...';
  resultEl.innerHTML = '⏳ 正在解析...';

  const formData = new FormData();
  formData.append('model', model);
  formData.append('file', fileInput.files[0]);

  try {
    const resp = await fetch('/api/import', {
      method: 'POST',
      headers: { 'X-Auth-Token': token },
      body: formData,
    });
    const data = await resp.json();
    btn.disabled = false;
    btn.textContent = '📤 导入 CSV';

    if (data.ok) {
      let html = `<span style="color:#22c55e;">✅ 成功导入 ${data.count} 条记录</span>`;
      if (data.failed > 0) {
        html += `<br><span style="color:#f59e0b;">⚠️ ${data.failed} 条错误:</span>`;
        if (data.errors) {
          data.errors.forEach((e, i) => {
            html += `<br><span style="color:#f59e0b;">  ${i+1}. ${escapeHtml(e)}</span>`;
          });
        }
      }
      resultEl.innerHTML = html;
      // 刷新相关数据
      loadBackupList();
    } else {
      resultEl.innerHTML = `<span style="color:#ef4444;">❌ ${escapeHtml(data.error || '导入失败')}</span>`;
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = '📤 导入 CSV';
    resultEl.innerHTML = `<span style="color:#ef4444;">❌ 网络错误: ${escapeHtml(err.message)}</span>`;
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
