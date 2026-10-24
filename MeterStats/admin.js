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
    // Store in localStorage so Api.* can use it
    localStorage.setItem('token', ADMIN_TOKEN);
    // 验证会话
    Api.system.me().then(function(res) {
        if (res.user) {
          setLoggedIn(res.user);
        } else {
          clearAuth();
        }
      }).catch(function() { clearAuth(); });
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
async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  errEl.style.display = 'none';

  // 先检查后端是否就绪（最多重试 15 次，每次间隔 1 秒，总超时 15 秒）
  // 使用相对路径 /api/health，避免 WKWebView 中绝对路径被拒绝
  let retries = 15;
  while (retries > 0) {
    try {
      const resp = await fetch('/api/health');
      if (resp.ok) break; // 后端已就绪
    } catch {}
    retries--;
    if (retries > 0) {
      errEl.textContent = '后端服务启动中，请稍候... (' + (15 - (15 - retries)) + '/15)';
      errEl.style.display = 'block';
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }

  try {
    const res = await Api.system.login(username, password);
    ADMIN_TOKEN = res.token;
    localStorage.setItem('token', ADMIN_TOKEN);
    setLoggedIn(res.user);
    renderAll();
  } catch (e) {
    // 如果健康检查失败，显示更友好的错误提示
    if (retries === 0) {
      errEl.textContent = '后端服务未启动，请重启 App';
    } else {
      errEl.textContent = '网络错误: ' + e.message;
    }
    errEl.style.display = 'block';
  }
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
    Api.system.logout().catch(function(){});
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
  Api.admin.users().then(function(users) {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;
    const usersList = users || [];

    // ---- 概览卡 ----
    const statEl = document.getElementById('users-stat-grid');
    if (statEl) {
      const byRole = { admin: 0, supervisor: 0, employee: 0 };
      usersList.forEach(u => { if (byRole[u.role] != null) byRole[u.role]++; });
      const card = (label, value, unit, sub) =>
        '<div class="trend-stat"><div class="trend-stat-label">' + label + '</div>' +
        '<div class="trend-stat-value">' + value + (unit ? '<small>' + unit + '</small>' : '') + '</div>' +
        '<div class="trend-stat-sub">' + sub + '</div></div>';
      statEl.innerHTML =
        card('总用户', usersList.length, '', usersList.length + ' 个账号') +
        card('管理员', byRole.admin, '', '全部权限') +
        card('主管', byRole.supervisor, '', '可编辑') +
        card('员工', byRole.employee, '', '仅录入');
    }

    tbody.innerHTML = usersList.map(u => `
        <tr>
          <td>${u.username}</td>
          <td>${u.name}</td>
          <td><span class="role-badge role-${u.role}">${ROLE_NAMES[u.role] || u.role}</span></td>
          <td>${u.enabled
              ? '<span class="status-dot on"></span>启用'
              : '<span class="status-dot off"></span>禁用'}</td>
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

  Api.admin.createUser({ username: username, password: password, name: name, role: role }).then(function(res) {
    if (!res.ok) { showAlert('添加失败: ' + (res.error || '未知错误'), 'error'); return; }
    showAlert('用户已添加: ' + username, 'success');
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-name').value = '';
    loadAdminUsers();
  }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
}

function editAdminUser(uid, oldUsername) {
  Api.admin.users().then(function(users) {
    const found = users.find(u => u.id == uid);
    if (!found) { showAlert('用户不存在', 'error'); return; }
    const u = found;
    const newName = prompt('显示名', u.name);
    if (newName === null) return;
    const newRole = prompt('角色 (admin/supervisor/employee)', u.role);
    if (newRole === null) return;
    const newPassword = prompt('新密码 (留空不修改)', '');

    const body = { name: newName, role: newRole };
    if (newPassword && newPassword.trim()) body.password = newPassword.trim();

    Api.admin.updateUser(uid, body).then(function(res2) {
      if (!res2.ok) { showAlert('编辑失败: ' + (res2.error || '未知错误'), 'error'); return; }
      showAlert('用户已更新', 'success');
      loadAdminUsers();
    }).catch(function(e) { showAlert('网络错误: ' + e.message, 'error'); });
  }).catch(function(e) { showAlert('加载用户失败: ' + e.message, 'error'); });
}

function deleteAdminUser(uid) {
  if (!confirm('确认删除此用户? 此操作不可恢复。')) return;
  Api.admin.deleteUser(uid).then(function(res) {
      if (!res.ok) { showAlert('删除失败: ' + (res.error || '未知错误'), 'error'); return; }
      showAlert('用户已删除', 'success');
      loadAdminUsers();
    }).catch(function(e) { showAlert('网络错误: ' + e.message, 'error'); });
}

// ===== 电表设置 =====
function loadMeterSettings() {
  Api.admin.meterSettings().then(function(res) {
      const form = document.getElementById('meter-settings-form');
      if (!form) return;
      const meter = res.meter || {};
      const config = res.config || {};

      // 填充配置
      const elecPrice = document.getElementById('config-elec-price');
      const waterPrice = document.getElementById('config-water-price');
      const mainMult = document.getElementById('config-main-mult');
      const subMult = document.getElementById('config-sub-mult');
      if (elecPrice) elecPrice.value = config.electricity_price || 0.9;
      if (waterPrice) waterPrice.value = config.water_price || 4.5;
      if (mainMult) mainMult.value = config.main_mult != null ? config.main_mult : 50;
      if (subMult) subMult.value = config.sub_mult != null ? config.sub_mult : 40;

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
    }).catch(function(e) { showAlert('加载电表设置失败', 'error'); });
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

  // 后端是整体替换 config，必须把全部字段都带上
  const numOr = function(id, fallback) {
    const el = document.getElementById(id);
    const v = el ? parseFloat(el.value) : NaN;
    return isNaN(v) ? fallback : v;
  };
  const config = {
    electricity_price: numOr('config-elec-price', 0.9),
    water_price: numOr('config-water-price', 4.5),
    main_mult: Math.round(numOr('config-main-mult', 50)),
    sub_mult: Math.round(numOr('config-sub-mult', 40)),
  };

  Api.admin.saveMeterSettings({ meter, config }).then(function(res) {
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
  Api.admin.backupConfig().then(function(res) {
      const display = document.getElementById('backup-dir-display');
      const pickBtn = document.getElementById('pick-backup-dir-btn');
      const resetBtn = document.getElementById('reset-backup-dir-btn');
      if (!display) return;

      if (res.customizable === false) {
        display.textContent = '🔒 ' + (res.backup_dir || res.data_dir);
        if (pickBtn) pickBtn.style.display = 'none';
        if (resetBtn) resetBtn.style.display = 'none';
      } else {
        const dir = res.backup_dir || '';
        display.textContent = dir ? ('📁 ' + dir) : ('📁 默认: ' + res.data_dir + '/backup');
        // 把当前目录填进输入框，用户可直接改
        const inp = document.getElementById('backup-dir-input');
        if (inp) inp.value = dir;
        if (pickBtn) pickBtn.style.display = '';
        if (resetBtn) resetBtn.style.display = '';
      }
    }).catch(function() {});
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
  Api.admin.backupStatus().then(function(res) {
      const cb = document.getElementById('admin-auto-backup-toggle');
      if (cb) {
        cb.checked = res.auto_backup !== false;
        // 避免重复绑定事件
        if (!cb._backupToggleBound) {
          cb._backupToggleBound = true;
          cb.addEventListener('change', e => {
            Api.admin.setAutoBackup(e.target.checked).then(() => showToast(e.target.checked ? '自动备份已开启' : '自动备份已关闭', 'info'));
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
    showAlert('保留个数必须 ≥ 1', 'error');
    return;
  }
  Api.admin.setBackupRetention(val).then(function(res) {
    if (!res.ok) {
      showAlert('保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    showAlert('已保存: 保留最新 ' + val + ' 个', 'success');
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
            ${isZip ? `<button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.zip_name}')">⬇️ 下载</button>` : ''}
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
            ${isZip ? `<button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.zip_name}')">⬇️ 下载</button>` : ''}
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

      const res = await Api.adminRestore.upload(file);
      const data = await res;

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
      const res = await Api.adminRestore.upload(file);
      const data = await res;

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

    try {
      const res = await Api.adminRestore.upload(file);
      const data = await res;

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

    try {
      const res = await Api.adminRestore.upload(file);
      const data = await res;

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

// ===== 备份目录：选择 / 保存 =====

/** 点「选择目录」：App 内弹原生目录选择器；浏览器回退到手动输入 */
async function pickBackupDirInput() {
  const input = document.getElementById('backup-dir-input');
  const inputWrap = document.getElementById('backup-dir-input-wrap');
  const hasBridge = window.webkit && window.webkit.messageHandlers &&
    window.webkit.messageHandlers.pickBackupDir;

  if (!hasBridge) {
    // 浏览器里没有原生目录选择器，退化为手动填写
    if (inputWrap) inputWrap.style.display = 'block';
    if (input) input.focus();
    showToast('浏览器里请直接填写完整路径', 'info');
    return;
  }

  const dir = await adminPickBackupDir();
  if (!dir) return;                       // 用户取消
  if (input) input.value = dir;
  if (inputWrap) inputWrap.style.display = 'block';
  showToast('已选择目录，点「保存」生效', 'info');
}

/** 一个按钮保存整张卡片：备份目录 + 自动备份保留个数 */
async function saveBackupSettings() {
  const input = document.getElementById('backup-dir-input');
  const retentionEl = document.getElementById('admin-backup-retention');
  const dir = input ? input.value.trim() : '';
  const retention = parseInt(retentionEl ? retentionEl.value : '5', 10);

  if (retentionEl && (!retention || retention < 1)) {
    showAlert('保留个数必须 ≥ 1', 'error');
    return;
  }

  try {
    // 目录：留空 = 回到默认（数据目录下的 backup/）
    const res = await api('PUT', '/api/admin/backup-config', { backup_dir: dir });
    if (!res.ok) {
      showAlert('目录保存失败: ' + (res.error || '未知错误'), 'error');
      return;
    }
    if (retentionEl) {
      const r2 = await Api.admin.setBackupRetention(retention);
      if (r2 && r2.ok === false) {
        showAlert('保留个数保存失败: ' + (r2.error || '未知错误'), 'error');
        return;
      }
    }
    showAlert('✅ 已保存' + (retentionEl ? '：保留最新 ' + retention + ' 个备份' : ''), 'success');
    loadBackupDirConfig();
    loadBackupStatus();
  } catch (e) {
    showAlert('保存失败: ' + e.message, 'error');
  }
}

// 页面加载时初始化
initAuth();
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ==================== 表单提交 (从旧 forms_submit.js 迁移) ====================

// 抄表录入侧栏/弹窗共用提交函数
function submitReadingAdd(source) {
  if (_submitting) return;
  var ids = source === 'sidebar'
    ? { date: 'date', hall: 'hall', fire: 'fire', private_room: 'private_room', ac: 'ac', note: 'entry-note', rehearsal: 'entry-rehearsal', programming: 'entry-programming' }
    : { date: 'reading-add-date', hall: 'reading-add-hall', fire: 'reading-add-fire', private_room: 'reading-add-private_room', ac: 'reading-add-ac', note: 'reading-add-note', rehearsal: 'reading-add-rehearsal', programming: 'reading-add-programming' };
  var num = function(id) { var v = document.getElementById(id).value; return v === '' ? null : parseFloat(v); };
  var hallV = num(ids.hall), fireV = num(ids.fire), prV = num(ids.private_room), acV = num(ids.ac);
  var allVals = [hallV, fireV, prV, acV];
  if (allVals.every(function(v) { return v === null; })) { showAlert('请至少填写一块表的读数', 'error'); return; }
  if (allVals.some(function(v) { return v !== null && isNaN(v); })) { showAlert('读数必须是数字', 'error'); return; }
  var row = {
    date: document.getElementById(ids.date).value,
    hall: hallV, fire: fireV, private_room: prV, ac: acV,
    note: document.getElementById(ids.note).value.trim(),
    rehearsal: ids.rehearsal ? document.getElementById(ids.rehearsal).checked : false,
    programming: ids.programming ? document.getElementById(ids.programming).checked : false,
  };
  if (!row.date) { showAlert('请选择日期', 'error'); return; }

  // 检查是否已有该日期的抄表记录
  fetchReadings().then(function(all) {
    var existing = all.find(function(r) { return r.date === row.date; });
    if (existing) {
      showModal({ title: '覆盖已有数据', icon: '⚠️', iconKind: 'warn',
        body: '<strong>' + row.date + '</strong> 已存在数据,是否覆盖?<br><br>' +
          '<span style="opacity:0.7">现有:</span> 大厅 ' + existing.hall + ' · 消防 ' + existing.fire + ' · 包厢 ' + existing.private_room + ' · 空调 ' + existing.ac + '<br>' +
          '<span style="opacity:0.7">新数据:</span> 大厅 ' + row.hall + ' · 消防 ' + row.fire + ' · 包厢 ' + row.private_room + ' · 空调 ' + row.ac,
        confirmText: '覆盖', confirmKind: 'primary' }).then(function(overOK) {
          if (!overOK) return; doSaveReading();
        });
    } else { doSaveReading(); }

    function doSaveReading() {
      setSubmitting(true);
      saveReadingRemote(row).then(function() {
        showAlert('✓ ' + row.date + ' 已保存', 'success');
        var paths = source === 'sidebar'
          ? { date: 'date', hall: 'hall', fire: 'fire', private_room: 'private_room', ac: 'ac', note: 'entry-note', rehearsal: 'entry-rehearsal', programming: 'entry-programming' }
          : { date: 'reading-add-date', hall: 'reading-add-hall', fire: 'reading-add-fire', private_room: 'reading-add-private_room', ac: 'reading-add-ac', note: 'reading-add-note', rehearsal: 'reading-add-rehearsal', programming: 'reading-add-programming' };
        ['hall', 'fire', 'private_room', 'ac', 'note'].forEach(function(k) { document.getElementById(paths[k]).value = ''; });
        if (paths.rehearsal) document.getElementById(paths.rehearsal).checked = false;
        if (paths.programming) document.getElementById(paths.programming).checked = false;
        if (source === 'modal') closeReadingAddModal();
        refreshAndRender();
      }).catch(function(err) { showAlert('保存失败: ' + err.message, 'error'); }).finally(function() { setSubmitting(false); });
    }
  });
}

// 抄表/水电弹窗管理
/**
 * 打开抄表 / 水电录入弹窗。
 * @param {string} mode - 'reading' 抄表（默认）| 'utility' 水电表底
 *
 * 记录页已经把「抄表 / 充值 / 水电」拆成三个 Tab，所以弹窗内**不再**提供
 * 抄表/水电二选一 —— 由入口决定显示哪个表单，避免出现两层重复导航，
 * 也避免"弹窗里的 Tab 点了没反应"（那批绑定在模块化重构时丢了）。
 */
function openReadingAddModal(mode) {
  const m = mode === 'utility' ? 'utility' : 'reading';
  const title = document.getElementById('reading-add-title');
  if (title) title.textContent = m === 'utility' ? '💧 新增水电表底' : '📝 新增抄表';

  document.querySelectorAll('#reading-add-modal-backdrop .tab-panel').forEach(function(p) {
    p.style.display = (p.dataset.panel === m) ? '' : 'none';
  });

  const dateEl = document.getElementById(m === 'utility' ? 'utility-add-date' : 'reading-add-date');
  if (dateEl && !dateEl.value) dateEl.value = todayStr();

  document.getElementById('reading-add-modal-backdrop').classList.add('show');
  const focusEl = document.getElementById(m === 'utility' ? 'utility-add-main_meter' : 'reading-add-hall');
  if (focusEl) focusEl.focus();
}
function closeReadingAddModal() {
  document.getElementById('reading-add-modal-backdrop').classList.remove('show');
}

// ===== 物品 / 申购 / 工作记录 新增弹窗（模块化重构时连同 open/close 一起丢失）=====
function openItemAddModal() {
  document.getElementById('item-add-modal-backdrop').classList.add('show');
  const el = document.getElementById('item-add-name');
  if (el) el.focus();
}
function closeItemAddModal() {
  document.getElementById('item-add-modal-backdrop').classList.remove('show');
}

function openPurchaseAddModal() {
  const d = document.getElementById('purchase-add-date');
  if (d && !d.value) d.value = todayStr();
  if (typeof resetFieldImages === 'function') resetFieldImages(['purchase-add-name', 'purchase-add-note']);
  document.getElementById('purchase-add-modal-backdrop').classList.add('show');
  const el = document.getElementById('purchase-add-name');
  if (el) el.focus();
}
function closePurchaseAddModal() {
  document.getElementById('purchase-add-modal-backdrop').classList.remove('show');
}

function openDutyAddModal() {
  const t = document.getElementById('duty-add-time');
  if (t && !t.value) t.value = nowDateTimeLocalStr();
  if (typeof resetFieldImages === 'function') resetFieldImages(['duty-add-note']);
  document.getElementById('duty-add-modal-backdrop').classList.add('show');
  const el = document.getElementById('duty-add-type');
  if (el) el.focus();
}
function closeDutyAddModal() {
  document.getElementById('duty-add-modal-backdrop').classList.remove('show');
}

// 值班图片管理
function addDutyImage(source) {
  document.getElementById(source === 'sidebar' ? 'duty-image-input' : 'duty-add-image-input').click();
}

function handleDutyImageSelect(input, source) {
  var previewId = source === 'sidebar' ? 'duty-image-preview' : 'duty-add-image-preview';
  var preview = document.getElementById(previewId);
  if (!preview) return;
  var files = input.files;
  for (var i = 0; i < files.length && preview.children.length < 3; i++) {
    var reader = new FileReader();
    reader.onload = function(e) {
      var img = document.createElement('img');
      img.src = e.target.result;
      img.style.cssText = 'width:60px;height:60px;object-fit:cover;border-radius:4px;cursor:pointer;';
      img.onclick = function() { openLightbox(e.target.src); };
      preview.appendChild(img);
    };
    reader.readAsDataURL(files[i]);
  }
  input.value = '';
}

// 值班处理弹窗
function openDutyHandleModal(id, duty) {
  document.getElementById('duty-handle-id').value = id;
  document.getElementById('duty-handle-original-type').textContent = duty.duty_type || '—';
  document.getElementById('duty-handle-original-area').textContent = duty.fault_area || '—';
  document.getElementById('duty-handle-time').value = '';
  document.getElementById('duty-handle-shift').value = '';
  document.getElementById('duty-handle-method').value = '';
  document.getElementById('duty-handle-note').value = '';
  document.querySelectorAll('input[name="duty-add-status"]').forEach(function(r) { r.checked = false; });
  if (typeof resetFieldImages === 'function') resetFieldImages(['duty-handle-method']);
  document.getElementById('duty-handle-modal-backdrop').classList.add('show');
}

function closeDutyHandleModal() {
  var b = document.getElementById('duty-handle-modal-backdrop');
  if (b) b.classList.remove('show');
}

// 充值计算弹窗 (从旧 features_topup.js 迁移)
function openTopupModal() {
  var backdrop = document.getElementById('topup-modal-backdrop');
  if (!backdrop) return;
  backdrop.classList.add('show');
  recalcTopup();
  document.getElementById('topup-days-modal')?.focus();
}

function closeTopupModal() {
  var backdrop = document.getElementById('topup-modal-backdrop');
  if (backdrop) backdrop.classList.remove('show');
}

function recalcTopup() {
  var daysEl = document.getElementById('topup-days-modal');
  var resultEl = document.getElementById('topup-result-modal');
  var totalEl = document.getElementById('topup-total-modal');
  if (!daysEl || !resultEl || !totalEl) return;
  var days = parseFloat(daysEl.value);
  var rs = (CURRENT_READINGS || []).filter(function(r) { return r.hall != null; });
  if (!days || days <= 0 || rs.length === 0) {
    resultEl.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">请输入预充天数(≥1)</div>';
    totalEl.value = '';
    return;
  }
  var totalMeter = 0, totalActual = 0, totalYuan = 0;
  var rows = '';
  for (var i = 0; i < CHARGE_METERS.length; i++) {
    var m = CHARGE_METERS[i];
    var usage = calcMonthlyDailyUsage(rs, CURRENT_CHARGES, m.key);
    var daily = usage ? usage.daily : 0;
    var actualKwh = daily * days;
    var meterVal = actualKwh / MULTIPLIER(m.key);
    var yuan = actualKwh * ELECTRICITY_PRICE;
    totalMeter += meterVal; totalActual += actualKwh; totalYuan += yuan;
    var basis = usage ? '<span style="opacity:.7">' + (usage.basisLabel || '本月日均') + '</span>' : '暂无日均数据';
    var mult = MULTIPLIER(m.key);
    var daysLeft = daily > 0 ? (actualKwh / daily) : 0;
    rows += '<div class="topup-meter-card" data-daily="' + daily.toFixed(4) + '">' +
      '<div class="topup-meter-row">' +
        '<span class="topup-meter-name">' + m.meterNo + m.label + '</span>' +
        '<input type="number" class="field-control topup-meter" value="' + Math.round(meterVal) + '" step="1" data-mult="' + mult + '" title="表读数(充值录入值,可输入取整,自动反算其他值)">' +
        '<span class="topup-mult">×' + mult + '</span>' +
        '<input type="number" class="field-control topup-actual" value="' + Math.round(actualKwh) + '" step="1" data-mult="' + mult + '" title="实际度数(可输入取整充值,自动反算其他值)">' +
        '<span class="topup-yuan">≈ ¥' + Math.round(yuan) + '</span>' +
      '</div>' +
      '<div class="topup-meter-meta">日均 ' + Math.round(daily) + ' 度/天 ' + basis + ' <span class="topup-daysleft">≈ 可用 ' + Math.round(daysLeft) + ' 天</span></div>' +
    '</div>';
  }
  resultEl.innerHTML = rows;
  updateTopupTotal();
}

function updateTopupTotal() {
  var totalEl = document.getElementById('topup-total-modal');
  if (!totalEl) return;
  var totalActual = 0, totalMeter = 0, totalYuan = 0;
  document.querySelectorAll('.topup-actual').forEach(function(inp) {
    var mult = parseFloat(inp.getAttribute('data-mult'));
    var actual = parseFloat(inp.value) || 0;
    totalActual += actual; totalMeter += actual / mult; totalYuan += actual * ELECTRICITY_PRICE;
  });
  totalEl.value = '合计 ' + Math.round(totalActual) + ' 度(实际) ≈ ¥ ' + Math.round(totalYuan) + '  (表读数 ' + Math.round(totalMeter) + ')';
}

// Tab 切换 (从旧 forms_tab.js 迁移)
function switchReadingTab(tab) {
  var tabs = document.querySelectorAll('#reading-add-tabs .tab-btn');
  tabs.forEach(function(btn) { btn.classList.toggle('active', btn.dataset.tab === tab); });
  var panels = document.querySelectorAll('#reading-add-modal-backdrop .tab-panel');
  panels.forEach(function(p) { p.style.display = (p.dataset.panel === tab ? '' : 'none'); });
}

// 水电录入侧栏/弹窗共用提交函数 (从旧 forms_submit.js 迁移)
function submitUtilityAdd(source) {
  if (_submitting) return;
  var ids = source === 'sidebar'
    ? { date: 'utility-date', main: 'main_meter', sub: 'sub_meter', water: 'water', note: 'utility-note' }
    : { date: 'utility-add-date', main: 'utility-add-main_meter', sub: 'utility-add-sub_meter', water: 'utility-add-water', note: 'utility-add-note' };
  var date = document.getElementById(ids.date).value;
  if (!date) { showAlert('请选择抄表日期', 'error'); return; }
  var numU = function(id) { var v = document.getElementById(id).value; return v === '' ? null : parseFloat(v); };
  var mainV = numU(ids.main), subV = numU(ids.sub), waterV = numU(ids.water);
  var vals = [mainV, subV, waterV];
  if (vals.every(function(v) { return v === null; })) { showAlert('请至少填写总表/分表/水表一项', 'error'); return; }
  if (vals.some(function(v) { return v !== null && isNaN(v); })) { showAlert('读数必须是数字', 'error'); return; }
  var row = { date: date, main_meter: mainV, sub_meter: subV, water: waterV, note: document.getElementById(ids.note).value.trim() };

  fetchWaterReadings().then(function(all) {
    var existing = all.find(function(r) { return r.date === row.date; });
    if (existing) {
      showModal({ title: '覆盖已有数据', icon: '⚠️', iconKind: 'warn',
        body: '<strong>' + row.date + '</strong> 已有水电表底,是否覆盖?<br><br>' +
          '<span style="opacity:0.7">现有:</span> 总表 ' + (existing.main_meter != null ? existing.main_meter : '—') + ' · 分表 ' + (existing.sub_meter != null ? existing.sub_meter : '—') + ' · 水表 ' + (existing.water != null ? existing.water : '—') + '<br>' +
          '<span style="opacity:0.7">新数据:</span> 总表 ' + (row.main_meter != null ? row.main_meter : '—') + ' · 分表 ' + (row.sub_meter != null ? row.sub_meter : '—') + ' · 水表 ' + (row.water != null ? row.water : '—'),
        confirmText: '覆盖', confirmKind: 'primary' }).then(function(overOK) {
          if (!overOK) return; doSaveWater();
        });
    } else { doSaveWater(); }

    function doSaveWater() {
      setSubmitting(true);
      saveWaterReadingRemote(row).then(function() {
        showAlert('✓ ' + date + ' 水电已保存', 'success');
        var paths = source === 'sidebar'
          ? { date: 'utility-date', main: 'main_meter', sub: 'sub_meter', water: 'water', note: 'utility-note' }
          : { date: 'utility-add-date', main: 'utility-add-main_meter', sub: 'utility-add-sub_meter', water: 'utility-add-water', note: 'utility-add-note' };
        ['main', 'sub', 'water', 'note'].forEach(function(k) { document.getElementById(paths[k]).value = ''; });
        if (source === 'modal') closeReadingAddModal();
        refreshAndRender();
      }).catch(function(err) { showAlert('保存失败: ' + err.message, 'error'); }).finally(function() { setSubmitting(false); });
    }
  });
}

