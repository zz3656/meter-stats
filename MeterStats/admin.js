// ===== 后台管理: 全局会话 =====
let ADMIN_TOKEN = localStorage.getItem('token') || localStorage.getItem('meter_admin_token');

// 统一的 token 读取口。历史上有 'token' / 'meter_admin_token' / 'meter_token' 三种键名，
// 登录后实际只写 'token'，另两个是死键 —— 导致刷新后掉登录态、备份下载/删除永远不带 token。
// 现在所有需要 token 的代码都走这里，不要再直接读 localStorage。
function currentAuthToken() {
  return ADMIN_TOKEN || localStorage.getItem('token') || '';
}
let ADMIN_USER = null;

const ROLE_NAMES = { admin: '管理员', supervisor: '主管', employee: '员工' };

// 权限: 管理员和主管有删除权限, 员工只有录入和编辑
const ADMIN_DELETE_ROLES = new Set(['admin', 'supervisor']);
const ADMIN_MANAGE_ROLES = new Set(['admin']);

// 主管以上 —— 与后端 routing.MANAGER_ROLES 保持一致。
// 数据管理(备份/恢复/NAS 同步/图片目录/保留期)全在后端的 MANAGER_ONLY_PREFIXES 里,
// 员工点这些按钮只会拿到 403 —— 与其让人点了个没反应,不如根本不显示。
const MANAGER_ROLES = new Set(['admin', 'supervisor']);

// 按角色隐藏侧栏里进不去的页面。
// data-roles="manager" → 主管以上可见;data-roles="admin" → 仅管理员可见。
// **fail-closed**:拿不到当前用户(未登录 / 会话失效)→ 一律隐藏。
function applyRoleVisibility() {
  var role = (ADMIN_USER && ADMIN_USER.role) || '';
  var allowed = {
    manager: MANAGER_ROLES.has(role),
    admin: ADMIN_MANAGE_ROLES.has(role),
  };
  var items = document.querySelectorAll('.sidebar-item[data-roles]');
  for (var i = 0; i < items.length; i++) {
    var need = items[i].getAttribute('data-roles');
    var ok = Object.prototype.hasOwnProperty.call(allowed, need) && allowed[need];
    items[i].style.display = ok ? '' : 'none';
  }
}

// ===== 初始化: 有token则验证, 否则显示登录页 =====
function initAuth() {
  showLoginVersion();
  if (ADMIN_TOKEN) {
    // Store in localStorage so Api.* can use it
    localStorage.setItem('token', ADMIN_TOKEN);
    // 验证会话
    Api.system.me().then(function(res) {
        if (res.user) {
          // ⚠️ 单独 catch:不要 return 给外层的 catch(那会把用户踢出登录)
          setLoggedIn(res.user).catch(function(e) {
            console.warn('登录后初始化失败:', e);
          });
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

// 登录页显示版本号：/api/version 无需登录即可访问，取不到就整行隐藏
function showLoginVersion() {
  var el = document.getElementById('login-version');
  if (!el) return;
  fetch('/api/version').then(function(r) {
    return r.ok ? r.json() : null;
  }).then(function(d) {
    el.textContent = (d && d.version) ? ('版本 v' + d.version) : '';
    if (!el.textContent) el.style.display = 'none';
  }).catch(function() {
    el.style.display = 'none';
  });
}

// 验证通过后: 隐藏登录页, 显示主应用
async function setLoggedIn(user) {
  ADMIN_USER = user;
  document.getElementById('logout-btn').style.display = '';
  document.getElementById('login-page').style.display = 'none';
  // admin-user-info was in the removed popup modal
  // 鉴权通过才允许加载业务数据（后端 /api/* 已强制 token）
  // 按角色隐藏进不去的设置页(数据管理要主管以上、用户管理仅管理员)
  applyRoleVisibility();
  // ⚠️ 必须先引导门店上下文再拉数据:
  //    数据请求要带 ?store=,门店没定下来时后端会落到默认店 ——
  //    那样员工看到的就不是自己该看的那家店了。
  var storeReady = true;
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) {
      await StoreContext.init();
      // 「当前店为空」有两种,必须分开处理:
      //   - hasNoStore():账号被管理员取消了门店 → 让用户去联系管理员
      //   - 有门店列表却没选出店(理论上不该发生)→ 让用户刷新重试
      // 两种都不拉数据 —— 拉了就是满屏 403。
      if (StoreContext.hasNoStore()) {
        showAlert('账号未分配门店,请联系管理员', 'error');
        storeReady = false;
      } else if (!StoreContext.getStoreId()) {
        showAlert('加载门店列表失败,请刷新重试', 'error');
        storeReady = false;
      }
    }
  } catch (e) {
    console.warn('门店上下文引导失败:', e);
  }
  // 渲染门店切换器(可见性取决于 all_stores / 门店数量)
  try {
    if (typeof initStoreSwitcher === 'function') initStoreSwitcher();
  } catch (e) {
    console.warn('门店切换器初始化失败:', e);
  }
  if (storeReady && typeof window.loadAppData === 'function') window.loadAppData();
}

// 无权限时: 显示登录页
function clearAuth() {
  ADMIN_TOKEN = null;
  ADMIN_USER = null;
  // 'token' 才是登录后实际写入的键，之前只删了死键 meter_admin_token，
  // 导致登出后 api.js 仍能读到旧 token。三个键一律清掉。
  localStorage.removeItem('token');
  localStorage.removeItem('meter_admin_token');
  localStorage.removeItem('meter_token');
  // 门店上下文也要清:换人登录不该继承上一个人选的门店。
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) StoreContext.reset();
  } catch (e) { /* ignore */ }
  document.getElementById('logout-btn').style.display = 'none';
  document.getElementById('login-page').style.display = 'flex';
  // 登出后管理类入口一律藏起来(不等下次登录)
  applyRoleVisibility();
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
    // 登录失败时后端仍返回 HTTP 200 + {ok:false}，Api 包装器不会抛错，
    // 必须在这里显式校验，否则会把 undefined 当 token 直接进入主界面。
    if (!res || res.ok !== true || !res.token || !res.user) {
      errEl.textContent = (res && res.error) ? res.error : '登录失败，请重试';
      errEl.style.display = 'block';
      return;
    }
    ADMIN_TOKEN = res.token;
    localStorage.setItem('token', ADMIN_TOKEN);
    try {
      await setLoggedIn(res.user);  // 内部会触发 loadAppData，不要再 renderAll() 一次
    } catch (e) {
      console.warn('登录后初始化失败:', e);
    }
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

/**
 * 拉门店列表并缓存到 window.STORE_LIST(用户表格要显示门店名)。
 * 与 js/modules/stores.js 共用同一份缓存 —— 那边的 STORE_LIST 就是 window.STORE_LIST。
 *
 * 请求本身也缓存一份:并发调用共享同一个 Promise,回调按注册顺序执行 ——
 * 「渲染勾选框」的回调先注册,「读取勾选框」的回调后注册,后者才读得到勾好的值。
 */
var _storeListPromise = null;
function ensureStoreList() {
  if (window.STORE_LIST && window.STORE_LIST.length) return Promise.resolve(window.STORE_LIST);
  if (!_storeListPromise) {
    _storeListPromise = Api.stores.list().then(function(res) {
      _storeListPromise = null;
      if (res && res.ok === false) {
        window.STORE_LIST = [];
        return window.STORE_LIST;
      }
      window.STORE_LIST = (res && res.stores) || [];
      return window.STORE_LIST;
    }).catch(function() {
      _storeListPromise = null;
      window.STORE_LIST = [];
      return window.STORE_LIST;
    });
  }
  return _storeListPromise;
}

/** 用户的门店范围摘要(表格「门店」列)。门店名走全局 escapeHtml(元素内容位置,够用)。 */
function userStoreScopeText(u) {
  if (!u) return '';
  if (u.all_stores) return '<span class="role-badge role-admin">全部门店</span>';
  var ids = Array.isArray(u.store_ids) ? u.store_ids : [];
  if (!ids.length) return '<span style="color:var(--text-muted);">未分配</span>';
  return ids.map(function(id) {
    var s = (window.STORE_LIST || []).find(function(x) { return String(x.id) === String(id); });
    return '<span class="role-badge">' + escapeHtml(s ? (s.name || s.id) : id) + '</span>';
  }).join(' ');
}

/** 渲染用户表格(「门店」列靠 window.STORE_LIST 里的门店名)。 */
function renderUsersTable(usersList) {
  const tbody = document.getElementById('users-table-body');
  if (!tbody) return;
  tbody.innerHTML = usersList.map(u => `
        <tr>
          <td>${u.username}</td>
          <td>${u.name}</td>
          <td><span class="role-badge role-${u.role}">${ROLE_NAMES[u.role] || u.role}</span></td>
          <td>${u.enabled
              ? '<span class="status-dot on"></span>启用'
              : '<span class="status-dot off"></span>禁用'}</td>
          <td>${userStoreScopeText(u)}</td>
          <td class="ta-right">
            <button class="btn btn-primary btn-xs" onclick="editAdminUser(${u.id},'${u.username}')">编辑</button>
            ${ADMIN_MANAGE_ROLES.has(ADMIN_USER?.role) ? `<button class="btn btn-secondary btn-xs" onclick="editUserStores(${u.id})">门店</button>` : ''}
            ${ADMIN_DELETE_ROLES.has(ADMIN_USER?.role) && u.id !== ADMIN_USER?.id ? `<button class="btn btn-danger btn-xs" onclick="deleteAdminUser(${u.id})">删除</button>` : ''}
          </td>
        </tr>
      `).join('');
}

/** 渲染「新增用户」的门店勾选框。门店 ID 进属性值 → 必须走 escapeAttr(全局 escapeHtml 是弱版)。 */
function renderNewUserStoreBoxes(stores) {
  const box = document.getElementById('new-store-ids-box');
  if (!box) return;
  const list = stores || [];
  if (!list.length) {
    box.innerHTML = '<span style="color:var(--text-muted);">暂无门店</span>';
    return;
  }
  box.innerHTML = list.map(function(s) {
    const sid = String(s.id == null ? '' : s.id);
    return '<label style="display:inline-flex;align-items:center;gap:4px;white-space:nowrap;">' +
      '<input type="checkbox" name="new-store-ids" value="' + escapeAttr(sid) + '" />' +
      escapeHtml(s.name || sid) + '</label>';
  }).join('');
}

function loadAdminUsers() {
  Api.admin.users().then(function(users) {
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

    renderUsersTable(usersList);

    // 门店列表拉到后:渲染「新增用户」的勾选框,并把表格「门店」列补成门店名
    ensureStoreList().then(function(stores) {
      renderNewUserStoreBoxes(stores);
      renderUsersTable(usersList);
    });
  }).catch(e => showAlert('加载用户失败: ' + e.message, 'error'));
}

/** 编辑某个用户的门店权限(弹窗多选)。仅管理员可用 —— 与 /api/admin/users 同一道闸。 */
function editUserStores(uid) {
  if (!ADMIN_MANAGE_ROLES.has(ADMIN_USER?.role)) { showAlert('只有管理员可以分配门店', 'error'); return; }
  Promise.all([Api.admin.users(), ensureStoreList()]).then(function(results) {
    var users = results[0] || [];
    var stores = results[1] || [];
    var u = users.find(function(x) { return String(x.id) === String(uid); });
    if (!u) { showAlert('用户不存在', 'error'); return; }

    var boxes = stores.map(function(s) {
      var sid = String(s.id == null ? '' : s.id);
      var ids = Array.isArray(u.store_ids) ? u.store_ids : [];
      var checked = ids.indexOf(sid) >= 0 ? ' checked' : '';
      return '<label style="display:inline-flex;align-items:center;gap:6px;margin:4px 12px 4px 0;">' +
        '<input type="checkbox" name="edit-store-ids" value="' + escapeAttr(sid) + '"' + checked + ' />' +
        escapeHtml(s.name || sid) + '</label>';
    }).join('') || '<div style="color:var(--text-muted);">还没有门店,请先到「门店管理」创建</div>';

    var allChecked = u.all_stores ? ' checked' : '';
    showModal({
      title: '门店权限: ' + (u.name || u.username),
      icon: '🏪', iconKind: 'info',
      body: '<div style="margin-bottom:10px;">' +
              '<label style="display:inline-flex;align-items:center;gap:6px;">' +
                '<input type="checkbox" id="edit-all-stores"' + allChecked + ' /> 全部门店(总部账号)</label>' +
            '</div>' +
            '<div>' + boxes + '</div>',
      confirmText: '保存', confirmKind: 'primary'
    }).then(function(ok) {
      if (!ok) return;
      var picked = Array.prototype.slice.call(
        document.querySelectorAll('input[name="edit-store-ids"]:checked')
      ).map(function(el) { return el.value; });
      var all = (document.getElementById('edit-all-stores') || {}).checked || false;
      Api.admin.updateUser(uid, { store_ids: picked, all_stores: all }).then(function(res2) {
        if (!res2 || res2.ok === false) { showAlert('保存失败: ' + ((res2 && res2.error) || '未知错误'), 'error'); return; }
        showAlert('门店权限已更新', 'success');
        loadAdminUsers();
      }).catch(function(e) { showAlert('网络错误: ' + e.message, 'error'); });
    });
  }).catch(function(e) { showAlert('加载失败: ' + e.message, 'error'); });
}

function addAdminUser() {
  const username = document.getElementById('new-username').value.trim();
  const password = document.getElementById('new-password').value;
  const name = document.getElementById('new-name').value.trim() || username;
  const role = document.getElementById('new-role').value;

  if (!username || !password) { showAlert('用户名和密码不能为空', 'error'); return; }
  if (!ADMIN_MANAGE_ROLES.has(ADMIN_USER?.role)) { showAlert('只有管理员可以添加用户', 'error'); return; }

  ensureStoreList().then(function() {
    var storeIds = Array.prototype.slice.call(
      document.querySelectorAll('input[name="new-store-ids"]:checked')
    ).map(function(el) { return el.value; });
    var allStores = (document.getElementById('new-all-stores') || {}).checked || false;
    Api.admin.createUser({
      username: username, password: password, name: name, role: role,
      store_ids: storeIds, all_stores: allStores
    }).then(function(res) {
      if (!res || res.ok === false) { showAlert('添加失败: ' + ((res && res.error) || '未知错误'), 'error'); return; }
      showAlert('用户已添加: ' + username, 'success');
      document.getElementById('new-username').value = '';
      document.getElementById('new-password').value = '';
      document.getElementById('new-name').value = '';
      const allBox = document.getElementById('new-all-stores');
      if (allBox) allBox.checked = false;
      loadAdminUsers();
    }).catch(e => showAlert('网络错误: ' + e.message, 'error'));
  }).catch(e => showAlert('加载门店列表失败: ' + e.message, 'error'));
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
// ===== 电表设置(P2:按店,可增删表) =====
//
// 改造前:表集合写死 4 块,只能改名和倍率,而且写的是**全局** settings ——
// 一家店改表名,全部门店跟着变。现在按当前门店读写 store.json,并支持增删表。

/** 当前编辑中的表定义(渲染与增删共用一份,避免表单与状态不同步) */
var _meterSettingsList = [];

/** 表单里的输入 → _meterSettingsList(用户可能已经改过名字,增删前必须先同步) */
function _syncMeterListFromForm(form) {
  if (!form || !window.MeterForm) return;
  _meterSettingsList = window.MeterForm.readSettings(form);
}

/** 渲染表定义单元格(实现在 MeterForm.renderSettings —— 与表单渲染同一处,便于测试) */
function _renderMeterCells(form, list) {
  if (!window.MeterForm) return;
  window.MeterForm.renderSettings(form, list, function (key) {
    _syncMeterListFromForm(form);
    _meterSettingsList = _meterSettingsList.filter(function (m) { return m.key !== key; });
    _renderMeterCells(form, _meterSettingsList);
  });
}

/** 新增一块表:key 自动生成(m1/m2/…),避开已用 */
function addMeterRow() {
  var form = document.getElementById('meter-settings-form');
  if (!form || !window.MeterForm) return;
  _syncMeterListFromForm(form);

  var used = _meterSettingsList.map(function (m) { return m.key; });
  var icons = window.MeterForm.SETTINGS_ICONS;
  _meterSettingsList.push({
    key: window.MeterForm.nextMeterKey(used),
    label: '新表' + (used.length + 1),
    icon: icons[used.length % icons.length],
    multiplier: 1,
  });
  _renderMeterCells(form, _meterSettingsList);
}

/** 当前正在编辑哪家店 —— 总部账号容易改错店,标题上写清楚 */
function _renderMeterStoreName() {
  var el = document.getElementById('meter-settings-store');
  if (!el) return;
  var name = '';
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) {
      var sid = StoreContext.getStoreId();
      var stores = StoreContext.getStores() || [];
      for (var i = 0; i < stores.length; i++) {
        if (String(stores[i].id) === String(sid)) { name = stores[i].name || sid; break; }
      }
      if (!name) name = sid || '';
    }
  } catch (e) { /* ignore */ }
  el.textContent = name ? ('当前门店:' + name) : '';
}

function loadMeterSettings() {
  Api.admin.meterSettings().then(function (res) {
    var form = document.getElementById('meter-settings-form');
    if (!form) return;

    var config = res.config || {};
    var elecPrice = document.getElementById('config-elec-price');
    var waterPrice = document.getElementById('config-water-price');
    var mainMult = document.getElementById('config-main-mult');
    var subMult = document.getElementById('config-sub-mult');
    if (elecPrice) elecPrice.value = config.electricity_price || 0.9;
    if (waterPrice) waterPrice.value = config.water_price || 4.5;
    if (mainMult) mainMult.value = config.main_mult != null ? config.main_mult : 50;
    if (subMult) subMult.value = config.sub_mult != null ? config.sub_mult : 40;

    // 表定义:后端给的是**有序字典** {key: {...}}(JSON 对象保序)
    var meters = res.meters || res.meter || {};
    var list = Object.keys(meters).map(function (k) {
      return Object.assign({ key: k }, meters[k] || {});
    });
    _meterSettingsList = list;
    _renderMeterCells(form, _meterSettingsList);
    _renderMeterStoreName();
  }).catch(function (e) { showAlert('加载电表设置失败: ' + (e && e.message ? e.message : ''), 'error'); });
}

function saveMeterSettings() {
  var form = document.getElementById('meter-settings-form');
  if (form) _syncMeterListFromForm(form);
  if (!_meterSettingsList.length) { showAlert('至少要有 1 块表', 'error'); return; }

  // 后端要的是数组:key / label / icon / multiplier
  var meters = window.MeterForm.settingsPayload(_meterSettingsList);

  // 后端是整体替换 config,必须把全部字段都带上
  var numOr = function (id, fallback) {
    var el = document.getElementById(id);
    var v = el ? parseFloat(el.value) : NaN;
    return isNaN(v) ? fallback : v;
  };
  var config = {
    electricity_price: numOr('config-elec-price', 0.9),
    water_price: numOr('config-water-price', 4.5),
    main_mult: Math.round(numOr('config-main-mult', 50)),
    sub_mult: Math.round(numOr('config-sub-mult', 40)),
  };

  Api.admin.saveMeterSettings({ meters: meters, config: config }).then(function (res) {
    if (!res || res.ok === false) {
      showAlert('保存失败: ' + ((res && res.error) || '未知错误'), 'error');
      return;
    }
    showAlert('电表设置已保存', 'success');
    // 保存后必须重载表元数据并重渲染表单/表头/报表 ——
    // 否则「加了一块表」要刷新页面才看得见,用户会以为没保存上。
    if (typeof loadMeterConfig === 'function') {
      loadMeterConfig().then(function () {
        if (typeof window.renderMeterUi === 'function') window.renderMeterUi();
        if (typeof refreshAndRender === 'function') refreshAndRender();
      }).catch(function () { /* 静默 */ });
    }
  }).catch(function (e) {
    // 后端校验失败(0 块表 / 倍率非正整数 / key 非法)会返回 400 → 这里拿到可读原因
    showAlert('保存失败: ' + (e && e.message ? e.message : '网络错误'), 'error');
  });
}

// ===== 数据管理 =====// ===== 数据管理 =====

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
  const token = currentAuthToken();
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

  const token = currentAuthToken();
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
  const token = currentAuthToken();
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
  const token = currentAuthToken();
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
  const token = currentAuthToken();
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
  // ⚠️ 必须 try/catch:api() 遇非 2xx 会 throw(403 = 权限不足)。
  //    没有 catch 就是 unhandled rejection —— 用户看到「正在备份数据…」
  //    然后什么也没发生,连报错都没有。
  let res;
  try {
    res = await api('POST', '/api/backup');
  } catch (e) {
    showAlert('备份失败: ' + (e && e.message ? e.message : '未知错误'), 'error');
    return;
  }
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
  var t = currentAuthToken();
  return t ? '?token=' + encodeURIComponent(t) : '';
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

// 注:escapeHtml 现在**只有一份** —— js/helpers/utils.js 的强版(转义 & < > " ')。
// 这里原来还有一份弱版(顶层函数声明,加载顺序在 utils.js 之后 → 运行时覆盖强版,
// 只转义 & < >,不转义引号)。弱版让自由文本进属性值就能被引号打断
// (例:js/modules/items.js 把 escapeHtml(物品名) 塞进 data-name="...") → 已删除。
// 元素内容位置用 escapeHtml,属性值位置一律用 escapeAttr。

// ==================== 表单提交 (从旧 forms_submit.js 迁移) ====================

// 抄表录入侧栏/弹窗共用提交函数
// 一行抄表/充值的表值摘要(「1#大厅 12.3 · 2#消防 —」)—— 覆盖确认弹窗用。
// 按当前门店的表集合生成(P2):门店可能是 2 块表,也可能 5 块。
function meterSummaryText(row) {
  return (window.MeterForm.keys() || []).map(function(k, i) {
    var meta = (typeof METER_META === 'function') ? METER_META(k) : { label: k };
    var v = (typeof meterValue === 'function') ? meterValue(row, k) : row[k];
    return (i + 1) + '#' + (meta.label || k) + ' ' + (v == null ? '—' : v);
  }).join(' · ');
}

function submitReadingAdd(source) {
  if (_submitting) return;
  var ctx = source === 'sidebar'
    ? { date: 'date', note: 'entry-note', rehearsal: 'entry-rehearsal', programming: 'entry-programming', prefix: '' }
    : { date: 'reading-add-date', note: 'reading-add-note', rehearsal: 'reading-add-rehearsal', programming: 'reading-add-programming', prefix: 'reading-add-' };
  // 表值按当前门店的表集合收集(P2);旧 4 表走顶层字段,自定义表走 meters 字典
  var picked = window.MeterForm.collect(ctx.prefix);
  if (picked.hasNaN) { showAlert('读数必须是数字', 'error'); return; }
  if (!picked.keys.some(function(k) { return picked.all[k] !== null; })) {
    showAlert('请至少填写一块表的读数', 'error'); return;
  }
  var row = { date: document.getElementById(ctx.date).value };
  var payload = window.MeterForm.toPayload(picked, { keepNullLegacy: true });
  Object.keys(payload).forEach(function(k) { row[k] = payload[k]; });
  row.note = document.getElementById(ctx.note).value.trim();
  row.rehearsal = ctx.rehearsal ? document.getElementById(ctx.rehearsal).checked : false;
  row.programming = ctx.programming ? document.getElementById(ctx.programming).checked : false;
  if (!row.date) { showAlert('请选择日期', 'error'); return; }

  // 检查是否已有该日期的抄表记录
  fetchReadings().then(function(all) {
    var list = Array.isArray(all) ? all : ((all && all.data) || []);
    // 表数不降反升检查：表数上升通常意味着刚充值，提醒先录充值再保存
    var prev = null;
    list.forEach(function(r) {
      if (r.date && r.date < row.date && (!prev || r.date > prev.date)) prev = r;
    });
    var rises = [];   // { key, label, deltaMeter } —— 保留数值，后面估算充值数要用
    if (prev) {
      window.MeterForm.keys().forEach(function(k) {
        var nv = meterValue(row, k), pv = meterValue(prev, k);
        if (nv != null && typeof pv === 'number' && nv > pv) {
          var lab = (typeof METER_META === 'function') ? METER_META(k).label : k;
          rises.push({ key: k, label: lab, deltaMeter: nv - pv });
        }
      });
    }
    var ups = rises.map(function(r) {
      return r.label + ' +' + Math.round(r.deltaMeter * 100) / 100;
    });
    var proceed = function() {
      var existing = list.find(function(r) { return r.date === row.date; });
      if (existing) {
        showModal({ title: '覆盖已有数据', icon: '⚠️', iconKind: 'warn',
          body: '<strong>' + row.date + '</strong> 已存在数据,是否覆盖?<br><br>' +
            '<span style="opacity:0.7">现有:</span> ' + meterSummaryText(existing) + '<br>' +
            '<span style="opacity:0.7">新数据:</span> ' + meterSummaryText(row),
          confirmText: '覆盖', confirmKind: 'primary' }).then(function(overOK) {
            if (!overOK) return; doSaveReading();
          });
      } else { doSaveReading(); }
    };

    if (ups.length) {
      showModal({ title: '表数上升提醒', icon: '💡', iconKind: 'info',
        body: '<strong>' + row.date + '</strong> 的表数比上一条记录（' + prev.date + '）不降反升：<br><br>' +
          '<strong>' + ups.join('　') + '</strong><br><br>' +
          '表数上升通常是因为刚充值。请确认：<br>' +
          '① 本次充值记录是否已经录入；<br>' +
          '② 是否录入了错误的字段（如把 A 表的数填到了 B 表）。',
        confirmText: '已充值，继续保存', confirmKind: 'primary',
        cancelText: '修正' }).then(function(ok) {
          // 「已充值，继续保存」= 确认上升合理，继续走保存流程（覆盖检查 + 提交）
          if (ok) { proceed(); } else { showAlert('已返回录入，请检查修正后重新保存', 'info'); }
        });
    } else { proceed(); }

    function doSaveReading() {
      setSubmitting(true);
      saveReadingRemote(row).then(function() {
        showAlert('✓ ' + row.date + ' 已保存', 'success');
        window.MeterForm.clear(ctx.prefix);
        var noteEl = document.getElementById(ctx.note); if (noteEl) noteEl.value = '';
        if (ctx.rehearsal) document.getElementById(ctx.rehearsal).checked = false;
        if (ctx.programming) document.getElementById(ctx.programming).checked = false;
        if (source === 'modal') closeReadingAddModal();
        refreshAndRender();
        // 抄表已保存；若表底上升却找不到对应充值记录，再追问一句，避免"忘了录充值"导致统计失真
        maybePromptReadingRiseCharge(row, prev, rises);
      }).catch(function(err) { showAlert('保存失败: ' + err.message, 'error'); }).finally(function() { setSubmitting(false); });
    }
  });
}

// 抄表保存后：表底上升但找不到对应充值记录 → 提示补录，并把估算值预填进充值表单。
// 预付费表的钱一旦打进表，表底立刻上升；但充值记录要人手工录。漏录会让余量、
// 日均、报表全部失真，所以这里主动追问，而不是等用户自己去对账。
function maybePromptReadingRiseCharge(row, prev, rises) {
  if (!prev || !rises || !rises.length) return;

  var charges = (typeof CURRENT_CHARGES !== 'undefined' && CURRENT_CHARGES) || [];
  var inWindow = charges.filter(function(c) {
    var rec = (c && c.date) || '';
    var land = (typeof chargeEffectiveDate === 'function') ? chargeEffectiveDate(c) : rec;
    return (rec >= prev.date && rec <= row.date) || (land >= prev.date && land <= row.date);
  });
  // 已有已确认(或历史无状态)的充值 → 说明录过了，不再打扰
  if (inWindow.some(function(c) { return c.status !== 'pending'; })) return;

  var detail = rises.map(function(r) {
    return r.label + ' +' + (Math.round(r.deltaMeter * 10) / 10) + ' 表字';
  }).join('　');

  if (inWindow.length) {
    // 有申请单但状态还是待确认：钱已进表，只差确认到账
    showModal({
      title: '有充值待确认到账', icon: '💡', iconKind: 'info',
      body: '<strong>' + row.date + '</strong> 的表底比上一条记录（' + prev.date + '）升高了：<br><br>' +
        '<strong>' + detail + '</strong><br><br>' +
        '找到 ' + inWindow.length + ' 笔<strong>待确认</strong>的充值申请。钱已经打进表了的话，' +
        '去确认到账，余量和报表才会把它算进去。',
      confirmText: '去确认到账', confirmKind: 'primary', cancelText: '稍后'
    }).then(function(ok) { if (ok) gotoChargeTab(); });
    return;
  }

  showModal({
    title: '充值数据是否没录入？', icon: '💡', iconKind: 'info',
    body: '抄表已保存。<strong>' + row.date + '</strong> 的表底比上一条（' + prev.date + '）升高了：<br><br>' +
      '<strong>' + detail + '</strong><br><br>' +
      '表底上升说明这段时间充过值，但没找到对应的充值记录。现在补录吗？<br>' +
      '<span style="opacity:.7;font-size:12px;">充值数按「上升量 + 这段时间的日均消耗」估算，取整到十位，可自行修改。</span>',
    confirmText: '去补录充值', confirmKind: 'primary', cancelText: '稍后再说'
  }).then(function(ok) { if (ok) prefillChargeFromRise(row, prev, rises); });
}

function gotoChargeTab() {
  if (typeof switchSection === 'function') switchSection('reading-record');
  if (typeof switchRecordTab === 'function') switchRecordTab('charge');
}

// 按表底上升量 + 日均估算各表充值数（表字，取整到十位），预填进「新增充值」表单
function prefillChargeFromRise(row, prev, rises) {
  gotoChargeTab();
  // 按当前门店的表集合清空(P2)—— 只清旧 4 表会把自定义表上一次的值留着
  window.MeterForm.clear('charge-add-');

  var days = (new Date(row.date) - new Date(prev.date)) / 86400000;
  if (!(days > 0)) days = 1;
  var readings = (typeof CURRENT_READINGS !== 'undefined' && CURRENT_READINGS) || [];
  var charges = (typeof CURRENT_CHARGES !== 'undefined' && CURRENT_CHARGES) || [];
  var filled = [];

  rises.forEach(function(r) {
    var mult = MULTIPLIER(r.key);
    var usage = calcMonthlyDailyUsage(readings, charges, r.key);
    var dailyKwh = usage ? usage.daily : 0;
    var est = r.deltaMeter + (dailyKwh * days) / mult;      // 上升量 + 这段用掉的
    var v = est >= 10 ? Math.round(est / 10) * 10 : Math.round(est);  // 充值都是整数，不存在个位
    var el = document.getElementById('charge-add-' + r.key);
    if (el) el.value = v;
    filled.push(r.label + ' ' + v);
  });

  var d = document.getElementById('charge-add-date');
  if (d) d.value = row.date;                                 // 表数异常的那一天
  var note = document.getElementById('charge-add-note');
  if (note && !note.value) note.value = '抄表发现表底上升，补录（' + filled.join('、') + '）';

  openChargeAddModal();
  showAlert('已按日均估算预填，核对后提交', 'info');
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
  const firstMeterKey = (window.MeterForm.keys() || ['hall'])[0];
  const focusEl = document.getElementById(m === 'utility' ? 'utility-add-main_meter' : 'reading-add-' + firstMeterKey);
  if (focusEl) focusEl.focus();
}
function closeReadingAddModal() {
  document.getElementById('reading-add-modal-backdrop').classList.remove('show');
}

// ===== 物品 / 申购 / 工作记录 新增弹窗（模块化重构时连同 open/close 一起丢失）=====
function openItemAddModal() {
  if (typeof resetFieldImages === 'function') resetFieldImages(['item-add-note']);
  var batch = document.getElementById('item-add-batch');
  if (batch) batch.checked = false;
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
  daysEl.disabled = false; // 重新计算 = 回到"建议值"模式,恢复天数输入
  var days = parseFloat(daysEl.value);
  var rs = (CURRENT_READINGS || []).filter(function(r) { return r.hall != null; });
  if (!days || days <= 0 || rs.length === 0) {
    resultEl.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">请输入预充天数(≥1)</div>';
    totalEl.value = '';
    return;
  }
  var totalMeter = 0, totalActual = 0, totalYuan = 0;
  var rows = '';
  // 表显余量走 remainingBalance():最近一次抄表读数 + 已到账未抄表的充值
  for (var i = 0; i < CHARGE_METERS.length; i++) {
    var m = CHARGE_METERS[i];
    var mult = MULTIPLIER(m.key);
    var usage = calcMonthlyDailyUsage(rs, CURRENT_CHARGES, m.key);
    var daily = usage ? usage.daily : 0;
    var basis = usage ? '<span style="opacity:.7">' + (usage.basisLabel || '本月日均') + '</span>' : '暂无日均数据';

    // 余量 = 最新抄表读数 + 已到账但还没抄进读数的充值（今天充的钱，明天抄表才看得见，
    // 但钱已经在表里了，不能等到明天才算）
    var bal = remainingBalance(CURRENT_CHARGES, m.key);
    var balMeter = bal.hasReading ? bal.meterVal : null;   // 表显余量(表字)
    var balKwh = bal.hasReading ? bal.kwh : null;          // 余量(实际度数)

    // 需充值 = 预充天数 × 日均 − 现有余量;余量足够则建议 0(不再多充)
    var needKwh = daily * days;
    var toBuyKwh = balKwh != null ? Math.max(0, needKwh - balKwh) : needKwh;
    var meterVal = toBuyKwh / mult;
    var yuan = toBuyKwh * ELECTRICITY_PRICE;
    totalMeter += meterVal; totalActual += toBuyKwh; totalYuan += yuan;

    var daysLeft = daily > 0 ? ((balKwh || 0) + toBuyKwh) / daily : 0;
    var enough = balKwh != null && daily > 0 && toBuyKwh <= 0;
    var balText = balMeter != null
      ? '余量 ' + (Math.round(balMeter * 10) / 10) + ' 表字(≈' + Math.round(balKwh) + ' 度,' + bal.readingDate + ' 抄表'
        + (bal.extraKwh > 0 ? ' + 已到账未抄表 ' + Math.round(bal.extraKwh) + ' 度' : '') + ')'
      : '未录余量';
    rows += '<div class="topup-meter-card" data-daily="' + daily.toFixed(4) + '" data-balkwh="' + (balKwh == null ? '' : balKwh) + '">' +
      '<div class="topup-meter-row">' +
        '<span class="topup-meter-name">' + m.meterNo + m.label + '</span>' +
        '<input type="number" class="field-control topup-meter" value="' + Math.round(meterVal) + '" step="1" data-mult="' + mult + '" oninput="updateTopupFromMeter(this)" title="表读数(充值录入值,可修改取整,自动刷新度数和金额)">' +
        '<span class="topup-mult">×' + mult + '</span>' +
        '<span class="topup-actual-val" title="本次需充值度数 = 天数 × 日均 − 表显余量×倍率(自动计算,不可修改)">' + Math.round(toBuyKwh) + '</span>' +
        '<span class="topup-yuan">≈ ¥' + Math.round(yuan) + '</span>' +
      '</div>' +
      '<div class="topup-meter-meta">日均 ' + Math.round(daily) + ' 度/天 ' + basis + ' · ' + balText +
        ' <span class="topup-daysleft">' + (enough ? '余量 ≈ 可用 ' : '充后 ≈ 可用 ') + Math.round(daysLeft) + ' 天</span>' +
        (enough ? ' <span style="color:var(--success);font-weight:600;">✓ 余量足够,本次无需充值</span>' : '') +
      '</div>' +
    '</div>';
  }
  resultEl.innerHTML = rows;
  updateTopupTotal();
}

// 修改表读数时，动态刷新该行的实际度数、金额、可用天数，以及底部合计；
// 一旦手动修改过表读数，预充天数就从「输入条件」变成「计算结果」，禁用天数输入框
function updateTopupFromMeter(input) {
  var row = input.closest('.topup-meter-card');
  if (!row) return;
  var mult = parseFloat(input.getAttribute('data-mult')) || 1;
  var meter = parseFloat(input.value) || 0;
  var actual = meter * mult;
  row.querySelector('.topup-actual-val').textContent = Math.round(actual);
  row.querySelector('.topup-yuan').textContent = '≈ ¥' + Math.round(actual * ELECTRICITY_PRICE);
  var daily = parseFloat(row.getAttribute('data-daily')) || 0;
  var balKwh = parseFloat(row.getAttribute('data-balkwh'));
  if (isNaN(balKwh)) balKwh = 0; // 该表没抄过数则视为无余量
  var daysLeft = daily > 0 ? (balKwh + actual) / daily : 0;
  row.querySelector('.topup-daysleft').textContent = '充后 ≈ 可用 ' + Math.round(daysLeft) + ' 天';
  var daysEl = document.getElementById('topup-days-modal');
  if (daysEl) daysEl.disabled = true;
  updateTopupTotal();
}

function updateTopupTotal() {
  var totalEl = document.getElementById('topup-total-modal');
  if (!totalEl) return;
  var totalActual = 0, totalMeter = 0, totalYuan = 0;
  document.querySelectorAll('.topup-meter').forEach(function(inp) {
    var mult = parseFloat(inp.getAttribute('data-mult')) || 1;
    var meter = parseFloat(inp.value) || 0;
    var actual = meter * mult;
    totalMeter += meter; totalActual += actual; totalYuan += actual * ELECTRICITY_PRICE;
  });
  totalEl.value = '合计 ' + Math.round(totalActual) + ' 度(实际) ≈ ¥ ' + Math.round(totalYuan) + '  (表读数 ' + Math.round(totalMeter) + ')';
}

// 充值计算器 → 提交充值申请:生成一条「待确认」充值记录,确认到账后才计入统计
function submitTopupApplication() {
  var charge = { date: todayStr(), status: 'pending', note: '充值申请(充值计算器)' };
  var total = 0;
  var cards = document.querySelectorAll('.topup-meter-card');
  cards.forEach(function(card, idx) {
    var m = CHARGE_METERS[idx];
    if (!m) return;
    var v = parseFloat(card.querySelector('.topup-meter').value) || 0;
    charge[m.key] = v;
    total += v;
  });
  if (!cards.length) { showAlert('请先计算充值度数', 'error'); return; }
  if (total <= 0) { showAlert('各表余量均足够(建议充值均为 0),无需提交充值申请', 'error'); return; }
  Api.charges.create(charge).then(function() {
    showAlert('✓ 充值申请已提交(待确认)，确认到账后计入统计', 'success');
    closeTopupModal();
    refreshCharges();
  }).catch(function(err) {
    showAlert('提交失败: ' + (err.message || err), 'error');
  });
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

