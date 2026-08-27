// ===== 后台管理: 全局会话 =====
let ADMIN_TOKEN = localStorage.getItem('meter_admin_token');
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
  // 切换到数据页时加载备份状态（不再需要加载备份目录配置）
  if (page === 'data') loadBackupStatus();
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
    showAlert('已保存: 保留最新 ' + val + ' 个备份', 'success');
    // 同步更新两个输入框
    const adminRet = document.getElementById('admin-backup-retention');
    if (adminRet) adminRet.value = val;
    const dmRet = document.getElementById('datamgmt-backup-retention');
    if (dmRet) dmRet.value = val;
  }).catch(e => showAlert('保存失败: ' + e.message, 'error'));
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
        html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);">
          <div>
            <span style="color:var(--text);font-weight:510;">${b.name}</span>
            <span style="color:var(--text-muted);margin-left:8px;">${fmtLabel}${b.file_count} 文件 · ${sizeStr}</span>
            <span style="color:var(--text-muted);margin-left:8px;font-size:10px;">${b.created_at}</span>
          </div>
          <div style="display:flex;gap:4px;">
            ${isZip ? `<button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.zip_name}')" style="padding:2px 8px;font-size:11px;white-space:nowrap;">⬇️ 下载</button>` : '<span style="font-size:10px;color:var(--text-muted);">旧格式</span>'}
            <button class="btn btn-danger btn-xs" onclick="${isZip ? `adminRestoreFromZip('${b.zip_name}')` : `datamgmtRestoreFromZip('${b.zip_name}')`}" style="padding:2px 8px;font-size:11px;white-space:nowrap;">↩️ 恢复</button>
            ${isZip ? `<button class="btn btn-danger btn-xs" onclick="deleteBackup('${b.zip_name}')" style="padding:2px 8px;font-size:11px;white-space:nowrap;">🗑️ 删除</button>` : ''}
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
        html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);">
          <div>
            <span style="color:var(--text);font-weight:510;">${b.name}</span>
            <span style="color:var(--text-muted);margin-left:8px;">${fmtLabel}${b.file_count} 文件 · ${sizeStr}</span>
          </div>
          <div style="display:flex;gap:4px;">
            ${isZip ? `<button class="btn btn-primary btn-xs" onclick="downloadBackup('${b.zip_name}')" style="padding:2px 8px;font-size:11px;white-space:nowrap;">⬇️ 下载</button>` : '<span style="font-size:10px;color:var(--text-muted);">旧格式</span>'}
            <button class="btn btn-danger btn-xs" onclick="datamgmtRestoreFromZip('${b.zip_name}')" style="padding:2px 8px;font-size:11px;white-space:nowrap;">↩️ 恢复</button>
            ${isZip ? `<button class="btn btn-danger btn-xs" onclick="deleteBackup('${b.zip_name}')" style="padding:2px 8px;font-size:11px;white-space:nowrap;">🗑️ 删除</button>` : ''}
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

// 从备份列表恢复（下载 ZIP 到本地后恢复）
async function adminRestoreFromZip(zipName) {
  // 先下载到本地
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

    const btn = document.querySelector('#admin-page-data button[onclick^="adminRestore"]');
    const original = btn ? btn.textContent : '恢复数据';
    if (btn) { btn.textContent = '⏳ 恢复中…'; btn.disabled = true; }

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
    refreshAll && refreshAll();
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

    const btn = document.getElementById('datamgmt-restore-btn');
    const original = btn ? btn.textContent : '恢复数据';
    if (btn) { btn.textContent = '⏳ 恢复中…'; btn.disabled = true; }

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
    refreshAll && refreshAll();
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
  // 弹出文件选择器，选择本地 ZIP 备份文件
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
    const formData = new FormData();
    formData.append('zip_file', zipFile);

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
    refreshAll && refreshAll();
  } catch (e) {
    showAlert('恢复失败: ' + e.message, 'error');
  } finally {
    if (btn) { btn.textContent = original; btn.disabled = false; }
  }
}

// 选择 ZIP 文件
function pickZipFile() {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.zip';
    input.onchange = () => {
      const file = input.files && input.files[0];
      resolve(file || null);
    };
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