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
        ? { date: 'charge-date', hall: 'charge-hall', fire: 'charge-fire', private_room: 'charge-private-room', ac: 'charge-ac', note: 'charge-note' }
        : { date: 'charge-add-date', hall: 'charge-add-hall', fire: 'charge-add-fire', private_room: 'charge-add-private-room', ac: 'charge-add-ac', note: 'charge-add-note' };
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

    setSubmitting(true);
    Api.charges.create(charge).then(function() {
        showAlert('✓ ' + date + ' 充值记录已保存', 'success');
        var paths = source === 'sidebar'
            ? { date: 'charge-date', hall: 'charge-hall', fire: 'charge-fire', private_room: 'charge-private-room', ac: 'charge-ac', note: 'charge-note' }
            : { date: 'charge-add-date', hall: 'charge-add-hall', fire: 'charge-add-fire', private_room: 'charge-add-private-room', ac: 'charge-add-ac', note: 'charge-add-note' };
        ['hall', 'fire', 'private_room', 'ac', 'note'].forEach(function(k) { document.getElementById(paths[k]).value = ''; });
        if (source === 'modal') closeChargeAddModal();
        refreshAndRender();
    }).catch(function(err) {
        showAlert('保存失败: ' + err.message, 'error');
    }).finally(function() { setSubmitting(false); });
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
