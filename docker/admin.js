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
      document.getElementById('backup-count').textContent = '当前备份数: ' + (res.backup_count || 0) + ' 个';
      if (cb) cb.addEventListener('change', e => {
        fetch('/api/admin/auto-backup' + getAuthParam(), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: e.target.checked }),
        }).then(() => showAlert(e.target.checked ? '自动备份已开启' : '自动备份已关闭', 'info'));
      }, { once: true });
    }).catch(() => {});
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
  const dir = await adminPickBackupDir();
  if (dir && dir._browser) {
    // 浏览器: 下载文件
    showAlert('正在下载数据文件…', 'info');
    for (const [name, content] of Object.entries(dir.files)) {
      const blob = new Blob([content], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      await new Promise(r => setTimeout(r, 200));
    }
    showAlert('✅ 数据文件已下载', 'success');
    return;
  }
  if (!dir) {
    // 浏览器/Docker 环境没有 Swift bridge: 从服务器获取所有数据并下载
    showAlert('正在从服务器获取数据…', 'info');
    try {
      const res = await api('GET', '/api/admin/data-files');
      if (!res.ok || !res.files) {
        showAlert('备份失败: ' + (res.error || '获取数据失败'), 'error');
        return;
      }
      const fileNames = Object.keys(res.files);
      if (!fileNames.length) {
        showAlert('当前没有可备份的数据文件', 'error');
        return;
      }
      showAlert('正在下载数据文件…', 'info');
      for (const [name, content] of Object.entries(res.files)) {
        const blob = new Blob([content], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        await new Promise(r => setTimeout(r, 200));
      }
      showAlert(`✅ 已下载 ${fileNames.length} 个数据文件`, 'success');
      return;
    } catch (e) {
      showAlert('备份失败: ' + e.message, 'error');
      return;
    }
  }
  const res = await api('POST', '/api/backup', dir ? { target_dir: dir } : {});
  showAlert(`数据已备份到 ${res.backup_dir || 'backup/'} 目录`, res.ok ? 'success' : 'error');
}

async function adminRestore() {
  let dir = await adminPickBackupDir();
  if (dir && dir._browser) {
    // 浏览器: 上传文件
    if (!confirm('确认上传选中的 JSON 文件覆盖当前数据？')) return;
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
    if (!confirm('确认上传选中的 JSON 文件覆盖当前数据？恢复前系统会自动备份。')) return;
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
  if (!confirm(`确认从 ${dir} 恢复数据? 恢复前会自动备份当前数据。`)) return;
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