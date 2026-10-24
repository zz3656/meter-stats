/**
 * 物品模块 — 增删改 + 借还 + 表格渲染。
 * 
 * 替代: render_tables.js (物品表 + 借出/归还记录)。
 */

// ==================== 数据刷新 ====================

function refreshItems() {
    Api.items.list().then(function(data) {
        State.set("items", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载物品数据失败: " + err);
    });
}

// ==================== CRUD 操作 ====================

function addItem(name, qty, unit, note) {
    Api.items.create({ name: name, qty: parseFloat(qty) || 0, unit: unit, note: note })
        .then(function() { refreshItems(); })
        .catch(function(err) { showAlert("添加失败: " + err); });
}

function updateItem(id, fields) {
    Api.items.update(id, fields).then(function() { refreshItems(); })
        .catch(function(err) { showAlert("更新失败: " + err); });
}

function deleteItem(id) {
    Api.items.delete(id).then(function() { refreshItems(); })
        .catch(function(err) { showAlert("删除失败: " + err); });
}

function lendItem(id, borrower, qty, note) {
    Api.items.lend(id, { borrower: borrower, qty: parseFloat(qty), note: note })
        .then(function() { refreshItems(); })
        .catch(function(err) { showAlert("借出失败: " + err); });
}

function returnItem(id, qty, note) {
    Api.items.return(id, { qty: parseFloat(qty), note: note })
        .then(function() { refreshItems(); })
        .catch(function(err) { showAlert("归还失败: " + err); });
}

// ==================== 表格渲染 (替代 renderItemTable + renderLendHistory) ====================

function renderItemTable(items) {
    var tbody = document.querySelector('#item-table tbody');
    if (!tbody) return;
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty">还没有物品,点击上方表单添加</td></tr>';
        return;
    }
    tbody.innerHTML = items.map(function(it) {
        var safeName = escapeHtml(it.name);
        var safeUnit = escapeHtml(it.unit || '');
        var safeNote = escapeHtml(it.note || '');
        var totalQty = it.qty || 0;
        var lentQty = it.lent_qty || 0;
        var availableQty = totalQty - lentQty;
        var canLend = availableQty > 0;
        var canReturn = lentQty > 0;
        var actionBtns = [];
        if (canLend) {
            actionBtns.push('<button class="save-btn" data-action="lend-item" data-id="' + it.id + '" data-name="' + safeName + '" data-available="' + availableQty + '" data-unit="' + safeUnit + '">借出</button>');
        }
        if (canReturn) {
            actionBtns.push('<button class="btn btn-secondary btn-sm" data-action="return-item" data-id="' + it.id + '" data-name="' + safeName + '" data-lent="' + lentQty + '" data-unit="' + safeUnit + '">归还</button>');
        }
        actionBtns.push('<button class="del-btn" data-action="del-item" data-id="' + it.id + '">删除</button>');
        return '<tr>' +
            '<td>' + safeName + '</td>' +
            '<td><strong>' + totalQty + '</strong></td>' +
            '<td>' + availableQty + '</td>' +
            '<td>' + lentQty + '</td>' +
            '<td>' + safeUnit + '</td>' +
            '<td>' + safeNote + '</td>' +
            '<td>' + actionBtns.join(' ') + '</td>' +
        '</tr>';
    }).join('');

    // 绑定删除按钮
    tbody.querySelectorAll('[data-action="del-item"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var id = btn.dataset.id;
            showModal({ title: '删除物品', body: '确定删除该物品?这会从列表移除(已申购入库的不影响)。', icon: '⚠', confirmText: '删除', confirmKind: 'danger' })
                .then(function(ok) {
                    if (!ok) return;
                    Api.items.delete(id).then(function() {
                        showAlert('✓ 已删除', 'success');
                        refreshAndRender();
                    }).catch(function(e) { showAlert('删除失败:' + e.message, 'error'); });
                });
        });
    });

    // 绑定借出按钮
    tbody.querySelectorAll('[data-action="lend-item"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            openLendModal(btn.dataset.id, btn.dataset.name, parseInt(btn.dataset.available), btn.dataset.unit);
        });
    });

    // 绑定归还按钮
    tbody.querySelectorAll('[data-action="return-item"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            openReturnModal(btn.dataset.id, btn.dataset.name, parseInt(btn.dataset.lent), btn.dataset.unit);
        });
    });
}

/** 渲染借出/归还历史 (替代 renderLendHistory) */
function renderLendHistory(items) {
    var tbody = document.querySelector('#lend-history-table tbody');
    var empty = document.getElementById('lend-history-empty');
    if (!tbody) return;

    var rows = [];
    (items || []).forEach(function(it) {
        var records = it.lend_records || [];
        records.forEach(function(r) {
            rows.push(Object.assign({}, r, { item_name: it.name, item_unit: it.unit || '' }));
        });
    });

    if (rows.length === 0) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';

    rows.sort(function(a, b) { return (b.lend_date || '').localeCompare(a.lend_date || ''); });

    var statusText = { lent: '借用中', returned: '已归还' };
    var statusColor = { lent: 'var(--warn)', returned: 'var(--success)' };

    tbody.innerHTML = rows.map(function(r) {
        var returnQty = (typeof r.return_qty === 'number') ? r.return_qty : 0;
        var returnDate = r.return_date || (r.status === 'returned' ? '—' : '');
        return '<tr>' +
            '<td>' + escapeHtml(r.lend_date || '—') + '</td>' +
            '<td>' + escapeHtml(r.item_name || '—') + '</td>' +
            '<td>' + escapeHtml(r.borrower || '—') + '</td>' +
            '<td>' + (r.qty != null ? r.qty : 0) + ' ' + escapeHtml(r.item_unit || '') + '</td>' +
            '<td>' + returnQty + ' ' + escapeHtml(r.item_unit || '') + '</td>' +
            '<td>' + escapeHtml(returnDate || '—') + '</td>' +
            '<td><span style="color:' + (statusColor[r.status] || 'var(--text-muted)') + ';font-weight:510;">' + (statusText[r.status] || r.status || '—') + '</span></td>' +
            '<td>' + escapeHtml(r.note || r.return_note || '—') + '</td>' +
        '</tr>';
    }).join('');
}

// ==================== 弹窗管理 (替代 openLendModal + openReturnModal) ====================

function openLendModal(id, name, available, unit) {
    document.getElementById('lend-item-id').value = id;
    document.getElementById('lend-item-name').textContent = name;
    document.getElementById('lend-available-qty').textContent = available + ' ' + unit;
    document.getElementById('lend-qty').value = '';
    document.getElementById('lend-qty').max = available;
    document.getElementById('lend-borrower').value = '';
    document.getElementById('lend-note').value = '';
    document.getElementById('lend-modal-backdrop').classList.add('show');
}

function closeLendModal() {
    document.getElementById('lend-modal-backdrop').classList.remove('show');
}

function openReturnModal(id, name, lent, unit) {
    document.getElementById('return-item-id').value = id;
    document.getElementById('return-item-name').textContent = name;
    document.getElementById('return-lent-qty').textContent = lent + ' ' + unit;
    document.getElementById('return-qty').value = lent;
    document.getElementById('return-qty').max = lent;
    document.getElementById('return-note').value = '';
    document.getElementById('return-modal-backdrop').classList.add('show');
}

function closeReturnModal() {
    document.getElementById('return-modal-backdrop').classList.remove('show');
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshItems, addItem, updateItem, deleteItem, lendItem, returnItem,
                       renderItemTable, renderLendHistory, openLendModal, closeLendModal, openReturnModal, closeReturnModal };
}
