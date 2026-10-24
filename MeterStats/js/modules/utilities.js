/**
 * 水电模块 — 录入/编辑/删除 + 表格渲染。
 * 
 * 通过 Api.utilities.* 调用后端,通过 State.get/set("water") 管理状态。
 * 替代: features_utilities.js (水电录入表单) + render_records.js (水电表底表)。
 */

// ==================== 数据刷新 ====================

function refreshUtilities() {
    Api.utilities.list().then(function(data) {
        State.set("water", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载水电数据失败: " + err);
    });
}

// ==================== CRUD 操作 ====================

function addWaterReading(date, main_meter, sub_meter, water, note) {
    Api.utilities.create({ date: date, main_meter: main_meter, sub_meter: sub_meter, water: water, note: note })
        .then(function() { refreshUtilities(); })
        .catch(function(err) { showAlert("添加失败: " + err); });
}

function updateWaterReading(date, fields) {
    Api.utilities.update(date, fields).then(function() { refreshUtilities(); })
        .catch(function(err) { showAlert("更新失败: " + err); });
}

function deleteWaterReading(date) {
    Api.utilities.delete(date).then(function() { refreshUtilities(); })
        .catch(function(err) { showAlert("删除失败: " + err); });
}

// ==================== 表格渲染 (复用 readings.js 的 renderWaterTable) ====================
// 注意: renderWaterTable 已移到 readings.js,通过 State.get("water") 读取数据

// ==================== 表单提交 (替代 submitUtilityAdd) ====================

/** 水电录入侧栏/弹窗通用提交函数 */
function submitUtilityAdd(source) {
    if (_submitting) return;
    var ids = source === 'sidebar'
        ? { date: 'utility-date', main: 'main_meter', sub: 'sub_meter', water: 'water', note: 'utility-note' }
        : { date: 'utility-add-date', main: 'utility-add-main_meter', sub: 'utility-add-sub_meter', water: 'utility-add-water', note: 'utility-add-note' };
    var date = document.getElementById(ids.date).value;
    if (!date) { showAlert('请选择抄表日期', 'error'); return; }

    var numU = function(id) {
        var v = document.getElementById(id).value;
        return v === '' ? null : parseFloat(v);
    };
    var mainV = numU(ids.main), subV = numU(ids.sub), waterV = numU(ids.water);
    var vals = [mainV, subV, waterV];
    if (vals.every(function(v) { return v === null; })) { showAlert('请至少填写总表/分表/水表一项', 'error'); return; }
    if (vals.some(function(v) { return v !== null && isNaN(v); })) { showAlert('读数必须是数字', 'error'); return; }

    var row = {
        date: date,
        main_meter: mainV,
        sub_meter: subV,
        water: waterV,
        note: document.getElementById(ids.note).value.trim(),
    };

    // 检查是否已有该日期的水电记录,如有则弹窗确认覆盖
    Api.utilities.list().then(function(all) {
        var existing = all.find(function(r) { return r.date === row.date; });
        if (existing) {
            showModal({
                title: '覆盖已有数据', icon: '⚠️', iconKind: 'warn',
                body: '<strong>' + row.date + '</strong> 已有水电表底,是否覆盖?<br><br>' +
                    '<span style="opacity:0.7">现有:</span> 总表 ' + (existing.main_meter != null ? existing.main_meter : '—') + ' · 分表 ' + (existing.sub_meter != null ? existing.sub_meter : '—') + ' · 水表 ' + (existing.water != null ? existing.water : '—') + '<br>' +
                    '<span style="opacity:0.7">新数据:</span> 总表 ' + (row.main_meter != null ? row.main_meter : '—') + ' · 分表 ' + (row.sub_meter != null ? row.sub_meter : '—') + ' · 水表 ' + (row.water != null ? row.water : '—'),
                confirmText: '覆盖', confirmKind: 'primary'
            }).then(function(overOK) {
                if (!overOK) return;
                doSaveWater();
            });
        } else {
            doSaveWater();
        }

        function doSaveWater() {
            setSubmitting(true);
            Api.utilities.create(row).then(function() {
                showAlert('✓ ' + date + ' 水电已保存', 'success');
                var paths = source === 'sidebar'
                    ? { date: 'utility-date', main: 'main_meter', sub: 'sub_meter', water: 'water', note: 'utility-note' }
                    : { date: 'utility-add-date', main: 'utility-add-main_meter', sub: 'utility-add-sub_meter', water: 'utility-add-water', note: 'utility-add-note' };
                ['main', 'sub', 'water', 'note'].forEach(function(k) { document.getElementById(paths[k]).value = ''; });
                if (source === 'modal') closeReadingAddModal();
                refreshAndRender();
            }).catch(function(err) {
                showAlert('保存失败: ' + err.message, 'error');
            }).finally(function() { setSubmitting(false); });
        }
    });
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshUtilities, addWaterReading, updateWaterReading, deleteWaterReading,
                       submitUtilityAdd };
}
