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
    var ctx = source === 'sidebar'
        ? { date: 'charge-date', note: 'charge-note', prefix: 'charge-' }
        : { date: 'charge-add-date', note: 'charge-add-note', prefix: 'charge-add-' };
    var date = document.getElementById(ctx.date).value;
    if (!date) { showAlert('请选择充值日期', 'error'); return; }

    // 表值按当前门店的表集合收集(P2);充值表单的空输入语义是 0(不是"没填")
    var picked = window.MeterForm.collect(ctx.prefix);
    if (picked.hasNaN) { showAlert('充值度数必须是数字', 'error'); return; }
    var charge = { date: date, meters: {} };
    var allZero = true;
    picked.keys.forEach(function(k) {
        var v = (picked.all[k] === null) ? 0 : picked.all[k];
        if (v !== 0) allZero = false;
        if (window.MeterForm.LEGACY_KEYS.indexOf(k) >= 0) charge[k] = v;
        else charge.meters[k] = v;
    });
    if (!Object.keys(charge.meters).length) delete charge.meters;
    charge.note = document.getElementById(ctx.note).value.trim();
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
        window.MeterForm.clear(ctx.prefix);
        var noteEl = document.getElementById(ctx.note);
        if (noteEl) noteEl.value = '';
        if (source === 'modal') closeChargeAddModal();
        refreshAndRender();
    }).catch(function(err) {
        showAlert('保存失败: ' + err.message, 'error');
    }).finally(function() { setSubmitting(false); });
}

/** 用当前抄表数据自查一笔待提交的充值,返回冲突说明或 null */
function findChargeConflictFor(charge) {
    if (typeof findPastedReadingCharges !== 'function') return null;
    // 直接把待提交的载荷当探针(含旧 4 表顶层字段与 meters 字典)
    var probe = Object.assign({}, charge, { id: '__probe__', status: 'confirmed' });
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
    // 聚焦第一块表(门店可能有 2 块,也可能 5 块)
    var firstKey = (window.MeterForm.keys() || [])[0];
    if (firstKey) document.getElementById('charge-add-' + firstKey)?.focus();
}

function closeChargeAddModal() {
    document.getElementById('charge-add-modal-backdrop').classList.remove('show');
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshCharges, addCharge, updateCharge, deleteCharge,
                       submitChargeAdd, openChargeAddModal, closeChargeAddModal };
}
