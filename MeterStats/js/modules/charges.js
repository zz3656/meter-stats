/**
 * 充值模块 — 录入/编辑/删除 + 表格渲染 + 表单提交。
 * 
 * 通过 Api.charges.* 调用后端,通过 State.get/set("charges") 管理状态。
 * 替代: render_records.js (充值记录表) + render_edit.js (充值编辑弹窗)
 *       + forms_submit.js (submitChargeAdd)。
 */

// ==================== 数据刷新 ====================

function refreshCharges() {
    Api.charges.list().then(function(data) {
        State.set("charges", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载充值数据失败: " + err);
    });
}

// ==================== CRUD 操作 ====================

function addCharge(date, hall, fire, private_room, ac, note) {
    Api.charges.create({ date: date, hall: hall, fire: fire, private_room: private_room, ac: ac, note: note })
        .then(function() { refreshCharges(); })
        .catch(function(err) { showAlert("添加失败: " + err); });
}

function updateCharge(id, fields) {
    Api.charges.update(id, fields).then(function() { refreshCharges(); })
        .catch(function(err) { showAlert("更新失败: " + err); });
}

function deleteCharge(id) {
    Api.charges.delete(id).then(function() { refreshCharges(); })
        .catch(function(err) { showAlert("删除失败: " + err); });
}

// ==================== 表格渲染 (复用 readings.js 的 renderChargeTable) ====================
// 注意: renderChargeTable 已移到 readings.js,通过 State.get("charges") 读取数据

// ==================== 表单提交 (替代 submitChargeAdd) ====================

/** 充值记录侧栏/弹窗通用提交函数 */
function submitChargeAdd(source) {
    if (_submitting) return;
    var ids = source === 'sidebar'
        ? { date: 'charge-date', hall: 'charge-hall', fire: 'charge-fire', private_room: 'charge-private_room', ac: 'charge-ac', note: 'charge-note' }
        : { date: 'charge-add-date', hall: 'charge-add-hall', fire: 'charge-add-fire', private_room: 'charge-add-private_room', ac: 'charge-add-ac', note: 'charge-add-note' };
    var date = document.getElementById(ids.date).value;
    if (!date) { showAlert('请选择充值日期', 'error'); return; }

    var charge = {
        date: date,
        hall: parseFloat(document.getElementById(ids.hall).value) || 0,
        fire: parseFloat(document.getElementById(ids.fire).value) || 0,
        private_room: parseFloat(document.getElementById(ids.private_room).value) || 0,
        ac: parseFloat(document.getElementById(ids.ac).value) || 0,
        note: document.getElementById(ids.note).value.trim(),
    };
    var allZero = true;
    for (var i = 0; i < CHARGE_METERS.length; i++) {
        if (charge[CHARGE_METERS[i].key] !== 0) { allZero = false; break; }
    }
    if (allZero) { showAlert('至少填写一块表的充值度数', 'error'); return; }

    // 录入前先自查:这笔充值和当天抄表对不上(多半是把抄表读数填进了充值栏)时
    // 直接拦下,别等统计被顶飞才发现。后端 POST /api/charges 会再兜一道。
    var conflict = findChargeConflictFor(charge);
    if (conflict) {
        showModal({
            title: '这笔充值和抄表对不上', icon: '⚠️', iconKind: 'warn',
            body: '<p style="margin:0 0 10px;line-height:1.6">' + escapeHtml(conflict.reason) + '</p>'
                + '<p style="margin:0;opacity:0.75;line-height:1.6">充值额是<strong>新充进去的表字数</strong>'
                + '(表底会往上跳的那部分),不是当前表底。确认无误可改用「待确认」提交。</p>',
            confirmText: '知道了'
        });
        return;
    }

    setSubmitting(true);
    Api.charges.create(charge).then(function() {
        showAlert('✓ ' + date + ' 充值记录已保存', 'success');
        var paths = source === 'sidebar'
            ? { date: 'charge-date', hall: 'charge-hall', fire: 'charge-fire', private_room: 'charge-private_room', ac: 'charge-ac', note: 'charge-note' }
            : { date: 'charge-add-date', hall: 'charge-add-hall', fire: 'charge-add-fire', private_room: 'charge-add-private_room', ac: 'charge-add-ac', note: 'charge-add-note' };
        ['hall', 'fire', 'private_room', 'ac', 'note'].forEach(function(k) { document.getElementById(paths[k]).value = ''; });
        if (source === 'modal') closeChargeAddModal();
        refreshAndRender();
    }).catch(function(err) {
        showAlert('保存失败: ' + err.message, 'error');
    }).finally(function() { setSubmitting(false); });
}

/** 用当前抄表数据自查一笔待提交的充值,返回冲突说明或 null */
function findChargeConflictFor(charge) {
    if (typeof findPastedReadingCharges !== 'function') return null;
    var probe = {
        id: '__probe__', date: charge.date, status: 'confirmed',
        hall: charge.hall, fire: charge.fire,
        private_room: charge.private_room, ac: charge.ac,
    };
    var hits = findPastedReadingCharges([probe]);
    for (var i = 0; i < hits.length; i++) {
        if (hits[i].charge_id === '__probe__') return hits[i];
    }
    if (typeof findChargeConflicts !== 'function') return null;
    hits = findChargeConflicts([probe]);
    for (var j = 0; j < hits.length; j++) {
        if (hits[j].charge_id === '__probe__') return hits[j];
    }
    return null;
}

// ==================== 弹窗管理 ====================

function openChargeAddModal() {
    var d = document.getElementById('charge-add-date');
    if (d && !d.value) d.value = todayStr();
    document.getElementById('charge-add-modal-backdrop').classList.add('show');
    document.getElementById('charge-add-hall')?.focus();
}

function closeChargeAddModal() {
    document.getElementById('charge-add-modal-backdrop').classList.remove('show');
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshCharges, addCharge, updateCharge, deleteCharge,
                       submitChargeAdd, openChargeAddModal, closeChargeAddModal };
}
