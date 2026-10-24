/**
 * 申购模块 — 增删改 + 表格渲染。
 * 
 * 替代: render_tables.js (申购记录表)。
 */

// ==================== 数据刷新 ====================

function refreshPurchases() {
    Api.purchases.list().then(function(res) {
        // 防御：后端目前返回裸数组，若日后改成分页对象也能用
        var list = Array.isArray(res) ? res : ((res && res.data) || []);
        State.set("purchases", list);
        renderPurchaseTable(State.get("purchases"));
    }).catch(function(err) {
        showAlert("加载申购数据失败: " + err);
    });
}

// ==================== CRUD 操作 ====================

function addPurchase(date, name, qty, unit, est_price, supplier, note, images, nameImages) {
    Api.purchases.create({
        date: date, name: name, qty: parseFloat(qty) || 0, unit: unit,
        est_price: est_price ? parseFloat(est_price) : 0,
        supplier: supplier, note: note,
        note_image_filenames: images || [],
        // 物品名称栏的图片（不知道叫什么就直接拍）
        name_image_filenames: nameImages || []
    })
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

/** 物品名称单元格：有名字显示名字，只有图片就显示缩略图 */
function _nameCell(p) {
    var out = p.name ? escapeHtml(p.name) : '';
    (p.name_image_filenames || []).forEach(function (fn) {
        out += '<img src="' + getDutyImageUrl(fn) + '" data-full="' + getDutyImageUrl(fn) + '" ' +
            'onclick="openLightbox(this.dataset.full)" title="名称照片" ' +
            'style="width:28px;height:28px;object-fit:cover;border-radius:4px;cursor:pointer;vertical-align:middle;margin-left:4px;border:1px solid var(--border);" />';
    });
    return out || '—';
}

/** 申购照片缩略图（点开看大图） */
function _purchaseThumbs(p) {
    var names = p.note_image_filenames || p.image_filenames || [];
    if (!names.length) return '—';
    return names.slice(0, 3).map(function(fn) {
        return '<img src="' + getDutyImageUrl(fn) + '" data-full="' + getDutyImageUrl(fn) + '" ' +
            'onclick="openLightbox(this.dataset.full)" ' +
            'style="width:26px;height:26px;object-fit:cover;border-radius:4px;cursor:pointer;margin-right:2px;" />';
    }).join('');
}

function renderPurchaseTable(purchases) {
    var tbody = document.querySelector('#purchase-table tbody');
    if (!tbody) return;
    if (!purchases || purchases.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty">还没有申购记录,点击左侧「申购」添加</td></tr>';
        return;
    }

    var statusText = { pending: '待购', purchased: '已购买', stocked: '已购买' };
    var statusColor = { pending: 'var(--warn)', purchased: 'var(--success)', stocked: 'var(--success)' };

    var sorted = purchases.slice().sort(function(a, b) { return b.date.localeCompare(a.date); });
    tbody.innerHTML = sorted.map(function(p) {
        var total = (p.qty || 0) * (p.est_price || 0);
        // kind='purchase' 是购买后生成的留档记录，不再提供"购买"操作
        var isBuyRecord = p.kind === 'purchase';
        var done = isBuyRecord || p.status === 'stocked' || p.status === 'purchased';
        var actionCell = done
            ? '<span style="color:var(--success);font-size:12px;font-weight:600;">✓ ' + (isBuyRecord ? '购买记录' : '已购买') + '</span>'
            : '<button class="save-btn" data-action="confirm-purchase" data-id="' + p.id + '">购买</button>';
        var kindBadge = isBuyRecord
            ? '<span style="font-size:11px;color:var(--success);border:1px solid var(--success);border-radius:4px;padding:0 4px;margin-right:4px;">购买</span>'
            : '';
        return '<tr' + (isBuyRecord ? ' style="background:var(--bg-surface);"' : '') + '>' +
            '<td>' + p.date + '</td>' +
            '<td>' + kindBadge + _nameCell(p) + '</td>' +
            '<td><strong>' + p.qty + '</strong> ' + escapeHtml(p.unit || '') + '</td>' +
            '<td>' + (total > 0 ? '¥ ' + total.toFixed(2) : '—') + '</td>' +
            '<td>' + escapeHtml(p.supplier || '—') + '</td>' +
            '<td>' + _purchaseThumbs(p) + '</td>' +
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
            showModal({
                title: '购买',
                body: '确认已购买「<strong>' + escapeHtml(nameCell) + '</strong>」（' + escapeHtml(qtyCell) + '）?<br>' +
                      '<span style="color:var(--text-muted);font-size:12px;">购买后会保留申购记录，并新增一条购买记录。</span>',
                icon: '🛒',
                confirmText: '购买',
                confirmKind: 'primary',
                // 默认不勾：小东西（胶带、螺丝）买回来直接用掉，不必进库存
                checkbox: {
                    label: '同时添加到物品记录（累加库存）',
                    defaultChecked: false,
                    withImage: true
                }
            }).then(function(res) {
                if (!res || !res.ok) return;
                Api.purchases.stock(id, {
                    add_to_items: !!res.checked,
                    image_filenames: res.images || []
                }).then(function() {
                    showAlert(res.checked ? '✓ 已购买，已加入物品记录' : '✓ 已购买', 'success');
                    refreshPurchases();
                    if (res.checked && typeof refreshItems === 'function') refreshItems();
                }).catch(function(e) {
                    showAlert('失败: ' + (e && e.message ? e.message : e), 'error');
                });
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
                        refreshPurchases();
                    }).catch(function(e) { showAlert('删除失败:' + e.message, 'error'); });
                });
        });
    });
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshPurchases, addPurchase, stockItem, deletePurchase, renderPurchaseTable };
}
