/**
 * 门店管理页 —— 维护分店登记信息(P0)。
 *
 * P0 范围:门店的增删改查。P1 会在这里接入门店切换器(总部账号在侧栏顶部切店)。
 *
 * 权限(与后端 modules/stores/handler.py 一致):
 * - 读(GET /api/stores):任何登录用户,但后端只返回自己有权限的门店
 * - 增删改:仅管理员 —— 前端按角色隐藏按钮,后端仍然是最终裁判
 *
 * 转义约定(别再踩这个坑):
 * - 全局 escapeHtml 被 admin.js 的弱版本覆盖(只转义 & < >),
 *   元素内容位置够用,属性值位置不够用
 * - 属性值位置一律走 escapeAttr(见下)—— 弱版 escapeHtml 不转义 " 和 ',
 *   自由文本进属性值能直接打断属性
 * - 本文件不定义 escapeHtml(全局那份已经够用,重复定义只会互相覆盖)
 */

// ===== 门店状态 =====
var STORE_LIST = [];            // 当前用户可见的门店(admin.js 的用户表格也用它显示门店名)
var STORE_EDITING_ID = null;    // 正在编辑的门店 ID(null = 新增)
var STORE_LOAD_ERROR = '';      // 列表加载失败的提示(渲染在页面上,不只弹一下 toast)
var DEFAULT_STORE_ID = 'main';  // 默认店(总店)不可删

/**
 * 属性值转义 —— 把值安全地放进双引号/单引号属性里。
 *
 * 不能直接用 escapeHtml:admin.js 的全局 escapeHtml 覆盖了 utils.js 的强版本,
 * 而那份弱版本只转义 & < >,不转义 " 和 '。
 * 自由文本(门店名称/地址/编号)一旦进了属性值,弱版本就能被引号打断。
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

/** 当前登录用户是不是管理员(门店的增删改仅 admin)。 */
function isStoreAdmin() {
    try {
        return !!(ADMIN_USER && ADMIN_USER.role === 'admin');
    } catch (e) {
        // ADMIN_USER 是 admin.js 里的 let 绑定 —— 那边还没加载时会抛 ReferenceError
        return false;
    }
}

// ===== 渲染 =====

/** 渲染门店管理页主体 */
function renderStoresPage() {
    var host = document.getElementById('stores-page');
    if (!host) return;

    bindStoresPageEvents(host);

    var canManage = isStoreAdmin();

    var rows = STORE_LIST.map(function (s) {
        var sid = String(s.id == null ? '' : s.id);
        var name = String(s.name || sid);
        var ops = '';
        if (canManage) {
            ops = '<button type="button" class="btn btn-secondary btn-sm" data-store-action="edit" data-store-id="' +
                escapeAttr(sid) + '">编辑</button> ';
            if (sid === DEFAULT_STORE_ID) {
                ops += '<span style="color:var(--text-muted);">默认店</span>';
            } else {
                ops += '<button type="button" class="btn btn-danger btn-sm" data-store-action="remove" data-store-id="' +
                    escapeAttr(sid) + '">删除</button>';
            }
        }
        return '<tr>' +
            '<td><strong>' + escapeHtml(name) + '</strong></td>' +
            '<td><code>' + escapeHtml(sid) + '</code></td>' +
            '<td>' + escapeHtml(s.code || '—') + '</td>' +
            '<td>' + escapeHtml(s.address || '—') + '</td>' +
            '<td>' + (s.active === false ? '停用' : '启用') + '</td>' +
            '<td>' + escapeHtml(s.created_at || '—') + '</td>' +
            '<td class="ta-right">' + ops + '</td>' +
        '</tr>';
    }).join('');

    if (!rows) {
        rows = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:20px;">' +
            escapeHtml(STORE_LOAD_ERROR || '暂无门店') + '</td></tr>';
    }

    host.innerHTML =
        '<div class="card">' +
            '<div class="card-header"><h2>🏪 门店管理</h2>' +
            (canManage
                ? '<button type="button" class="btn btn-primary btn-sm" data-store-action="new">+ 新增门店</button>'
                : '') +
            '</div>' +
            '<div style="overflow-x:auto;">' +
            '<table class="settings-table"><thead><tr>' +
                '<th>门店名称</th><th>门店 ID</th><th>编号</th><th>地址</th><th>状态</th><th>创建时间</th><th class="ta-right">操作</th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>' +
            '</div>' +
        '</div>' +
        (canManage ? storeFormHtml() : '');
}

/** 门店表单(新增/编辑共用一张卡)。 */
function storeFormHtml() {
    return '<div class="card" id="store-form-card" style="display:none;">' +
        '<div class="card-header"><h3 id="store-form-title">新增门店</h3></div>' +
        '<form id="store-form">' +
            '<div class="form-row">' +
                '<label>门店 ID<code style="color:var(--text-muted);">(字母/数字/下划线/连字符,1-32 位,创建后不可改)</code></label>' +
                '<input type="text" id="store-id-input" required placeholder="例如 s002" pattern="[A-Za-z0-9_-]{1,32}" />' +
            '</div>' +
            '<div class="form-row">' +
                '<label>门店名称</label>' +
                '<input type="text" id="store-name" required placeholder="例如 国贸店" />' +
            '</div>' +
            '<div class="form-row">' +
                '<label>编号</label>' +
                '<input type="text" id="store-code" placeholder="例如 B002" />' +
            '</div>' +
            '<div class="form-row">' +
                '<label>地址</label>' +
                '<input type="text" id="store-address" placeholder="选填" />' +
            '</div>' +
            '<div class="settings-inline" style="margin-top:12px;">' +
                '<button type="submit" class="btn btn-primary">保存</button>' +
                '<button type="button" class="btn btn-secondary" data-store-action="cancel">取消</button>' +
            '</div>' +
        '</form>' +
    '</div>';
}

/**
 * 事件绑定(只绑一次)。
 *
 * 门店 ID 不写进 inline onclick —— HTML 实体在 JS 解析前就被还原了,
 * 转义挡不住引号。用 data 属性 + 事件委托,属性值走 escapeAttr 就够了。
 */
function bindStoresPageEvents(host) {
    if (host.dataset.storeEventsBound) return;
    host.dataset.storeEventsBound = '1';

    host.addEventListener('click', function (ev) {
        var btn = ev.target && ev.target.closest ? ev.target.closest('[data-store-action]') : null;
        if (!btn || !host.contains(btn)) return;
        var action = btn.getAttribute('data-store-action');
        var sid = btn.getAttribute('data-store-id') || '';
        if (action === 'new') resetStoreForm();
        else if (action === 'edit') editStore(sid);
        else if (action === 'remove') removeStore(sid);
        else if (action === 'cancel') hideStoreForm();
    });

    host.addEventListener('submit', function (ev) {
        if (ev.target && ev.target.id === 'store-form') {
            ev.preventDefault();
            saveStore();
        }
    });
}

/** 加载门店列表 */
async function loadStores() {
    STORE_LOAD_ERROR = '';
    try {
        var res = await Api.stores.list();
        if (res && res.ok === false) {
            // 后端约定:失败也是 HTTP 200 + { ok: false, error }
            STORE_LOAD_ERROR = res.error || '没有权限查看门店列表';
            STORE_LIST = [];
        } else {
            STORE_LIST = (res && res.stores) || [];
        }
    } catch (e) {
        STORE_LIST = [];
        STORE_LOAD_ERROR = '加载门店列表失败:' + (e && e.message ? e.message : e);
    }
    renderStoresPage();
}

// ===== 操作 =====

/** 开始新增门店 */
function resetStoreForm() {
    STORE_EDITING_ID = null;
    var card = document.getElementById('store-form-card');
    var title = document.getElementById('store-form-title');
    var idInput = document.getElementById('store-id-input');
    if (card) card.style.display = 'block';
    if (title) title.textContent = '新增门店';
    if (idInput) { idInput.value = ''; idInput.disabled = false; }
    setStoreFormValue('store-name', '');
    setStoreFormValue('store-code', '');
    setStoreFormValue('store-address', '');
    var nameInput = document.getElementById('store-name');
    if (nameInput) nameInput.focus();
}

/** 收起门店表单 */
function hideStoreForm() {
    var card = document.getElementById('store-form-card');
    if (card) card.style.display = 'none';
    STORE_EDITING_ID = null;
}

/** 开始编辑门店 */
function editStore(id) {
    var s = STORE_LIST.find(function (x) { return String(x.id) === String(id); });
    if (!s) return;
    STORE_EDITING_ID = String(s.id);
    var card = document.getElementById('store-form-card');
    var title = document.getElementById('store-form-title');
    var idInput = document.getElementById('store-id-input');
    if (card) card.style.display = 'block';
    if (title) title.textContent = '编辑门店: ' + (s.name || s.id);
    if (idInput) { idInput.value = String(s.id); idInput.disabled = true; }
    setStoreFormValue('store-name', s.name || '');
    setStoreFormValue('store-code', s.code || '');
    setStoreFormValue('store-address', s.address || '');
}

/** 写单个表单字段的值 */
function setStoreFormValue(inputId, value) {
    var input = document.getElementById(inputId);
    if (input) input.value = value == null ? '' : String(value);
}

/** 保存门店(新增或编辑) */
async function saveStore() {
    var id = ((document.getElementById('store-id-input') || {}).value || '').trim();
    var name = ((document.getElementById('store-name') || {}).value || '').trim();
    var code = ((document.getElementById('store-code') || {}).value || '').trim();
    var address = ((document.getElementById('store-address') || {}).value || '').trim();
    if (!id || !name) {
        showAlert('门店 ID 和名称不能为空', 'error');
        return false;
    }
    var editing = STORE_EDITING_ID;
    var payload = { name: name, code: code, address: address };
    try {
        var res;
        if (editing) {
            res = await Api.stores.update(editing, payload);
        } else {
            payload.id = id;
            res = await Api.stores.create(payload);
        }
        if (res && res.ok === false) {
            showAlert(res.error || '保存失败', 'error');
            return false;
        }
        showAlert(editing ? '门店已更新' : '门店已创建', 'success');
        hideStoreForm();
        await loadStores();
    } catch (e) {
        showAlert('保存失败: ' + (e && e.message ? e.message : e), 'error');
    }
    return false;
}

/** 删除门店(只删登记信息,数据目录保留) */
async function removeStore(id) {
    var s = STORE_LIST.find(function (x) { return String(x.id) === String(id); });
    var name = s ? (s.name || s.id) : id;
    var msg = '确定删除门店「' + name + '」?\n\n' +
        '注意:只删除门店的登记信息,该店的数据目录(stores/' + id + '/)会保留,不会被删除。\n' +
        '已经分配到该门店的用户会失去这家店的访问权限。';
    if (!confirm(msg)) return;
    try {
        var res = await Api.stores.remove(id);
        if (res && res.ok === false) {
            showAlert(res.error || '删除失败', 'error');
            return;
        }
        showAlert('门店已删除', 'success');
        await loadStores();
    } catch (e) {
        showAlert('删除失败: ' + (e && e.message ? e.message : e), 'error');
    }
}
