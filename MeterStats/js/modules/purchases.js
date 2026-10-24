/**
 * 申购模块 — 增删改 + 表格渲染。
 * 
 * 替代: render_tables.js (申购记录表)。
 */

// ==================== 数据刷新 ====================

function refreshPurchases() {
    Api.purchases.list().then(function(data) {
        State.set("purchases", data);
        renderPurchaseTable(State.get("purchases"));
    }).catch(function(err) {
        showAlert("加载申购数据失败: " + err);
    });
}

// ==================== CRUD 操作 ====================

function addPurchase(date, name, qty, unit, est_price, supplier, note) {
    Api.purchases.create({ date: date, name: name, qty: parseFloat(qty) || 0, unit: unit, est_price: est_price ? parseFloat(est_price) : 0, supplier: supplier, note: note })
        .then(function() { refreshPurchases(); })
        .catch(function(err) { showAlert("添加失败: " + err); });
}

function stockItem(id) {
    Api.purchases.update(id, { status: 'stocked' }).then(function() { refreshPurchases(); })
        .catch(function(err) { showAlert("操作失败: " + err); });
}

function deletePurchase(id) {
    Api.purchases.delete(id).then(function() { refreshPurchases(); })
        .catch(function(err) { showAlert("删除失败: " + err); });
}

// ==================== 表格渲染 (替代 renderPurchaseTable) ====================

function renderPurchaseTable(purchases) {
    var tbody = document.querySelector('#purchase-table tbody');
    if (!tbody) return;
    if (!purchases || purchases.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty">还没有申购记录,点击左侧「申购」添加</td></tr>';
        return;
    }

    var statusText = { pending: '待购', purchased: '已购', stocked: '已购买' };
    var statusColor = { pending: 'var(--warn)', purchased: '#2563eb', stocked: 'var(--success)' };

    var sorted = purchases.slice().sort(function(a, b) { return b.date.localeCompare(a.date); });
    tbody.innerHTML = sorted.map(function(p) {
        var total = (p.qty || 0) * (p.est_price || 0);
        var actionCell = p.status === 'stocked'
            ? '<span style="color:var(--success);font-size:12px;font-weight:600;">✓ 已购买</span>'
            : '<button class="save-btn" data-action="confirm-purchase" data-id="' + p.id + '">确认购买</button>';
        return '<tr>' +
            '<td>' + p.date + '</td>' +
            '<td>' + escapeHtml(p.name) + '</td>' +
            '<td><strong>' + p.qty + '</strong> ' + escapeHtml(p.unit || '') + '</td>' +
            '<td>' + (total > 0 ? '¥ ' + total.toFixed(2) : '—') + '</td>' +
            '<td>' + escapeHtml(p.supplier || '—') + '</td>' +
            '<td><span style="color:' + (statusColor[p.status] || 'var(--text-muted)') + ';font-weight:510;">' + (statusText[p.status] || p.status) + '</span></td>' +
            '<td>' + actionCell + ' <button class="del-btn" data-action="del-purchase" data-id="' + p.id + '" style="margin-left:4px;">删除</button></td>' +
        '</tr>';
    }).join('');

    // 绑定操作按钮
    tbody.querySelectorAll('[data-action="confirm-purchase"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var id = btn.dataset.id;
            var nameCell = btn.closest('tr').cells[1].textContent;
            var qtyCell = btn.closest('tr').cells[2].textContent.trim();
            showModal({ title: '确认购买', body: '确认已购买「<strong>' + escapeHtml(nameCell) + '</strong>】(' + escapeHtml(qtyCell) + ')?<br><br>确认后:该记录打上「已购买」标签,物品<strong>自动累加</strong>到物品记录。', icon: '🛒', confirmText: '确认购买', confirmKind: 'primary' })
                .then(function(ok) {
                    if (!ok) return;
                    Api.purchases.update(id, { status: 'stocked' }).then(function() {
                        showAlert('✓ 已确认购买,数量已自动加入物品记录', 'success');
                        refreshAndRender();
                    }).catch(function(e) { showAlert('失败:' + e.message, 'error'); });
                });
        });
    });
    tbody.querySelectorAll('[data-action="del-purchase"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var id = btn.dataset.id;
            showModal({ title: '删除申购', body: '确定删除这条申购记录?', icon: '🗑', confirmText: '删除', confirmKind: 'danger' })
                .then(function(ok) {
                    if (!ok) return;
                    Api.purchases.delete(id).then(function() {
                        showAlert('✓ 已删除', 'success');
                        refreshAndRender();
                    }).catch(function(e) { showAlert('删除失败:' + e.message, 'error'); });
                });
        });
    });
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshPurchases, addPurchase, stockItem, deletePurchase, renderPurchaseTable };
}
