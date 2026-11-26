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
// ⚠️ submitUtilityAdd 的**真实实现**在 admin.js(它是运行时最后加载的那份,
//    也就是一直真正生效的那一行代码)。这里原来还有一份几乎同名的副本,
//    被 admin.js 静默覆盖 —— 改这一份是改不出任何效果的。
//    已删(2026-11 B 批:消除「同名全局互相覆盖」);要改水电录入逻辑去 admin.js,
//    或者下次把 admin.js 那份搬回来,让这份成为唯一实现。


// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    // submitUtilityAdd 不在本文件定义(见上方说明),不要写进导出 ——
    // 导出里放一个未定义的标识符会让 Node 下 require 直接抛 ReferenceError。
    module.exports = { refreshUtilities, addWaterReading, updateWaterReading, deleteWaterReading };
}
